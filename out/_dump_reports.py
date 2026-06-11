# -*- coding: utf-8 -*-
import importlib.util, sys
from pathlib import Path
REPO = Path(r"C:\Users\bernh\local-email-stack")
sys.path.insert(0, str(REPO / "sequences"))
def load(name, path):
    s = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(s); s.loader.exec_module(m); return m
# Diraya
dz = load("dz", REPO/"scripts"/"diraya-report.py")
agg = dz.aggregate(dz.fetch()); (REPO/"out"/"_diraya_report.html").write_text(dz.render(agg), encoding="utf-8")
print("diraya ->", len(dz.render(agg)), "bytes; sends", agg["today"]["sent"])
# Aureon (daily-report) — render via its own pipeline
ar = load("ar", REPO/"scripts"/"daily-report.py")
data = ar.fetch_all_data(); aagg = ar.aggregate(data); html = ar.render_html(aagg)
(REPO/"out"/"_aureon_report.html").write_text(html, encoding="utf-8")
print("aureon ->", len(html), "bytes")
