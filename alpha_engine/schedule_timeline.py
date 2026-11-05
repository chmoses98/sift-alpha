"""Fail-closed point-in-time *scheduled* start ledger for NBA/NHL.

All rows originate in independently captured, Git-blob-verified schedule files.
The file name's second-granularity capture clock is NOT enough to establish
availability: the row's own observed timestamp must also precede a query.
Scheduled starts are NOT verified actual tip/puck drops; this module NEVER
assigns Kalshi tickers, pregame eligibility, or trading authority.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import timedelta
from .delta_timeutil import parse_iso
from .context_source_audit import REPOS, capture_at, check_manifest, read_source

MAX_SCHEDULE_ROWS = 1000
MAX_CLOCK_SKEW_SECONDS = 1


def _iso(dt):
    return dt.isoformat().replace('+00:00', 'Z')


def normalize_schedule_row(row, source, sport):
    """Require observed schedule identity and source availability, never a score."""
    if not isinstance(row, dict):
        raise ValueError('Non-object schedule row')
    game_id = row.get('game_id')
    if not isinstance(game_id, str) or not game_id.strip() or len(game_id) > 64:
        raise ValueError('Missing/invalid independent game id')
    if sport == 'NBA' and not (game_id.startswith('espn:') or (game_id.isdigit() and len(game_id) == 10)):
        raise ValueError('NBA game id is not an official/ESPN schedule identifier')
    if sport == 'NHL' and not (game_id.isdigit() and len(game_id) == 10):
        raise ValueError('NHL game id is not a ten-digit NHL identifier')
    home, away = row.get('home_team_id'), row.get('away_team_id')
    if type(home) is not int or type(away) is not int or home <= 0 or away <= 0 or home == away:
        raise ValueError('Missing or contradictory official team ids')
    if not isinstance(row.get('start_time_utc'), str) or not isinstance(row.get('_observed_at_utc'), str):
        raise ValueError('Missing scheduled start or row observation clock')
    start = parse_iso(row['start_time_utc'])
    observed = parse_iso(row['_observed_at_utc'])
    capture = parse_iso(source['captured_at'])
    # Ledger writes file path to whole second and rows with subsecond UTC.
    if not capture <= observed < capture + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        raise ValueError('Row observation clock inconsistent with source capture')
    return {
        'sport': sport, 'game_id': game_id, 'home_team_id': home,
        'away_team_id': away, 'scheduled_start_utc': _iso(start),
        'observed_at_utc': _iso(observed), 'source_capture_at_utc': _iso(capture),
        'source_path': source['path'], 'source_commit': source['commit'],
        'source_blob_sha1': source['sha'],
        'source_provider': row.get('source') if isinstance(row.get('source'), str) else None,
        'start_authority': 'ARCHIVED_SCHEDULED_START_NOT_ACTUAL_START',
        'kalshi_contract_join': 'NOT_ESTABLISHED',
        'pregame_authority': 'NONE',
    }


def schedule_asof(observations, cutoff):
    """A game may be quarantined ONLY by conflicting evidence observed as of cutoff.

    Later team-identity changes must not retroactively erase an earlier known
    game. This is a historical research ledger, not a physical game/market join.
    """
    at = parse_iso(cutoff)
    eligible = [r for r in observations if parse_iso(r['observed_at_utc']) <= at]
    latest = {}
    identities = defaultdict(set)
    revisions = defaultdict(set)
    for row in eligible:
        gid = row['game_id']
        identities[gid].add((row['home_team_id'], row['away_team_id']))
        revisions[gid].add(row['scheduled_start_utc'])
        latest[gid] = row
    conflicts = {gid for gid, teams in identities.items() if len(teams) > 1}
    for gid in conflicts:
        latest.pop(gid, None)
    return {
        'asof_utc': _iso(at),
        'n_games_with_known_schedule': len(latest),
        'n_games_quarantined_for_identity_conflict_asof': len(conflicts),
        'n_games_with_scheduled_start_after_asof':
            sum(parse_iso(r['scheduled_start_utc']) > at for r in latest.values()),
        'n_games_with_observed_schedule_start_revision':
            sum(len(revisions[gid]) > 1 for gid in latest),
        'n_future_schedule_rows_excluded':
            len(observations) - len(eligible),
        'examples': [latest[gid] for gid in sorted(latest)[:3]],
        'start_authority': 'SCHEDULE_ONLY', 'pregame_authority': 'NONE',
    }


def verified_tape_ticks(tape_rows, tape_report):
    """Require complete verified sparse-tape tick inventory, not invented clocks.

    Upstream verified_tape builds and verifies hashes. Here, require every row
    to agree with that report's source identities, counts and verified window.
    """
    if not isinstance(tape_rows, list) or len(tape_rows) > 120000:
        raise ValueError('Missing/unbounded verified tape rows')
    counts = Counter()
    clocks = defaultdict(set)
    clock_sources = defaultdict(lambda: defaultdict(set))
    for row in tape_rows:
        if not isinstance(row, dict) or row.get('sport') not in REPOS:
            raise ValueError('Unrecognized tape sport/row')
        sport = row['sport']
        tape = tape_report['sports'][sport]
        if row.get('pregame_status') != 'UNVERIFIED' or row.get('quote_execution_authority') != 'NONE':
            raise ValueError('Tape row improperly claims betting authority')
        if not isinstance(row.get('ticker'), str) or not row['ticker']:
            raise ValueError('Missing exact market ticker')
        sources = {x['path']: x['blob_sha1'] for x in tape['source_files']}
        path = row.get('source_path')
        if path not in sources or row.get('source_blob_sha1') != sources[path]:
            raise ValueError('Tape source not in verified manifest')
        at = parse_iso(row['observed_at_utc'])
        if not parse_iso(tape['base_at']) <= at <= parse_iso(tape['last_verified_at']):
            raise ValueError('Tape observation outside verified window')
        expected_kind = 'CHECKPOINT' if path == tape['source_files'][0]['path'] else 'DELTA_TOUCHED'
        if row.get('source_kind') != expected_kind:
            raise ValueError('Tape source kind inconsistent with source path')
        if expected_kind == 'CHECKPOINT' and at != parse_iso(tape['base_at']):
            raise ValueError('Checkpoint observation clock mismatch')
        if expected_kind == 'DELTA_TOUCHED' and at <= parse_iso(tape['base_at']):
            raise ValueError('Delta clock before/at checkpoint')
        counts[sport] += 1
        clocks[sport].add(at)
        clock_sources[sport][at].add(path)
    result = {}
    for sport in sorted(REPOS):
        tape = tape_report['sports'][sport]
        if counts[sport] != tape['n_sparse_tape_rows']:
            raise ValueError('Sparse tape rows missing or added')
        ordered = sorted(clocks[sport])
        if (len(ordered) != tape['n_verified_delta_ticks'] + 1 or
                ordered[0] != parse_iso(tape['base_at']) or
                ordered[-1] != parse_iso(tape['last_verified_at'])):
            raise ValueError('Incomplete verified market observation ticks')
        if any(len(clock_sources[sport][at]) != 1 for at in ordered):
            raise ValueError('Multiple source files share one observation tick')
        if {next(iter(clock_sources[sport][at])) for at in ordered} != {
                x['path'] for x in tape['source_files']}:
            raise ValueError('Missing or duplicate source tick')
        result[sport] = [_iso(at) for at in ordered]
    return result


def build_schedule_timeline(manifest, tape_report, downloader=None, tape_rows=None):
    entries = check_manifest(manifest)
    if tape_report.get('authority') != 'RESEARCH_ONLY' or set(tape_report.get('sports', {})) != set(REPOS):
        raise ValueError('Requires verified NBA/NHL tape report')
    if tape_report.get('full_day_or_season') is not False:
        raise ValueError('Full-tape status not verified')
    ticks = verified_tape_ticks(tape_rows, tape_report) if tape_rows is not None else None
    by_sport = defaultdict(list)
    diagnostics = defaultdict(Counter)
    for source in entries:
        if source['kind'] != 'schedule':
            continue
        sport = source['sport']
        rows, _ = read_source(source, manifest['max_decompressed_bytes_per_file'], downloader)
        if len(rows) > MAX_SCHEDULE_ROWS:
            raise ValueError('Unbounded schedule game rows')
        capture = capture_at(source)
        evidence = {**source, 'captured_at': capture}
        seen = {}
        duplicates = set()
        for row in rows:
            try:
                normalized = normalize_schedule_row(row, evidence, sport)
            except (ValueError, KeyError, TypeError, OverflowError):
                diagnostics[sport]['quarantined_invalid_rows'] += 1
                continue
            key = normalized['game_id']
            if key in seen:
                duplicates.add(key)
                diagnostics[sport]['duplicate_game_rows'] += 1
            else:
                seen[key] = normalized
        # Duplicate official IDs are ambiguous even if the rows happen to agree.
        for key in duplicates:
            seen.pop(key, None)
            diagnostics[sport]['quarantined_duplicate_game_ids'] += 1
        by_sport[sport].extend(seen.values())
        diagnostics[sport]['source_schedule_files'] += 1
        diagnostics[sport]['accepted_rows'] += len(seen)

    results = {}
    for sport in sorted(REPOS):
        tape = tape_report['sports'][sport]
        base, end = parse_iso(tape['base_at']), parse_iso(tape['last_verified_at'])
        if base > end:
            raise ValueError('Tape time window reversed')
        observations = sorted(by_sport[sport], key=lambda x: (parse_iso(x['observed_at_utc']), x['game_id']))
        if not observations:
            raise ValueError('No accepted independently observed game schedules')
        # Only evidence visible at each as-of time may quarantine an identity.
        # Future conflicting snapshots cannot erase a previously valid game.
        identities = defaultdict(set)
        for row in observations:
            identities[row['game_id']].add((row['home_team_id'], row['away_team_id']))
        snapshots = [schedule_asof(observations, _iso(at)) for at in (base, end)]
        end_conflicts = snapshots[1]['n_games_quarantined_for_identity_conflict_asof']
        diagnostics[sport]['quarantined_identity_conflict_game_ids'] = end_conflicts
        tick_snapshots = (
            [schedule_asof(observations, at) for at in ticks[sport]]
            if ticks is not None else None
        )
        results[sport] = {
            'source_diagnostics': dict(diagnostics[sport]),
            'n_distinct_schedule_games_across_both_files': len(identities),
            'n_quarantined_game_identities': end_conflicts,
            'n_accepted_point_in_time_schedule_rows': len(observations),
            'asof_verified_market_ticks': tick_snapshots,
            'asof_tape_base': snapshots[0], 'asof_tape_end': snapshots[1],
            'physical_game_ids': 'SCHEDULE_SOURCE_IDENTIFIERS_ONLY',
            'market_contract_join': 'NOT_ESTABLISHED',
            'actual_game_start_verified': False,
            'pregame_market_eligibility': 'NOT_ESTABLISHED',
            'settlement_rule_authority': 'NONE',
            'execution_or_profitability_authority': 'NONE',
        }
    return {
        'schema_version': 1, 'authority': 'RESEARCH_ONLY',
        'sports': results,
        'limitations': [
            'A scheduled start observed in a source is not verified actual tip/puck drop.',
            'Row observation time, not only file name capture time, gates point-in-time selection.',
            'No Kalshi event/ticker-to-physical-game mapping or settlement rule has been established.',
            'A schedule observed before a quote does not prove the quote was before actual start.',
            'Only two pinned schedule files per sport, not full-season coverage.',
            'An identity conflict observed later must never retroactively remove an earlier valid schedule.',
            'Verified market tick alignment is temporal only: no contract-to-game mapping.',
        ],
    }
