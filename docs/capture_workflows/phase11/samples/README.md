# Phase 11 capture-quality fixtures (synthetic)

These files are **synthetic fixtures** derived only in shape from archived captures. Player names, provider IDs, team IDs,
birthplaces, physical measurements and run IDs are replaced. Only the fields the classifiers read (status labels, observation
and report timestamps, source labels) keep realistic values so the tests exercise real edge cases.

The original raw provider rows (ESPN roster rows, DailyFaceoff goalie rows) were removed before this work reached `main`
because their redistribution rights are unresolved. The originals stay in the owner's private capture archive.

`nba_status_context_*.json` is a run-count summary (no provider records).
