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


def build_schedule_timeline(manifest, tape_report, downloader=None):
    entries = check_manifest(manifest)
    if tape_report.get('authority') != 'RESEARCH_ONLY' or set(tape_report.get('sports', {})) != set(REPOS):
        raise ValueError('Requires verified NBA/NHL tape report')
    if tape_report.get('full_day_or_season') is not False:
        raise ValueError('Full-tape status not verified')
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
        # Team identity must not silently mutate across historical snapshots.
        identities = defaultdict(set)
        for row in observations:
            identities[row['game_id']].add((row['home_team_id'], row['away_team_id']))
        unstable = {gid for gid, ids in identities.items() if len(ids) != 1}
        diagnostics[sport]['quarantined_identity_conflict_game_ids'] = len(unstable)
        observations = [r for r in observations if r['game_id'] not in unstable]
        snapshots = []
        for at in (base, end):
            eligible = [r for r in observations if parse_iso(r['observed_at_utc']) <= at]
            latest = {}
            for row in eligible:
                latest[row['game_id']] = row
            future = sum(parse_iso(r['observed_at_utc']) > at for r in observations)
            scheduled_future = sum(parse_iso(r['scheduled_start_utc']) > at for r in latest.values())
            changes = sum(1 for gid in latest if len({r['scheduled_start_utc'] for r in eligible if r['game_id'] == gid}) > 1)
            snapshots.append({
                'asof_utc': _iso(at), 'n_games_with_known_schedule': len(latest),
                'n_games_with_scheduled_start_after_asof': scheduled_future,
                'n_games_with_observed_schedule_start_revision': changes,
                'n_future_schedule_rows_excluded': future,
                'examples': [latest[gid] for gid in sorted(latest)[:3]],
                'start_authority': 'SCHEDULE_ONLY', 'pregame_authority': 'NONE',
            })
        results[sport] = {
            'source_diagnostics': dict(diagnostics[sport]),
            'n_distinct_schedule_games_across_both_files': len(identities),
            'n_quarantined_game_identities': len(unstable),
            'n_accepted_point_in_time_schedule_rows': len(observations),
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
        ],
    }
