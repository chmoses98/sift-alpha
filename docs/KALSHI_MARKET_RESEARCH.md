# Kalshi archive-first research architecture

**Priority: P0.** Alpha's archive of Kalshi contracts, book snapshots, trades, movements, and settlements is a primary scientific dataset. The owner correctly identified that focusing first on small replay status reports overlooked a much larger and richer research corpus.

Verified observations, as of Oct 30 2026 (not summed across sports):
- CFB current main catalog: **13,122 contracts, 239 physical games**, with latest snapshot/change timestamp, not a full historical movement history.
- NBA archive health: **13,716 discovered markets**; **59,840 settlement records** (record count, not proven unique contracts); **4,101 unresolved ontology markets**. NBA keeps full market checkpoints, market deltas, orderbooks and settlements. Reconstructing checkpoints and deltas must preserve observation times and chain hashes.
- NFL open-set capture on Oct 24: **16,673 open tickers**, with timestamped quotes, books, trades and captures. Open ticker set is not a unique settled sample.
- CBB Oct 25 capture: **12,209 contracts**, of which **8,643 FUTURES_OTHER** and **368 GAME_WINNER**. Future/event contracts, their settlement times and data horizons differ from game props.
- NHL: market checkpoints, deltas, books and settlement partitions. MLB: market, CLV quote and settlement archives. Tennis: Kalshi captures. Soccer: JSONL snapshots and settlement archives. CFB: prospective settlement archive plus current market catalog.

## What should be analyzed

Alpha must build a canonical event and contract ontology that preserves **the exact settlement rule**, event identity, YES/NO side, period, line threshold, original series, league and underlying game. Never translate different market families into a common probability without exact rules.

A reliable time-series warehouse should have, at minimum, observation timestamp vs change timestamp, opened/pre-start cutoff, quote age, both sides' best bid/ask, displayed quantity and depth, trades, price history/deltas, market halt and lifecycle, settlement value and timestamp, fee schedule, and source commit/content hash. Match to the true independent **physical-game** outcome and player/team statistics while respecting nested correlated contract structures.

For every sport and market family, quantify **capture coverage**, proportion with actual pregame quotes, valid market-family classification, eligible settlement, and independent outcomes. Missing values are not zero. A series may be intentionally untradeable or unresolved. The discovery universe must include failed, unfilled, illiquid and unchanged markets; only examining settled winners introduces selection bias.

## Research priorities (after real tape reconstruction)
1. Market calibration by probability bucket, sport, contract type, time horizon, liquidity, spread and volatility.
2. Early-to-late price movement: does the signal persist after T-24h, T-6h, T-60m or T-10m, not just backward hindsight?
3. Compare actual returns on executable asks after fees and realistic depth, with a strict pregame cutoff, no assumption of passive maker fills.
4. Correlations, alternative expressions, winning-margin, period, player props, team totals: grouping must account for one outcome generating many correlated contracts.
5. Join sport context to price reactions (NBA injuries and potential assists; MLB pitcher lineup/pitch mix; CFB personnel/tempo; tennis starting time, etc.) to identify testable mechanisms.
6. Hypotheses are preregistered; repeated searches require multiple-comparison control and fresh chronological prospective validation. True post-fee edge is an empirical question, not a guarantee.

## Code in this initial archive pivot

`research/kalshi_archive_sources.json` contains **18 verified archive location entries** across eight sports. It is a registry of *where files live*, not an assertion of historical full-coverage. `alpha_engine/market_inventory.py` can query limited public GitHub metadata on demand. It does not download huge trading datasets, infer contract totals, join settlements, or create a trading strategy. `tests/test_market_inventory.py` guards against invented market counts and unsafe URLs.

Command (only when needed; not on a cron):

```sh
python3 -m unittest discover -s tests -p 'test_market_inventory.py' -v
python3 -m alpha_engine.market_inventory --out artifacts/market_archive_inventory.json
```

The main warehouse is the **next implementation step**: incremental stream/decompression adapters for historical archives, checkpoint/delta reconstruction, canonical contract/outcome joins, then preregistered experiments. This must remain within the **$0** budget. It should read the existing archives rather than duplicate expensive ongoing capture infrastructure.

This work is covered by [Market History Warehouse #4](https://github.com/chmoses98/sift-alpha/issues/4), [Scientific Cycle #3](https://github.com/chmoses98/sift-alpha/issues/3), and [Quality / $0 #2](https://github.com/chmoses98/sift-alpha/issues/2).
