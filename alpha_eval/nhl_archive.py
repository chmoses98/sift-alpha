"""READ-ONLY adapter: NHL producer archive (``NHL-edge-finder@data-archive``) + Kalshi official settlements -> ``sift-alpha-eval/1``.

Inputs are LOCAL files; this module performs no network IO, imports no producer engine and writes nothing. It feeds the
standard's own grader; it scores nothing itself.

Forecasts (BINARY, one per model x ticker): the producer's frozen per-contract probabilities
  DATA_ONLY_V1   predictions/        p_data_only       (sim nhl-sim-1.1)
  DATA_ONLY_V2   predictions_v2/     p_data_only_v2    (sim nhl-sim-2.0)
  PLAYER_SIM_V1  predictions_player/ p_player          (player props only)
The market-anchored columns are NOT forecasts here (they consume the quote). All three arms are declared ``sports_only``
by the producer (docs/POINT_IN_TIME.md: nothing in DATA_ONLY reads sportsbook odds); Alpha does not verify that claim.

Selection rule (fixed before any outcome is read, outcome-independent): per (model, ticker) the LATEST capture made before
the scheduled start whose archive file was committed to the append-only ``data-archive`` branch before that start. That
capture is PROSPECTIVE. If no capture of that ticker was committed before the start, the latest pre-start capture is
emitted with ``frozen_at`` = its commit time, so the standard BLOCKS it (freeze not attested before the event).

Freeze attestation = the git commit that first added the forecast file (``git log --diff-filter=A``), on a branch whose
history was verified append-only by the caller (an earlier pinned head is an ancestor; no forecast file is ever modified
or deleted). Commit times are the producer runner's clock: this is weaker than an external timestamp and is stated as a
limitation, not hidden.

Quotes: the Kalshi yes bid/ask each producer capture read from its own board (``market_observed_at_utc``), cents -> dollars,
kept per ticker only where the grader can use them (last at/before each emitted freeze; last before start).

Outcomes: Kalshi's OWN settlement (``result`` from the public settled-markets endpoint) -> ``source=market_settlement``.
Independent checks, each from a different artefact:
  * event identity: the Kalshi event ticker's date + team codes are matched to the NHL schedule archive; the matched
    game id becomes the outcome ``event_id``. A ticker whose identity does not match the producer's ``game_id`` therefore
    BLOCKS at the standard's event-identity join. Nothing is re-keyed.
  * outcome value: the producer's settle engine (derived from the NHL API final/goal events, a separate implementation
    and a separate source) is compared with Kalshi's result. A YES/NO disagreement adds a second, conflicting outcome row,
    so the standard's conflict rule BLOCKS that market.
Eligible universe: every settled Kalshi market in a game-bound NHL series whose event maps to an archived NHL game, plus
every producer-listed ticker (so unsettled listed markets are counted too).
"""
from __future__ import annotations

import glob
import gzip
import json
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Optional

from .schema import BACKTEST, LADDER_RUNG, MAIN, PROSPECTIVE, SCHEMA_VERSION, SPORTS_ONLY

SPORT = "NHL"
ARMS = (  # model_id, archive dir, probability column
    ("DATA_ONLY_V1", "predictions", "p_data_only"),
    ("DATA_ONLY_V2", "predictions_v2", "p_data_only_v2"),
    ("PLAYER_SIM_V1", "predictions_player", "p_player"),
)
MAIN_FAMILIES = frozenset({"game_winner", "period_winner", "first_goal", "game_early_goal", "game_overtime"})

# Kalshi series -> producer-vocabulary native family (game-bound series only; anything else is not a per-game market).
SERIES_FAMILY = {
    "KXNHLGAME": "game_winner", "KXNHLSPREAD": "game_spread", "KXNHLTOTAL": "game_total", "KXNHLTEAMTOTAL": "team_total",
    "KXNHL1P": "period_winner", "KXNHL2P": "period_winner", "KXNHL3P": "period_winner",
    "KXNHL1PSPREAD": "period_spread", "KXNHL2PSPREAD": "period_spread", "KXNHL3PSPREAD": "period_spread",
    "KXNHL1PTOTAL": "period_total", "KXNHL2PTOTAL": "period_total", "KXNHL3PTOTAL": "period_total",
    "KXNHLGOAL": "player_goals", "KXNHLPTS": "player_points", "KXNHLAST": "player_assists", "KXNHLSAVE": "goalie_saves",
    "KXNHLFIRSTGOAL": "first_goal", "KXNHLF10G": "game_early_goal", "KXNHLOT": "game_overtime",
    "KXNHL1PBTTS": "period_btts", "KXNHL2PBTTS": "period_btts", "KXNHL3PBTTS": "period_btts",
    "KXNHL1STTEAM": "first_team_to_score", "KXNHL2OT": "game_double_overtime", "KXNHL30COMEBACK": "game_comeback",
    "KXNHLANYGOAL": "player_anytime_goal", "KXNHLSAVES": "goalie_saves_alt", "KXNHLOVERTIME": "game_overtime_alt",
}
_EVT = re.compile(r"-(\d{2})([A-Z]{3})(\d{2})([A-Z]+)$")
_MON = {m: i + 1 for i, m in enumerate(("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"))}
# Kalshi team codes that differ from NHL API abbreviations. Only entries observed in the data are listed; an unknown code
# simply fails to match (counted), it is never guessed.
KALSHI_TEAM_ALIAS = {"LA": "LAK", "NJ": "NJD", "SJ": "SJS", "TB": "TBL", "UTAH": "UTA"}


def _ts(s: str) -> datetime:
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(root: str, sub: str):
    for f in sorted(glob.glob(os.path.join(root, sub, "dt=*", "*.jsonl.gz"))):
        rel = os.path.relpath(f, root)
        with gzip.open(f, "rt") as fh:
            for line in fh:
                if line.strip():
                    yield rel, json.loads(line)


# ----------------------------------------------------------------------------- inputs
def load_file_adds(path: str) -> dict:
    """Parse ``git log --diff-filter=A --name-only --format='C %H %cI'`` output -> {path: (commit, commit_time)}.
    A path added twice (never expected on an append-only ledger) keeps the EARLIEST add and is reported by the caller."""
    adds, cur, dup = {}, None, []
    with open(path) as fh:
        for line in fh:
            line = line.strip()
            if line.startswith("C "):
                _, sha, t = line.split()
                cur = (sha, _ts(t))
            elif line:
                if line in adds:
                    dup.append(line)
                    if cur[1] < adds[line][1]:
                        adds[line] = cur
                else:
                    adds[line] = cur
    return dict(adds=adds, duplicate_adds=dup)


def load_schedule(root: str) -> dict:
    """game_id -> latest schedule observation (start, ET date, team abbrevs, status)."""
    out = {}
    for _, r in _rows(root, "context/schedule"):
        g = str(r["game_id"])
        if g not in out or r["_observed_at_utc"] >= out[g]["_observed_at_utc"]:
            out[g] = r
    return out


def load_contracts(root: str) -> dict:
    """ticker -> latest producer contract row (family, game_id, event_ticker, ...)."""
    out = {}
    for _, r in _rows(root, "contracts"):
        t = r["ticker"]
        if t not in out or r["_observed_at_utc"] >= out[t]["_observed_at_utc"]:
            out[t] = r
    return out


def load_producer_settlements(root: str) -> dict:
    """ticker -> latest producer settle-engine row."""
    out = {}
    for _, r in _rows(root, "settlements"):
        t = r["ticker"]
        if t not in out or r["_observed_at_utc"] >= out[t]["_observed_at_utc"]:
            out[t] = r
    return out


def load_kalshi_settled(kdir: str) -> dict:
    """ticker -> settled market (from fetch_kalshi_settled.py pages). A ticker seen twice keeps the later settlement."""
    out = {}
    for f in sorted(glob.glob(os.path.join(kdir, "*_p*.json.gz"))):
        series = os.path.basename(f).rsplit("_p", 1)[0]
        with gzip.open(f, "rt") as fh:
            d = json.load(fh)
        for m in d.get("markets", []):
            m = dict(m, _series=series)
            prev = out.get(m["ticker"])
            if prev is None or str(m.get("settlement_ts") or "") >= str(prev.get("settlement_ts") or ""):
                out[m["ticker"]] = m
    return out


# ----------------------------------------------------------------------------- identity
def game_index(schedule: dict) -> dict:
    """(ET date, frozenset{abbrevs}) -> [game_id]."""
    ix = defaultdict(list)
    for g, r in schedule.items():
        ix[(r["game_date_et"], frozenset((r["home_abbrev"], r["away_abbrev"])))].append(g)
    return ix


def _split_teams(code: str, abbrevs: set) -> Optional[frozenset]:
    """'BUFCHI' -> {'BUF','CHI'} using known abbreviations (NHL + Kalshi aliases); None if no unique split."""
    known = abbrevs | set(KALSHI_TEAM_ALIAS)
    splits = []
    for i in range(2, len(code) - 1):
        a, b = code[:i], code[i:]
        if a in known and b in known:
            splits.append(frozenset((KALSHI_TEAM_ALIAS.get(a, a), KALSHI_TEAM_ALIAS.get(b, b))))
    return splits[0] if len(set(splits)) == 1 else None


def ticker_game(event_ticker: str, gix: dict, abbrevs: set) -> tuple:
    """Kalshi event ticker -> (game_id | None, reason)."""
    m = _EVT.search(event_ticker or "")
    if not m:
        return None, "EVENT_TICKER_UNPARSEABLE"
    yy, mon, dd, teams = m.groups()
    if mon not in _MON:
        return None, "EVENT_TICKER_UNPARSEABLE"
    date = f"20{yy}-{_MON[mon]:02d}-{dd}"
    pair = _split_teams(teams, abbrevs)
    if pair is None:
        return None, "TEAM_CODES_UNMATCHED"
    hits = gix.get((date, pair), [])
    if len(hits) != 1:
        return None, "NO_ARCHIVED_GAME" if not hits else "AMBIGUOUS_GAME"
    return hits[0], "OK"


# ----------------------------------------------------------------------------- build
def build(root: str, file_adds: dict, kalshi: dict, *, as_of: str) -> dict:
    schedule = load_schedule(root)
    contracts = load_contracts(root)
    psett = load_producer_settlements(root)
    gix = game_index(schedule)
    abbrevs = {r["home_abbrev"] for r in schedule.values()} | {r["away_abbrev"] for r in schedule.values()}
    adds = file_adds["adds"]
    info = Counter()

    def start_of(g):
        r = schedule.get(str(g))
        return _ts(r["start_time_utc"]) if r else None

    # --- forecasts: select per (arm, ticker)
    pick, quotes_seen = {}, defaultdict(dict)
    seen_any, seen_prob, seen_prob_pre = set(), set(), set()   # tickers: any capture / any probability / probability before start
    for arm, sub, col in ARMS:
        for rel, r in _rows(root, sub):
            info[f"{arm}.rows"] += 1
            st = start_of(r["game_id"])
            if r.get("market_observed_at_utc") and r.get("market_yes_bid") is not None:
                quotes_seen[r["ticker"]][r["market_observed_at_utc"]] = (r["market_yes_bid"], r["market_yes_ask"])
            p = r.get(col)
            seen_any.add(r["ticker"])
            if p is not None and 0.0 < float(p) < 1.0:
                seen_prob.add(r["ticker"])
                if st is not None and _ts(r["predicted_at_utc"]) < st:
                    seen_prob_pre.add(r["ticker"])
            if p is None or not (0.0 < float(p) < 1.0):
                info[f"{arm}.no_probability"] += 1
                continue
            if st is None:
                info[f"{arm}.no_schedule"] += 1
                continue
            t_pred = _ts(r["predicted_at_utc"])
            if t_pred >= st:
                info[f"{arm}.captured_after_start"] += 1
                continue
            add = adds.get(rel)
            if add is None:
                info[f"{arm}.file_not_in_history"] += 1
                continue
            attested = add[1] < st
            k = (arm, r["ticker"])
            cand = (attested, t_pred, r, add, float(p))
            cur = pick.get(k)
            # attested beats unattested; then latest capture
            if cur is None or (cand[0], cand[1]) > (cur[0], cur[1]):
                pick[k] = cand

    forecasts, freeze_by_ticker = [], defaultdict(set)
    for (arm, ticker), (attested, t_pred, r, add, p) in sorted(pick.items(), key=lambda kv: kv[0]):
        st = start_of(r["game_id"])
        fam = r["family"]
        frozen = t_pred if attested else add[1]
        info[f"{arm}.emitted.{'PROSPECTIVE' if attested else 'UNATTESTED_FREEZE'}"] += 1
        freeze_by_ticker[ticker].add(frozen)
        mv = f"{r['model_version']}|{r.get('sim_version')}|{r.get('feature_version')}"
        forecasts.append(dict(
            schema=SCHEMA_VERSION, forecast_id=f"{arm}|{ticker}|{r['prediction_id']}", sport=SPORT, event_id=str(r["game_id"]),
            group_id=str(r["game_id"]), market_id=ticker, model_id=arm, model_version=mv, model_independence=SPORTS_ONLY,
            market_inputs_used=[], frozen_at=_iso(frozen), event_start=_iso(st),
            evidence_class=PROSPECTIVE if attested else BACKTEST, scoring_type="BINARY",
            payload=dict(p_yes=p), native_family=fam,
            line=r.get("threshold"), line_role=MAIN if fam in MAIN_FAMILIES else LADDER_RUNG,
            meta=dict(horizon_label=r.get("horizon_label"), minutes_to_start=round((st - t_pred).total_seconds() / 60, 1),
                      archive_commit=add[0], committed_at=_iso(add[1]), predicted_at=_iso(t_pred))))

    # --- quotes: last at/before each emitted freeze + last before start, per ticker
    quotes = []
    for ticker, obs in quotes_seen.items():
        c = contracts.get(ticker)
        st = start_of(c["game_id"]) if c else None
        times = sorted(obs)
        keep = set()
        for fz in freeze_by_ticker.get(ticker, ()):
            prior = [t for t in times if _ts(t) <= fz]
            if prior:
                keep.add(prior[-1])
        if st is not None:
            prior = [t for t in times if _ts(t) < st]
            if prior:
                keep.add(prior[-1])
        for t in sorted(keep):
            yb, ya = obs[t]
            quotes.append(dict(schema=SCHEMA_VERSION, market_id=ticker, observed_at=t,
                               yes_bid=None if not yb else yb / 100.0, yes_ask=None if (not ya or ya >= 100) else ya / 100.0,
                               source="producer_board_read"))

    # --- outcomes (Kalshi official) + independent identity + producer cross-check
    outcomes, ident, xcheck, eligible = [], Counter(), Counter(), {}
    for ticker, m in kalshi.items():
        fam = SERIES_FAMILY.get(m["_series"])
        if fam is None:
            info["kalshi.non_game_series_markets"] += 1
            continue
        g, why = ticker_game(m.get("event_ticker", ""), gix, abbrevs)
        ident[why] += 1
        ev = g if g else f"UNMAPPED:{why}:{m.get('event_ticker')}"
        st = start_of(g) if g else None
        eligible[ticker] = dict(schema=SCHEMA_VERSION, market_id=ticker, event_id=ev, sport=SPORT,
                                event_start=_iso(st) if st else None, native_family=fam, source="kalshi_settled")
        res = (m.get("result") or "").lower()
        obs = m.get("settlement_ts") or m.get("close_time")
        if res in ("yes", "no"):
            outcomes.append(dict(schema=SCHEMA_VERSION, market_id=ticker, event_id=ev, state="final", observed_at=obs,
                                 source="market_settlement", value=res == "yes"))
        elif res in ("void", "canceled", "cancelled", "scalar"):
            # scalar = Kalshi's "active but never entered" rule: settled at the last pre-start fair price, not YES/NO.
            # The producer's player probabilities are conditional on playing, so this is a void for binary scoring.
            info[f"kalshi.void_or_scalar.{res}"] += 1
            outcomes.append(dict(schema=SCHEMA_VERSION, market_id=ticker, event_id=ev, state="void", observed_at=obs,
                                 source="market_settlement", value=None))
        else:
            info[f"kalshi.result_other.{res or 'EMPTY'}"] += 1
            continue
        ps = psett.get(ticker)
        if ps is None:
            xcheck["NO_PRODUCER_SETTLEMENT"] += 1
        elif ps["outcome"] not in ("YES", "NO"):
            xcheck[f"PRODUCER_{ps['outcome']}"] += 1
        elif res not in ("yes", "no"):
            xcheck[f"KALSHI_{res.upper()}_PRODUCER_{ps['outcome']}"] += 1
        elif (ps["outcome"] == "YES") == (res == "yes"):
            xcheck["AGREE"] += 1
        else:
            xcheck["DISAGREE"] += 1
            outcomes.append(dict(schema=SCHEMA_VERSION, market_id=ticker, event_id=ev, state="final",
                                 observed_at=ps.get("settled_at_utc"), source="sports", value=ps["outcome"] == "YES"))
    # producer-listed tickers absent from Kalshi's settled list are still eligible (event_id from the producer)
    for ticker, c in contracts.items():
        if ticker not in eligible:
            st = start_of(c["game_id"])
            eligible[ticker] = dict(schema=SCHEMA_VERSION, market_id=ticker, event_id=str(c["game_id"]), sport=SPORT,
                                    event_start=_iso(st) if st else None, native_family=c["family"], source="producer_listing_only")
            info["eligible.producer_listed_not_in_kalshi_settled"] += 1

    not_fc = Counter()
    fc_t = {f["market_id"] for f in forecasts}
    for t, e in eligible.items():
        if t in fc_t:
            continue
        if e["event_id"].startswith("UNMAPPED:"):
            why = "EVENT_NOT_MAPPED_TO_ARCHIVED_GAME"
        elif t not in contracts:
            why = "NEVER_LISTED_BY_PRODUCER"
        elif t not in seen_any:
            why = "LISTED_NO_PREDICTION_ROW"
        elif t not in seen_prob:
            why = "LISTED_PROBABILITY_ALWAYS_NULL"
        elif t not in seen_prob_pre:
            why = "PROBABILITY_ONLY_AFTER_START"
        else:
            why = "PRE_START_PROBABILITY_BUT_FILE_NOT_IN_HISTORY"
        not_fc[(e["native_family"], why)] += 1
    nf = defaultdict(dict)
    for (fam, why), n in sorted(not_fc.items()):
        nf[fam][why] = n
    return dict(forecasts=forecasts, outcomes=outcomes, quotes=quotes, eligible=list(eligible.values()),
                market_not_forecast_reasons=dict(nf),
                info=dict(sorted(info.items())), identity=dict(ident), producer_crosscheck=dict(xcheck),
                n_games_scheduled=len(schedule), n_producer_contracts=len(contracts), as_of=as_of,
                duplicate_file_adds=len(file_adds.get("duplicate_adds", [])))


def reconcile(eligible: list, graded_rows: list, forecasts: list) -> dict:
    """Every eligible market in exactly one category, by native family (partition asserted)."""
    fc = defaultdict(set)
    for f in forecasts:
        fc[f["market_id"]].add(f["model_id"])
    gr = defaultdict(set)
    for r in graded_rows:
        if r["accuracy"]["status"] == "GRADED":
            gr[r["market_id"]].add(r.get("model_id"))
    cat = defaultdict(Counter)
    for e in eligible:
        m, fam = e["market_id"], e["native_family"]
        if e["event_id"].startswith("UNMAPPED:"):
            c = "EVENT_NOT_MAPPED_TO_ARCHIVED_GAME"
        elif m not in fc:
            c = "NOT_FORECAST_FAMILY_NOT_MODELLED" if fam not in _MODELLED else "NOT_FORECAST_MODELLED_FAMILY"
        elif m in gr:
            c = "FORECAST_AND_GRADED"
        else:
            c = "FORECAST_NOT_GRADED"
        cat[fam][c] += 1
    tot = Counter()
    for v in cat.values():
        tot.update(v)
    assert sum(tot.values()) == len(eligible), "partition violated"
    return dict(total=dict(tot), by_native_family={k: dict(v) for k, v in sorted(cat.items())}, n_eligible=len(eligible))


_MODELLED = frozenset({"game_winner", "game_spread", "game_total", "team_total", "period_winner", "period_spread", "period_total",
                       "player_goals", "player_points", "player_assists", "first_goal", "goalie_saves", "game_early_goal",
                       "game_overtime"})


# ----------------------------------------------------------------------------- secondary slices (the standard's own cells)
PRIOR_AUDIT_DATA_PIN = "2026-11-04T19:38:30Z"   # commit time of NHL-edge-finder@data-archive eacc3b9d, the input of reports/outcome_intel/nhl_audit.json
# The one candidate the prior audit carried forward (PLAYER_SIM_V1 goalie saves, PROMISING_INSUFFICIENT). Fixed before any
# goalie-saves-specific number on post-pin games was computed: one hypothesis, two-sided, alpha 0.05, standard's Brier delta.
CONFIRMATION_TEST = dict(model_id="PLAYER_SIM_V1", native_family="goalie_saves", games_starting_after=PRIOR_AUDIT_DATA_PIN,
                         metric="paired Brier delta (market - model), event-clustered bootstrap, sift-alpha-eval/1 market_cell",
                         alpha=0.05, sidedness="two-sided")


def native_family_cells(rows: list, forecasts: list) -> dict:
    """Model-vs-market per (model, native family) over all games and split at the prior audit's data pin, using
    ``aggregate.market_cell`` / ``verdict_for`` / ``holm`` unchanged. SECONDARY: its own Holm family, never pooled with
    the primary grid, never a promotion input."""
    from .aggregate import _clean, market_cell, verdict_for
    from sift_research.stats import holm
    start = {f["forecast_id"]: f["event_start"] for f in forecasts}
    groups = defaultdict(list)
    for r in rows:
        if r["evidence_class"] != PROSPECTIVE:
            continue
        nf = r["native_family"]
        post = start[r["forecast_id"]] > PRIOR_AUDIT_DATA_PIN
        groups[(r["model_id"], nf, "ALL")].append(r)
        groups[(r["model_id"], nf, "AFTER_PRIOR_AUDIT_PIN" if post else "UP_TO_PRIOR_AUDIT_PIN")].append(r)
    cells = [(k, market_cell(v)) for k, v in sorted(groups.items())]
    cells = [(k, m) for k, m in cells if m.get("n_paired_rows")]
    ph = holm([m["_p"] if m["_p"] is not None else 1.0 for _, m in cells]) if cells else []
    out = []
    for (k, m), h in zip(cells, ph):
        b = m["brier_delta_market_minus_model"]
        out.append(dict(model_id=k[0], native_family=k[1], window=k[2], n_paired_rows=m["n_paired_rows"], n_events=m["n_events"],
                        brier_delta=b, logloss_delta=m["logloss_delta_market_minus_model"], p_holm_secondary=round(float(h), 6),
                        verdict_secondary=verdict_for(m, p_holm=float(h))))
    ct = [c for c in out if c["model_id"] == CONFIRMATION_TEST["model_id"] and c["native_family"] == CONFIRMATION_TEST["native_family"]
          and c["window"] == "AFTER_PRIOR_AUDIT_PIN"]
    conf = dict(CONFIRMATION_TEST)
    if ct:
        b = ct[0]["brier_delta"]
        conf.update(n_paired_rows=ct[0]["n_paired_rows"], n_events=ct[0]["n_events"], brier_delta=b, logloss_delta=ct[0]["logloss_delta"],
                    result=("CONFIRMED_MODEL_BETTER" if b["lo"] is not None and b["lo"] > 0 and b["p"] is not None and b["p"] < 0.05
                            else "MARKET_BETTER" if b["hi"] is not None and b["hi"] < 0 else "NOT_CONFIRMED"))
    else:
        conf.update(result="NO_PAIRED_DATA")
    return dict(cells=out, confirmation_test=conf, note="secondary slice; separate Holm family; not a promotion input")


def native_family_markdown(sec: dict) -> str:
    L = ["", "## Secondary: model vs market by native family (separate Holm family; not a promotion input)", "",
         f"Split at the prior NHL audit's data pin ({PRIOR_AUDIT_DATA_PIN}). Δ = market − model (positive favours the model).", "",
         "| model | native family | window | rows | events | Δ Brier [95% CI] | Δ log-loss [95% CI] | p_holm (secondary) | verdict |",
         "|---|---|---|---|---|---|---|---|---|"]
    f = lambda d: "–" if not d or d.get("mean") is None else f"{d['mean']:+.4f} [{d['lo']:+.4f}, {d['hi']:+.4f}]"  # noqa: E731
    for c in sec["cells"]:
        L.append(f"| {c['model_id']} | {c['native_family']} | {c['window']} | {c['n_paired_rows']} | {c['n_events']} | {f(c['brier_delta'])} | "
                 f"{f(c['logloss_delta'])} | {c['p_holm_secondary']} | {c['verdict_secondary']} |")
    t = sec["confirmation_test"]
    L += ["", "### Pre-specified confirmation test", "",
          f"`{t['model_id']}` / `{t['native_family']}`, games starting after {t['games_starting_after']}; {t['metric']}; {t['sidedness']}, alpha {t['alpha']}.", "",
          f"- result: **{t['result']}**" + (f"; rows {t['n_paired_rows']}, events {t['n_events']}, Δ Brier {f(t['brier_delta'])} (p {t['brier_delta'].get('p')}), "
                                            f"Δ log-loss {f(t['logloss_delta'])}" if "brier_delta" in t else ""), ""]
    return "\n".join(L)
