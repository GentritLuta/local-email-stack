"""Print the daily report's geography aggregation (ready vs queue per metro)."""
import importlib.util
from pathlib import Path
R = Path(".").resolve()
s = importlib.util.spec_from_file_location("dr", R / "scripts" / "daily-report.py")
dr = importlib.util.module_from_spec(s); s.loader.exec_module(dr)
agg = dr.aggregate(dr.fetch_all_data())
g = agg["geography"]
print(f"\nAUREON LEAD GEOGRAPHY — {g['covered']}/{g['total']} "
      f"({100*g['covered']//max(g['total'],1)}%) in a metro with a ready curated list\n")
for metro, r in list(g["by_metro"].items())[:16]:
    print(f"  {'READY' if r['covered'] else 'queue':5}  {r['leads']:4}  {metro:28} [{r['state'] or '-'}]")
