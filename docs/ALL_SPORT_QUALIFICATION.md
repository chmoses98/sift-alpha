# SIFT Alpha — All-sport metadata qualification

This is the **first cross-sport verification milestone**, not a complete market-research engine.

Eight public source references from our existing repos are immutable full-commit pinned, content hash-verified and read through strictly bounded public `raw.githubusercontent.com` downloads. No authentication, paid API calls or orders. Validation is `$0` within standard GitHub Actions public repository runners subject to their actual terms/quotas.

All sports are represented: NFL, CFB, NBA, NHL, MLB, CBB, soccer, tennis. NCAA baseball remains a data/market-feasibility track rather than claiming it has existing qualified Kalshi contracts.

```sh
python3 -m unittest discover -s tests -p 'test_all_sport.py' -v
python3 -m alpha_engine.all_sport_cli
```

**What this proves:** each pinned file exists with expected bytes, appropriate schema and type-specific denominators. It establishes historical evidence of market-capture activity and explicit blockers (e.g. MLB ineligible replay days, CBB futures-heavy contract population, soccer unpublished lineups).

**What it doesn't prove:** exact historical price tape completeness, legitimate order fills, independently resolved outcomes, a useful predictive model or any betting edge. Market open-set tickers, settlement archive rows, market snapshots and independent physical games are *not* interchangeable sample counts. Current status pointers are historically pinned and MUST NOT be presented as live current status.

Work in order: full-tape event/market price history reconstruction by sport; point-in-time game/lineup/context joins; contract outcome and exact settlement rule verification; fee-aware backtest and adversarial independent evaluation; only then autonomous self-directed market discoveries.

Main issue: [P0 Market Warehouse #4](https://github.com/chmoses98/sift-alpha/issues/4).
