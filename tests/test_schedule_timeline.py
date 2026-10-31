"""Adversarial schedule time travel, source identity, reschedule and safety QA."""
from datetime import datetime
import unittest
from alpha_engine.schedule_timeline import normalize_schedule_row, build_schedule_timeline

CAPTURE = '2026-10-24T23:15:57Z'
SRC = {'captured_at': CAPTURE, 'path':'context/schedule/dt=2026-10-24/f.jsonl.gz',
       'commit':'a'*40, 'sha':'b'*40}

def row(gid='espn:401', start='2026-10-25T01:00:00Z', observed='2026-10-24T23:15:57.500Z', home=1, away=2):
    return {'game_id':gid, 'start_time_utc':start, '_observed_at_utc':observed,
            'home_team_id':home, 'away_team_id':away, 'source':'espn_scoreboard'}

class ScheduleTimelineTests(unittest.TestCase):
    def test_scheduled_not_actual_or_kalshi(self):
        r=normalize_schedule_row(row(), SRC, 'NBA')
        self.assertEqual(r['start_authority'],'ARCHIVED_SCHEDULED_START_NOT_ACTUAL_START')
        self.assertEqual(r['pregame_authority'],'NONE')
        self.assertNotIn('actual_tip_utc',r)
        self.assertNotIn('result',r)
        self.assertNotIn('ticker',r)

    def test_filename_second_is_not_sufficient_to_admit_future_row(self):
        r=normalize_schedule_row(row(), SRC, 'NBA')
        self.assertLess(datetime.fromisoformat(CAPTURE.replace('Z','+00:00')),
                        datetime.fromisoformat(r['observed_at_utc'].replace('Z','+00:00')))
        self.assertGreater(datetime.fromisoformat(r['observed_at_utc'].replace('Z','+00:00')),
                           datetime.fromisoformat('2026-10-24T23:15:57.250+00:00'))

    def test_timestamp_and_team_forgery_rejected(self):
        with self.assertRaises(ValueError):
            normalize_schedule_row(row(observed='2026-10-25T00:00:00Z'), SRC, 'NBA')
        with self.assertRaises(ValueError):
            normalize_schedule_row(row(home=2,away=2), SRC, 'NBA')
        with self.assertRaises(ValueError):
            normalize_schedule_row(row(home=True), SRC, 'NBA')
        with self.assertRaises(ValueError):
            normalize_schedule_row(row(start='2026-10-25T01:00:00'), SRC, 'NBA')
        with self.assertRaises(ValueError):
            normalize_schedule_row(row(gid='FAKE'), SRC, 'NBA')

    def test_nhl_identity_and_time_validation(self):
        good=normalize_schedule_row(row(gid='2026020001'), SRC, 'NHL')
        self.assertEqual(good['game_id'],'2026020001')
        with self.assertRaises(ValueError):
            normalize_schedule_row(row(gid='espn:401'), SRC, 'NHL')

import gzip
import hashlib
import json
from copy import deepcopy

def fixture(revised=True, conflicting=False, duplicate=False):
    stamps = [('20261024T231557Z','2026-10-24T23:15:57Z'),
              ('20261025T001844Z','2026-10-25T00:18:44Z')]
    blobs={}
    sources=[]
    for sport, repo in [('NBA','chmoses98/nba-edge-finder'),
                        ('NHL','chmoses98/NHL-edge-finder')]:
        gid='espn:401' if sport=='NBA' else '2026020001'
        for i,(stamp,at) in enumerate(stamps):
            start='2026-10-25T01:00:00Z' if not revised or i==0 else '2026-10-25T01:30:00Z'
            game=row(gid=gid,observed=at.replace('Z','.500Z'),start=start,home=1 if not conflicting or i==0 else 3)
            games=[game,deepcopy(game)] if duplicate and i==0 else [game]
            path=f'context/schedule/dt=2026-10-{24+i}/context_schedule_{stamp}_{123 if sport=="NBA" else 456}.jsonl.gz'
            blob=gzip.compress(('\n'.join(json.dumps(x) for x in games)+'\n').encode(),mtime=0)
            entry={'sport':sport,'kind':'schedule','repository':repo,'commit':'a'*40,
                   'path':path,'sha':hashlib.sha1(b'blob '+str(len(blob)).encode()+b'\0'+blob).hexdigest(),
                   'bytes':len(blob)}
            sources.append(entry)
            blobs[(repo,path)]=blob
        stamp='20261026T001946Z'
        path=f'settlements/dt=2026-10-26/settlements_{stamp}_{123 if sport=="NBA" else 456}.jsonl.gz'
        blob=gzip.compress(b'{"ticker":"KXFAKE","result":"YES"}\n',mtime=0)
        sources.append({'sport':sport,'kind':'settlement','repository':repo,'commit':'a'*40,
                        'path':path,'sha':hashlib.sha1(b'blob '+str(len(blob)).encode()+b'\0'+blob).hexdigest(),
                        'bytes':len(blob)})
        blobs[(repo,path)]=blob
    manifest={'schema_version':1,'max_total_compressed_bytes':100000,
              'max_decompressed_bytes_per_file':3000000,'sources':sources}
    report={'authority':'RESEARCH_ONLY','full_day_or_season':False,
            'sports':{sport:{'base_at':'2026-10-24T23:15:57.250Z',
                             'last_verified_at':'2026-10-25T00:20:00Z'}
                      for sport in ('NBA','NHL')}}
    return manifest,report,lambda item:blobs[(item['repository'],item['path'])]

class TimelineIntegrationTests(unittest.TestCase):
    def test_row_time_excludes_subsecond_future_and_tracks_reschedule(self):
        manifest,tape,download=fixture()
        report=build_schedule_timeline(manifest,tape,download)
        self.assertEqual(report['authority'],'RESEARCH_ONLY')
        for sport in ('NBA','NHL'):
            r=report['sports'][sport]
            self.assertEqual(r['asof_tape_base']['n_games_with_known_schedule'],0)
            self.assertEqual(r['asof_tape_base']['n_future_schedule_rows_excluded'],2)
            self.assertEqual(r['asof_tape_end']['n_games_with_known_schedule'],1)
            self.assertEqual(r['asof_tape_end']['n_games_with_observed_schedule_start_revision'],1)
            self.assertEqual(r['asof_tape_end']['examples'][0]['scheduled_start_utc'],'2026-10-25T01:30:00Z')
            self.assertFalse(r['actual_game_start_verified'])
            self.assertEqual(r['market_contract_join'],'NOT_ESTABLISHED')

    def test_conflicting_team_identity_quarantines_entire_game(self):
        manifest,tape,download=fixture(conflicting=True)
        report=build_schedule_timeline(manifest,tape,download)
        for sport in ('NBA','NHL'):
            self.assertEqual(report['sports'][sport]['n_quarantined_game_identities'],1)
            self.assertEqual(report['sports'][sport]['asof_tape_end']['n_games_with_known_schedule'],0)

    def test_duplicate_snapshot_id_quarantined_not_silently_last_write_wins(self):
        manifest,tape,download=fixture(duplicate=True)
        report=build_schedule_timeline(manifest,tape,download)
        for sport in ('NBA','NHL'):
            self.assertEqual(report['sports'][sport]['source_diagnostics']['quarantined_duplicate_game_ids'],1)
            self.assertEqual(report['sports'][sport]['asof_tape_end']['n_games_with_known_schedule'],1)
            self.assertEqual(report['sports'][sport]['asof_tape_end']['n_games_with_observed_schedule_start_revision'],0)

    def test_malformed_or_tampered_source_is_rejected(self):
        manifest,tape,download=fixture()
        broken=deepcopy(manifest)
        broken['sources'][0]['sha']='f'*40
        with self.assertRaises(ValueError):
            build_schedule_timeline(broken,tape,download)
        broken=deepcopy(tape)
        broken['authority']='TRADING_ALLOWED'
        with self.assertRaises(ValueError):
            build_schedule_timeline(manifest,broken,download)

if __name__ == '__main__':
    unittest.main()
