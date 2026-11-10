"""usage: python3 -I assemble.py <SCRATCH>  -> <SCRATCH>/result.json"""
import sys, json, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import proposals as P
S = sys.argv[1]
nba = json.load(open(f"{S}/nba_measured.json"))
nhlg = json.load(open(f"{S}/nhl_goalies_measured.json"))
nhli = json.load(open(f"{S}/nhl_injuries_measured.json"))
R = {"generated_for": "SIFT Alpha read-only capture audit", "audited_utc": "2026-11-10",
     "method": "anonymous blobless shallow clones of public repos; measured from archived files; schedule = last snapshot per archive day",
     "workflow_schedules_on_main": {
        "nba capture_worker.yml": "cron */5 bootstrap + self-dispatching ~300-min worker; in-worker plan cadence 15/10/7/5 min tiers; context job (schedule, starters, injuries, rosters) gated by conductor.decide(): >55 min in active window with tip within 30h, 6 min inside 40 min of tip, 6h/24h floors",
        "nba pit_injuries.yml": "cron 41 * * * * (hourly) + PR backfill; writes data-injury-pit",
        "nba starters-live-check.yml": "workflow_dispatch + push of .trigger/starters-live only (no schedule); read-only artifact",
        "nhl capture_worker.yml": "cron */5 bootstrap + self-dispatching worker; context job >55 min in active window (<=30h to tip), PREGAME_FAST_REFRESH_MIN=20 within 3h",
        "nhl nhl_lineup_probe.yml": "workflow_dispatch only; requires nhl_rights_ack='written-permission-received', from_utc, to_utc",
        "nhl slate_watch.yml": "cron 11,41 14-23,0-3 * * * ; read-only watchdog; does not capture goalies/injuries"},
     "not_found_or_not_checked": ["audit/nba-starters-* branches do not exist in chmoses98/nba-edge-finder (only in sift-alpha); feat/pit-espn-starters-capture and feat/starters-live-verification-20261104 point at the same commit d31d6dd (starters.py + live-check script; no captured data on them)"]}
sg = nba["nba_starters"]; ni = nba["nba_injuries"]; pit = nba["nba_injuries_pit"]
R["nba_starters"] = sg | {
  "verdict": "READY_WITH_GAPS",
  "verdict_reasons": ["Only 5 archive days (2026-11-06..11-10), 57 files, 33 games - too short to power any study yet, but it is running in the production worker.",
     "Both sides CONFIRMED at the last pre-tip poll for 28/33 games (85%); first CONFIRMED observed a median 14.7 min before tip (max 27.2), i.e. flags appear late; resolution is bounded by poll spacing.",
     "Capture window is T-120..T-0 by construction (WINDOW_MIN=120), polls inside it have median gap 10 min / p90 36.6 / max 82 min (design 5-6 min); 3/32 games had last pre-tip poll >30 min before tip.",
     "No source publication timestamp in the ESPN core-roster payload; absence of change IS distinguishable from absence of capture (each poll writes a row, NONE_PUBLISHED included).",
     "No FETCH_FAILED, empty roster or empty body rows observed (0/304)."],
  "proposed_changes": P.NBA_STARTERS}
R["nba_injuries"] = {"archive_context_injuries": ni, "pit_branch_data_injury_pit": pit,
  "verdict": "READY_WITH_GAPS",
  "verdict_reasons": [f"Archive: 681 files over 54 days; inside game windows gap median {ni['capture_instants_active_game_windows']['gap_minutes']['median']} min, p90 {ni['capture_instants_active_game_windows']['gap_minutes']['p90']}, max {ni['capture_instants_active_game_windows']['gap_minutes']['max']} (n=291) vs a 15-min tier design and a 15-min official publication cadence.",
     "Per game (n=220 games with full T-6h window): median 6 captures in T-6h..T0, latest capture before tip median 32 min (p90 57 min, max 314); 114/220 games had their latest capture >30 min before tip; 0 games with zero captures.",
     "Official-PDF rows missing in 300 of 681 capture files (the stream is ESPN-only there) and game_id/nba_id are 100% null in 94,024 rows.",
     "Source timestamp: report_time_utc present (official slot); no upload time in the archive rows. The pit branch has last_modified_utc, sha256 and a hash chain, but only 100 official + 139 ESPN files in 29 days (20% of the hourly cron; median gap 300-322 min, max 652 min), so it cannot support pregame timing on its own.",
     "Archive rows are full snapshots (not delta-only): absence of change is distinguishable from absence of capture. pit official is delta-only by (slot, sha256): a skipped run leaves no trace.",
     "ESPN archive rows change on every capture (0/680 identical) because report_time_utc for ESPN rows is the capture time, not a source time."],
  "proposed_changes": P.NBA_INJ}
R["nhl_goalies"] = {"archive_goalie_observations": nhlg["nhl_goalies"], "lineup_probe_branch_lineup_probe_data": nhlg["nhl_goalies_probe"],
  "verdict": "READY_WITH_GAPS",
  "verdict_reasons": ["Archive: 929 files over 43 days, 22,970 rows, 298 games with goalie rows; in game windows capture gap median 30 min, p90 63, max 164 (n=509).",
     "Per game (n=285 with full T-6h window): median 7 captures in T-6h..T0, latest capture before start median 22.9 min (p90 56.7); 10 games had zero captures in the window; 109 had latest capture >30 min before start.",
     "At the last pre-start capture 480/596 team observations were CONFIRMED (80.5%); 58 PROJECTED + 58 PROBABLE (19.5%). Both teams confirmed in 205/298 games.",
     "source_reported_at_utc exists but is null for 65% of dailyfaceoff rows (all PROJECTED); where present the observed-minus-reported lag is median 5.1 h / p90 16.9 h (n=7,908), so first-seen precision is limited by poll spacing; player_id null in 98.5% of rows.",
     "Full snapshots (not delta-only); 95.5% of consecutive same-(game,team) observations identical -> change vs no-capture distinguishable.",
     "Lineup probe is NOT usable as a dataset: manual dispatch only, rights-gated, one campaign (5 games, 2026-10-25/26), stores hashes and id lists rather than parsed lineups.",
     "Third-party dependency on DailyFaceoff (not an official NHL source); terms status not verified here."],
  "probe_verdict": "NOT_READY", "proposed_changes": P.NHL_GOALIES}
R["nhl_injuries"] = nhli["nhl_injuries"] | {
  "verdict": "READY_WITH_GAPS",
  "verdict_reasons": ["832 files over 43 days, 103,898 rows (ESPN injuries list, full snapshot each context run, median 127 rows/file); same capture instants as goalies: in-window gap median 31 min, p90 63.7, max 164.3 (n=480).",
     "Per game (n=285): median 6 captures in T-6h..T0; 10 games zero captures; latest capture before tip median 23.3 min (p90 58).",
     "'reported' is a minute-resolution ESPN item date separate from capture time, but it is the newest update only (median age at observation 143 h, long-term IR dominated): no status-change history; espn_id null in 100% of rows.",
     "Only 320/831 consecutive files identical: ~1,430 rows added/removed across all consecutive pairs, so changes are detectable by diffing full snapshots; no explicit delta log exists."],
  "proposed_changes": P.NHL_INJ}
R["cannot_verify"] = [
  "Whether GitHub Actions runs that did not commit (skipped or cancelled) happened: only committed files are visible; absent captures cannot be separated from run failures.",
  "Capture timestamps used are the file-name instants; for starters I also used the in-row observed_at_utc. Commit/push lag of data-archive was not measured.",
  "Games absent from the 43/54 last-of-day schedule snapshots (e.g. postponed or added late) are invisible to the per-game test; start times are as last seen, not 'scheduled at capture time'.",
  "DailyFaceoff / ESPN / NHL terms-of-use and rights status (NHL docs say unresolved; not independently checked).",
  "Whether ESPN core roster flags appear earlier than the first poll that saw them (poll spacing bounds this).",
  "audit/nba-starters-* branches (not present in the public repo); contents of docs/ were deliberately not used for numbers.",
  "Actions-minutes cost of the proposals; none of the proposed diffs were applied or tested."]
json.dump(R, open(f"{S}/result.json", "w"), indent=1, default=str)
print("written", os.path.getsize(f"{S}/result.json"))
