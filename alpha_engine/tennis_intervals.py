"""Document which intervals each tennis results source covers, from the source files themselves.

Usage: python -m alpha_engine.tennis_intervals ODDS_CSV OUT_JSON SOURCE_COMMIT
ODDS_CSV: valuebetennis open match/odds CSV (columns date, genre, vainqueur_id, score) as mirrored in
sumeetamin/tennis-history-data. A month is flagged THIN when its row count is < 50% of the median of the other months.
Frozen primary sources are taken from Tennis-Edge-Finder docs/DATA_SOURCES.md (documented, not recomputed)."""
import collections, csv, hashlib, json, statistics, sys

FROZEN = {"atp": {"source": "Kadantte/tennis_atp (Sackmann fork)", "last_match": "2026-06-01"}, "wta": {"source": "VictorSquidWei/tennis_wta (Sackmann fork)", "last_match": "2026-04-27"}}


def analyse(path, since="2026-01"):
    rows = collections.Counter(); full = collections.Counter(); last = {}
    for r in csv.DictReader(open(path, newline="")):
        d = r["date"][:10]; g = r["genre"]
        last[g] = max(last.get(g, ""), d)
        if d[:7] >= since:
            rows[(g, d[:7])] += 1; full[(g, d[:7])] += bool(r.get("vainqueur_id") and r.get("score"))
    out = {}
    for g in ("atp", "wta"):
        months = sorted(m for (gg, m) in rows if gg == g)
        med = statistics.median(rows[(g, m)] for m in months) if months else 0
        out[g] = {"candidate_last_match": last.get(g), "months": [{"month": m, "rows": rows[(g, m)], "rows_with_winner_and_score": full[(g, m)], "thin": rows[(g, m)] < 0.5 * med} for m in months]}
    return out


def build(path, commit):
    res = analyse(path)
    for g, fz in FROZEN.items():
        res[g]["primary_frozen"] = fz
        res[g]["unavailable_from_primary"] = {"from": fz["last_match"], "to": res[g]["candidate_last_match"]}
        res[g]["candidate_thin_months_inside_gap"] = [m["month"] for m in res[g]["months"] if m["thin"] and m["month"] > fz["last_match"][:7]]
    return {"schema_version": "audit-1.0", "candidate_source": {"name": "valuebetennis open match/odds CSV via sumeetamin/tennis-history-data", "commit": commit, "path": "data/odds/atp_wta_match_odds.csv",
            "sha256": hashlib.sha256(open(path, "rb").read()).hexdigest(), "licence": "CC BY-NC-SA 4.0 (Sackmann-derived layers); odds provider terms unverified",
            "caveats": ["covers only matches that have a Pinnacle quote, not every match", "winner+score missing on part of the rows", "no result-publication timestamps; match date is an availability proxy", "third-party mirror, provenance chain not independently verified"]},
            "status": "REPLACEMENT_AVAILABLE_PARTIAL_NOT_INGESTED", "tours": res}


if __name__ == "__main__":
    json.dump(build(sys.argv[1], sys.argv[3]), open(sys.argv[2], "w"), indent=1)
