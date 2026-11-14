"""python -m alpha_engine.input_research.data_foundation.replay_nfl_pbp2 PBP_DIR GAMES.csv OUT.json [--quick]   (batch-2 NFL pbp builders; same generic replay gates as replay_nfl_pbp)"""
import json, sys
from pathlib import Path
from ...features import nfl_pbp_ext2 as X
from . import replay_generic as G


def main(a=None) -> int:
    a = a or sys.argv[1:]; raw = X.load_raw(a[0], a[1])
    r = G.run(X, raw, "NFL", {"pbp": ("game_id", X.SCRAMBLE), "games": ("game_id", ["home_score"])}, quick="--quick" in a)
    Path(a[2]).write_text(json.dumps(r, default=str, indent=0)); print("replayed", len(r["inputs"]), r["seconds"], "s"); return 0


if __name__ == "__main__":
    raise SystemExit(main())
