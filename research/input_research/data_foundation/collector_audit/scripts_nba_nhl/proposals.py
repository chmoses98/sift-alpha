"""PROPOSAL diffs (text only; nothing applied to any repo). Line numbers are indicative against main as read 2026-11-10."""
NBA = "chmoses98/nba-edge-finder"
NHL = "chmoses98/NHL-edge-finder"

def P(repo, file, text, why, approval):
    return {"repo": repo, "file": file, "status": "PROPOSAL - NOT APPLIED", "why": why, "diff_text": text,
            "requires_owner_approval": True, "owner_must_approve": approval}

NBA_STARTERS = [
 P(NBA, "src/nba_edge/workflows/conductor.py", """--- a/src/nba_edge/workflows/conductor.py
+++ b/src/nba_edge/workflows/conductor.py
@@ -70,2 +70,2 @@
-STARTER_WINDOW_MIN = 40.0     # fast context refresh when a tip is this close (confirmed-starter capture)
-STARTER_REFRESH_MIN = 6.0
+STARTER_WINDOW_MIN = 45.0     # fast context refresh when a tip is this close (confirmed-starter capture)
+STARTER_REFRESH_MIN = 3.0     # measured: first CONFIRMED seen 5.4-27.2 min before tip (median 14.7, n=28); 6-min polls bound the flag time only to +-6 min
""", "Measured in-window poll gaps: median 10 min, p90 36.6 min, max 82 min (n=83) vs the 5-6 min design. Tighter refresh narrows the first-seen bound for a flag that appears a median 14.7 min before tip.",
  "Increases the number of ESPN scoreboard+roster fetches and archive commits in the last 45 min before each tip (context job also re-fetches 11 scoreboard days). Owner must accept the extra commit volume and ESPN request rate."),
 P(NBA, ".github/workflows/starters-live-check.yml", """--- a/.github/workflows/starters-live-check.yml
+++ b/.github/workflows/starters-live-check.yml
@@ -5,6 +5,12 @@
 on:
   workflow_dispatch:
     inputs:
       minutes:
         description: "How long to poll"
         default: "280"
+  schedule:
+    # OPTIONAL redundancy for the capture_worker starters stream (research artifact only; pushes nothing).
+    # 20:30Z + 280 min covers 22:00Z-01:10Z tips; add a second cron for 00:00Z-03:30Z West-coast tips.
+    - cron: "30 20 * * *"
+    - cron: "10 0 * * *"
   push:
     paths:
       - ".trigger/starters-live"
""", "The capture_worker already captures starters (data-archive context/starters). This only adds an independent, 4-min-interval ESPN poll as a cross-check; output lives in a 30-day run artifact, so it is NOT a durable dataset unless the workflow is also changed to push to a data branch.",
  "Owner decides whether a second ESPN poller is wanted (GitHub cron delivery is unreliable: pit_injuries delivered ~20% of hourly runs). Minutes of Actions consumed: ~280 min x 2 per day."),
 P(NBA, "src/nba_edge/data/starters.py", """--- a/src/nba_edge/data/starters.py
+++ b/src/nba_edge/data/starters.py
@@ -26,7 +26,7 @@
 STARTERS_KIND = "context/starters"
-WINDOW_MIN = 120.0
+WINDOW_MIN = 120.0   # DO NOT widen to T-6h for flags: measured earliest CONFIRMED = 27.2 min before tip; rows before T-60 are all NONE_PUBLISHED
 SOURCE = "espn_core_roster"
+# FIELD ADDITION (optional): response_etag / last_modified header of the core roster fetch, stored on each row as
+#   "http_last_modified": resp.headers.get("Last-Modified"), "http_etag": resp.headers.get("ETag")
+# so that a source-side publish time can be bounded when ESPN supplies it (payload itself has no timestamp).
""", "Measured: the ESPN core-roster payload has no publish timestamp; at most an HTTP Last-Modified/ETag could be added. A T-6h window would only add NONE_PUBLISHED rows.",
  "Owner approval to change the stored schema (new optional columns) - schema version bump for context/starters."),
]
NBA_INJ = [
 P(NBA, "src/nba_edge/workflows/conductor.py", """--- a/src/nba_edge/workflows/conductor.py
+++ b/src/nba_edge/workflows/conductor.py
@@ -97,3 +97,3 @@
     context = (
-        (in_season and next_tip_h is not None and next_tip_h <= 30 and active_window and (last_context_age_min is None or last_context_age_min > 55))
+        (in_season and next_tip_h is not None and next_tip_h <= 30 and active_window and (last_context_age_min is None or last_context_age_min > (20 if next_tip_h <= 6 else 55)))
         or last_context_age_min is None
""", "Measured archive cadence inside game windows: median 60 min, p90 68, max 143 (n=291 gaps); the official report publishes every 15 min and the newest report visible at the last pre-tip capture is a median 30 min (max 150) before tip.",
  "Raises capture/commit frequency to ~3/h in the last 6 h before the next tip (all context kinds, not only injuries). Owner must accept the volume and the effect on the preregistered sealed-study commit-lag assumptions."),
 P(NBA, ".github/workflows/pit_injuries.yml", """--- a/.github/workflows/pit_injuries.yml
+++ b/.github/workflows/pit_injuries.yml
@@ -17,3 +17,6 @@
   schedule:
-    # hourly at :41 (off the :00 rush); the report itself is published every 15 minutes
-    - cron: "41 * * * *"
+    # MEASURED delivery of the hourly cron: 139 runs wrote files vs ~698 expected (20%); median gap 300 min.
+    # Report slots are 15 min apart; request 4 wakes/hour at off-peak minutes so ~20% delivery still yields ~hourly.
+    - cron: "7,22,37,52 * * * *"
   workflow_dispatch: {}
""", "pit capture is the only stream with last_modified_utc (upload instant) and a hash chain; its delivery is the weakest of all (official files: median gap 322 min, p90 475, max 652).",
  "Owner approves ~4x Actions invocations on this workflow. Cron alone is documented unreliable (docs: 3.9% delivery for */10); the durable fix is to run scripts/pit_capture.py as a capture_worker job (separate proposal below)."),
 P(NBA, "src/nba_edge/worker/run.py", """--- a/src/nba_edge/worker/run.py
+++ b/src/nba_edge/worker/run.py
@@ -408,3 +408,6 @@
         ("matchup_shadow", ["nba", "matchup-shadow", "--out", "ARCHIVE"], 300.0),
+        # PROPOSAL: PIT injury capture inside the worker cycle (no cron dependence). Writes under the archive branch, NOT data-injury-pit.
+        # Needs a decide() gate (e.g. due when last pit capture > 15 min and a tip is within 6 h) and ALWAYS_DUE membership or a STATUS key.
+        ("pit_injuries", ["python", "scripts/pit_capture.py", "--root", "ARCHIVE/injury_pit"], 300.0),
""", "Moves the point-in-time injury capture (with last_modified_utc and sha256 chain) onto the one process that demonstrably runs every cycle.",
  "Owner decision: pit data would move from branch data-injury-pit to data-archive/injury_pit (changes the provenance/hash-chain location); requires a decide() gate and tests (tests/test_worker_health.py forbids new silent jobs)."),
 P(NBA, "src/nba_edge/data/injuries.py (field additions, indicative)", """FIELD ADDITIONS to context/injuries rows (currently game_id and nba_id are 100% null):
+  "last_modified_utc": <PDF HTTP Last-Modified>   # already computed by availability/capture.py, dropped by context
+  "pdf_sha256": <sha256 of PDF bytes>            # lets repeats be told from new publications
+  "slot_et": <report slot string>                 # source publication slot, distinct from report_time_utc parse
+  "espn_entry_date_utc": <ESPN item date>        # for source=espn_injuries rows (today report_time_utc is the capture time)
+  resolve nba_id via the identity registry (null in 100% of 94,024 rows) and game_id via home/away team + game_date_et
""", "Measured: 100% null game_id and nba_id in 94,024 archive rows; official rows have no upload time in this stream; ESPN rows' report_time_utc is not a source time.",
  "Schema change to a ledger kind consumed by simulate/evaluate; owner approves version bump and downstream test updates."),
]
NHL_GOALIES = [
 P(NHL, "src/nhl_edge/workflows/conductor.py", """--- a/src/nhl_edge/workflows/conductor.py
+++ b/src/nhl_edge/workflows/conductor.py
@@ -72,2 +72,2 @@
-PREGAME_FAST_HOURS = 3.0   # inside this window starters, lines and injuries move: refresh context and re-price far more often than hourly
-PREGAME_FAST_REFRESH_MIN = 20.0
+PREGAME_FAST_HOURS = 3.0   # inside this window starters, lines and injuries move: refresh context and re-price far more often than hourly
+PREGAME_FAST_REFRESH_MIN = 10.0
""", "Measured goalie capture in game windows: median gap 30 min, p90 63, max 164 (n=509 gaps); 116 of 596 team-observations (19.5%) were still PROJECTED/PROBABLE at the last pre-start capture.",
  "Halves the interval of the whole NHL context+simulate cycle inside T-3h (also drives sim_refresh_min). Owner accepts commit volume/runtime; DailyFaceoff request rate doubles (terms/etiquette check)."),
 P(NHL, "src/nhl_edge/data/goalie_watch.py + src/nhl_edge/worker/run.py (from branch claude/goalie-capture-proposal 57b52a7)", """PROPOSAL (already drafted on branch claude/goalie-capture-proposal, NOT wired):
 - cherry-pick src/nhl_edge/data/goalie_watch.py (append-only change log: FIRST_SEEN / STATUS_CHANGE / GOALIE_CHANGE / CONFIRMED with source_reported_at_utc and latency_min)
 - call watch_once() from the capture-worker cycle between 10:00 ET and puck drop, behind a repo variable GOALIE_WATCH=1 (default off), 1-3 min resolution
--- a/src/nhl_edge/worker/run.py
+++ b/src/nhl_edge/worker/run.py
@@ (inside _one_cycle, after the capture step; indicative)
+        if os.environ.get("GOALIE_WATCH") == "1" and cyc.hours_to_next_tip is not None and cyc.hours_to_next_tip <= 7:
+            self._run_goalie_watch(now)   # one DailyFaceoff GET; appends events under ARCHIVE/context/goalie_events/
""", "Measured: source_reported_at_utc is null for 65% of dailyfaceoff rows (all PROJECTED) and observed-minus-reported lag median 5.1 h / p90 16.9 h (n=7,908 non-null), so first-seen times cannot be separated from poll spacing at current cadence. The change log fixes that at near-zero storage.",
  "Owner approves enabling the poll (repo variable), the extra request rate against DailyFaceoff, and a >=4-week shadow period per the proposal doc."),
 P(NHL, "src/nhl_edge/data/goalies.py (field additions, indicative)", """FIELD ADDITIONS to context/goalie_observations rows:
+  "player_id": resolved NHL player id via roster map (currently null in 98.5% of 22,970 rows; only nhl_api_boxscore rows carry it)
+  "dfo_label": raw label ('Confirmed'|'Likely'|'Unconfirmed'...) as a column (currently only inside free-text `note`)
+  "game_time_gmt": from `note` as a column
+  "first_seen_status_utc": time this (game,team,status,name) tuple first appeared in our captures (derivable offline; add for convenience)
""", "Measured: player_id null 98.5%; label/time only embedded in the `note` string.",
  "Schema change to a ledger kind; owner approves schema version bump."),
 P(NHL, ".github/workflows/nhl_lineup_probe.yml", """--- a/.github/workflows/nhl_lineup_probe.yml
+++ b/.github/workflows/nhl_lineup_probe.yml
@@ -1,6 +1,9 @@
 on:
   workflow_dispatch:
     inputs:
       ...
+  schedule:
+    # NOT RECOMMENDED until NHL API rights are resolved (docs/research/lineup_sources/NHL_API_TERMS.md). A scheduled run has no inputs:
+    # the rights gate and from_utc/to_utc must come from a repo variable and be derived from the schedule snapshot.
+    - cron: "20 16 * * *"
@@ steps.watch (env)
-          FROM_IN: ${{ inputs.from_utc }}
-          TO_IN: ${{ inputs.to_utc }}
+          FROM_IN: ${{ inputs.from_utc || '' }}     # if empty: now ; TO_IN empty: now + 5.5 h
+          TO_IN: ${{ inputs.to_utc || '' }}
@@ rights gate
-          ACK: ${{ inputs.nhl_rights_ack }}
+          ACK: ${{ inputs.nhl_rights_ack || vars.NHL_RIGHTS_ACK }}
""", "Probe measured: one campaign, 5 games, 3 runs (2026-10-25/26), manual dispatch only; 10 offsets (T-120..T-5), 17/86 consecutive polls changed payload. Stores sha256 + id lists only (raw body for a subset).",
  "BLOCKING owner/legal decision: the workflow's own gate says 'written-permission-received' and the docs say NHL terms prohibit new automated compilation while rights are unresolved. Do not schedule without that written permission."),
]
NHL_INJ = [
 P(NHL, "src/nhl_edge/workflows/conductor.py", """(same change as the goalie proposal: PREGAME_FAST_REFRESH_MIN 20.0 -> 10.0 drives the injuries capture because injuries are written by the same `nhl context` job)""",
   "Injuries share the context job cadence; no separate injuries job exists.", "Same approval as the goalie cadence change (single knob)."),
 P(NHL, "src/nhl_edge/data/injuries.py (field additions, indicative)", """FIELD ADDITIONS to context/injuries rows (ESPN snapshot):
+  "reported_at_utc": ESPN item date parsed to full ISO UTC (today 'reported' is a minute-resolution string)
+  "first_seen_utc": first capture in which this (team, player, status, detail, reported) tuple appeared
+  "status_changed": bool vs previous capture (add an append-only injury_events change log analogous to goalie_watch)
+  "espn_id": currently null in 100% of 103,898 rows (resolve via the ESPN athlete id in the feed)
""", "ESPN's feed is a current-state list with no history: a player removed from the list (returned) leaves no trace except by diffing consecutive captures.",
  "Owner approves schema/new ledger kind."),
]
