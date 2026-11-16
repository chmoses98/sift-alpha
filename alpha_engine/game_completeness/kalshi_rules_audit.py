"""Per-series settlement-semantics audit from Kalshi's own rules text (RESEARCH_ONLY, offline).

Reads the <series>[__historical].rules.json files written by kalshi_official.fetch_series and classifies, per
series, how the rules treat overtime / extra innings.  The output is counts per clause class and nothing else: no
rules text is reproduced.  Purpose: catch engine-vs-rule mismatches such as NBA 2H (rules include OT; the engine
excluded it) before they show up as settlement disagreements.

    python -m alpha_engine.game_completeness.kalshi_rules_audit OUT_DIR [OUT_DIR ...]
"""
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

INLINE = re.compile(r"\((including|excluding) (overtime|extra innings)\)", re.I)
NOTE = re.compile(r"(1st|2nd|3rd|4th) (half|quarter|period)s? markets? (are inclusive of|include|do not include|"
                  r"are exclusive of|exclude)s? (overtime|extra innings)", re.I)


def classify(text):
    """Contract-specific clause first ("... 2nd half (including overtime) ..."), then the generic notes, which
    often describe OTHER periods (a 1H contract can carry "2nd half markets are inclusive of overtime"), so each
    note is reported with the period it names."""
    text = text or ""
    out = [f"inline:{m.group(1).lower()}" for m in INLINE.finditer(text)]
    for m in NOTE.finditer(text):
        verdict = "excludes" if re.search(r"not|exclu", m.group(3), re.I) else "includes"
        out.append(f"note:{m.group(1).lower()} {m.group(2).lower()} {verdict}")
    if re.search(r"\bregulation\b", text, re.I):
        out.append("mentions_regulation")
    return tuple(sorted(set(out))) or ("no_ot_clause",)


def audit(folders):
    per = defaultdict(Counter)
    for folder in folders:
        for f in sorted(Path(folder).glob("**/*.rules.json")):
            sport = f.parent.name
            series = f.name.split(".rules.json")[0].replace("__historical", "")
            for r in json.loads(f.read_text()).values():
                per[f"{sport}/{series}"]["+".join(classify(" ".join(v or "" for v in r.values())))] += 1
    return {k: dict(v) for k, v in sorted(per.items())}


if __name__ == "__main__":
    print(json.dumps(audit(sys.argv[1:]), indent=1))
