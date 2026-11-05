"""Real public source qualification across eight SIFT sports."""
import json
from pathlib import Path
from .all_sport_evidence import run
if __name__=="__main__":
    manifest=json.loads(Path("research/all_sport_metadata_pins.json").read_text(encoding="utf-8"))
    report=run(manifest)
    dest=Path("artifacts/all_sport_evidence_status.json")
    dest.parent.mkdir(parents=True,exist_ok=True)
    dest.write_text(json.dumps(report,sort_keys=True,indent=2)+"\n",encoding="utf-8")
    for row in report["sources"]:
        print(row["sport"],"validated pinned metadata",row["role"])
    print("RESEARCH_ONLY:",dest)
