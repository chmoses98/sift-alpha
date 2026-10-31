"""Audit independent NBA/NHL scheduled-start timelines, research only."""
import gzip
import json
from pathlib import Path
from .schedule_timeline import build_schedule_timeline

if __name__ == '__main__':
    manifest = json.loads(Path('research/context_join_pins.json').read_text())
    tape = json.loads(Path('artifacts/verified_sparse_tape_status.json').read_text())
    with gzip.open('artifacts/verified_sparse_quote_tape.jsonl.gz', 'rt', encoding='utf-8') as source:
        rows = [json.loads(line) for line in source]
    report = build_schedule_timeline(manifest, tape, tape_rows=rows)
    target = Path('artifacts/scheduled_start_timeline_status.json')
    target.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    for sport, row in sorted(report['sports'].items()):
        print(sport, 'schedule games known at tape base', row['asof_tape_base']['n_games_with_known_schedule'],
              'at tape end', row['asof_tape_end']['n_games_with_known_schedule'],
              'quarantined identities at tape end', row['n_quarantined_game_identities'],
              'verified quote ticks', len(row['asof_verified_market_ticks']))
    print('RESEARCH_ONLY scheduled starts, no market join:', target)
