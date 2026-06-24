# -*- coding: utf-8 -*-
"""_reply-correlation-analysis.py — professional reply/conversion correlation
analysis across all campaign data. Linear (Pearson) + non-linear (Spearman,
mutual information, random-forest importance), with Wilson CIs and explicit
small-sample handling. Writes charts + a stats JSON for the report.
"""
from __future__ import annotations
import json, math, urllib.request, re
from pathlib import Path
from collections import defaultdict, Counter
import numpy as np
import pandas as pd
from scipy import stats
from sklearn.feature_selection import mutual_info_regression
from sklearn.ensemble import RandomForestRegressor
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "out" / "research"; OUT.mkdir(parents=True, exist_ok=True)
env = {}
for line in (REPO / "sequences" / "supabase.env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1); env[k.strip()] = v.strip()
URL = env["SUPABASE_URL"]; KEY = env["SUPABASE_ANON_KEY"]
H = {"apikey": KEY, "Authorization": "Bearer " + KEY, "User-Agent": "les-research/1.0"}
ORANGE = "#E8740C"; INK = "#1a1a1a"; SLATE = "#475569"


def fetch(path):
    out, step, off = [], 1000, 0
    sep = "&" if "?" in path else "?"
    while True:
        req = urllib.request.Request(f"{URL}/rest/v1/{path}{sep}limit={step}&offset={off}", headers=H)
        chunk = json.loads(urllib.request.urlopen(req, timeout=120).read())
        out.extend(chunk)
        if len(chunk) < step: break
        off += step
    return out


def wilson(k, n, z=1.96):
    if n == 0: return (0.0, 0.0, 0.0)
    p = k / n
    d = 1 + z*z/n
    c = (p + z*z/(2*n)) / d
    h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / d
    return (p, max(0, c-h), min(1, c+h))


def main():
    # ── domain -> brand map ──
    dom2brand = {}
    for pf in sorted((REPO/"profiles").glob("*.json")):
        if pf.name.endswith(".private.json"): continue
        d = json.loads(pf.read_text(encoding="utf-8")); slug = d.get("slug", pf.stem)
        for fd in (d.get("relay") or {}).get("from_domains", []):
            dom2brand[fd["domain"].lower()] = slug

    # ── variants -> body features per (brand, step) ──
    GIVE = re.compile(r"\b(audit|review|teardown|ghosts|free|checklist|template|report|analyse|auswertung|check|fallen|mockup|rate)\b", re.I)
    variants = fetch("variants?select=profile_slug,n,subject,body")
    vfeat = {}
    for v in variants:
        body = v.get("body") or ""
        vfeat[(v["profile_slug"], v["n"])] = {
            "body_words": len(body.split()),
            "has_give": 1 if GIVE.search(body) else 0,
            "has_question": 1 if "?" in (v.get("subject") or "") else 0,
            "subj_words_v": len((v.get("subject") or "").split()),
        }

    # ── send_log ──
    sends = fetch("send_log?select=from_addr,subject,step_n,opened_at,clicked_at,replied,bounced,error,sent_at")
    rows = []
    for s in sends:
        fa = (s.get("from_addr") or "").lower(); dom = fa.split("@")[-1] if "@" in fa else ""
        brand = dom2brand.get(dom)
        if not brand:
            parts = dom.split(".")
            for i in range(len(parts)-1):
                if ".".join(parts[i:]) in dom2brand: brand = dom2brand[".".join(parts[i:])]; break
        if not brand: continue
        subj = s.get("subject") or ""; step = s.get("step_n")
        vf = vfeat.get((brand, step), {})
        sent_at = s.get("sent_at") or ""
        hour = int(sent_at[11:13]) if len(sent_at) >= 13 and sent_at[11:13].isdigit() else None
        rows.append({
            "brand": brand, "step": step,
            "replied": 1 if s.get("replied") else 0,
            "opened": 1 if s.get("opened_at") else 0,
            "clicked": 1 if s.get("clicked_at") else 0,
            "bounced": 1 if s.get("bounced") else 0,
            "delivered": 0 if (s.get("bounced") or s.get("error")) else 1,
            "subj_chars": len(subj), "subj_words": len(subj.split()),
            "subj_q": 1 if "?" in subj else 0, "subj_lower": 1 if subj == subj.lower() else 0,
            "body_words": vf.get("body_words", np.nan), "has_give": vf.get("has_give", np.nan),
            "hour": hour,
        })
    df = pd.DataFrame(rows)
    df = df[df["step"].notna()]
    n_sends = len(df); n_reply = int(df["replied"].sum())
    print(f"sends mapped: {n_sends} | replies: {n_reply} | delivered: {int(df['delivered'].sum())}")

    res = {"n_sends": n_sends, "n_replies": n_reply, "delivered": int(df["delivered"].sum())}

    # ── per-brand table (Wilson CI on reply rate over delivered) ──
    brand_tbl = []
    for b, g in df.groupby("brand"):
        deliv = int(g["delivered"].sum()); rep = int(g["replied"].sum())
        p, lo, hi = wilson(rep, deliv)
        brand_tbl.append({"brand": b, "sends": len(g), "delivered": deliv, "replies": rep,
                          "reply_rate": round(p*100, 2), "ci_lo": round(lo*100, 2), "ci_hi": round(hi*100, 2),
                          "open_rate": round(g["opened"].sum()/max(deliv,1)*100, 1),
                          "click_rate": round(g["clicked"].sum()/max(deliv,1)*100, 1),
                          "bounce_rate": round(g["bounced"].sum()/max(len(g),1)*100, 1)})
    brand_tbl.sort(key=lambda x: -x["reply_rate"]); res["by_brand"] = brand_tbl

    # ── per-step table ──
    step_tbl = []
    for st, g in df.groupby("step"):
        deliv = int(g["delivered"].sum()); rep = int(g["replied"].sum())
        p, lo, hi = wilson(rep, deliv)
        step_tbl.append({"step": int(st), "sends": len(g), "delivered": deliv, "replies": rep,
                         "reply_rate": round(p*100, 2), "ci_lo": round(lo*100, 2), "ci_hi": round(hi*100, 2)})
    res["by_step"] = step_tbl

    # ── funnel ──
    deliv = int(df["delivered"].sum())
    res["funnel"] = {"sent": n_sends, "delivered": deliv,
                     "delivered_pct": round(deliv/max(n_sends,1)*100, 1),
                     "open_pct": round(df["opened"].sum()/max(deliv,1)*100, 1),
                     "click_pct": round(df["clicked"].sum()/max(deliv,1)*100, 1),
                     "reply_pct": round(df["replied"].sum()/max(deliv,1)*100, 2)}

    # ── LINEAR (point-biserial = Pearson with binary) per-send: feature vs replied ──
    feats = ["opened", "clicked", "subj_chars", "subj_words", "subj_q", "subj_lower", "body_words", "has_give", "step", "hour"]
    lin = {}
    dd = df.dropna(subset=["body_words", "has_give"])  # body feats need variant join
    for f in feats:
        sub = df.dropna(subset=[f])
        if sub[f].nunique() < 2 or sub["replied"].nunique() < 2:
            lin[f] = None; continue
        r, p = stats.pearsonr(sub[f].astype(float), sub["replied"].astype(float))
        rho, prho = stats.spearmanr(sub[f].astype(float), sub["replied"].astype(float))
        lin[f] = {"pearson_r": round(r, 4), "pearson_p": round(p, 4),
                  "spearman_rho": round(rho, 4), "spearman_p": round(prho, 4), "n": len(sub)}
    res["per_send_corr"] = lin

    # ── per-VARIANT cell aggregation (brand, step): continuous reply_rate ──
    cells = []
    for (b, st), g in df.groupby(["brand", "step"]):
        deliv = int(g["delivered"].sum())
        if deliv < 5: continue  # need a floor for a rate to mean anything
        cells.append({"brand": b, "step": int(st), "n": deliv,
                      "reply_rate": g["replied"].sum()/deliv,
                      "open_rate": g["opened"].sum()/deliv,
                      "subj_words": g["subj_words"].mean(), "subj_chars": g["subj_chars"].mean(),
                      "body_words": g["body_words"].mean(), "has_give": g["has_give"].mean(),
                      "subj_q": g["subj_q"].mean()})
    cdf = pd.DataFrame(cells)
    res["n_variant_cells"] = len(cdf)
    cell_corr = {}
    if len(cdf) >= 5:
        for f in ["open_rate", "subj_words", "subj_chars", "body_words", "has_give", "step", "subj_q"]:
            if cdf[f].nunique() < 2: cell_corr[f] = None; continue
            r, p = stats.pearsonr(cdf[f], cdf["reply_rate"])
            rho, pr = stats.spearmanr(cdf[f], cdf["reply_rate"])
            cell_corr[f] = {"pearson_r": round(r, 3), "pearson_p": round(p, 3),
                            "spearman_rho": round(rho, 3), "spearman_p": round(pr, 3)}
        # non-linear: mutual information + RF importance (reply_rate ~ features)
        X = cdf[["open_rate", "subj_words", "body_words", "has_give", "step"]].fillna(0).values
        y = cdf["reply_rate"].values
        try:
            mi = mutual_info_regression(X, y, random_state=0)
            res["mutual_info"] = dict(zip(["open_rate", "subj_words", "body_words", "has_give", "step"], [round(float(x), 4) for x in mi]))
            rf = RandomForestRegressor(n_estimators=300, random_state=0).fit(X, y)
            res["rf_importance"] = dict(zip(["open_rate", "subj_words", "body_words", "has_give", "step"], [round(float(x), 4) for x in rf.feature_importances_]))
        except Exception as e:
            res["mutual_info_error"] = str(e)
    res["variant_cell_corr"] = cell_corr

    # ── CHARTS ──
    plt.rcParams.update({"font.family": "DejaVu Sans", "axes.edgecolor": "#cccccc", "figure.dpi": 130})
    # 1. reply rate by brand
    bt = [x for x in brand_tbl if x["delivered"] >= 20]
    if bt:
        fig, ax = plt.subplots(figsize=(7, 3.6))
        names = [x["brand"] for x in bt]; vals = [x["reply_rate"] for x in bt]
        errs = [[x["reply_rate"]-x["ci_lo"] for x in bt], [x["ci_hi"]-x["reply_rate"] for x in bt]]
        ax.bar(names, vals, color=ORANGE, yerr=errs, capsize=4, ecolor=SLATE)
        ax.set_ylabel("reply rate % (of delivered)"); ax.set_title("Reply rate by brand (95% Wilson CI)")
        plt.xticks(rotation=30, ha="right"); plt.tight_layout(); fig.savefig(OUT/"reply_by_brand.png"); plt.close()
    # 2. funnel
    fig, ax = plt.subplots(figsize=(7, 3.4))
    f = res["funnel"]; stages = ["sent", "delivered", "opened", "clicked", "replied"]
    vals = [100, f["delivered_pct"], f["delivered_pct"]*f["open_pct"]/100, f["delivered_pct"]*f["click_pct"]/100, f["delivered_pct"]*f["reply_pct"]/100]
    ax.barh(stages[::-1], vals[::-1], color=[ORANGE]*5); ax.set_xlabel("% of sent")
    ax.set_title("Funnel (operation-wide)")
    for i, v in enumerate(vals[::-1]): ax.text(v+1, i, f"{v:.1f}%", va="center", fontsize=9)
    plt.tight_layout(); fig.savefig(OUT/"funnel.png"); plt.close()
    # 3. reply rate by step
    st = [x for x in step_tbl if x["delivered"] >= 10]
    if st:
        fig, ax = plt.subplots(figsize=(7, 3.2))
        ax.plot([x["step"] for x in st], [x["reply_rate"] for x in st], "o-", color=ORANGE)
        ax.set_xlabel("sequence step"); ax.set_ylabel("reply rate %"); ax.set_title("Reply rate by sequence step")
        plt.tight_layout(); fig.savefig(OUT/"reply_by_step.png"); plt.close()
    # 4. correlation bar (variant-cell Spearman)
    if cell_corr:
        items = [(k, v["spearman_rho"]) for k, v in cell_corr.items() if v]
        if items:
            fig, ax = plt.subplots(figsize=(7, 3.6))
            items.sort(key=lambda x: x[1])
            ax.barh([k for k, _ in items], [v for _, v in items], color=[ORANGE if v >= 0 else "#2b2a2b" for _, v in items])
            ax.axvline(0, color="#999"); ax.set_xlabel("Spearman rho vs reply rate"); ax.set_title("Non-linear (rank) correlation with reply rate")
            plt.tight_layout(); fig.savefig(OUT/"corr_spearman.png"); plt.close()

    (OUT/"stats.json").write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    print("\n=== SUMMARY ===")
    print("by_brand:", json.dumps(brand_tbl, indent=1)[:1200])
    print("funnel:", res["funnel"])
    print("variant_cell_corr:", json.dumps(cell_corr, indent=1))
    print("mutual_info:", res.get("mutual_info"))
    print("rf_importance:", res.get("rf_importance"))
    print("charts + stats.json ->", OUT)


if __name__ == "__main__":
    main()
