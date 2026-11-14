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
    h = sub.add_parser("nhl-archive", help="read-only postmortem from a LOCAL sparse checkout of NHL-edge-finder@data-archive + Kalshi settled pages")
    h.add_argument("--root", required=True); h.add_argument("--file-adds", required=True, help="git log --diff-filter=A --name-only --format='C %%H %%cI' output")
    h.add_argument("--kalshi-dir", required=True); h.add_argument("--as-of", required=True, help="data horizon (archive head commit time)")
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
        from . import nhl_archive as H
        b = H.build(a.root, H.load_file_adds(a.file_adds), H.load_kalshi_settled(a.kalshi_dir), as_of=a.as_of)
        g = grade_all(b["forecasts"], b["outcomes"], b["quotes"], [], eligible_rows=b["eligible"], as_of=a.as_of)
        rep = build_report(g, kind="cumulative", title=a.title or "NHL archive postmortem")
        rep["source_accounting"] = dict(info=b["info"], identity=b["identity"], producer_crosscheck=b["producer_crosscheck"],
                                        n_games_scheduled=b["n_games_scheduled"], n_producer_contracts=b["n_producer_contracts"],
                                        n_forecast_rows=len(b["forecasts"]), n_outcome_rows=len(b["outcomes"]), n_quote_rows=len(b["quotes"]),
                                        n_eligible_rows=len(b["eligible"]), duplicate_file_adds=b["duplicate_file_adds"], as_of=a.as_of,
                                        universe_basis="KALSHI_SETTLED_GAME_BOUND_PLUS_PRODUCER_LISTING",
                                        market_reconciliation=H.reconcile(b["eligible"], g["rows"], b["forecasts"]),
                                        market_not_forecast_reasons=b["market_not_forecast_reasons"])
        rep["secondary_native_family"] = H.native_family_cells(g["rows"], b["forecasts"])
        _write(out, "nhl_archive_cumulative", rep)
        with open(out / "nhl_archive_cumulative.md", "a") as fh:
            fh.write(H.native_family_markdown(rep["secondary_native_family"]))
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
