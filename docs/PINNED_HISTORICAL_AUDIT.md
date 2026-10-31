# Pinned Historical Audit — Genuine CFB and MLB Records

This is the first **real-source** reproducibility exercise in SIFT Alpha. It does **not** purport to be a deep pitcher-vs-lineup or NBA guard-vs-defense model; it establishes an honest, guarded evidence pipeline before those investigations can begin.

## Input provenance

Two public **derived** datasets originating in the user's existing sports research repositories. Both are pinned to full Git commits and Git blob SHA-1 digests, so that the auditor fails on changed content:

- CFB: `chmoses98/cfb-edge-finder`, `prospective/2026/settlements.jsonl`, pinned revision in `research/pinned_sources.json`. Capture and pregame timestamps, game scores, control identity, quoted prices and settlement records. The sample contains 25 distinct settled games on first inspection.
- MLB: `chmoses98/edge-finder-api`, `data/edgelab/forward_replay_status.json`, pinned revision in `research/pinned_sources.json`. 81 historical workflow days on first inspection; contains only replay eligibility and results such as completed, no decision, or missing input.

Both files are fetched read-only from **raw.githubusercontent.com**, with strict repository/path allowlisting, fixed commit and hash, 100 kB read limits and 18-second timeout. No credential or billed external API. The owner-authored derived record availability is not proof that original third-party licensing, point-in-time underlying data truth, or independent settlement corroboration has been fully validated.

## Run

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
python3 -m alpha_engine.historical_cli --out artifacts/historical_diagnostics.json
```

For CI, the historical audit is intentionally **not** a scheduled process. The PR verification runs it once to prove the pinned public archives can be read and that findings reproduce. It emits a small JSON report with source SHA256, actual sample denominators, conservative descriptive metrics and a hard **RESEARCH_ONLY** authority label.

## Independent checks

- CFB: unique physical-game events, valid schema, legitimate pregame capture and model publication clocks, actual settlement after kickoff, score/outcome consistency, quote bounded in (0,1), descriptive market-price Brier and Wilson interval on **all** source games.
- MLB: unique archive-date keys, explicit timestamp, permitted outcomes, and rejection of any retroactive upgrade of ineligible days to completed.
- Independent reviewer recomputes all reported numbers from the same pinned bytes; alters to win-rate or trading authority are rejected.
- Deliberately adversarial unit tests cover future-data leakage, duplicate games, score reversals, paid/unknown provider references and source-content tampering.

**Limitations:** The reviewer shares input bytes and codebase; this is a deterministic replication guard, not external independent scientific replication. The CFB sample is small and selected; quoted `entry.price` is not verified as a contemporaneously executable ask, and there is no untouched holdout. MLB replay statuses are *not pitch-level data*. Neither audit may claim edge, ROI, causality or actual betting authority. Full validation requires stronger original source verification, well specified sample selection, forward predictions, executable prices, fees, distributional evaluation, and prospective holdout.

## Next work

1. Audit free, permitted pitch-level event data (e.g. availability of Statcast coverage/terms) and lineup start-state history for MLB, without mistaking postgame observed pitch counts for pregame inputs.
2. Audit independently available NBA potential assists, defender/matchup and lineup clock granularity. If licensed tracking is unavailable, document this honestly and find an identifiable, scientifically meaningful alternative.
3. Write a frozen experimental protocol and run genuinely deep, high powered, independent studies as data permits.
4. Only **after** the above qualify and validate: enable independent self-directed experiment scheduling, with checkpoints and failure alerts. No unsupervised paid requests or trading.
