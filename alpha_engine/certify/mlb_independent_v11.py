"""Blind re-implementation of docs/certification/MLB_FEATURE_SPEC_V11.md.

Written from the specification alone, without reading the primary builder or
any other document. Imports only the standard library, numpy and pandas.

CLI: python mlb_independent_v11.py --feed-root <dir with season dirs> --out <file.parquet> [--lead-hours L]
"""
import argparse
import bisect
import calendar
import json
import os
import re
import sys

import numpy as np
import pandas as pd

NS = 1_000_000_000
SIDES = ("home", "away")
_TS = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:[.,](\d+))?)?\s*(Z|z|[+-]\d{2}:?\d{2}|[+-]\d{2})?$"
)


def parse_instant(value):
    """ISO-8601 string -> integer nanoseconds since the epoch (UTC), or None."""
    if not isinstance(value, str):
        return None
    m = _TS.match(value.strip())
    if not m:
        return None
    y, mo, d, hh, mi, ss, frac, tz = m.groups()
    try:
        secs = calendar.timegm((int(y), int(mo), int(d), int(hh), int(mi), int(ss or 0), 0, 0, 0))
    except Exception:
        return None
    ns = int(((frac or "") + "000000000")[:9])
    off = 0
    if tz and tz not in ("Z", "z"):
        sign = -1 if tz[0] == "-" else 1
        digits = tz[1:].replace(":", "")
        off = sign * (int(digits[:2]) * 3600 + (int(digits[2:4]) if len(digits) >= 4 else 0) * 60)
    return (secs - off) * NS + ns


def fmt_instant(ns):
    """Integer nanoseconds -> 'YYYY-MM-DDTHH:MM:SS.mmmZ' (truncated to ms)."""
    secs, rem = divmod(ns, NS)
    days, sod = divmod(secs, 86400)
    # civil-from-days (proleptic Gregorian)
    z = days + 719468
    era = z // 146097
    doe = z - era * 146097
    yoe = (doe - doe // 1460 + doe // 36524 - doe // 146096) // 365
    y = yoe + era * 400
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    d = doy - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    if m <= 2:
        y += 1
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        y, m, d, sod // 3600, (sod % 3600) // 60, sod % 60, rem // 1_000_000)


def num(v):
    """Missing / null numeric counts as 0; values are exact integers."""
    if v is None or isinstance(v, bool):
        return int(v) if isinstance(v, bool) else 0
    if isinstance(v, int):
        return v
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    if f != f:
        return 0
    return int(f) if f == int(f) else f


def dget(obj, *keys):
    for k in keys:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(k)
    return obj


def season_key(name):
    try:
        return (0, int(name), name)
    except ValueError:
        return (1, 0, name)


def find_files(feed_root):
    out = []
    for season_dir in sorted(os.listdir(feed_root), key=season_key):
        top = os.path.join(feed_root, season_dir)
        if not os.path.isdir(top):
            continue
        for base, dirs, files in os.walk(top):
            dirs.sort()
            for fn in sorted(files):
                if fn.startswith("_") or not fn.endswith(".json"):
                    continue
                out.append((season_key(season_dir), os.path.join(base, fn)))
    out.sort()
    return out


def extract(d):
    """Per-game record from a parsed feed (steps 3-8). Times may be None."""
    g = {}
    g["game_id"] = int(d["pk"])
    g["season"] = int(dget(d, "game", "season"))
    g["official_date"] = dget(d, "datetime", "officialDate")
    g["game_number"] = num(dget(d, "game", "gameNumber"))
    g["start"] = parse_instant(dget(d, "game_info", "firstPitch"))
    plays = d.get("plays")
    last = plays[-1] if isinstance(plays, list) and plays else None
    g["end"] = parse_instant(last.get("end")) if isinstance(last, dict) else None
    innings = dget(d, "linescore", "innings")
    innings = innings if isinstance(innings, list) else []
    for X in SIDES:
        g[X + "_id"] = num(dget(d, "teams", X, "id"))
        g[X + "_runs"] = num(dget(d, "linescore", "teams", X, "runs"))
        bat = dget(d, "box", X, "team_stats", "batting") or {}
        for short, key in (("H", "hits"), ("BB", "baseOnBalls"), ("HR", "homeRuns"),
                           ("TB", "totalBases"), ("AB", "atBats")):
            g[X + "_" + short] = num(bat.get(key)) if isinstance(bat, dict) else 0
        r6 = 0
        for inn in innings:
            if not isinstance(inn, dict):
                continue
            n = inn.get("n")
            if n is None:
                continue
            try:
                if float(n) <= 6:
                    r6 += num(dget(inn, X, "runs"))
            except (TypeError, ValueError):
                continue
        g[X + "_r6"] = r6
        pitchers = dget(d, "box", X, "pitchers")
        players = dget(d, "box", X, "players")
        by_id = {}
        if isinstance(players, list):
            for p in players:
                if isinstance(p, dict) and p.get("id") is not None and p.get("id") not in by_id:
                    by_id[p.get("id")] = p
        elif isinstance(players, dict):
            for p in players.values():
                if isinstance(p, dict) and p.get("id") is not None and p.get("id") not in by_id:
                    by_id[p.get("id")] = p
        rr = ro = 0
        if isinstance(pitchers, list):
            for pid in pitchers[1:]:
                pit = (by_id.get(pid) or {}).get("pit")
                if isinstance(pit, dict):
                    rr += num(pit.get("runs"))
                    ro += num(pit.get("outs"))
        g[X + "_rel_runs"] = rr
        g[X + "_rel_outs"] = ro
    return g


def load_games(feed_root, stats):
    seen = {}
    for skey, path in find_files(feed_root):  # ascending season directory
        stats["files"] += 1
        try:
            with open(path, "r", encoding="utf-8") as fh:
                d = json.load(fh)
        except Exception:
            stats["unreadable"] += 1
            continue
        if not isinstance(d, dict) or dget(d, "game", "type") != "R":
            stats["not_regular_season"] += 1
            continue
        try:
            g = extract(d)
        except Exception:
            stats["malformed_pk_or_season"] += 1
            continue
        if g["game_id"] in seen:
            stats["duplicate_pk"] += 1
            continue
        seen[g["game_id"]] = g
    kept = []
    for g in seen.values():
        if g["start"] is None or g["end"] is None:
            if g["start"] is None and g["end"] is None:
                stats["missing_start_and_end"] += 1
            elif g["start"] is None:
                stats["missing_start"] += 1
            else:
                stats["missing_end"] += 1
            continue
        kept.append(g)
    return kept


def bsr(H, BB, HR, TB, AB):
    A = H + BB - HR
    B = 1.02 * (1.4 * TB - 0.6 * H - 3 * HR + 0.1 * BB)
    C = AB - H
    if B + C <= 0:
        return None
    return A * B / (B + C) + HR


def pyth(s, a):
    ps, pa = float(s) ** 1.83, float(a) ** 1.83
    return ps / (ps + pa)


# per-team-game integer columns (prefix-summed)
COLS = ["rs", "ra", "win", "loss", "tie", "one", "one_w", "lc", "lc_w",
        "H", "BB", "HR", "TB", "AB", "oH", "oBB", "oHR", "oTB", "oAB", "rel_runs", "rel_outs"]
CI = {c: i for i, c in enumerate(COLS)}

FEATS = ["n_pre", "wins_pre", "losses_pre", "ties_pre", "games_remaining_pre", "run_diff_pre",
         "unresolved_pre", "rs_pg_pre", "ra_pg_pre", "rs_l10_pre", "ra_l10_pre", "win_pct_pre",
         "pyth_pct_pre", "pyth_luck_pre", "one_run_n_pre", "one_run_win_pct_pre", "bsr_rs_pg_pre",
         "bsr_ra_pg_pre", "bsr_pct_pre", "bsr_luck_pre", "late_close_n_pre",
         "late_close_win_pct_pre", "bullpen_ra9_pre"]
INT_FEATS = {"n_pre", "wins_pre", "losses_pre", "ties_pre", "games_remaining_pre", "run_diff_pre",
             "unresolved_pre", "one_run_n_pre", "late_close_n_pre"}


def team_row(g, X):
    O = "away" if X == "home" else "home"
    rs, ra = g[X + "_runs"], g[O + "_runs"]
    one = 1 if abs(rs - ra) == 1 else 0
    lc = 1 if abs(g[X + "_r6"] - g[O + "_r6"]) <= 1 else 0
    w = 1 if rs > ra else 0
    return [rs, ra, w, 1 if rs < ra else 0, 1 if rs == ra else 0, one, one * w, lc, lc * w,
            g[X + "_H"], g[X + "_BB"], g[X + "_HR"], g[X + "_TB"], g[X + "_AB"],
            g[O + "_H"], g[O + "_BB"], g[O + "_HR"], g[O + "_TB"], g[O + "_AB"],
            g[X + "_rel_runs"], g[X + "_rel_outs"]]


class TeamHist:
    def __init__(self, entries):
        # entries: (end, game_id, start, row)
        entries.sort(key=lambda e: (e[0], e[1]))
        self.ends = [e[0] for e in entries]
        self.gids = [e[1] for e in entries]
        self.pos = {gid: i for i, gid in enumerate(self.gids)}
        self.starts = np.array([e[2] for e in entries], dtype=np.int64)
        self.ends_np = np.array(self.ends, dtype=np.int64)
        self.rows = [e[3] for e in entries]
        self.cum = [[0] * len(COLS)]
        for r in self.rows:  # Python ints/floats: exact prefix sums
            prev = self.cum[-1]
            self.cum.append([a + b for a, b in zip(prev, r)])

    def features(self, gid, T):
        nan = float("nan")
        k = bisect.bisect_left(self.ends, T)  # games with end < T strictly
        me = self.pos[gid]
        sums = list(self.cum[k])
        idx_hi = k
        self_in = me < k
        if self_in:  # a game is never prior to itself
            sums = [a - b for a, b in zip(sums, self.rows[me])]
        n = k - (1 if self_in else 0)
        S = lambda c: sums[CI[c]]
        f = {}
        f["n_pre"] = n
        f["wins_pre"], f["losses_pre"], f["ties_pre"] = S("win"), S("loss"), S("tie")
        f["games_remaining_pre"] = 162 - n
        f["run_diff_pre"] = S("rs") - S("ra")
        unres = int(np.count_nonzero((self.starts < T) & (self.ends_np >= T)))
        if self.starts[me] < T and self.ends_np[me] >= T:
            unres -= 1
        f["unresolved_pre"] = unres
        f["rs_pg_pre"] = S("rs") / n if n else nan
        f["ra_pg_pre"] = S("ra") / n if n else nan
        if n:
            last = [i for i in range(max(0, idx_hi - 11), idx_hi) if i != me][-10:]
            f["rs_l10_pre"] = sum(self.rows[i][CI["rs"]] for i in last) / len(last)
            f["ra_l10_pre"] = sum(self.rows[i][CI["ra"]] for i in last) / len(last)
            last_idx = last[-1]
        else:
            f["rs_l10_pre"] = f["ra_l10_pre"] = nan
            last_idx = None
        wl = S("win") + S("loss")
        f["win_pct_pre"] = S("win") / wl if wl else nan
        f["pyth_pct_pre"] = pyth(S("rs"), S("ra")) if (S("rs") + S("ra")) != 0 else nan
        f["pyth_luck_pre"] = f["win_pct_pre"] - f["pyth_pct_pre"]
        f["one_run_n_pre"] = S("one")
        f["one_run_win_pct_pre"] = S("one_w") / S("one") if S("one") else nan
        own = bsr(S("H"), S("BB"), S("HR"), S("TB"), S("AB"))
        opp = bsr(S("oH"), S("oBB"), S("oHR"), S("oTB"), S("oAB"))
        f["bsr_rs_pg_pre"] = own / n if (n and own is not None) else nan
        f["bsr_ra_pg_pre"] = opp / n if (n and opp is not None) else nan
        if own is None or opp is None or own + opp <= 0 or own < 0 or opp < 0:
            f["bsr_pct_pre"] = nan
        else:
            f["bsr_pct_pre"] = pyth(own, opp)
        f["bsr_luck_pre"] = f["win_pct_pre"] - f["bsr_pct_pre"]
        f["late_close_n_pre"] = S("lc")
        f["late_close_win_pct_pre"] = S("lc_w") / S("lc") if S("lc") else nan
        f["bullpen_ra9_pre"] = 27 * S("rel_runs") / S("rel_outs") if S("rel_outs") else nan
        last_end = fmt_instant(self.ends[last_idx]) if last_idx is not None else ""
        return f, last_end


def build(feed_root, lead_hours):
    stats = {k: 0 for k in ("files", "unreadable", "not_regular_season", "malformed_pk_or_season",
                            "duplicate_pk", "missing_start", "missing_end", "missing_start_and_end")}
    games = load_games(feed_root, stats)
    lead_ns = int(round(float(lead_hours) * 3600 * NS))
    hist = {}
    for g in games:
        for X in SIDES:
            hist.setdefault((g["season"], g[X + "_id"]), []).append(
                (g["end"], g["game_id"], g["start"], team_row(g, X)))
    hist = {k: TeamHist(v) for k, v in hist.items()}
    games.sort(key=lambda g: (g["start"], g["game_id"]))
    recs = []
    for g in games:
        T = g["start"] - lead_ns
        rec = {"game_id": g["game_id"], "season": g["season"], "official_date": g["official_date"],
               "start_utc": fmt_instant(g["start"]), "end_utc": fmt_instant(g["end"]),
               "game_number": g["game_number"], "home_id": g["home_id"], "away_id": g["away_id"]}
        lasts = {}
        for X in SIDES:
            f, lasts[X] = hist[(g["season"], g[X + "_id"])].features(g["game_id"], T)
            for name in FEATS:
                rec[X + "_" + name] = f[name]
        rec["home_last_end_utc"] = lasts["home"]
        rec["away_last_end_utc"] = lasts["away"]
        rec["home_runs"] = g["home_runs"]
        rec["away_runs"] = g["away_runs"]
        rec["total_runs"] = g["home_runs"] + g["away_runs"]
        rec["y_home_win"] = 1 if g["home_runs"] > g["away_runs"] else 0
        recs.append(rec)
    columns = (["game_id", "season", "official_date", "start_utc", "end_utc", "game_number",
                "home_id", "away_id"]
               + [X + "_" + n for X in SIDES for n in FEATS]
               + ["home_last_end_utc", "away_last_end_utc", "home_runs", "away_runs", "total_runs",
                  "y_home_win"])
    df = pd.DataFrame(recs, columns=columns)
    ints = (["game_id", "season", "game_number", "home_id", "away_id", "home_runs", "away_runs",
             "total_runs", "y_home_win"] + [X + "_" + n for X in SIDES for n in INT_FEATS])
    for c in columns:
        if c in ints:
            df[c] = df[c].astype("int64")
        elif c in ("official_date", "start_utc", "end_utc", "home_last_end_utc", "away_last_end_utc"):
            df[c] = df[c].astype(object)
        else:
            df[c] = df[c].astype("float64")
    return df, stats


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--feed-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lead-hours", type=float, default=0.0)
    a = ap.parse_args(argv)
    if a.lead_hours < 0:
        ap.error("--lead-hours must be non-negative")
    df, stats = build(a.feed_root, a.lead_hours)
    out_dir = os.path.dirname(os.path.abspath(a.out))
    os.makedirs(out_dir, exist_ok=True)
    df.to_parquet(a.out, index=False)
    stats["rows_written"] = len(df)
    stats["lead_hours"] = a.lead_hours
    print(json.dumps(stats, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
