"""Walk-forward #307/p15 features (cfg lam_c=0, periods=True) per season, using the research code verbatim.
    CFB_WORK=/tmp/cfb_work python feats.py RESEARCH_DIR   (RESEARCH_DIR = checkout of the p15 branch research/cfb_challenger)
"""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
import os

R = Path(sys.argv[1])
sys.path[:0] = [str(R), str(R / "phase15")]
WORK = Path(os.environ.get("CFB_WORK", "/tmp/cfb_work"))


def job(s):
    import pandas as pd
    import p15model as X
    from challenger import model as M
    out = WORK / f"feat_s{s}.parquet"
    if out.exists():
        return s
    tg = pd.read_parquet(WORK / "team_games.parquet")
    per = pd.read_parquet(WORK / "periods.parquet")
    tgp = X.add_period_points(tg, per)
    X.walk_forward(tgp, M.games_table(tg), M.preseason_table(WORK / "2014-2026"), X.Params15(periods=True), [s]).to_parquet(out)
    return s


if __name__ == "__main__":
    with ProcessPoolExecutor(4) as ex:
        for s in ex.map(job, [2026, 2025, 2024, 2023, 2022, 2021, 2019, 2018, 2017, 2016]):
            print("done", s, flush=True)
