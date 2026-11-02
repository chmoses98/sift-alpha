# sweep-data

Data branch for Kalshi series sweeps (see `.github/workflows/kalshi-series-sweep.yml`).

- `sweeps/<queue>/latest.json` + `state_*.json`: raw sweeper state with provenance (written by the publish job once PR #10 is on main).
- `seed/*.compact.json`: the 2026-11-02 MLB (215) and soccer (48) sweep results, parsed from job logs; marked as such.
- `index.jsonl`: append-only publish log.
