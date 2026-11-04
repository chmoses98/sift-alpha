# Prospective shadow-order ledger (research-only)

**Purpose.** Compare `BUY_NOW`, `WAIT`, `LIMIT`, `LIMIT_FB` (resting bid, remainder taken at the deadline) and `PASS` on *matched* decisions with equal exposure, using only point-in-time information, so execution questions can be answered out of sample without any order being placed.
Nothing here can place an order: no credentials, no exchange client, GET-only git reads of public market data. Every record is `status = RESEARCH_ONLY`, `generated = HYPOTHETICAL_SHADOW`; fill evidence is never `FILLED`.

## Pipeline (`.github/workflows/shadow-ledger.yml`, every 30 min + manual)
1. `research/exec_track/shadow_sync.py` — lists new capture runs of nfl-edge-finder `market-data` **by name** (blobless clone), sparse-checks-out only runs newer than `state.last_run_id`, appends KXNFLGAME quotes and **pre-kickoff** trades (de-duplicated on `trade_id`) to a compact extract.
2. `research/exec_track/shadow_ledger.py` — for each contract and horizon (7d/72h/48h/24h/6h/90m) the **first live quote at or after the horizon crossing** becomes the decision snapshot (`placed_at` = that quote's observation time ⇒ quote age ≈ 0, no look-ahead). One PLACED row per tactic: BUY_NOW, WAIT, PASS and, for each rule in AT_BID / BID_PLUS_1 / ASK_MINUS_2, LIMIT (unfilled = no bet) and LIMIT_FB (`fallback = TAKE_AT_CLOSE`). Fields: bid, ask, spread, displayed sizes, **displayed queue at the limit price**, quote age, source run, deadline (last quote ≤ kickoff−15m).
   After the deadline: OBSERVED rows — `TAPE_FILL_BOUND_LO` (a print strictly below our price: confirmed through-fill, queue-independent), `TAPE_FILL_BOUND_UP` (front-of-queue possible), `TAPE_TOUCH` (displayed-queue central estimate, never a fill) — and a SETTLED row with close bid/ask (fallback / WAIT price), mid movement to the close, and the settlement result when known (`win = null` until then; never scored as a loss).
3. `research/exec_track/shadow_report.py` / `sift_exec/shadow_report.py` — matched equal-exposure table (¢/contract, all-in of fees; taker 0.07, maker scenarios M0/M25/M100; fill range lo/central/up), game-clustered bootstrap, split by `generation`.
4. Output is an append-only JSONL on the `shadow-data` branch.

## Prospective vs retrospective
`prospective = (recorded_at − placed_at) ≤ 30 min`. Rows rebuilt later from the archive are `RETROSPECTIVE_REPLAY` and **must not** be counted as prospective validation (the dashboard and tests enforce the separation). Because the job runs every 30 minutes against a ~15-minute capture cadence, rows created by the schedule are prospective.

## Replay of the existing 2026 capture (weeks 1–8; 11,916 decisions, 11,466 closed; all RETROSPECTIVE_REPLAY)
Matched `LIMIT_FB − WAIT` (¢/contract, game-clustered 95% interval; 107 games), displayed-queue central fill estimate:
| horizon | rule | M0 | M25 | M100 | lo / up fill bound at M25 |
|---|---|---|---|---|---|
| 24h | at bid | +0.60 [0.46, 0.75] | +0.43 [0.31, 0.56] | +0.01 [−0.10, 0.10] | +0.33 / +2.17 |
| 24h | ask−2 | +0.82 [0.66, 0.98] | +0.67 [0.53, 0.81] | +0.28 [0.18, 0.37] | +0.11 / +0.68 |
| 6h | at bid | +0.41 | +0.29 | −0.01 | +0.25 / +2.16 |
| 90m | at bid | +0.26 | +0.19 | +0.03 | +0.18 / +2.16 |
The "up" bound assumes every order sits at the front of the queue (displayed queues are 10⁵ contracts) and is not a realistic estimate. Conservative (`lo`) values at M100 are ≈ 0: no improvement survives both a taker-equivalent maker fee and a through-print-only fill rule.
Reproduces the independent 2026 study (`reports/exec_track/nfl_live_2026.json`) to within the rule definitions; aggregates in `reports/exec_track/shadow_replay_summary.json`.

## Not done / limits
Moneyline only (KXNFLGAME); spread/total need their own series fee evidence (UNVERIFIED maker multiplier) and a quote source with depth. Queue behind the displayed size at levels *below* the best bid is unknown (assumed 0 ⇒ optimistic for ask−2). The first scheduled run requires this workflow to exist on `main`; until then no prospective rows exist.
