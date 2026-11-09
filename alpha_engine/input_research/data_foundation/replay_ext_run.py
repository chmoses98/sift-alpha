"""Run the generic extension replay for one builder family and write verification/replay_ext-style JSON.

    python -m alpha_engine.input_research.data_foundation.replay_ext_run tennis RAW_DIR OUT.json [--quick]
    python -m alpha_engine.input_research.data_foundation.replay_ext_run mlb_pitch PITCH_DIR SCHEDULE.csv.gz OUT.json [--quick]
"""
import json
import sys
from pathlib import Path

from . import replay_generic as G


def main(a=None) -> int:
    a = a or sys.argv[1:]; fam = a[0]; quick = "--quick" in a
    if fam == "tennis":
        from ...features import tennis_ext as X
        raw = X.load_raw(a[1]); out = a[2]
        r = G.run(X, raw, "TENNIS", {"matches": ("game_id", ["score", "date"])}, games_table="matches", games_date_col="date", quick=quick)
    elif fam == "mlb_pitch":
        from ...features import mlb_pitch_ext as X
        raw = X.load_raw(a[1], a[2]); out = a[3]
        r = G.run(X, raw, "MLB", {"pitches": ("game_id", X.CONTENT), "games": ("game_id", ["home_score"])}, games_table="games", games_date_col="date", quick=quick)
    else:
        raise SystemExit("unknown family " + fam)
    Path(out).write_text(json.dumps(r, default=str, indent=0)); print("replayed", len(r["inputs"]), r["seconds"], "s"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
