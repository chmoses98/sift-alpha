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
    r=x.get("report",{})
    fs=r.get("familyModelCoverage",{})
    if not isinstance(fs,dict) or not fs:
        raise ValueError("Missing model coverage denominator")
    holes={}
    for family, stats in fs.items():
        observed=stats.get("observed")
        evaluated=stats.get("modelEvaluated")
        rate=stats.get("coverageRate")
        if not isinstance(family,str) or type(observed) is not int or type(evaluated) is not int or observed<0 or not 0<=evaluated<=observed:
            raise ValueError("Invalid coverage count")
        if type(rate) not in (float,int) or not 0<=rate<=1 or abs(rate-(evaluated/observed if observed else 0))>0.001:
            raise ValueError("Invalid claimed model coverage rate")
        if observed>=100 and evaluated==0:
            holes[family]={"model_evaluated":evaluated,"market_observations":observed}
    return {
        "source_type":"dated_retrospective_market_to_model_coverage_audit",
        "date_range":r.get("dateRange"),
        "unmodeled_families_with_100plus_observations":holes,
        "n_market_families_with_unmodeled_coverage":len(holes),
        "finding":"Market availability cannot be mistaken for valid independent model predictions or retrospective returns.",
        "requires":"Reconcile each target market family with timestamped original feature inputs, actually published projection snapshots, and independently settled outcomes.",
        "model_accuracy_certified":False,
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
