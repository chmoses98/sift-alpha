"""python -m alpha_engine.input_research.data_foundation.replay_nfl_part PBP_DIR PART_DIR GAMES.csv OUT.json [--quick]   (participation-based NFL builders; same generic replay gates)"""
import json, sys
from pathlib import Path
from ...features import nfl_part_ext as X
from . import replay_generic as G


def main(a=None) -> int:
    a = a or sys.argv[1:]; raw = X.load_raw(a[0], a[1], a[2])
    r = G.run(X, raw, "NFL", {"pbp": ("game_id", X.SCR_PBP), "part": ("nflverse_game_id", X.SCR_PART), "games": ("game_id", ["home_score"])}, quick="--quick" in a)
    Path(a[3]).write_text(json.dumps(r, default=str, indent=0)); print("replayed", len(r["inputs"]), r["seconds"], "s"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
