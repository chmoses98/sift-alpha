"""Literal contract ontology over a source-verified sparse NBA/NHL quote tape.

This is not a physical game mapping, exchange settlement, executable price,
pregame assertion or profit study. Terms are evaluated as-of observation time;
future conflicts never poison historical knowledge.
"""
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
import json
from .delta_timeutil import parse_iso
from .schedule_timeline import verified_tape_ticks

SEMANTIC = ("event_ticker", "series_ticker", "strike_type", "floor_strike",
            "cap_strike", "yes_sub_title", "no_sub_title")
DESCRIPTIVE = ("title", "subtitle")
SIDES = {"yes_bid", "yes_ask", "no_bid", "no_ask"}


def _literal(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _validate(row):
    if row.get("lifecycle") not in ("PRESENT", "REMOVED"):
        raise ValueError("Unknown contract lifecycle")
    terms = row.get("contract_terms_as_observed")
    quotes = row.get("direct_quotes_dollars")
    if row["lifecycle"] == "REMOVED":
        if terms is not None or quotes is not None:
            raise ValueError("Removed contract retains quotes or terms")
    else:
        if not isinstance(terms, dict) or not isinstance(quotes, dict) or set(quotes) != SIDES:
            raise ValueError("Missing literal contract terms or quote sides")
        for side, price in quotes.items():
            if price is None:
                continue
            if isinstance(price, bool) or not isinstance(price, (int, float, str)):
                raise ValueError("Invalid quote type")
            try:
                value = Decimal(str(price))
            except InvalidOperation as exc:
                raise ValueError("Unparseable quote") from exc
            if not value.is_finite() or not Decimal(0) <= value <= Decimal(1):
                raise ValueError("Invalid literal price")
        for key in SEMANTIC + DESCRIPTIVE:
            if key in terms and terms[key] is not None:
                _literal(terms[key])
    changed = row.get("direct_quote_changed_since_previous_ticker_record")
    if row.get("source_kind") == "CHECKPOINT":
        if changed is not None:
            raise ValueError("Checkpoint falsely claims quote change")
    elif row.get("source_kind") == "DELTA_TOUCHED":
        if type(changed) is not bool:
            raise ValueError("Delta must have direct-quote change flag")
    else:
        raise ValueError("Unrecognized market observation kind")


def lineage_asof(history, cutoff):
    """One validated ticker's literal identity, restricted to observed evidence."""
    at = parse_iso(cutoff)
    visible = sorted((r for r in history if parse_iso(r["observed_at_utc"]) <= at),
                     key=lambda r: parse_iso(r["observed_at_utc"]))
    if not visible:
        return {"status": "NOT_OBSERVED", "event_ticker": None,
                "series_ticker": None, "lifecycle": "NOT_OBSERVED",
                "observations": 0, "semantic_conflict_fields": [],
                "description_changed": False}
    values, texts = defaultdict(set), defaultdict(set)
    for row in visible:
        terms = row["contract_terms_as_observed"]
        if not isinstance(terms, dict):
            continue
        for key in SEMANTIC:
            if key in terms and terms[key] is not None:
                values[key].add(_literal(terms[key]))
        for key in DESCRIPTIVE:
            if key in terms and terms[key] is not None:
                texts[key].add(_literal(terms[key]))
    conflicts = sorted(k for k in SEMANTIC if len(values[k]) > 1)
    def known(key):
        return json.loads(next(iter(values[key]))) if len(values[key]) == 1 else None
    event, series = known("event_ticker"), known("series_ticker")
    if conflicts:
        status = "QUARANTINED_TERM_CONFLICT"
    elif not isinstance(event, str) or not event or not isinstance(series, str) or not series:
        status = "UNRESOLVED_LITERAL_IDENTITY"
    else:
        status = "LITERAL_CONTRACT_IDENTITY_OBSERVED"
    return {
        "status": status, "event_ticker": event, "series_ticker": series,
        "lifecycle": visible[-1]["lifecycle"], "observations": len(visible),
        "last_observed_at_utc": visible[-1]["observed_at_utc"],
        "semantic_conflict_fields": conflicts,
        "description_changed": any(len(v) > 1 for v in texts.values()),
        "semantic_fields_observed": sorted(k for k in SEMANTIC if values[k]),
        "contract_to_physical_game": "NOT_ESTABLISHED",
        "actual_game_start": "NOT_VERIFIED",
        "exchange_settlement": "NOT_VERIFIED",
        "pregame_or_execution_authority": "NONE",
    }


def audit_contract_lineage(tape_report, tape_rows):
    if (tape_report.get("authority") != "RESEARCH_ONLY"
            or tape_report.get("full_day_or_season") is not False):
        raise ValueError("Expected research-only verified tape prefix")
    if not isinstance(tape_rows, list) or len(tape_rows) > 120000:
        raise ValueError("Missing or unbounded sparse tape")
    # Verify all source paths/hashes, source kinds, clocks and tick counts.
    ticks = verified_tape_ticks(tape_rows, tape_report)
    histories, by_ticker, seen = defaultdict(list), defaultdict(set), set()
    for row in tape_rows:
        _validate(row)
        key = (row["sport"], row["ticker"], parse_iso(row["observed_at_utc"]))
        if key in seen:
            raise ValueError("Duplicate ticker observation in one verified tick")
        seen.add(key)
        histories[(row["sport"], row["ticker"])].append(row)
        by_ticker[row["ticker"]].add(row["sport"])
    cross_sport = {t for t, sports in by_ticker.items() if len(sports) > 1}
    result = {}
    for sport in sorted(ticks):
        tape = tape_report["sports"][sport]
        counts, series_counts, examples = Counter(), Counter(), []
        for (s, ticker), history in sorted(histories.items()):
            if s != sport:
                continue
            history.sort(key=lambda r: parse_iso(r["observed_at_utc"]))
            first = lineage_asof(history, tape["base_at"])
            final = lineage_asof(history, tape["last_verified_at"])
            if ticker in cross_sport:
                final["status"] = "QUARANTINED_CROSS_SPORT_TICKER"
            counts["n_unique_tickers"] += 1
            counts["n_literal_identity_observed_at_base"] += first["status"] == "LITERAL_CONTRACT_IDENTITY_OBSERVED"
            counts["n_literal_identity_observed_at_end"] += final["status"] == "LITERAL_CONTRACT_IDENTITY_OBSERVED"
            counts["n_term_conflict_tickers"] += bool(final["semantic_conflict_fields"])
            counts["n_cross_sport_ticker_collisions"] += ticker in cross_sport
            counts["n_unresolved_identity_tickers"] += final["status"] == "UNRESOLVED_LITERAL_IDENTITY"
            counts["n_removed_at_end"] += final["lifecycle"] == "REMOVED"
            counts["n_multiple_observation_tickers"] += final["observations"] > 1
            counts["n_descriptive_text_changed"] += final["description_changed"]
            counts["n_with_literal_result_field"] += any(
                r["contract_terms_as_observed"].get("result") is not None
                for r in history if isinstance(r["contract_terms_as_observed"], dict))
            if final["status"] == "LITERAL_CONTRACT_IDENTITY_OBSERVED":
                series_counts[final["series_ticker"]] += 1
            if final["status"].startswith("QUARANTINED") and len(examples) < 5:
                examples.append({"ticker": ticker, "status": final["status"],
                                 "conflicting_fields": final["semantic_conflict_fields"],
                                 "status_at_tape_base": first["status"]})
        result[sport] = {
            **dict(counts),
            "n_verified_observation_ticks": len(ticks[sport]),
            "n_distinct_literal_series_with_identity": len(series_counts),
            "top_literal_series": [
                {"series_ticker": k, "n_unique_contract_tickers": v}
                for k, v in sorted(series_counts.items(), key=lambda x: (-x[1], x[0]))[:15]],
            "quarantined_examples": examples,
            "coverage": "VERIFIED_CHECKPOINT_PLUS_DELTA_PREFIX_ONLY",
            "market_family_classification": "LITERAL_SERIES_ONLY_NO_INFERRED_FAMILY",
            "contract_to_physical_game": "NOT_ESTABLISHED",
            "actual_game_start": "NOT_VERIFIED",
            "exchange_settlement": "NOT_VERIFIED",
            "pregame_or_execution_authority": "NONE",
        }
    return {
        "schema_version": 1, "authority": "RESEARCH_ONLY", "sports": result,
        "n_cross_sport_literal_ticker_collisions": len(cross_sport),
        "limitations": [
            "Series and event ticker strings do not independently identify physical games.",
            "Term conflicts are quarantined only after observation, never before.",
            "Title edits are descriptive, not contract rule changes.",
            "No full-day coverage, actual start, exchange settlement, fill, fee or ROI authority.",
            "NFL, CFB, MLB, CBB, soccer and tennis await comparable verified time-series input.",
        ],
    }
