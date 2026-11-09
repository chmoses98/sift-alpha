"""Prioritised, exact-hostname network access PROPOSAL (RESEARCH_ONLY). It changes nothing: no environment setting, allowlist or permission is touched by this code.

    python -m alpha_engine.input_research.data_foundation.access_proposal

Unlock counts are computed from the committed audit rows (which inputs require a dataset that only this host can supply), not estimated. Terms-of-use and cost statements are DOCUMENTED
from the providers' public terms as the author knows them, NOT verified from this runner: the owner must read the terms before approving a host. Nothing here recommends blanket allowlisting,
restricted scraping or any paid service.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import evidence as EV

ROOT = EV.ROOT
DF = EV.DF
OUT_JSON = DF / "network_access_proposal.json"
OUT_DOC = ROOT / "docs/NETWORK_ACCESS_PROPOSAL.md"

# host: (probe ids, datasets this host would let us VERIFY and then collect, access method, tos, cost, history/prospective, tier, condition)
H = [
 ("archive-api.open-meteo.com", ["openmeteo_archive"], ["env.weather_observed"], "official free REST API (no key for non-commercial use)", "low (CC BY 4.0; non-commercial free tier with daily call limits; commercial use needs a paid plan: this is research-only)", "free", "HISTORICAL (observations back to 1940)", "ALLOW", "attribute; stay inside the free-tier call limits; cache locally"),
 ("historical-forecast-api.open-meteo.com", ["openmeteo_histfc"], ["env.weather_forecast_pit"], "official free REST API: archive of past forecast model runs", "low (same terms as above)", "free", "HISTORICAL from about 2022 (the only free source of point-in-time forecast vintages); earlier years need prospective capture", "ALLOW", "same as above; verify the vintage semantics (model-run time) on a sample before relying on it"),
 ("api.weather.gov", ["nws_forecast"], ["env.weather_forecast_pit"], "official US government REST API (requires a descriptive User-Agent; no key)", "low (US public domain)", "free", "PROSPECTIVE only (serves the current forecast); gives a second, independent forecast vintage from the capture date", "ALLOW", "needs a scheduled capture job, which this sandbox cannot host (see the capture note below)"),
 ("api.collegefootballdata.com", ["cfbd_api"], ["cfb.pbp_cfbd"], "official REST API; free account + API key (owner registers; free tier has a monthly call quota)", "low (published API terms; attribute)", "free (key; no purchase)", "HISTORICAL (plays/drives/stats from about 2001; thinner before about 2014)", "ALLOW", "the OWNER must register the key; store it only as a session credential via the environment's secrets flow, never in the repo"),
 ("api.nhle.com", ["nhl_stats_rest", "nhl_shiftcharts"], ["nhl.shifts_lines"], "unofficial-but-public NHL stats REST (shift charts, skater/goalie summaries); same provider as the already-reachable api-web.nhle.com", "medium (no published terms; unofficial API; use politely)", "free", "HISTORICAL (shift charts for recent seasons; depth to be measured on a sample)", "ALLOW_WITH_CONDITIONS", "rate-limit to a few requests per second; measure how many seasons of shifts exist before planning around it"),
 ("api.clubelo.com", ["clubelo"], ["soc.ratings_elo"], "free public CSV API by date (DNS did not resolve from this runner)", "low (free, attribute)", "free", "HISTORICAL (club Elo by date, decades)", "ALLOW", "if DNS stays unresolved after allowlisting, report back: it may be a resolver policy rather than a host policy"),
 ("en.wikipedia.org", ["wikipedia_api"], ["xx.awards_results", "xx.rules_reference"], "official MediaWiki REST/Action API (read-only)", "low (CC BY-SA; honour the API etiquette)", "free", "HISTORICAL (awards, drafts, formats, coaching changes: final facts, not time-stamped news)", "ALLOW", "read-only API only, not page scraping; wording of rules still needs hand-encoding"),
 ("official.nba.com", [], ["nba.referees"], "official NBA operations pages (referee assignments published on game day; last-two-minute reports)", "low-medium (public pages; read the site terms)", "free", "PROSPECTIVE (assignments are published the morning of the game; archives of past days are partial)", "ALLOW_WITH_CONDITIONS", "unprobed so far: a single-page probe must confirm it is reachable and machine-readable before any plan depends on it"),
 ("retrosheet.org", ["retrosheet"], ["mlb.retrosheet"], "static bulk downloads of event files and game logs", "low (free for non-commercial use with the required attribution notice)", "free", "HISTORICAL (1901 onward)", "LOW_PRIORITY", "adds little: the MLB Stats API already gives pitch-level data for 2008+ (measured); only long pre-2008 history is new"),
 ("peter-tanner.com", ["moneypuck"], ["nhl.shots_xy"], "bulk CSV/zip downloads (MoneyPuck data page)", "low (free with attribution)", "free", "HISTORICAL (shots with xG 2007+)", "LOW_PRIORITY", "already collected into the NHL archive (1.4M extension rows); only useful to re-verify rows"),
 ("www.barttorvik.com", ["barttorvik"], ["cbb.ratings_barttorvik"], "public tables/CSVs (no official API)", "medium-high (site asks for gentle use; no explicit bulk licence)", "free", "HISTORICAL (daily time-machine ratings back several seasons)", "HOLD_FOR_OWNER", "ask the site owner or use a documented dataset (cbbdata API with a free key) instead of scraping"),
 ("understat.com", ["understat"], ["soc.xg_events"], "public pages with embedded JSON (no API)", "medium-high (no explicit licence; scraping)", "free", "HISTORICAL (shot-level xG for 6 leagues from 2014-15)", "HOLD_FOR_OWNER", "restricted-scraping territory: do not allowlist without the owner's decision; StatsBomb open data (already reachable) covers selected competitions"),
]
NOT = [
 ("baseballsavant.mlb.com", "Statcast CSV export: terms restrict automated bulk use and the same pitch/hit data is already reachable through statsapi.mlb.com (measured). Not needed."),
 ("www.pro-football-reference.com / www.basketball-reference.com / www.sports-reference.com / fbref.com", "Sports-Reference terms restrict bulk scraping and enforce rate limits; FBref's advanced Opta data was withdrawn (catalog marks it unavailable_public). Do not collect from them."),
 ("www.transfermarkt.com", "terms prohibit automated scraping; injuries/values are live-only anyway."),
 ("www.fangraphs.com", "terms restrict scraping; projections are current-vintage only, so history is not obtainable here."),
 ("www.dailyfaceoff.com, www.rotowire.com", "scraping-only lineup/news pages with restrictive terms; the value is prospective vintages, which the owner should capture from permitted official feeds instead."),
 ("kenpom.com, api.the-odds-api.com, stats.nba.com paid tiers, Opta/StatsBomb commercial, PFF, Synergy, Sportradar", "PAID or market-derived: not added without separate permission; odds data is a benchmark and never a market-free input."),
 ("cdn.nba.com, stats.nba.com", "these returned an ORIGIN block (HTTP 403 from the provider), not an egress denial: allowlisting cannot fix it (the provider blocks cloud IP ranges)."),
 ("www.atptour.com, www.wtatennis.com", "terms prohibit scraping; draws/order-of-play are live-only; Sackmann files cover results."),
]
NO_NEW_HOST = [
 ("site.api.espn.com (already reachable)", ["cbb.box_player", "cfb.box_player"], "The probe 404 for ESPN's summary endpoint used a guessed event id. Test it with real event ids from the collected scoreboards: no allowlist change needed. Unlocks college box scores / play-by-play for the college inputs."),
 ("github.com release assets for nflverse (already reachable)", ["nfl.pbp", "nfl.snap_counts", "nfl.injuries_weekly", "nfl.depth_charts", "nfl.participation", "nfl.ftn_charting", "nfl.nextgen_stats", "nfl.pfr_advstats", "nfl.player_stats_weekly", "nfl.rosters"], "Reachable and measured (206 range probes + earlier year probes): the NFL raw data can be pulled today (the replay in this phase pulled pbp 2010-2026 and games.csv)."),
 ("statsapi.mlb.com (already reachable)", ["mlb.pitch_pa_events", "mlb.boxscore_player", "mlb.transactions"], "Pitch/PA feed and boxscores for 2008+ can be pulled without any new host; only collection effort is needed."),
 ("api-web.nhle.com (already reachable)", ["nhl.shots_xy"], "Coordinates and play-by-play already reachable; shift charts are on a different host (api.nhle.com, proposed above)."),
 ("www.football-data.co.uk (already reachable)", ["soc.results_shots_cards"], "Pulled in this phase's replay (5 leagues x 11 seasons)."),
]


def build() -> dict:
    rows = json.loads((DF / "input_audit.json").read_text())["rows"]
    reg = json.loads((DF / "datasets.json").read_text())["datasets"]
    probes = EV.probes(); out = []
    for host, pids, dss, method, tos, cost, hist, tier, cond in H:
        touched = [r for r in rows if any(x["satisfied_by"] in dss for x in r["requirements"])]
        limiting = [r for r in rows if r["bucket"] in ("REQUIRES_COLLECTION", "BLOCKED") and (lambda lim: lim and lim[0]["satisfied_by"] in dss)(sorted((x for x in r["requirements"] if x["satisfied_by"]), key=lambda x: -reg[x["satisfied_by"]]["access_rank"]))]
        arch = sorted({f"{r['sport']}:{a}" for r in touched for a in r["archetypes"]})
        res = [probes[p]["result"] for p in pids if p in probes]
        out.append({"host": host, "tier": tier, "datasets": dss, "dataset_status_now": {d: reg[d]["access_status"] for d in dss if d in reg}, "probe_results_now": dict(zip(pids, res)), "access_method": method, "tos_risk": tos, "cost": cost, "history_or_prospective": hist, "condition": cond,
                    "inputs_that_depend_on_it": len(touched), "inputs_limited_by_it": len(limiting), "archetype_links": len(arch), "sports": sorted({r["sport"] for r in touched}),
                    "buckets_of_dependent_inputs": {b: sum(1 for r in touched if r["bucket"] == b) for b in ("COMPUTABLE", "REQUIRES_COLLECTION", "BLOCKED")}})
    order = {"ALLOW": 0, "ALLOW_WITH_CONDITIONS": 1, "HOLD_FOR_OWNER": 2, "LOW_PRIORITY": 3}
    out.sort(key=lambda x: (order[x["tier"]], -x["inputs_that_depend_on_it"]))
    nn = []
    for h, dss, note in NO_NEW_HOST:
        touched = [r for r in rows if any(x["satisfied_by"] in dss for x in r["requirements"])]
        nn.append({"host": h, "datasets": dss, "note": note, "inputs_that_depend_on_it": len(touched), "archetype_links": len({f"{r['sport']}:{a}" for r in touched for a in r["archetypes"]})})
    return {"schema_version": "network-access-proposal-1.0", "status": "RESEARCH_ONLY", "changes_made": "none: this is a proposal; no environment setting, allowlist or permission was changed", "needs_new_host": out, "no_new_host_needed": nn, "not_recommended": [{"host": h, "why": w} for h, w in NOT],
            "prospective_capture_note": "Vintage data (injury/lineup/news/forecast snapshots) cannot be backfilled. Capture needs a scheduled job; this sandbox is ephemeral, so the capture should run where the owner already runs scheduled work (for example GitHub Actions in the sibling *-edge-finder repos, free tier) against hosts that are already reachable. Starting it early matters: every day of delay is a day of vintage history that can never be recovered."}


def render(p: dict) -> str:
    L = ["# SIFT Alpha network access proposal (RESEARCH_ONLY: proposal only, nothing changed)", "",
         "Generated by `python -m alpha_engine.input_research.data_foundation.access_proposal`; do not edit by hand. **No environment setting, allowlist or permission was changed.** Every host below needs the owner's explicit approval, one host at a time; none is a blanket request, none involves a paid service, and anything that would need restricted scraping is listed under *not recommended*. "
         "Unlock counts are computed from the committed audit rows. Terms-of-use and cost statements are documented from providers' public terms as known to the author and are **not verified from this runner**: read each provider's terms before approving.", "",
         "## 1. Datasets obtainable with NO new host (collect now)", "", "| Host (already reachable) | Datasets | Inputs depending | Archetype links | Note |", "|---|---|---|---|---|"]
    for x in p["no_new_host_needed"]:
        L.append(f"| `{x['host']}` | {', '.join('`'+d+'`' for d in x['datasets'])} | {x['inputs_that_depend_on_it']} | {x['archetype_links']} | {x['note']} |")
    L += ["", "## 2. Hosts proposed for allowlisting, in priority order", "", "Priority = tier, then number of inputs depending on the dataset. `ALLOW` = low terms risk and clear value; `ALLOW_WITH_CONDITIONS` = approve only with the stated condition; `HOLD_FOR_OWNER` = restricted-scraping territory, not recommended without a decision; `LOW_PRIORITY` = little incremental value.", "",
          "| # | Exact hostname | Tier | Datasets unlocked (status now) | Inputs depending / limited by it | Archetype links | Access method | ToS risk | Cost | Historical vs prospective | Condition |", "|---|---|---|---|---|---|---|---|---|---|---|"]
    for i, x in enumerate(p["needs_new_host"], 1):
        L.append(f"| {i} | `{x['host']}` | {x['tier']} | " + ", ".join(f"`{d}` ({s})" for d, s in x["dataset_status_now"].items()) + f" | {x['inputs_that_depend_on_it']} / {x['inputs_limited_by_it']} | {x['archetype_links']} | {x['access_method']} | {x['tos_risk']} | {x['cost']} | {x['history_or_prospective']} | {x['condition']} |")
    L += ["", "## 3. Not recommended", "", "| Host(s) | Why |", "|---|---|"] + [f"| {x['host']} | {x['why']} |" for x in p["not_recommended"]]
    L += ["", "## 4. Prospective capture (cannot be backfilled)", "", p["prospective_capture_note"], ""]
    return "\n".join(L)


def main() -> int:
    p = build()
    OUT_JSON.write_text(json.dumps(p, indent=0, sort_keys=True, ensure_ascii=False) + "\n")
    OUT_DOC.write_text(render(p))
    print("wrote", OUT_DOC.relative_to(ROOT), len(p["needs_new_host"]), "hosts proposed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
