"""harden-task-xml.py — patch a Windows Task Scheduler XML file to add the
hardening flags we want on every recurring LES-* task:
  - DisallowStartIfOnBatteries=false  (don't skip when laptop on battery)
  - StopIfGoingOnBatteries=false      (don't stop mid-tick when battery)
  - WakeToRun=true                    (wake laptop from sleep)
  - StartWhenAvailable=true           (run missed tasks when laptop wakes)
  - RestartOnFailure (3× at 10min)    (retry if tick fails)
  - ExecutionTimeLimit=PT15M          (hard cap so it can't hang forever)

The exported XML has UTF-16 LE BOM. We read+rewrite in UTF-16.
"""
from __future__ import annotations
import sys
from pathlib import Path

# Windows cp1252 stdout chokes on unicode checkmarks otherwise
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

if len(sys.argv) != 3:
    sys.exit("usage: harden-task-xml.py <input.xml> <output.xml>")
src, dst = Path(sys.argv[1]), Path(sys.argv[2])

# Read as UTF-16 (schtasks export default)
try:
    raw = src.read_text(encoding="utf-16")
except UnicodeError:
    raw = src.read_text(encoding="utf-8")

def replace_or_insert(xml: str, tag: str, value: str) -> str:
    """If <tag>...</tag> exists inside <Settings>, replace its content;
    otherwise insert before </Settings>."""
    import re
    pat = re.compile(rf"<{tag}>.*?</{tag}>", flags=re.DOTALL)
    if pat.search(xml):
        return pat.sub(f"<{tag}>{value}</{tag}>", xml, count=1)
    return xml.replace("</Settings>", f"    <{tag}>{value}</{tag}>\n  </Settings>", 1)

xml = raw
xml = replace_or_insert(xml, "DisallowStartIfOnBatteries", "false")
xml = replace_or_insert(xml, "StopIfGoingOnBatteries", "false")
xml = replace_or_insert(xml, "WakeToRun", "true")
xml = replace_or_insert(xml, "StartWhenAvailable", "true")
xml = replace_or_insert(xml, "ExecutionTimeLimit", "PT15M")
# RestartOnFailure is a nested element
if "<RestartOnFailure>" not in xml:
    xml = xml.replace(
        "</Settings>",
        "    <RestartOnFailure>\n      <Interval>PT10M</Interval>\n      <Count>3</Count>\n    </RestartOnFailure>\n  </Settings>",
        1,
    )

# Write as UTF-16 (schtasks expects same encoding)
dst.write_text(xml, encoding="utf-16")
print(f"✓ Wrote hardened XML to {dst}")
