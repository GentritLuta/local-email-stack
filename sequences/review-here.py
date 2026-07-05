# -*- coding: utf-8 -*-
"""review-here.py - approve prospect replies ON THE LAPTOP (popups on your own PC).

The email op runs on the VPS, but its approval popups used to only appear on the VPS
desktop. This pulls the pending-reply queue from the VPS over SSH, runs the SAME approval
dialog HERE on the laptop, sends approved replies from here, then merges your decisions
back to the VPS. Single reviewer (the VPS review task is disabled), so no double-send.

Usage:  python sequences/review-here.py     (or double-click work-replies.cmd)
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
KEY = str(Path.home() / ".ssh" / "id_ed25519_hostinger")
VPS = "Administrator@188.209.157.127"
VPS_STORE = "C:/Users/Administrator/local-email-stack/out/pending_replies.json"
SSH_OPTS = ["-i", KEY, "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=20"]


def scp(a, b):
    subprocess.run(["scp", *SSH_OPTS, a, b], check=True, capture_output=True, text=True)


def main() -> int:
    tmp = Path(tempfile.gettempdir()) / "pending_replies.laptop.json"
    print("Pulling the reply queue from the VPS...")
    try:
        scp(f"{VPS}:{VPS_STORE}", str(tmp))
    except subprocess.CalledProcessError as e:
        print(f"Could not reach the VPS over SSH: {e.stderr or e}")
        return 1

    data = json.loads(tmp.read_text("utf-8"))
    todo = [x for x in data.get("pending", []) if not x.get("resolved")]
    if not todo:
        print("Nothing awaiting a decision. Done.")
        return 0
    print(f"{len(todo)} reply(ies) awaiting your decision - popups appear on THIS PC now.")

    # Run the review here, pointed at the pulled file (REPLY_STORE override).
    env = dict(os.environ, REPLY_STORE=str(tmp))
    subprocess.run([sys.executable, str(REPO / "sequences" / "reply-review.py"), "run"], env=env)

    # Merge decisions back: re-pull the CURRENT VPS queue (it may have new items), apply
    # only my resolutions by reply_id, push. Never clobbers items the VPS added meanwhile.
    reviewed = json.loads(tmp.read_text("utf-8"))
    resolved = {it.get("reply_id"): it for it in reviewed.get("pending", []) if it.get("resolved")}
    fresh = Path(tempfile.gettempdir()) / "pending_replies.vps.json"
    scp(f"{VPS}:{VPS_STORE}", str(fresh))
    vps = json.loads(fresh.read_text("utf-8"))
    changed = 0
    for it in vps.get("pending", []):
        r = resolved.get(it.get("reply_id"))
        if r and not it.get("resolved"):
            it["resolved"] = True
            it["action"] = r.get("action")
            it["resolved_at"] = r.get("resolved_at")
            changed += 1
    fresh.write_text(json.dumps(vps, indent=2, ensure_ascii=False), "utf-8")
    scp(str(fresh), f"{VPS}:{VPS_STORE}")
    print(f"Synced {changed} decision(s) back to the VPS. Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
