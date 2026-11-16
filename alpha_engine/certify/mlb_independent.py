"""Independent implementation of MLB game-level feature spec v1 (from the spec text alone).

SPEC AMBIGUITIES and the literal reading chosen:
A1  Duplicate pk across season directories: "keep the lowest season" - I filter game.type=="R" first (step 1),
    then de-duplicate by pk keeping the lowest season DIRECTORY name (step 2). The spec does not say whether
    dedup precedes the type filter, nor whether "season" is the directory or game.season.
A2  `season` used in the point-in-time rule is integer game.season (step 3), not the directory name.
A3  Timestamp output precision: spec says millisecond strings but not whether sub-millisecond digits are
    truncated or rounded. I truncate (floor) to milliseconds for output.
A4  The strict comparison h.end_utc < g.start_utc is done on the fully parsed instants (full input precision),
    not on the millisecond-formatted strings. Ordering of H by end_utc likewise uses full precision.
A5  Timestamps without an explicit zone designator are assumed UTC; explicit offsets are converted to UTC.
A6  A game with an empty/missing box.<side>.pitchers list (no starter id) is not covered by the spec. I drop it
    and count it under a separate reason, since integer X_sp_id cannot be missing.
A7  A starter whose id is absent from box.<side>.players, or whose `pit` object is absent: the spec only says a
    missing VALUE counts as 0; I extend this to a missing line (all five stats 0) and count occurrences.
A8  Missing linescore runs are not covered. I drop such a game and count it under a separate reason.
A9  "Missing when |P| = 0" is stated only for ip_ps; ra9/k_rate/bb_rate are missing whenever their denominator
    sum is 0 (which includes |P| = 0), exactly as written.
A10 X_win_pct_pre: ties (rs == ra) count as non-wins in the numerator and stay in the denominator.
A11 Team features: "All five are missing when |H| = 0" - there are five float features besides X_n_pre
    (rs_pg, ra_pg, win_pct, rs_l10, ra_l10); X_n_pre is 0.
A12 Integer columns are written as int64; float columns float64; official_date, start_utc, end_utc as strings.
A13 A game is "kept" (and hence usable as a prior game) only after all drops (A6, A8, missing start/end).
A14 Empty-string / null firstPitch, empty `plays`, or last play lacking `end` are all treated as "missing".
A15 Starter history P is keyed by pitcher id across both sides and any team (same season only), per the rule.
A16 No "final" status check is applied (the spec gives no status field; it asserts all R games are final).
A17 Stat values are coerced with int(); non-numeric / null values count as 0.
"""
import argparse, bisect, calendar, json, os, re, sys, time
from collections import defaultdict
from multiprocessing import Pool

import numpy as np
import pandas as pd

_TS = re.compile(r'^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:[.,](\d+))?\s*(Z|[+-]\d{2}:?\d{2})?$')


def parse_ts(s):
    """ISO-8601 -> integer nanoseconds since epoch (UTC), or None."""
    if not isinstance(s, str):
        return None
    m = _TS.match(s.strip())
    if not m:
        return None
    y, mo, d, h, mi, sec, frac, tz = m.groups()
    secs = calendar.timegm((int(y), int(mo), int(d), int(h), int(mi), int(sec)))
    ns = int((frac or '0')[:9].ljust(9, '0'))
    if tz and tz != 'Z':
        sign = 1 if tz[0] == '+' else -1
        digits = tz[1:].replace(':', '')
        secs -= sign * (int(digits[:2]) * 3600 + int(digits[2:]) * 60)
    return secs * 1_000_000_000 + ns


def fmt_ts(ns):
    secs, rem = divmod(ns, 1_000_000_000)
    t = time.gmtime(secs)
    return '%04d-%02d-%02dT%02d:%02d:%02d.%03dZ' % (t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min,
                                                     t.tm_sec, rem // 1_000_000)


def _int0(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


STATS = ('outs', 'runs', 'strikeOuts', 'baseOnBalls', 'battersFaced')


def load(args):
    season_dir, path = args
    with open(path, 'rb') as f:
        j = json.load(f)
    game = j.get('game') or {}
    if game.get('type') != 'R':
        return None
    r = {'dir': season_dir, 'pk': int(j['pk']), 'season': int(game['season']),
         'game_number': game.get('gameNumber'),
         'official_date': (j.get('datetime') or {}).get('officialDate'),
         'start': parse_ts((j.get('game_info') or {}).get('firstPitch')), 'end': None, 'flags': []}
    plays = j.get('plays') or []
    if plays and isinstance(plays[-1], dict):
        r['end'] = parse_ts(plays[-1].get('end'))
    ls = ((j.get('linescore') or {}).get('teams')) or {}
    box = j.get('box') or {}
    for side in ('home', 'away'):
        r[side + '_id'] = ((j.get('teams') or {}).get(side) or {}).get('id')
        r[side + '_runs'] = (ls.get(side) or {}).get('runs')
        b = box.get(side) or {}
        pitchers = b.get('pitchers') or []
        sp = pitchers[0] if pitchers else None
        r[side + '_sp_id'] = sp
        line = None
        if sp is not None:
            for p in b.get('players') or []:
                if isinstance(p, dict) and p.get('id') == sp:
                    line = p.get('pit')
                    break
            if not isinstance(line, dict):
                r['flags'].append('starter_line_missing')
                line = {}
        else:
            line = {}
        r[side + '_line'] = tuple(_int0(line.get(k)) for k in STATS)
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--feed-root', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--workers', type=int, default=os.cpu_count() or 1)
    a = ap.parse_args()
    t0 = time.time()
    tasks = []
    for sd in sorted(os.listdir(a.feed_root)):
        d = os.path.join(a.feed_root, sd)
        if not os.path.isdir(d):
            continue
        for fn in sorted(os.listdir(d)):
            if fn.startswith('_') or not fn.endswith('.json'):
                continue
            tasks.append((sd, os.path.join(d, fn)))
    with Pool(a.workers) as pool:
        recs = pool.map(load, tasks, chunksize=32)
    n_files = len(tasks)
    recs = [r for r in recs if r is not None]
    n_R = len(recs)
    # dedup by pk, lowest season dir
    recs.sort(key=lambda r: (r['pk'], int(r['dir']) if r['dir'].isdigit() else r['dir']))
    seen, ded = set(), []
    for r in recs:
        if r['pk'] in seen:
            continue
        seen.add(r['pk'])
        ded.append(r)
    n_dup = n_R - len(ded)
    drops = defaultdict(int)
    kept = []
    for r in ded:
        if r['start'] is None or r['end'] is None:
            drops['missing start_utc/end_utc'] += 1
        elif r['home_sp_id'] is None or r['away_sp_id'] is None:
            drops['missing starter id'] += 1
        elif r['home_runs'] is None or r['away_runs'] is None:
            drops['missing linescore runs'] += 1
        else:
            kept.append(r)
    n_flag = sum(len(r['flags']) for r in kept)
    n_dir_mismatch = sum(1 for r in kept if str(r['season']) != r['dir'])
    n_end_before_start = sum(1 for r in kept if r['end'] <= r['start'])

    # histories: (season, team) -> sorted by (end, pk)
    team_h = defaultdict(list)
    sp_h = defaultdict(list)
    for r in kept:
        hr, ar = int(r['home_runs']), int(r['away_runs'])
        team_h[(r['season'], r['home_id'])].append((r['end'], r['pk'], hr, ar))
        team_h[(r['season'], r['away_id'])].append((r['end'], r['pk'], ar, hr))
        for side in ('home', 'away'):
            sp_h[(r['season'], r[side + '_sp_id'])].append((r['end'], r['pk']) + r[side + '_line'])
    team_idx, sp_idx = {}, {}
    for k, v in team_h.items():
        v.sort()
        ends = [x[0] for x in v]
        rs = np.array([x[2] for x in v], dtype=np.int64)
        ra = np.array([x[3] for x in v], dtype=np.int64)
        z = np.zeros(1, dtype=np.int64)
        team_idx[k] = (ends, np.concatenate([z, rs.cumsum()]), np.concatenate([z, ra.cumsum()]),
                       np.concatenate([z, (rs > ra).astype(np.int64).cumsum()]))
    for k, v in sp_h.items():
        v.sort()
        ends = [x[0] for x in v]
        arr = np.array([x[2:] for x in v], dtype=np.int64).reshape(len(v), 5)
        sp_idx[k] = (ends, np.vstack([np.zeros((1, 5), dtype=np.int64), arr.cumsum(axis=0)]))

    kept.sort(key=lambda r: (r['start'], r['pk']))
    nan = float('nan')
    rows = []
    for r in kept:
        row = {'game_id': r['pk'], 'season': r['season'], 'official_date': r['official_date'],
               'start_utc': fmt_ts(r['start']), 'end_utc': fmt_ts(r['end']),
               'game_number': int(r['game_number']), 'home_id': int(r['home_id']), 'away_id': int(r['away_id']),
               'home_sp_id': int(r['home_sp_id']), 'away_sp_id': int(r['away_sp_id'])}
        for X in ('home', 'away'):
            ends, crs, cra, cw = team_idx[(r['season'], r[X + '_id'])]
            n = bisect.bisect_left(ends, r['start'])  # strictly end < start
            row[X + '_n_pre'] = n
            if n:
                m = min(10, n)
                row[X + '_rs_pg_pre'] = int(crs[n]) / n
                row[X + '_ra_pg_pre'] = int(cra[n]) / n
                row[X + '_win_pct_pre'] = int(cw[n]) / n
                row[X + '_rs_l10_pre'] = int(crs[n] - crs[n - m]) / m
                row[X + '_ra_l10_pre'] = int(cra[n] - cra[n - m]) / m
            else:
                for c in ('rs_pg', 'ra_pg', 'win_pct', 'rs_l10', 'ra_l10'):
                    row['%s_%s_pre' % (X, c)] = nan
            ends, cum = sp_idx[(r['season'], r[X + '_sp_id'])]
            n = bisect.bisect_left(ends, r['start'])
            outs, runs, so, bb, bf = (int(x) for x in cum[n])
            row[X + '_sp_n_pre'] = n
            row[X + '_sp_ip_ps_pre'] = outs / 3 / n if n else nan
            row[X + '_sp_ra9_pre'] = 27 * runs / outs if outs else nan
            row[X + '_sp_k_rate_pre'] = so / bf if bf else nan
            row[X + '_sp_bb_rate_pre'] = bb / bf if bf else nan
        hr, ar = int(r['home_runs']), int(r['away_runs'])
        row.update(home_runs=hr, away_runs=ar, total_runs=hr + ar, y_home_win=1 if hr > ar else 0)
        rows.append(row)
    cols = ['game_id', 'season', 'official_date', 'start_utc', 'end_utc', 'game_number', 'home_id', 'away_id',
            'home_sp_id', 'away_sp_id']
    for X in ('home', 'away'):
        cols += [X + s for s in ('_n_pre', '_rs_pg_pre', '_ra_pg_pre', '_win_pct_pre', '_rs_l10_pre', '_ra_l10_pre',
                                 '_sp_n_pre', '_sp_ip_ps_pre', '_sp_ra9_pre', '_sp_k_rate_pre', '_sp_bb_rate_pre')]
    cols += ['home_runs', 'away_runs', 'total_runs', 'y_home_win']
    df = pd.DataFrame(rows, columns=cols)
    ints = ['game_id', 'season', 'game_number', 'home_id', 'away_id', 'home_sp_id', 'away_sp_id', 'home_runs',
            'away_runs', 'total_runs', 'y_home_win'] + [c for c in cols if c.endswith('_n_pre')]
    for c in cols:
        if c in ints:
            df[c] = df[c].astype('int64')
        elif c not in ('official_date', 'start_utc', 'end_utc'):
            df[c] = df[c].astype('float64')
    df.to_parquet(a.out, index=False, engine='pyarrow')
    print(json.dumps({'files': n_files, 'type_R': n_R, 'dup_pk_removed': n_dup, 'drops': dict(drops),
                      'rows': len(df), 'starter_line_missing': n_flag, 'season_ne_dir': n_dir_mismatch,
                      'end_le_start': n_end_before_start, 'per_season': df.season.value_counts().sort_index().to_dict(),
                      'ties': int((df.home_runs == df.away_runs).sum()),
                      'runtime_s': round(time.time() - t0, 1)}))


if __name__ == '__main__':
    main()
