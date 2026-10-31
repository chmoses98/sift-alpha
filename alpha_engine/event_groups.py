"""Point-in-time literal Kalshi event groups over the verified NBA/NHL tape.

An event ticker is an exchange catalog identity, NOT a physical sports game.
No family, game, start, settlement, probability, or bet inference is permitted.
Each group is reconstructed at a verified board tick from observations already
known by that tick; changes in later ticks cannot affect earlier groupings.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from .contract_lineage import audit_contract_lineage, lineage_asof
from .delta_timeutil import parse_iso
from .schedule_timeline import verified_tape_ticks

MAX_GROUP_ROWS = 100000


def event_groups_at(tape_rows, cutoff, sport):
    """Active literal contract groupings as-of one timestamp, with quarantines.

    Callers must independently verify the cutoff is a genuine archived tick.
    The function never guesses an event from a ticker or title.
    """
    at = parse_iso(cutoff)
    histories = defaultdict(list)
    for row in tape_rows:
        if parse_iso(row["observed_at_utc"]) <= at:
            histories[(row["sport"], row["ticker"])].append(row)
    other_event_tickers = set()
    for (other_sport, ticker), history in histories.items():
        if other_sport == sport:
            continue
        state = lineage_asof(history, cutoff)
        if (state["status"] == "LITERAL_CONTRACT_IDENTITY_OBSERVED"
                and state["lifecycle"] == "PRESENT"):
            other_event_tickers.add(state["event_ticker"])

    groups = defaultdict(lambda: {"tickers": set(), "series": set()})
    excluded = Counter()
    for (s, ticker), history in histories.items():
        if s != sport:
            continue
        state = lineage_asof(history, cutoff)
        if state["lifecycle"] == "REMOVED":
            excluded["removed_tickers"] += 1
            continue
        if state["status"] != "LITERAL_CONTRACT_IDENTITY_OBSERVED":
            excluded["unresolved_or_conflicted_active_tickers"] += 1
            continue
        event = state["event_ticker"]
        groups[event]["tickers"].add(ticker)
        groups[event]["series"].add(state["series_ticker"])

    result = []
    for event, group in sorted(groups.items()):
        series = sorted(group["series"])
        if len(series) > 1:
            status = "QUARANTINED_EVENT_MULTIPLE_LITERAL_SERIES"
        elif event in other_event_tickers:
            status = "QUARANTINED_EVENT_CROSS_SPORT_COLLISION"
        else:
            status = "LITERAL_EVENT_GROUP_OBSERVED"
        result.append({
            "sport": sport,
            "observed_board_tick_utc": cutoff,
            "event_ticker": event,
            "series_ticker": series[0] if len(series) == 1 else None,
            "literal_series_tickers": series,
            "active_contract_tickers": sorted(group["tickers"]),
            "n_active_contract_tickers": len(group["tickers"]),
            "group_status": status,
            "contract_to_physical_game": "NOT_ESTABLISHED",
            "actual_start": "NOT_VERIFIED",
            "exchange_settlement": "NOT_VERIFIED",
            "pregame_or_execution_authority": "NONE",
        })
    return result, dict(excluded)


def audit_event_groups(tape_report, tape_rows):
    """Verify source integrity first; emit bounded, chronological group ledger."""
    lineage = audit_contract_lineage(tape_report, tape_rows)
    if lineage["authority"] != "RESEARCH_ONLY":
        raise ValueError("Unverified contract lineage")
    ticks = verified_tape_ticks(tape_rows, tape_report)
    result, report = [], {}
    for sport in sorted(ticks):
        snapshots = []
        for cutoff in ticks[sport]:
            groups, excluded = event_groups_at(tape_rows, cutoff, sport)
            if len(result) + len(groups) > MAX_GROUP_ROWS:
                raise ValueError("Unbounded event ledger")
            result.extend(groups)
            counts = Counter(row["group_status"] for row in groups)
            n_active = sum(row["n_active_contract_tickers"] for row in groups)
            if n_active + sum(excluded.values()) <= 0:
                raise ValueError("No observed contracts at tick")
            snapshots.append({
                "asof_utc": cutoff,
                "n_literal_event_tickers": len(groups),
                "n_active_contracts_with_literal_event": n_active,
                "n_multi_contract_events": sum(
                    row["n_active_contract_tickers"] > 1 for row in groups),
                "n_quarantined_multi_series_events": counts[
                    "QUARANTINED_EVENT_MULTIPLE_LITERAL_SERIES"],
                "n_quarantined_cross_sport_event_collisions": counts[
                    "QUARANTINED_EVENT_CROSS_SPORT_COLLISION"],
                "n_unresolved_or_conflicted_active_contracts":
                    excluded.get("unresolved_or_conflicted_active_tickers", 0),
                "n_removed_contracts":
                    excluded.get("removed_tickers", 0),
                "top_literal_events_by_contract_count": [
                    {"event_ticker": row["event_ticker"],
                     "n_active_contract_tickers": row["n_active_contract_tickers"],
                     "group_status": row["group_status"]}
                    for row in sorted(groups, key=lambda r: (
                        -r["n_active_contract_tickers"], r["event_ticker"]))[:5]],
                "game_or_settlement_authority": "NONE",
            })
        report[sport] = {
            "n_verified_board_ticks": len(snapshots),
            "snapshots": snapshots,
            "coverage": "PINNED_CHECKPOINT_PLUS_CONTIGUOUS_DELTA_PREFIX_ONLY",
            "event_to_physical_game": "NOT_ESTABLISHED",
            "exchange_settlement": "NOT_VERIFIED",
            "pregame_or_execution_authority": "NONE",
        }
    if not result or {r["sport"] for r in result} != set(ticks):
        raise ValueError("Missing event-group coverage")
    return {
        "schema_version": 1,
        "authority": "RESEARCH_ONLY",
        "sports": report,
        "n_group_rows": len(result),
        "limitations": [
            "Kalshi event identifiers are not independently verified physical games.",
            "Only observed source terms, never ticker-pattern or title guesses, define groups.",
            "Group members are as-of board state, not independent bets or opportunities.",
            "No official actual starts, exchange settlement, fills, fees, or profitability.",
            "Other six sports remain at archival inventory stage.",
        ],
    }, result
