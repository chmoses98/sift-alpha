"""Classification and roll-up.  Pure functions over (games, specs, observations); no I/O."""
from collections import Counter, defaultdict

from .model import (COMPLETE, MISSING, NOT_APPLICABLE, PARTIAL, RIGHTS_BLOCKED, STALE, STATUSES, UNVERIFIED,
                    DatasetSpec, Game, Observation)


def classify(game: Game, spec: DatasetSpec, obs: Observation | None) -> tuple[str, str]:
    """-> (status, reason).  Order matters: applicability, absence, pregame vintage, read-back, content."""
    if not spec.applicable(game):
        return NOT_APPLICABLE, "dataset does not apply to this game"
    if obs is None or (obs.n_records <= 0 and not obs.post_start_only):
        if spec.rights_blocked:
            return RIGHTS_BLOCKED, "no rights-cleared source; not archived by policy"
        return MISSING, "no record archived for an expected game"
    if spec.pregame:
        if obs.post_start_only:
            return MISSING, "only post-start observations exist; never substituted for a pregame vintage"
        if game.start_utc is None or obs.observed_at is None:
            return UNVERIFIED, "pregame observation without a usable start or capture timestamp"
        age_h = (game.start_utc - obs.observed_at).total_seconds() / 3600
        if age_h < 0:
            return MISSING, "newest observation is after the scheduled start"
        if spec.max_age_hours is not None and age_h > spec.max_age_hours:
            return STALE, f"newest pre-start observation {age_h:.1f}h before start (limit {spec.max_age_hours:g}h)"
    if not obs.verified:
        return UNVERIFIED, "existence evidence only; content not read back"
    short = [f for f in spec.required_fields if f not in obs.fields_present]
    if obs.n_records < spec.min_records:
        return PARTIAL, f"{obs.n_records} record(s), expected at least {spec.min_records}"
    if short:
        return PARTIAL, "required field(s) absent: " + ",".join(short)
    return COMPLETE, ""


def evaluate(games, specs, observations):
    """games: iterable[Game]; specs: iterable[DatasetSpec]; observations: {(game_id, spec.key): Observation}.
    -> list of cell dicts, one per game x dataset (NOT_APPLICABLE cells included so the ledger is total)."""
    cells = []
    specs = list(specs)
    for g in games:
        for s in specs:
            o = observations.get((g.game_id, s.key))
            status, reason = classify(g, s, o)
            cells.append({"sport": g.sport, "season": g.season, "game_id": g.game_id, "date": g.date, "dataset": s.key,
                          "category": s.category, "status": status, "reason": reason,
                          "n_records": o.n_records if o else 0,
                          "observed_at": o.observed_at.isoformat() if o and o.observed_at else None,
                          "evidence": o.evidence if o else ""})
    return cells


def _pct(n, d):
    return round(n / d, 4) if d else None


def rollup(cells, specs):
    """Per dataset (overall and per season): the denominator (applicable expected games) and every status count.
    `complete_rate` is COMPLETE / expected - UNVERIFIED and PARTIAL never count toward it."""
    spec = {s.key: s for s in specs}
    by_ds = defaultdict(Counter)
    by_ds_season = defaultdict(lambda: defaultdict(Counter))
    reasons = defaultdict(Counter)
    for c in cells:
        by_ds[c["dataset"]][c["status"]] += 1
        by_ds_season[c["dataset"]][c["season"]][c["status"]] += 1
        if c["status"] not in (COMPLETE, NOT_APPLICABLE):
            reasons[c["dataset"]][c["status"] + ": " + c["reason"].split(" (")[0][:90]] += 1

    def block(cnt):
        expected = sum(cnt[s] for s in STATUSES)
        return {"expected": expected, **{s: cnt[s] for s in STATUSES}, "not_applicable": cnt[NOT_APPLICABLE],
                "complete_rate": _pct(cnt[COMPLETE], expected)}

    out = []
    for key, s in spec.items():
        b = block(by_ds[key])
        gaps = b["expected"] - b[COMPLETE]
        out.append({"dataset": key, "category": s.category, "title": s.title, "source": s.source,
                    "recoverability": s.recoverability, "map_datasets": list(s.map_datasets), "pregame": s.pregame,
                    "note": s.note, **b,
                    "gap_cells": gaps,
                    "top_reasons": [{"reason": r, "n": n} for r, n in reasons[key].most_common(5)],
                    "by_season": {season: block(c) for season, c in sorted(by_ds_season[key].items())}})
    return out


def game_status(cells):
    """Per game: worst-first summary over its applicable datasets -> COMPLETE only when every applicable cell is."""
    per = defaultdict(Counter)
    for c in cells:
        if c["status"] != NOT_APPLICABLE:
            per[c["game_id"]][c["status"]] += 1
    order = (MISSING, RIGHTS_BLOCKED, STALE, PARTIAL, UNVERIFIED, COMPLETE)
    return {gid: next(s for s in order if cnt[s]) for gid, cnt in per.items()}
