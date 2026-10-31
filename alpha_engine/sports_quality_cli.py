"""Evidence-based NBA roster and MLB projection-coverage gap report."""
import json
from pathlib import Path
from .sports_quality_evidence import audit
if __name__=="__main__":
    manifest=json.loads(Path("research/sports_quality_evidence_sources.json").read_text(encoding="utf-8"))
    report=audit(manifest)
    out=Path("artifacts/sports_quality_gaps.json")
    out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    print("Historical sports data-quality gaps independently reproduced from pinned source reports.")
    print("NBA games",report["sport_source_audits"]["NBA"]["games_in_study"])
    print("MLB unmodeled market families",report["sport_source_audits"]["MLB"]["n_market_families_with_unmodeled_coverage"])
    print("No certification of underlying original data or current production model:",out)
