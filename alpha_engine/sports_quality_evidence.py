"""Report *actual historical* sport-side data quality caveats from immutable QA files.

This consumes existing research audits, not original game/lineup sources; it
never declares production models fixed or unverified values true.
"""
from __future__ import annotations
import hashlib
import json
import re
from urllib.request import Request, urlopen
from pathlib import Path

REPOS={"NBA":"chmoses98/nba-edge-finder","MLB":"chmoses98/edge-finder-api"}
PATHS={
"NBA":"docs/research/w1_nba/player_team_identity_roster_audit.json",
"MLB":"data/edgelab/analytics/latest_research_research_data_quality.json",
}

def check_sources(m):
    if m.get("schema_version")!=1 or m.get("max_bytes_total")!=20000:
        raise ValueError("Unexpected historical QA manifest/budget")
    src=m.get("sources",[])
    if len(src)!=2 or {x.get("sport") for x in src}!={"NBA","MLB"}:
        raise ValueError("Two sport audit sources required")
    for x in src:
        if x.get("repository")!=REPOS[x["sport"]] or x.get("path")!=PATHS[x["sport"]]:
            raise ValueError("Unapproved data source")
        if any(re.fullmatch(r"[a-f0-9]{40}",str(x.get(z))) is None for z in ("commit","blob_sha1")):
            raise ValueError("Missing source pin")
        if x.get("max_bytes") not in (8000,12000):
            raise ValueError("Outside approved per-document byte budget")
    return src

def _raw(x):
    return f"https://raw.githubusercontent.com/{x['repository']}/{x['commit']}/{x['path']}"

def read(x,downloader=None):
    if downloader:
        content=downloader(x)
    else:
        url=_raw(x)
        with urlopen(Request(url,headers={"User-Agent":"Alpha-sport-truth/1"}),timeout=15) as response:
            if response.geturl()!=url:
                raise ValueError("Unexpected remote redirect")
            content=response.read(x["max_bytes"]+1)
    if not content or len(content)>x["max_bytes"]:
        raise ValueError("Oversized/empty audit input")
    actual=hashlib.sha1(b"blob "+str(len(content)).encode()+b"\0"+content).hexdigest()
    if actual!=x["blob_sha1"]:
        raise ValueError("Historical audit data source hash mismatch")
    value=json.loads(content)
    if not isinstance(value,dict):
        raise ValueError("Source audit must be JSON object")
    return value,hashlib.sha256(content).hexdigest()

def audit_nba(x):
    c=x.get("counts",{})
    old=c.get("v1",{})
    candidate=c.get("both",{})
    for row in [old,candidate]:
        for k in ("entries","entries_stale_third_team","entries_stale_opponent","box_wrong_team"):
            if type(row.get(k)) is not int or row[k]<0 or row[k]>row["entries"]:
                raise ValueError("Malformed roster data-quality denominator")
    if candidate["entries"]>old["entries"]:
        raise ValueError("Candidate denominator unexpectedly grows")
    return {
        "source_type":"historical_comparative_roster_audit",
        "games_in_study":x.get("n_games"),
        "old_entries":old["entries"],
        "old_stale_third_team_entries":old["entries_stale_third_team"],
        "old_wrong_team_box_entries":old["box_wrong_team"],
        "candidate_entries":candidate["entries"],
        "candidate_stale_third_team_entries":candidate["entries_stale_third_team"],
        "candidate_wrong_team_box_entries":candidate["box_wrong_team"],
        "finding":"Stale roster and wrong-team attribution appeared in prior historical study; candidate reduced these. Production deployment and current accuracy not verified.",
        "requires":"Inspect actual published model code/version and live frozen minute/roster inputs; corroborate game-by-game official team membership and box/lineup attribution.",
        "production_model_certified":False,
    }

def audit_mlb(x):
    """Reconcile the *entire* historical MLB opportunity denominator.

    These are source-reported opportunity rows, not independent games, unique
    contracts, contemporaneous executable fills, or certified forecasts.
    """
    import math

    r = x.get("report", {})
    if not isinstance(r, dict):
        raise ValueError("Missing MLB quality report")

    def count(value, label):
        if type(value) is not int or value < 0:
            raise ValueError("Invalid count: " + label)
        return value

    def rate(value, numerator, denominator, label):
        if type(value) not in (float, int) or not math.isfinite(value):
            raise ValueError("Invalid coverage rate: " + label)
        expected = numerator / denominator if denominator else 0
        if not 0 <= value <= 1 or abs(value - expected) > 0.001:
            raise ValueError("Inconsistent coverage rate: " + label)

    total = count(r.get("totalOpportunityRows"), "totalOpportunityRows")
    if not total or x.get("rowCount") != total:
        raise ValueError("Missing or inconsistent global opportunity denominator")
    unique_games = count(r.get("uniqueGames"), "uniqueGames")
    unique_tickers = count(r.get("uniqueMarketTickers"), "uniqueMarketTickers")
    if unique_games > total or unique_tickers > total:
        raise ValueError("Unique identity count exceeds row denominator")
    missing_model = count(r.get("rowsLackingModelEvaluation"), "rowsLackingModelEvaluation")
    missing_valid_model = count(
        r.get("rowsLackingTemporallyValidModelEvaluation"),
        "rowsLackingTemporallyValidModelEvaluation",
    )
    missing_price = count(
        r.get("rowsLackingExecutablePregamePrice"),
        "rowsLackingExecutablePregamePrice",
    )
    if not missing_model <= missing_valid_model <= total or missing_price > total:
        raise ValueError("Impossible global missingness counts")

    model_families = r.get("familyModelCoverage")
    settlement_families = r.get("familySettlementCoverage")
    if not isinstance(model_families, dict) or not model_families or not isinstance(settlement_families, dict):
        raise ValueError("Missing family coverage denominators")
    if set(model_families) != set(settlement_families):
        raise ValueError("Model and settlement family inventories disagree")

    holes = {}
    family_observed = family_evaluated = family_settled = 0
    for family, stats in model_families.items():
        if not isinstance(family, str) or not family or not isinstance(stats, dict):
            raise ValueError("Malformed market family")
        observed = count(stats.get("observed"), family + " observed")
        evaluated = count(stats.get("modelEvaluated"), family + " evaluated")
        if evaluated > observed:
            raise ValueError("Model coverage exceeds family denominator")
        rate(stats.get("coverageRate"), evaluated, observed, family + " model")
        settlement = settlement_families[family]
        if not isinstance(settlement, dict):
            raise ValueError("Malformed settlement family")
        settled_observed = count(settlement.get("observed"), family + " settlement observed")
        settled = count(settlement.get("settled"), family + " settled")
        if settled_observed != observed or settled > observed:
            raise ValueError("Settlement and model denominators disagree")
        rate(settlement.get("coverageRate"), settled, observed, family + " settlement")
        family_observed += observed
        family_evaluated += evaluated
        family_settled += settled
        if observed >= 100 and evaluated == 0:
            holes[family] = {"model_evaluated": evaluated, "market_observations": observed}

    statuses = r.get("settlementStatusCounts")
    if not isinstance(statuses, dict) or set(statuses) != {
        "SETTLED", "NOT_SETTLED", "SETTLEMENT_UNRESOLVED"
    }:
        raise ValueError("Missing or unknown settlement status category")
    status_counts = {key: count(value, key) for key, value in statuses.items()}
    if (family_observed != total
            or family_evaluated != total - missing_model
            or family_settled != status_counts["SETTLED"]
            or sum(status_counts.values()) != total):
        raise ValueError("Family and global coverage denominators disagree")

    return {
        "source_type": "dated_retrospective_market_to_model_coverage_audit",
        "date_range": r.get("dateRange"),
        "opportunity_rows": total,
        "unique_market_tickers_reported": unique_tickers,
        "unique_physical_games_reported_not_independently_verified": unique_games,
        "model_evaluated_rows": family_evaluated,
        "model_evaluation_coverage_fraction": family_evaluated / total,
        "rows_without_model_evaluation": missing_model,
        "rows_without_temporally_valid_model_evaluation": missing_valid_model,
        "settled_rows_reported": family_settled,
        "settlement_unresolved_rows": status_counts["SETTLEMENT_UNRESOLVED"],
        "not_settled_rows": status_counts["NOT_SETTLED"],
        "rows_reported_without_executable_pregame_price": missing_price,
        "executable_pregame_price_independently_verified": False,
        "unmodeled_families_with_100plus_observations": holes,
        "n_market_families_with_unmodeled_coverage": len(holes),
        "finding": "Historical market capture has vastly broader coverage than model evaluation; row counts are not independent games, valid forecasts, executable trades or verified returns.",
        "requires": "Verify source-side family definitions, frozen point-in-time forecasts, independent outcomes, actual starts, executable side/depth and per-family exclusions.",
        "model_accuracy_certified": False,
    }

def audit(manifest,downloader=None):
    sources=check_sources(manifest)
    data={}
    evidence=[]
    for s in sources:
        doc,digest=read(s,downloader)
        data[s["sport"]]=doc
        evidence.append({"sport":s["sport"],"commit":s["commit"],"path":s["path"],"sha256":digest,
                         "original_sport_truth_independently_checked":False})
    findings={"NBA":audit_nba(data["NBA"]),"MLB":audit_mlb(data["MLB"])}
    return {"schema_version":1,"authority":"HISTORICAL_QUALITY_LIMITATIONS_ONLY",
            "sport_source_audits":findings,"evidence":evidence,
            "source_accuracy_certified":False,
            "limitations":["Audited source-side analytical summaries, not independent raw stat/lineup outcomes.",
                           "Do not interpret candidate roster settings as active production behavior.",
                           "Historical market capture alone does not establish player model forecast coverage, calibration, or profitable betting edge."]}
