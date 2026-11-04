# Fee schedule validation (2026-11-04)

Method: `scripts/validate_fee_schedule.py` compares each real opening buy's EXCHANGE-REPORTED fee with `ceil(0.07·C·P(1−P))`.
Result (NFL/CFB/NBA/NHL ledgers, 646 wagers, 53 series): 643 match the taker 0.07 schedule (implied rate 0.0699-0.0703);
3 outliers (implied 0.042-0.068, NFL spread/total families, likely multi-fill or partly maker); **0 maker-coded fills; 0 zero-fee fills**.

What this does and does not establish:
- Taker coefficient 0.07 is empirically confirmed for every series observed.
- The maker coefficient (0.0175 in `canonical.estimate_fee`) is **unverified**: no real maker fill exists in the ledgers, and the
  exchange's own fee schedule and series `fee_type`/`fee_multiplier` fields could not be fetched (kalshi.com and the API host
  are not reachable from this environment). Third-party descriptions say most series charge makers nothing and some sports
  series charge a quarter of the taker rate, so 0.0175 is an upper bound for resting orders. Execution research must therefore
  report maker fee sensitivity at 0 and 0.0175, never a single assumed point.
- Series-level multipliers and date changes cannot be confirmed here; every observed series was consistent with 0.07 flat.

## Erratum (2026-11-04, execution track — see docs/EXECUTION_RESEARCH.md §2)
The statements above that "third-party descriptions say most series charge makers nothing" and that "0.0175 is an upper bound for resting orders" are **not supported for the NFL moneyline, spread and total series**.
The exchange's own series metadata, captured weekly on `market-data` (`data/kalshi/fees/*.json`, `GET /series` `fee_type`), labels `KXNFLGAME`, `KXNFLSPREAD` and `KXNFLTOTAL` as `quadratic_with_maker_fees` (makers pay) and 367 of 392 archived NFL-family series as `quadratic` (makers pay 0).
The committed schedule window attests a maker multiplier only for `KXNFLGAME` (⇒ 0.0175); `KXNFLSPREAD`/`KXNFLTOTAL` are maker-fee series with NO listed multiplier (UNVERIFIED, fail closed). NBA/NHL/CFB series are not in any fee archive (UNVERIFIED).
The taker conclusion (0.07, 643/646 fills) stands. Still no real maker fill exists, so no maker coefficient is *observed*: all execution results use scenarios M0 (0), M25 (0.0175), M100 (0.07). Evidence tool: `research/exec_track/fee_evidence.py`.
