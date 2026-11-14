"""nflverse dataset/column licence-lane audit (RESEARCH_ONLY, documentation only, no data downloaded).

Usage: python3 -I nflverse_column_audit.py <path to nflverse/nflreadr checkout>
Input: nflreadr data-raw/dictionary_* files (metadata only) at the commit recorded in the output.
Output: nflverse_column_audit.csv + nflverse_column_audit_summary.json next to this file.

Lanes (licence statements are as published by nflverse; no upstream terms were read because the
upstream hosts are unreachable from this environment):
  A_CC_BY_4_0_NFLVERSE_DERIVED  nflverse/nflfastR model outputs or identifiers computed by nflverse (CC BY 4.0 wrapper);
                                still trained on / keyed to NFL-feed data, so upstream caveat remains
  B_CC_BY_SA_4_0_FTN            FTN-provided data, explicitly CC BY-SA 4.0, attribution "FTN Data via nflverse"
  B2_CC_BY_SA_4_0_FFVERSE       ffopportunity model outputs, CC BY-SA 4.0 (ffverse README)
  C_UPSTREAM_NFL                NFL feeds (GSIS / Shield API / Next Gen Stats / injury API) redistributed under the
                                CC BY 4.0 wrapper; nflreadr README: "NFL data ... belong to their respective owners,
                                and are governed by their terms of use"  -> UNRESOLVED
  D_UPSTREAM_PFR                Pro-Football-Reference (Sports Reference LLC) -> UNRESOLVED
  E_UPSTREAM_OTHER              OverTheCap, ESPN, FantasyPros/DynastyProcess, nfldata (no licence file) -> UNRESOLVED
  F_BETTING_LINES               sportsbook-derived lines/odds columns; upstream unstated or PFR -> UNRESOLVED
"""
import csv, json, sys, re, hashlib, pathlib, subprocess

src = pathlib.Path(sys.argv[1]); dr = src / "data-raw"
here = pathlib.Path(__file__).parent
commit = subprocess.run(["git", "-C", str(src), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()

FILE_LANE = {
    "dictionary_ftn_charting.csv": ("B_CC_BY_SA_4_0_FTN", "load_ftn_charting.R: 'released under the CC-BY-SA 4.0 ... attribution must be made to FTN Data via nflverse'"),
    "dictionary_participation.csv": ("MIXED_B_FTN_2023PLUS_C_NGS_PRE2023", "load_participation.R: pre-2023 from NFL NGS; 2023+ courtesy of FTN, CC-BY-SA 4.0"),
    "dictionary_nextgenstats.csv": ("C_UPSTREAM_NFL", "load_nextgen_stats.R: 'provided by NFL Next Gen Stats'"),
    "dictionary_injuries.csv": ("C_UPSTREAM_NFL", "load_injuries.R: 'Data collected from an API for weekly injury report data' (API owner unstated)"),
    "dictionary_rosters.csv": ("C_UPSTREAM_NFL", "nflverse-data release weekly_rosters: 'via NFL Shield v2 API'"),
    "dictionary_roster_status.csv": ("C_UPSTREAM_NFL", "roster status codes (NFL)"),
    "dictionary_players.csv": ("MIXED_C_NFL_D_PFR_A_IDS", "load_players.R: bio mostly from GSIS; draft info from PFR; id crosswalk built by nflverse"),
    "dictionary_playerstats.csv": ("C_UPSTREAM_NFL", "load_stats.R: aggregates computed by nflfastR::calculate_stats() from NFL play-by-play"),
    "dictionary_playerstats_def.csv": ("C_UPSTREAM_NFL", "as playerstats"),
    "dictionary_player_stats.json": ("C_UPSTREAM_NFL", "as playerstats"),
    "dictionary_team_stats.json": ("C_UPSTREAM_NFL", "as playerstats"),
    "dictionary_pfr_passing.csv": ("D_UPSTREAM_PFR", "load_pfr_advstats.R: 'provided by Pro Football Reference'"),
    "dictionary_snap_counts.csv": ("D_UPSTREAM_PFR", "load_snap_counts.R: 'provided by Pro Football Reference'"),
    "dictionary_combine.csv": ("D_UPSTREAM_PFR", "load_combine.R: 'courtesy of PFR'"),
    "dictionary_draft_picks.csv": ("D_UPSTREAM_PFR", "load_draft_picks.R: 'courtesy of PFR'"),
    "dictionary_contracts.csv": ("E_UPSTREAM_OTHER", "load_contracts.R: 'from OverTheCap.com'"),
    "dictionary_espn_qbr.csv": ("E_UPSTREAM_OTHER", "load_espn_qbr.R: ESPN QBR"),
    "dictionary_depth_charts.csv": ("E_UPSTREAM_OTHER", "NEWS.md: source changed from NFL Data Exchange to ESPN (2025 structure); earlier seasons NFL"),
    "dictionary_ff_rankings.csv": ("E_UPSTREAM_OTHER", "load_ffverse.R: FantasyPros ECR via DynastyProcess"),
    "dictionary_ff_playerids.csv": ("E_UPSTREAM_OTHER", "load_ffverse.R: DynastyProcess player id database"),
    "dictionary_ffopps.csv": ("B2_CC_BY_SA_4_0_FFVERSE", "ffopportunity README 'Terms of Use': models and expected points data CC BY-SA 4.0"),
    "dictionary_schedules.csv": ("E_UPSTREAM_OTHER", "load_schedules.R: 'maintained by Lee Sharpe' (nflverse/nfldata; no LICENSE file found, raw LICENSE/LICENSE.md 404)"),
    "dictionary_trades.csv": ("E_UPSTREAM_OTHER", "load_trades.R: 'maintained by Lee Sharpe' (nfldata; no LICENSE file)"),
}
MODEL = re.compile(r"^(ep|epa|wp|wpa|def_wp|home_wp|away_wp|home_wp_post|away_wp_post|cp|cpoe|xpass|pass_oe|qb_epa|"
                   r"(total_)?(home|away)_.*_(epa|wpa)|.*_epa|.*_wpa|xyac_.*|no_score_prob|opp_.*_prob|.*_td_prob|"
                   r".*_prob|success|vegas_.*)$")
ODDS = re.compile(r"(moneyline|spread_line|total_line|_odds$|^vegas_)")
ID = re.compile(r"(_id$|_ids$|^id$|_player_id|gsis|pfr_id|espn_id)")

rows = []
for f in sorted([p for p in dr.glob("dictionary_*") if p.suffix in (".csv", ".json")]):
    if f.suffix == ".json":
        data = json.loads(f.read_text()); fields = [(d.get("field") or d.get("variable") or d.get("name"), d.get("description", "")) for d in (data if isinstance(data, list) else data.get("fields", []))]
    else:
        txt = f.read_text(encoding="utf-8-sig"); delim = ";" if f.name == "dictionary_nextgenstats.csv" else ","
        rd = list(csv.reader(txt.splitlines(), delimiter=delim)); hdr = [h.lower() for h in rd[0]]
        fi = next(i for i, h in enumerate(hdr) if h in ("field", "field_name", "status")); di = next((i for i, h in enumerate(hdr) if h == "description"), None)
        fields = [(r[fi], r[di] if di is not None and di < len(r) else "") for r in rd[1:] if r]
    for name, desc in fields:
        if f.name == "dictionary_pbp.csv":
            m = re.search(r"\(Source: ([^)]+)\)", desc or "")
            if ODDS.search(name):
                lane, basis = "F_BETTING_LINES", ("vegas_* model uses spread_line (Source: Pro-Football-Reference)" if name.startswith("vegas_") else f"description: (Source: {m.group(1) if m else 'unstated'})")
            elif m:
                lane, basis = ("D_UPSTREAM_PFR" if "Pro-Football-Reference" in m.group(1) else "E_UPSTREAM_OTHER"), f"description: (Source: {m.group(1)})"
            elif MODEL.match(name):
                lane, basis = "A_CC_BY_4_0_NFLVERSE_DERIVED", "nflfastR model output computed from NFL play-by-play (EP/WP/CP/xYAC/xpass)"
            else:
                lane, basis = "C_UPSTREAM_NFL", "NFL play-by-play feed field via nflfastR (no source annotation)"
        elif f.name == "dictionary_schedules.csv" and ODDS.search(name):
            lane, basis = "F_BETTING_LINES", "schedules odds/lines column; sportsbook upstream unstated (nfldata)"
        else:
            lane, basis = FILE_LANE.get(f.name, ("UNCLASSIFIED", ""))
        rows.append({"dictionary": f.name, "field": name, "lane": lane, "basis": basis, "is_identifier": bool(ID.search(name or ""))})

out = here / "nflverse_column_audit.csv"
with out.open("w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
summ = {}
for r in rows: summ.setdefault(r["dictionary"], {}).setdefault(r["lane"], 0); summ[r["dictionary"]][r["lane"]] += 1
sha = {f.name: hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted([p for p in dr.glob("dictionary_*") if p.suffix in (".csv", ".json")])}
(here / "nflverse_column_audit_summary.json").write_text(json.dumps({"nflreadr_commit": commit, "dictionary_sha256": sha, "fields_by_lane": summ}, indent=1, sort_keys=True))
print(commit, len(rows)); print(json.dumps(summ, indent=0))
