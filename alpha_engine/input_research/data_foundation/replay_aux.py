"""Point-in-time replay of AUXILIARY columns of a certified builder (RESEARCH_ONLY): columns an experiment consumed that are not catalog inputs.

    python -m alpha_engine.input_research.data_foundation.replay_aux cfb_espn RAW_DIR[,RAW_DIR...] OUT.json [--quick]

Runs exactly the generic replay (determinism, 3 truncation cuts, 3 perturbation seeds, own-game, non-vacuity) on the builder's
intermediate columns under a pseudo-spec `aux.<family>.base`. The result is evidence about leakage only: it does NOT certify the columns
(no blind re-implementation, no catalog entry, no ledger row) and it is never read by verified_coverage.
"""
import json
import sys
import types
from pathlib import Path

from . import replay_generic as G
from ...features.core import FeatureSpec

AUX = {"cfb_espn": ("cfb_espn_ext", "BASE", "CFB walk-forward ridge expectations: regulation points, margin, total (intermediate columns; consumed by research/cfb_bet_selection and cfb_forward_validation)")}


def main(a=None) -> int:
    a = a or sys.argv[1:]; fam = a[0]; quick = "--quick" in a
    modname, attr, desc = AUX[fam]
    X = __import__(f"alpha_engine.features.{modname}", fromlist=["x"]); cols = list(getattr(X, attr))
    spec = FeatureSpec(X.S, f"aux.{fam}.base", "team", cols, "AUXILIARY", desc, [], ["not a catalog input; not blind-verified"], ["see builder"], "pregame_rolling")
    W = types.SimpleNamespace(compute=X.compute, specs=lambda: [spec], S=X.S)
    raw = X.load_raw(a[1])
    r = G.run(W, raw, X.S, {"games": ("game_id", X.CONTENT)}, games_table="games", games_date_col="game_date", quick=quick)
    r["kind"] = "replay_aux"; r["note"] = __doc__.split("\n\n")[2].strip()
    Path(a[2]).write_text(json.dumps(r, indent=1) + "\n"); t = r["inputs"][spec.catalog_id]["tests"]
    print({k: (v["ok"] if isinstance(v, dict) else [x["ok"] for x in v]) for k, v in t.items() if k in ("determinism", "truncation", "perturbation", "own_game", "pit_check_perturbation_not_vacuous")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
