"""Row-level grading. One input forecast -> exactly one result row with FOUR separately-labelled evaluations:
accuracy, market (paired vs market), economics (hypothetical + verified fills), clv. Accuracy never depends on prices;
value evaluations never rewrite the accuracy status. Nothing is dropped: every forecast row (including parse failures
handed in as ``rejects``) ends up in the output with a status and reason."""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal
from typing import Iterable, Optional

from sift_clv import canonical as C

from . import scoring as S
from .families import classify_contract
from .universe import normalise_eligible
from .schema import (BINARY, BLOCKED, CATEGORICAL, CONTINUOUS, GRADED, MARKET_INFORMED, ORDINAL_PMF, PENDING, R, SPORTS_ONLY,
                     UNSUPPORTED, FillRow, Forecast, Outcome, QuoteRow, SchemaError, forecast_from_row, fill_from_row,
                     outcome_from_row, parse_ts, quote_from_row)

HORIZONS = ((2.0, "le_2h"), (6.0, "2h_6h"), (24.0, "6h_24h"), (72.0, "24h_72h"))
DEFAULT_MAX_QUOTE_AGE_S = 3600
DEFAULT_MAX_CLOSE_AGE_S = 3600


CONFLICT = object()     # sentinel: >1 non-identical outcome rows for one market_id (cannot know which is true)


def horizon_bucket(h: float) -> str:
    for edge, name in HORIZONS:
        if h <= edge:
            return name
    return "gt_72h"


def _st(status, reason, **kw):
    return dict(status=status, reason=reason, **kw)


# ------------------------------------------------------------------ accuracy
def grade_accuracy(f: Forecast, o: Optional[Outcome], cls: dict, *, seen: set, as_of=None, grace_h: float = 24.0) -> dict:
    if f.forecast_id in seen:
        return _st(BLOCKED, R.DUPLICATE)
    if cls["support"] != "SCORABLE":
        return _st(UNSUPPORTED, cls["reason"])
    if f.scoring_type not in cls["allowed_scoring"]:
        return _st(UNSUPPORTED, R.TYPE_MISMATCH, detail=f"{f.scoring_type} not allowed for {cls['family']}")
    if not f.model_version:
        return _st(BLOCKED, R.NO_MODEL_VERSION)
    if f.frozen_at >= f.event_start:
        return _st(BLOCKED, R.NOT_FROZEN)
    if f.model_independence == SPORTS_ONLY and f.market_inputs_used:
        return _st(BLOCKED, R.INDEPENDENCE, detail=",".join(f.market_inputs_used))
    if o is None:
        if as_of is not None and f.event_start + timedelta(hours=grace_h) < as_of:
            return _st(BLOCKED, R.OVERDUE, detail=f"event_start {f.event_start.isoformat()} + {grace_h}h < data horizon {as_of.isoformat()}")
        return _st(PENDING, R.NO_OUTCOME)
    if o is CONFLICT:
        return _st(BLOCKED, R.OUTCOME_CONFLICT)
    if o.event_id != f.event_id:        # outcome joins on market AND event identity; a reused/recycled ticker must not grade
        return _st(BLOCKED, R.EVENT_MISMATCH, detail=f"forecast event {f.event_id!r} != outcome event {o.event_id!r}")
    if o.state == "pending":
        return _st(PENDING, R.EVENT_NOT_FINAL)
    if o.state == "void":
        return _st(BLOCKED, R.VOID)
    if o.observed_at is not None and f.frozen_at >= o.observed_at:
        return _st(BLOCKED, R.AFTER_OUTCOME)
    try:
        return _score(f, o)
    except (ValueError, TypeError, KeyError):
        return _st(BLOCKED, R.BAD_PAYLOAD)


def _score(f: Forecast, o: Outcome) -> dict:
    p, v = f.payload, o.value
    if f.scoring_type == BINARY:
        if v not in (0, 1, True, False):
            return _st(BLOCKED, R.BAD_OUTCOME)
        y = int(v)
        return _st(GRADED, R.OK, y=y, p=S.check_prob(p["p_yes"]), **S.binary_row(p["p_yes"], y))
    if f.scoring_type == CONTINUOUS:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return _st(BLOCKED, R.BAD_OUTCOME)
        return _st(GRADED, R.OK, y=v, **S.continuous_row(float(p["mean"]), float(v), p.get("quantiles")))
    if f.scoring_type == ORDINAL_PMF:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return _st(BLOCKED, R.BAD_OUTCOME)
        return _st(GRADED, R.OK, y=v, **S.ordinal_row(p["pmf"], float(v)))
    if f.scoring_type == CATEGORICAL:
        if not isinstance(v, str):
            return _st(BLOCKED, R.BAD_OUTCOME)
        return _st(GRADED, R.OK, y=v, **S.categorical_row(p["probs"], v))
    return _st(UNSUPPORTED, R.TYPE_MISMATCH)


# ------------------------------------------------------------------ point-in-time quotes
def pit_quote(f: Forecast, quotes: list, max_age_s: int = DEFAULT_MAX_QUOTE_AGE_S):
    """Last two-sided, uncrossed quote of THIS market observed at or before the forecast freeze. Never a later quote."""
    cands = [q for q in quotes if q.observed_at <= f.frozen_at]
    if not cands:
        return None, R.NO_QUOTE
    cq = [C.Quote.of(q.market_id, q.yes_bid, q.yes_ask, q.observed_at) for q in cands]
    best = C.select_close(cq, ticker=f.market_id, start=f.frozen_at + timedelta(microseconds=1))
    if best is None:
        return None, R.ONE_SIDED
    if (f.frozen_at - best.observed_at).total_seconds() > max_age_s:
        return None, R.STALE_QUOTE
    return best, R.OK


def _side_ask(q: C.Quote, side: str) -> Optional[Decimal]:
    return q.ask(side)


def hypothetical_roi_row(q: C.Quote, side: str, y: int, role: str = "taker") -> Optional[dict]:
    """One contract bought at the archived ask. QUOTED/HYPOTHETICAL: assumes a fill at the top-of-book ask, size 1, no queue,
    no slippage, no depth. Fee = canonical Kalshi estimate (hypothetical entries only). Held to settlement, no exit fee."""
    ask = _side_ask(q, side)
    if ask is None:
        return None
    fee = C.estimate_fee(ask, 1, role=role)
    win = 1 if (y == 1) == (side == "YES") else 0
    cost = ask + fee
    return dict(side=side, price=float(ask), fee=float(fee), cost=float(cost), pnl=float(Decimal(win) - cost), win=win)


# ------------------------------------------------------------------ full grading pass
def grade_all(forecast_rows: Iterable[dict], outcome_rows: Iterable[dict], quote_rows: Iterable[dict] = (),
              fill_rows: Iterable[dict] = (), *, eligible_rows: Optional[Iterable[dict]] = None, max_quote_age_s: int = DEFAULT_MAX_QUOTE_AGE_S,
              max_close_age_s: int = DEFAULT_MAX_CLOSE_AGE_S, edge_threshold: float = 0.0, as_of=None,
              outcome_grace_hours: float = 24.0) -> dict:
    """-> {rows: [...one per input forecast...], rejects: [...], accounting: {...}}.  ``as_of`` (data horizon) makes a missing outcome row for an event that started more than ``outcome_grace_hours`` earlier BLOCKED
    ``NO_OUTCOME_ROW_EVENT_OVERDUE`` instead of PENDING (a finished event with no outcome is a data gap, not "not yet").
    ``len(rows)+len(rejects)`` always equals
    the number of input forecast rows (asserted by the conformance suite)."""
    as_of_ts = None if as_of is None else parse_ts(as_of, "as_of")   # data horizon; None => no overdue judgement (PENDING only)
    outcomes, quotes, fills = {}, defaultdict(list), defaultdict(list)
    ev_errors = []
    for r in outcome_rows:
        try:
            o = outcome_from_row(r)
            prev = outcomes.get(o.market_id)
            if prev is None or prev is o:
                outcomes[o.market_id] = o
            elif prev is CONFLICT or (prev.event_id, prev.state, prev.value) != (o.event_id, o.state, o.value):
                # a second row for the same market that disagrees (incl. a different event_id): refuse to pick one.
                # Exact duplicates (same event/state/value) are harmless and collapse.
                outcomes[o.market_id] = CONFLICT
        except SchemaError as e:
            ev_errors.append(("outcome", str(e)))
    for r in quote_rows:
        try:
            q = quote_from_row(r)
            quotes[q.market_id].append(q)
        except SchemaError as e:
            ev_errors.append(("quote", str(e)))
    for r in fill_rows:
        try:
            fl = fill_from_row(r)
            fills[fl.forecast_id].append(fl)
        except SchemaError as e:
            ev_errors.append(("fill", str(e)))

    rows, rejects, seen, n_in = [], [], set(), 0
    for raw in forecast_rows:
        n_in += 1
        try:
            f = forecast_from_row(raw)
        except SchemaError as e:
            rejects.append(dict(forecast_id=raw.get("forecast_id"), sport=raw.get("sport"), accuracy=_st(BLOCKED, "SCHEMA_INVALID", detail=str(e))))
            continue
        cls = classify_contract(f.sport, f.native_family, f.market_id, f.line_role)
        o = outcomes.get(f.market_id)
        acc = grade_accuracy(f, o, cls, seen=seen, as_of=as_of_ts, grace_h=outcome_grace_hours)
        seen.add(f.forecast_id)
        row = dict(forecast_id=f.forecast_id, sport=f.sport, event_id=f.event_id, group_id=f.group_id, market_id=f.market_id,
                   family=cls["family"], base_kind=cls["base_kind"], period=cls["period"], line_role=f.line_role,
                   model_id=f.model_id, model_version=f.model_version, independence=f.model_independence or "UNDECLARED",
                   evidence_class=f.evidence_class, scoring_type=f.scoring_type, horizon_hours=round(f.horizon_hours, 3),
                   horizon=horizon_bucket(f.horizon_hours), event_date=f.event_start.date().isoformat(),
                   outcome_source=o.source if (o and o is not CONFLICT) else None, accuracy=acc)
        row.update(_value_evals(f, o, acc, quotes.get(f.market_id, []), fills.get(f.forecast_id, []),
                                max_quote_age_s, max_close_age_s, edge_threshold))
        rows.append(row)
    assert len(rows) + len(rejects) == n_in
    for fid in sorted(set(fills) - seen):       # fills that attach to no forecast are surfaced, not ignored
        ev_errors.append(("fill", f"{R.FILL_ORPHAN}: {fid} ({len(fills[fid])} fill rows)"))
    return dict(rows=rows, rejects=rejects, aux_rejects=ev_errors, n_input_forecasts=n_in,
                eligible=normalise_eligible(eligible_rows))


def _value_evals(f, o, acc, qs, fills, max_q_age, max_c_age, thr) -> dict:
    na = lambda why: dict(status=UNSUPPORTED, reason=why)  # noqa: E731
    out = dict(market=na(R.NOT_APPLICABLE), economics=na(R.NOT_APPLICABLE), clv=na(R.NOT_APPLICABLE))
    if acc["status"] != GRADED:
        for k in out:
            out[k] = _st(acc["status"] if acc["status"] in (PENDING,) else BLOCKED, "ACCURACY_" + acc["reason"])
        return out
    if f.scoring_type != BINARY:
        return out                        # nonbinary: priced comparison needs per-outcome quotes (documented gap), no Brier
    q, why = pit_quote(f, qs, max_q_age)
    if q is None:
        for k in out:
            out[k] = _st(BLOCKED, why)
        return out
    y, p = acc["y"], acc["p"]
    mp = float(q.mid("YES"))
    ind = f.model_independence
    out["market"] = _st(GRADED if ind else BLOCKED, R.OK if ind else R.NO_INDEPENDENCE, p_model=p, p_market=mp,
                        quote_age_s=(f.frozen_at - q.observed_at).total_seconds(),
                        signed_disagreement=p - mp,               # model - market; direction preserved, NOT evidence of edge
                        brier_model=acc["brier"], brier_market=(mp - y) ** 2, log_model=acc["log"],
                        log_market=S.binary_row(mp, y)["log"], independent=(ind == SPORTS_ONLY))
    side = "YES" if p > mp else "NO"
    h = hypothetical_roi_row(q, side, y)
    yes_edge = h and (p - h["cost"] if side == "YES" else (1 - p) - h["cost"])
    if h is None:
        out["economics"] = _st(BLOCKED, R.ONE_SIDED)
    else:
        out["economics"] = _st(GRADED, R.OK, execution_class="QUOTED_HYPOTHETICAL", fill_verified=False, role="taker",
                               edge_after_fee=yes_edge, traded_under_threshold=bool(yes_edge > thr), **h)
    out["economics"]["verified_fill"] = _verified(f, fills, y)
    # --- CLV: signed, close strictly before start, same ticker; fills measured separately
    cq = [C.Quote.of(x.market_id, x.yes_bid, x.yes_ask, x.observed_at) for x in qs]
    close = C.select_close(cq, ticker=f.market_id, start=f.event_start)
    cfills = [C.Fill.of(x.price, x.count, x.fee, x.is_taker) for x in screen_fills(f, fills)[0] if x.side == side]
    res = C.evaluate(ticker=f.market_id, side=side, recommendation=q, close=close, start=f.event_start, fills=cfills,
                     max_close_age_seconds=max_c_age)
    if res.status != C.OK:
        out["clv"] = _st(BLOCKED, R.NO_CLOSE, detail=res.status)
    else:
        d = lambda x: None if x is None else float(x)  # noqa: E731
        out["clv"] = _st(GRADED, R.OK, side=side, selection_clv=d(res.selection_clv),
                         quoted_execution_clv=d(res.quoted_execution_clv), actual_fill_clv=d(res.actual_execution_clv),
                         actual_fill_clv_fee_adjusted=d(res.fee_adjusted_difference),
                         actual_fill_verified=bool(cfills), notes=list(res.notes))
    return out


def screen_fills(f: Forecast, fills: list):
    """Context integrity for fills attributed to forecast ``f``: same market; not before the freeze it claims to follow;
    strictly before the event starts (a post-start fill is in-play, not the pre-event entry being evaluated).
    -> (valid fills, {reason: n} for the excluded ones). Excluded fills are counted, never silently dropped."""
    ok, bad = [], {}
    for x in fills:
        if x.market_id != f.market_id:
            why = R.FILL_MARKET
        elif x.filled_at >= f.event_start:
            why = R.FILL_POST_EVENT
        elif x.filled_at < f.frozen_at:
            why = R.FILL_PRE_FREEZE
        else:
            ok.append(x)
            continue
        bad[why] = bad.get(why, 0) + 1
    return ok, bad


def _verified(f: Forecast, fills: list, y: int) -> dict:
    fills, bad = screen_fills(f, fills)
    if bad:
        r = _verified_valid(f, fills, y) if fills else _st(BLOCKED, R.NO_VALID_FILL)
        r["fills_rejected"] = bad
        return r
    return _verified_valid(f, fills, y)


def _verified_valid(f: Forecast, fills: list, y: int) -> dict:
    if not fills:
        return _st(BLOCKED, R.NO_FILL)
    n = sum(x.count for x in fills)
    if n <= 0 or any(x.fee is None for x in fills):
        return _st(BLOCKED, "FILL_FEE_OR_COUNT_MISSING")
    sides = {x.side for x in fills}
    if len(sides) != 1 or not sides <= {"YES", "NO"}:
        return _st(BLOCKED, "FILL_SIDE_AMBIGUOUS")
    side = sides.pop()
    cost = sum(x.price * x.count + x.fee for x in fills)
    win = 1 if (y == 1) == (side == "YES") else 0
    return _st(GRADED, R.OK, execution_class="VERIFIED_FILL", side=side, contracts=n, cost=cost, pnl=win * n - cost)
