"""Series-aware Kalshi fee evidence and explicit fee scenarios.

Evidence ladder for the MAKER rate of a series (never merged, always reported with the result):
  EXCHANGE_FEE_TYPE   the exchange's own ``GET /series`` ``fee_type`` captured weekly on market-data (``data/kalshi/fees``):
                      ``quadratic`` = taker-only (maker pays 0); ``quadratic_with_maker_fees`` = makers pay too.
  SCHEDULE_ATTESTED   the committed schedule window (nfl-edge-finder ``config/kalshi_fee_schedule.json``, operator-attested reading
                      of the regulatory Fee Schedule) lists the series' maker multiplier.  Coefficient 0.0175 x multiplier.
  UNVERIFIED          maker-fee type with no listed multiplier, or a series with no fee archive at all (NBA/NHL): sensitivity only.
The TAKER coefficient 0.07 is empirically confirmed against 643/646 real exchange-reported fees (docs/FEE_VALIDATION.md, PR #26).
No real maker fill exists in any ledger, so NO maker fee is *observed*; every maker result is reported under explicit scenarios.

Whole-order rounding: ``ceil_to_cent(rate*C*P*(1-P))`` (the convention of sift_clv/PR #25).  The exchange's per-order rounding
accumulator makes fragmented fills converge to this; ``fills_fee_upper`` (each fill ceiled independently) is the worst case.
"""
from __future__ import annotations
import glob, json, math, os
from dataclasses import dataclass

TAKER_COEF, MAKER_COEF = 0.07, 0.0175

# Fee scenarios for MAKER fills (taker fills always 0.07). Names are used in every report.
SCENARIOS = {
    "M0": 0.0,                # makers free (what a taker-only 'quadratic' series would charge)
    "M25": MAKER_COEF,        # 0.0175 = quarter of the taker rate (schedule coefficient for maker-fee series)
    "M100": TAKER_COEF,       # stress: makers pay the taker rate
}


def _ceil_cent(x: float) -> float:
    return math.ceil(round(x * 100.0, 9)) / 100.0


def order_fee(price_c: int, qty: float, coef: float) -> float:
    """Whole-order fee in dollars for ``qty`` contracts at integer-cent price ``price_c``."""
    if qty <= 0 or coef <= 0:
        return 0.0
    p = price_c / 100.0
    return _ceil_cent(coef * qty * p * (1.0 - p))


def fills_fee_upper(fills, coef: float) -> float:
    """Worst case: every fill (price_c, qty) ceiled to the cent independently."""
    return sum(order_fee(p, q, coef) for p, q in fills)


def taker_fee_per_contract(price_c: int, qty: float = 10.0) -> float:
    return order_fee(price_c, qty, TAKER_COEF) / qty


@dataclass(frozen=True)
class SeriesFee:
    series: str
    fee_type: str | None          # exchange fee_type, None if no archive for the series
    fee_multiplier: float | None
    maker_evidence: str           # EXCHANGE_FEE_TYPE | SCHEDULE_ATTESTED | UNVERIFIED
    maker_coef_supported: float | None   # coefficient supported by evidence (None = unknown)
    note: str = ""


def load_fee_archive(fees_dir: str):
    """{date: {series: (fee_type, multiplier)}}, plus the fee_changes list of the latest capture."""
    out, changes = {}, []
    for f in sorted(glob.glob(os.path.join(fees_dir, "*.json"))):
        d = json.load(open(f))
        out[os.path.basename(f)[:-5]] = {k: (v.get("fee_type"), v.get("fee_multiplier")) for k, v in d["series"].items()}
        changes = d.get("fee_changes", {}).get("changes", changes)
    return out, changes


def series_fee(series: str, archive, schedule_series: dict | None = None) -> SeriesFee:
    """Evidence-graded fee record for one series using the LATEST archived capture."""
    sched = schedule_series or {}
    if not archive:
        return SeriesFee(series, None, None, "UNVERIFIED", None, "no fee archive for this series")
    last = archive[max(archive)]
    if series not in last:
        return SeriesFee(series, None, None, "UNVERIFIED", None, "series absent from exchange fee archive")
    ft, mult = last[series]
    types = {a.get(series, (None,))[0] for a in archive.values()}
    note = "" if len(types) == 1 else f"fee_type changed across captures: {sorted(map(str, types))}"
    if ft == "quadratic":
        return SeriesFee(series, ft, mult, "EXCHANGE_FEE_TYPE", 0.0, "taker-only series: maker fee 0" + (("; " + note) if note else ""))
    if series in sched:
        return SeriesFee(series, ft, mult, "SCHEDULE_ATTESTED", MAKER_COEF * float(sched[series].get("maker_multiplier", 0)), note)
    return SeriesFee(series, ft, mult, "UNVERIFIED", None, "maker-fee series with no listed maker multiplier (fail closed)")


def effective_from(changes, series: str):
    """Earliest exchange-announced fee change timestamp for a series (None = none recorded)."""
    ts = sorted(c["scheduled_ts"] for c in changes if c["series_ticker"] == series)
    return ts[0] if ts else None
