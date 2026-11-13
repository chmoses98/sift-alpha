"""python -m alpha_eval {report|coverage|example}. File IO only; no network; no writes outside --out-dir."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import coverage as cov
from .grading import grade_all
from .report import build_report, to_markdown
from .schema import SCHEMA_VERSION


def _jsonl(p):
    return [json.loads(l) for l in Path(p).read_text().splitlines() if l.strip()] if p else []


def _write(out: Path, stem: str, rep: dict):
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{stem}.json").write_text(json.dumps(rep, indent=1, sort_keys=True, default=str) + "\n")
    (out / f"{stem}.md").write_text(to_markdown(rep))


def run_nhl(root, api_cache, git_log_text, *, title=""):
    from . import nhl_archive as H
    from . import nba_universe as U
    b = H.build(root, api_cache, git_log_text)
    quotes, qinfo, integ = H.quotes_from_board(root, b["quote_lookups"])
    api = b["api"]
    finals = sorted(g["game"]["date"] for g in api.values() if g["res"]["status"] == "final")
    horizon = finals[-1]
    window_start = min(g["game"]["date"] for g in api.values())
    cl = H.classify_universe(H.load_board_universe(root), api, H.schedule_index(root), window_start=window_start, horizon=horizon)
    eligible = H.eligible_rows(cl)
    as_of = max(g["fetched_at"] for g in api.values())
    g = grade_all(b["forecasts"], b["outcomes"], quotes, [], eligible_rows=eligible, as_of=as_of)
    recon = U.reconcile(cl, g["rows"], {f["market_id"] for f in b["forecasts"]}, {(f["native_family"], f["event_id"]) for f in b["forecasts"]},
                        evaluated_families=H.EVALUATED, frozen_not_evaluated=H.FROZEN_NOT_EVALUATED)
    recon.pop("detail")
    recon["market_not_forecast_reasons"] = H.market_not_forecast_reasons(cl, {f["market_id"] for f in b["forecasts"]}, b["seen"])
    rep = build_report(g, kind="cumulative", title=title or "NHL data-archive frozen forecasts postmortem")
    rep["source_accounting"] = dict(info=b["info"], quote_info=qinfo, board_integrity=integ,
                                    embedded_quote_agreement=H.embedded_quote_agreement(b["forecasts"], quotes),
                                    window=dict(start=window_start, horizon=horizon, as_of=as_of), n_official_games=len(api),
                                    n_official_final=len(finals), n_forecast_rows=len(b["forecasts"]), n_outcome_rows=len(b["outcomes"]),
                                    n_quote_rows=len(quotes), n_eligible_rows=len(eligible), universe_basis="ALL_BOARD_GAME_BOUND",
                                    market_reconciliation=recon)
    return rep


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="alpha_eval", description=f"SIFT Alpha evaluation standard {SCHEMA_VERSION} (RESEARCH_ONLY)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("--forecasts", required=True); r.add_argument("--outcomes", required=True)
    r.add_argument("--quotes"); r.add_argument("--fills"); r.add_argument("--eligible", help="JSONL eligible-market universe; without it coverage is FORECAST_ONLY")
    r.add_argument("--kind", choices=("daily", "cumulative"), default="cumulative"); r.add_argument("--date")
    r.add_argument("--title", default=""); r.add_argument("--out-dir", required=True)
    n = sub.add_parser("nba-shadow", help="read-only postmortem from a LOCAL checkout of the NBA PURE shadow store")
    n.add_argument("--root", required=True); n.add_argument("--out-dir", required=True); n.add_argument("--title", default="")
    n.add_argument("--projection-data", help="local checkout of nba-edge-finder@projection-data (game identity + official availability)")
    n.add_argument("--board-dir", help="local dir of full-board Kalshi checkpoints (data-archive/kalshi/markets): eligible universe = ALL NBA game-bound families")
    n.add_argument("--settlements", help="local dir of producer settle-engine files (data-archive/settlements) for the independent outcome cross-check")
    h = sub.add_parser("nhl-archive", help="read-only postmortem from LOCAL copies of NHL-edge-finder@data-archive + the official NHL API cache")
    h.add_argument("--root", required=True, help="local (sparse) checkout of NHL-edge-finder@data-archive")
    h.add_argument("--api-cache", required=True, help="dir written by scripts/fetch_nhl_api_outcomes.py")
    h.add_argument("--git-log", required=True, help="output of: git log --no-renames --format='C %%H %%cI %%aI %%s' --name-status <data-archive ref> "
                   "-- predictions predictions_v2 predictions_player predictions_oa")
    h.add_argument("--out-dir", required=True); h.add_argument("--title", default="")
    c = sub.add_parser("coverage"); c.add_argument("--out-dir", required=True)
    e = sub.add_parser("example"); e.add_argument("--out-dir", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out_dir)
    if a.cmd == "report":
        g = grade_all(_jsonl(a.forecasts), _jsonl(a.outcomes), _jsonl(a.quotes), _jsonl(a.fills),
                      eligible_rows=_jsonl(a.eligible) if a.eligible else None)
        _write(out, f"{a.kind}_{a.date or 'all'}", build_report(g, kind=a.kind, date=a.date, title=a.title))
    elif a.cmd == "nba-shadow":
        from . import nba_shadow
        pd = a.projection_data
        b = nba_shadow.build(a.root, game_identity=nba_shadow.load_game_identity(pd) if pd else None,
                             availability=nba_shadow.load_availability(pd) if pd else None,
                             settlements=nba_shadow.load_settlements(a.settlements) if a.settlements else None)
        recon = None
        eligible = b["eligible"]
        if a.board_dir:
            from . import nba_universe as U
            gi = nba_shadow.load_game_identity(pd)
            gx = U.game_index(gi)
            cl = U.classify(U.load_board(a.board_dir), gx, window_start=min(k[0] for k in gx), horizon=b["info"]["data_horizon"][:10])
            eligible = U.eligible_rows(cl)
            if pd:
                from . import nba_games
                gm = nba_games.build(pd, cl, settlements=nba_shadow.load_settlements(a.settlements) if a.settlements else None,
                                     game_identity=gi)
                b["forecasts"] = b["forecasts"] + gm["forecasts"]
                b["outcomes"] = b["outcomes"] + gm["outcomes"]
                b["quotes"] = b["quotes"] + gm["quotes"]
                b["info"].update({f"games.{k}": v for k, v in gm["info"].items()})
        g = grade_all(b["forecasts"], b["outcomes"], b["quotes"], [], eligible_rows=eligible, as_of=b["info"]["data_horizon"])
        if a.board_dir:
            recon = U.reconcile(cl, g["rows"], {f["market_id"] for f in b["forecasts"]}, {(f["native_family"], f["event_id"]) for f in b["forecasts"]},
                                evaluated_families=frozenset(U.EVALUATED_BY_ADAPTER | (U.GAME_LEVEL if pd else set())))
            recon.pop("detail")
            ffg = {(f["native_family"], f["event_id"]) for f in b["forecasts"]}
            recon["market_not_forecast_reasons"] = U.market_not_forecast_reasons(
                cl, {f["market_id"] for f in b["forecasts"]}, b["listing_tickers"], b["listing_games"], ffg)
        rep = build_report(g, kind="cumulative", title=a.title or "NBA PURE shadow store postmortem")
        rep["source_accounting"] = dict(info=b["info"], board=b["board"], model_hash_counts=b["model_hash_counts"], chain=b["chain"],
                                        n_forecast_rows=len(b["forecasts"]), n_outcome_rows=len(b["outcomes"]), n_quote_rows=len(b["quotes"]),
                                        n_eligible_rows=len(eligible), universe_basis="ALL_BOARD_GAME_BOUND" if a.board_dir else "SHADOW_LISTING_ARCHIVE_ONLY",
                                        market_reconciliation=recon)
        _write(out, "nba_shadow_cumulative", rep)
    elif a.cmd == "nhl-archive":
        _write(out, "nhl_archive_cumulative", run_nhl(a.root, a.api_cache, Path(a.git_log).read_text(), title=a.title))
    elif a.cmd == "coverage":
        m = cov.build()
        out.mkdir(parents=True, exist_ok=True)
        (out / "coverage_matrix.json").write_text(json.dumps(m, indent=1, sort_keys=True) + "\n")
        (out / "COVERAGE_MATRIX.md").write_text(cov.to_markdown(m))
    else:
        from .synthetic import generate
        F, O, Q, X = generate()
        g = grade_all(F, O, Q, X)
        t = "SYNTHETIC FIXTURE - exercises code paths; NOT evidence about any real model or market"
        _write(out, "example_cumulative", build_report(g, kind="cumulative", title=t))
        _write(out, "example_daily_2026-11-03", build_report(g, kind="daily", date="2026-11-03", title=t))
    return 0
