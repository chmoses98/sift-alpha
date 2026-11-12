"""Standardised postmortem reports. Daily = events starting on that UTC date; cumulative = everything through that date.
Organised by sport, market family, model version, calibration bucket and forecast horizon. Evidence classes
(HISTORICAL / BACKTEST / PROSPECTIVE) are NEVER pooled: each gets its own section."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Optional

from . import aggregate as A
from . import universe as U
from .schema import BINARY, EVIDENCE_CLASSES, GRADED, SCHEMA_VERSION


def _slice(rows, key):
    d = defaultdict(list)
    for r in rows:
        d[key(r)].append(r)
    return dict(sorted(d.items()))


def build_report(graded: dict, *, kind: str = "cumulative", date: Optional[str] = None, title: str = "") -> dict:
    rows = graded["rows"]
    if kind == "daily":
        rows_sel = [r for r in rows if r["event_date"] == date]
    else:
        rows_sel = [r for r in rows if date is None or r["event_date"] <= date]
    rep = dict(schema=SCHEMA_VERSION, kind=kind, date=date, title=title, status="RESEARCH_ONLY",
               n_input_forecasts=graded["n_input_forecasts"], n_in_window=len(rows_sel), n_schema_rejects=len(graded["rejects"]),
               accounting=dict(accuracy=A.status_counts(rows_sel, "accuracy"), market=A.status_counts(rows_sel, "market"),
                               economics=A.status_counts(rows_sel, "economics"), clv=A.status_counts(rows_sel, "clv")),
               coverage=U.coverage(graded.get('eligible'), rows_sel, date=date, kind=kind),
               auxiliary_input_rejects=_aux(graded.get("aux_rejects", [])),
               schema_rejects=[dict(forecast_id=r["forecast_id"], reason=r["accuracy"]["detail"]) for r in graded["rejects"]],
               by_evidence_class={})
    for ev in EVIDENCE_CLASSES:
        er = [r for r in rows_sel if r["evidence_class"] == ev]
        if not er:
            continue
        sec = dict(overall=A.cell(er), model_vs_market_primary_grid=A.primary_grid(er),
                   by_sport={k: A.cell(v) for k, v in _slice(er, lambda r: r["sport"]).items()},
                   by_family={k: A.cell(v) for k, v in _slice(er, lambda r: r["family"]).items()},
                   by_sport_family={f"{k[0]}/{k[1]}": A.cell(v) for k, v in _slice(er, lambda r: (r["sport"], r["family"])).items()},
                   by_model_version={k: A.cell(v) for k, v in _slice(er, lambda r: r["model_version"] or "MISSING").items()},
                   by_horizon={k: A.cell(v) for k, v in _slice(er, lambda r: r["horizon"]).items()},
                   by_calibration_bucket=calibration_by_bucket(er))
        rep["by_evidence_class"][ev] = sec
    return rep


def _aux(items) -> dict:
    c = Counter(k for k, _ in items)
    return dict(counts=dict(c), examples=[f"{k}: {m}" for k, m in items[:5]],
                note="outcome/quote/fill rows that failed schema validation; surfaced, never silently dropped")


def calibration_by_bucket(rows) -> list:
    """Binary only. Pooled across the slice's rows; each bucket row reports n, mean forecast, observed, signed gap."""
    g = [r["accuracy"] for r in rows if r["accuracy"]["status"] == GRADED and r["scoring_type"] == BINARY]
    from . import scoring as S
    return S.calibration_buckets([x["p"] for x in g], [x["y"] for x in g])


def to_markdown(rep: dict) -> str:
    L = [f"# SIFT Alpha evaluation report ({rep['kind']}{' ' + rep['date'] if rep['date'] else ''})", "",
         f"`{rep['schema']}` | status **{rep['status']}** | {rep['title']}", "",
         f"Forecast rows in input: {rep['n_input_forecasts']}; in window: {rep['n_in_window']}; schema rejects: {rep['n_schema_rejects']}; "
         f"auxiliary (outcome/quote/fill) rows rejected: {sum(rep['auxiliary_input_rejects']['counts'].values())}", ""]
    cv = rep["coverage"]
    L += ["## Coverage", "", f"- basis: **{cv['basis']}**; complete eligible-market coverage: **{cv['complete_eligible_market_coverage']}**"]
    if cv["basis"] == U.FORECAST_ONLY:
        L += [f"- forecast rows {cv['n_forecast_rows']} over {cv['n_forecast_markets']} markets. {cv['note']}"]
    else:
        L += [f"- eligible markets {cv['n_eligible_markets']}; forecast coverage {cv['forecast_coverage_of_eligible']}; graded coverage {cv['graded_coverage_of_eligible']}",
              f"- status: {cv['status_counts']}", f"- forecast markets outside the eligible universe: {cv['n_forecast_markets_outside_universe']}"]
    L += [""]
    L += ["## Accounting (nothing silently excluded)", "", "| evaluation | status | reason | n |", "|---|---|---|---|"]
    for dim, d in rep["accounting"].items():
        for st, rs in d.items():
            for reason, n in rs.items():
                L.append(f"| {dim} | {st} | {reason} | {n} |")
    for ev, sec in rep["by_evidence_class"].items():
        L += ["", f"## Evidence class: {ev}", ""]
        ov = sec["overall"]
        L += _acc_table(ov)
        L += ["", "### Model vs market (primary grid; Holm / BH adjusted across cells)", "",
              "| sport | family | model | rows | events | Δ Brier (mkt−model) [95% CI] | p_holm | verdict |", "|---|---|---|---|---|---|---|---|"]
        for c in sec["model_vs_market_primary_grid"]:
            b = c["brier_delta_market_minus_model"]
            L.append(f"| {c['sport']} | {c['family']} | {c['model_version']} | {c['n_paired_rows']} | {c['n_events']} | "
                     f"{b['mean']} [{b['lo']}, {b['hi']}] | {c['p_holm']} | {c['verdict']} |")
        if not sec["model_vs_market_primary_grid"]:
            L.append("| – | – | – | 0 | 0 | no paired priced rows | – | NO_PAIRED_DATA |")
        L += ["", "### Economics (hypothetical unless stated)", ""]
        e = ov["economics"]
        pop, sel, vf = e["hypothetical_all_rows_model_side"], e["hypothetical_positive_edge_subset"], e["verified_fills"]
        L += [f"- full priced population: n={pop['n']}, ROI {_roi(pop['roi'])}", f"- positive-edge subset (selection-biased): n={sel['n']}, ROI {_roi(sel['roi'])}",
              f"- verified fills: n={vf['n']}", f"- **{e['profitability_claim']}**"]
        c = ov["clv"]
        L += ["", "### CLV (signed; quoted vs actual-fill kept apart)", "",
              f"- selection CLV: {c['selection_clv']['mean']} (n={c['selection_clv']['n']})",
              f"- quoted-execution CLV: {c['quoted_execution_clv']['mean']} (n={c['quoted_execution_clv']['n']})",
              f"- actual-fill CLV: {c['actual_fill_clv']['mean']} (n={c['actual_fill_clv']['n']})"]
        for dim in ("by_sport", "by_family", "by_model_version", "by_horizon"):
            L += ["", f"### Accuracy {dim.replace('_', ' ')}", "", "| slice | forecasts | graded | binary Brier | binary signed bias | calibration reading |", "|---|---|---|---|---|---|"]
            for k, v in sec[dim].items():
                a = v["accuracy"]
                b = a["by_scoring_type"].get(BINARY)
                L.append(f"| {k} | {a['n_forecasts']} | {a['n_graded']} | {b['brier']['mean'] if b else '–'} | "
                         f"{b['reliability']['signed_bias'] if b and b['reliability'].get('n') else '–'} | {b['reliability'].get('confidence_reading', '–') if b else '–'} |")
        L += ["", "### Calibration by probability bucket (binary)", "", "| bucket | n | mean forecast | observed | signed gap (fcst − obs) |", "|---|---|---|---|---|"]
        for b in sec["by_calibration_bucket"]:
            f = lambda x: "–" if x is None else f"{x:.3f}"  # noqa: E731
            L.append(f"| {b['bucket']} | {b['n']} | {f(b['mean_p'])} | {f(b['observed'])} | {f(b['signed_gap'])} |")
    L += ["", "_Descriptive only. No model promotion, order, or authority change follows from this report._", ""]
    return "\n".join(L)


def _acc_table(ov) -> list:
    a = ov["accuracy"]
    L = [f"Graded {a['n_graded']} of {a['n_forecasts']} forecasts across {a['n_events']} events.", "",
         "| scoring type | n | primary metric | signed bias |", "|---|---|---|---|"]
    for st, d in a["by_scoring_type"].items():
        prim = {"BINARY": ("brier", "Brier"), "CONTINUOUS": ("mae", "MAE"), "ORDINAL_PMF": ("crps", "CRPS"), "CATEGORICAL": ("brier_multiclass", "multiclass Brier")}[st]
        sb = d.get("signed_bias")
        sb = sb["mean"] if isinstance(sb, dict) else (d["reliability"]["signed_bias"] if st == BINARY and d["reliability"].get("n") else "–")
        L.append(f"| {st} | {d['n']} | {prim[1]} {d[prim[0]]['mean']} [{d[prim[0]]['lo']}, {d[prim[0]]['hi']}] | {sb} |")
    return L


def _roi(r):
    return "n/a" if not r or r.get("ratio") is None else f"{r['ratio']} [{r['lo']}, {r['hi']}]"
