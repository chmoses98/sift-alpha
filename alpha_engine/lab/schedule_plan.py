"""Window-driven wake-up plan for the capture worker (RESEARCH_ONLY).  Derived from the schedule alone, never hand-typed.

A firing at minute `FIRE_MIN` of hour h runs `capture-window` for `SPAN` minutes, so it can serve any capture window that overlaps [h:FIRE_MIN, h:FIRE_MIN+SPAN].  `needed_firings` lists
every hour whose firing is needed; `weekly_pattern` keeps the (weekday, hour) slots needed in >= `min_weeks` weeks and leaves the rest as dated exceptions; `to_cron` renders both as
cron lines.  `uncovered` re-checks a plan against a (possibly updated) schedule so a schedule change can never silently leave a decision window without a wake-up."""
from __future__ import annotations
import collections
import pandas as pd
from . import capture_window as CW

FIRE_MIN, SPAN = 37, 57


def needed_firings(games: pd.DataFrame, now, season: int = 2026, fire_min: int = FIRE_MIN, span: int = SPAN) -> list[pd.Timestamp]:
    now = pd.Timestamp(now); ko = CW.kickoffs(games, season)
    out = set()
    for _, _, dt in CW.decision_times(ko, now):
        a, b = dt - pd.Timedelta(minutes=CW.PRE_MIN), dt + pd.Timedelta(minutes=CW.POST_MIN)
        if b < now:
            continue
        t = (a - pd.Timedelta(minutes=fire_min + span)).ceil("h") - pd.Timedelta(hours=0)
        t = (a - pd.Timedelta(minutes=fire_min)).floor("h") - pd.Timedelta(hours=1)
        while t + pd.Timedelta(minutes=fire_min) <= b:
            if t + pd.Timedelta(minutes=fire_min + span) >= a and t + pd.Timedelta(minutes=fire_min) >= now - pd.Timedelta(hours=1):
                out.add(t)
            t += pd.Timedelta(hours=1)
    return sorted(out)


def weekly_pattern(needed: list[pd.Timestamp], min_weeks: int = 3) -> tuple[dict, list[pd.Timestamp]]:
    cnt = collections.Counter((t.dayofweek, t.hour) for t in needed)
    pat = {k: v for k, v in cnt.items() if v >= min_weeks}
    exc = [t for t in needed if (t.dayofweek, t.hour) not in pat]
    return pat, exc


def to_cron(pattern: dict, exceptions: list[pd.Timestamp], fire_min: int = FIRE_MIN) -> list[str]:
    """cron (UTC) lines: one per distinct hour-set per weekday group, plus dated exceptions grouped by (month, hour-set)."""
    byd: dict = collections.defaultdict(set)
    for (d, h) in pattern:
        byd[d].add(h)
    groups: dict = collections.defaultdict(list)
    for d, hs in byd.items():
        groups[tuple(sorted(hs))].append(d)
    lines = [f"{fire_min} {','.join(map(str, hs))} * * {','.join(str((d + 1) % 7) for d in sorted(ds))}" for hs, ds in sorted(groups.items())]      # cron: 0=Sunday, pandas: 0=Monday
    ex: dict = collections.defaultdict(lambda: collections.defaultdict(set))
    for t in exceptions:
        ex[(t.month, tuple())][t.day].add(t.hour)
    byset: dict = collections.defaultdict(list)
    for (m, _), days in ex.items():
        for day, hs in days.items():
            byset[(m, tuple(sorted(hs)))].append(day)
    for (m, hs), days in sorted(byset.items()):
        lines.append(f"{fire_min} {','.join(map(str, hs))} {','.join(map(str, sorted(days)))} {m} *")
    return lines


def uncovered(games: pd.DataFrame, fired: set, now, season: int = 2026, fire_min: int = FIRE_MIN, span: int = SPAN) -> list[str]:
    """Windows with NO planned firing overlapping them (`fired` = set of firing hours, tz-aware Timestamps floored to the hour)."""
    ko = CW.kickoffs(games, season); bad = []
    for gid, h, dt in CW.decision_times(ko, pd.Timestamp(now)):
        a, b = dt - pd.Timedelta(minutes=CW.PRE_MIN), dt + pd.Timedelta(minutes=CW.POST_MIN)
        if b < pd.Timestamp(now):
            continue
        if not any(t + pd.Timedelta(minutes=fire_min + span) >= a + pd.Timedelta(minutes=5) and t + pd.Timedelta(minutes=fire_min) <= b - pd.Timedelta(minutes=5) for t in fired):
            bad.append(f"{gid}:{h}")
    return bad


def expand_cron_hours(lines: list[str], start, end) -> set:
    """Expand simple cron lines of the forms generated above into the set of firing hours in [start, end] (tz-aware)."""
    out = set()
    for ln in lines:
        mi, hr, dom, mon, dow = ln.split()
        hours = {int(x) for x in hr.split(",")}
        doms = None if dom == "*" else {int(x) for x in dom.split(",")}
        mons = None if mon == "*" else {int(x) for x in mon.split(",")}
        dows = None if dow == "*" else {int(x) for x in dow.split(",")}
        for t in pd.date_range(pd.Timestamp(start).floor("h"), pd.Timestamp(end), freq="h"):
            cron_dow = (t.dayofweek + 1) % 7
            if t.hour in hours and (doms is None or t.day in doms) and (mons is None or t.month in mons) and (dows is None or cron_dow in dows):
                out.add(t)
    return out
