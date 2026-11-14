"""Which source-rights questions would clear the most already-built inputs (RESEARCH_ONLY, deterministic).

    python -m alpha_engine.input_research.data_foundation.rights_questions

An input's tier is the weakest tier over its raw sources, so an input is cleared by a question only when EVERY source it uses is cleared. The ranking therefore reports (a) inputs that depend on that source alone, and (b) inputs that also need another source.
Nothing here asserts any provider term: `evidence_state` says what authoritative text was actually read, and each question names the exact page to read.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from . import rights as RT
from . import market_completeness as M

OUT = M.DF / "rights_questions.json"
BUILT = ("VERIFIED_FULL", "VERIFIED_PARTIAL", "VERIFIED_PROXY")
QUESTIONS = {
    "espn_scoreboard_and_archives": ("Does Disney/ESPN grant any right to retain and analyse data pulled from its undocumented site.api.espn.com endpoints for internal non-commercial research (and, separately, commercial use)?", "https://disneytermsofuse.com/", "NOT_REACHED (DNS blocked here)"),
    "nflverse": ("Which upstream terms (NFL.com game feeds, NGS, FTN charting, ESPN) govern the nflverse releases, and does the wrapper CC BY 4.0 licence carry them?", "https://github.com/nflverse/nflverse-data (LICENSE.md and release notes) plus the NFL and FTN terms", "WRAPPER_LICENCE_READ_UPSTREAM_NOT_READ"),
    "sackmann_tennis": ("COMMERCIAL only: research use is cleared by CC BY-NC-SA 4.0. Is a commercial licence available from Tennis Abstract / Jeff Sackmann?", "tennisabstract.com / the tennis_atp README", "NC_LICENCE_READ_VERBATIM"),
    "nhl_api_moneypuck": ("NHL terms for api-web.nhle.com data (MoneyPuck is now tracked separately).", "https://www.nhl.com/info/terms-of-service", "NOT_REACHED (DNS blocked here)"),
    "moneypuck_listed_downloads": ("Research use of MoneyPuck's explicitly listed downloads is cleared non-commercially with attribution (owner-reported). Which exact files are listed, and is a commercial licence available?", "https://www.moneypuck.com/data.htm", "OWNER_REPORTED_NOT_AGENT_VERIFIED (host denied here)"),
    "moneypuck_unlisted": ("MoneyPuck data not on the listed-downloads page needs MoneyPuck approval.", "https://www.moneypuck.com/data.htm", "OWNER_REPORTED_NOT_AGENT_VERIFIED"),
    "cfbd_cbbd_direct_api": ("Direct CFBD/CBBD API terms (owner-reported): research and commercial derived outputs permitted within the shared quota, no raw redistribution. Quota measurement and an owner-authorised key workflow are needed before any collection.", "https://collegefootballdata.com/terms", "OWNER_REPORTED_NOT_AGENT_VERIFIED (host denied here)"),
    "mlb_stats_api": ("MLB Advanced Media terms for statsapi.mlb.com bulk reuse (the long-standing Gameday notice limits use to individual, non-commercial purposes; confirm the current text).", "https://www.mlb.com/official-information/terms-of-use", "NOT_REACHED (DNS blocked here)"),
    "football_data_co_uk": ("Provider states private-individual use only and no automated bots/scrapers/AI data training: is internal automated research use permitted, or is written permission needed?", "https://football-data.co.uk/data.php and /disclaimer.php", "PROVIDER_STATEMENT_READ_2026-11-10 (restrictive); disclaimer page not read"),
    "sportsdataverse_espn_mbb_cfb": ("ESPN terms (see ESPN) plus CollegeFootballData.com terms for the CFBD-derived tables and NCAA terms.", "https://collegefootballdata.com/ and https://www.ncaa.com/", "NOT_REACHED (DNS blocked here)"),
    "nba_official_injury_report": ("NBA terms for the official injury report PDFs/rows.", "https://www.nba.com/termsofuse", "NOT_REACHED"),
    "UNMATCHED": ("Registry gap: the raw source 'owner schedule archive' matches no registry token, so it fails closed. Identify which provider's schedule it archives and register it.", "owner", "REGISTRY_GAP"),
}


def build() -> dict:
    vc = {r["key"]: r for r in json.loads((M.DF / "verified_coverage.json").read_text())["rows"]}
    reg = RT.registry(); raw = RT.raw_sources_by_key()
    def ids_of(n):
        m = [s for s in reg["sources"] if any(t in n.lower() for t in s["tokens"])]; sup = {x for s in m for x in s.get("supersedes", [])}      # same specificity rule as rights.tier_of_source
        return [s["id"] for s in m if s["id"] not in sup] or ["UNMATCHED"]
    built = sorted(k for k, r in vc.items() if r["verified_status"] in BUILT)
    prim = defaultdict(int)
    for a in M.archetypes():
        for iid, role in a["inputs"]:
            k = f"{a['sport']}:{iid}"
            if role == "primary" and k in vc and vc[k]["verified_status"] in BUILT and iid not in M.NON_PREDICTIVE_IDS: prim[k] += 1
    sets = {k: frozenset(i for r in raw.get(k, []) for i in ids_of(r)) or frozenset(["UNMATCHED"]) for k in built}
    rows = []
    for sid in sorted({i for s in sets.values() for i in s}):
        touch = [k for k, s in sets.items() if sid in s]; sole = [k for k in touch if sets[k] == {sid}]
        src = next((s for s in reg["sources"] if s["id"] == sid), None); tier = src["tier"] if src else RT.registry()["tier_order"][0]
        q, url, st = QUESTIONS.get(sid, ("unrecorded", "", "unrecorded"))
        rows.append({"source": sid, "current_tier": tier, "built_inputs_touching": len(touch), "built_inputs_cleared_by_this_alone": len(sole), "primary_slots_of_sole_dependents": sum(prim[k] for k in sole),
                     "by_sport": {sp: sum(k.startswith(sp + ":") for k in touch) for sp in M.SPORTS if any(k.startswith(sp + ":") for k in touch)},
                     "question": q, "read_this": url, "evidence_state": st})
    rows.sort(key=lambda r: (-r["built_inputs_cleared_by_this_alone"], r["source"]))
    for i, r in enumerate(rows, 1): r["rank"] = i
    return {"schema": "rights-questions-1.0", "status": "RESEARCH_ONLY", "built_inputs": len(built), "rows": rows,
            "note": "No provider term is asserted unless evidence_state says it was read. Clearing a research question never implies commercial clearance; the two are separate."}


def main() -> int:
    OUT.write_text(json.dumps(build(), indent=1) + "\n"); print(OUT); return 0


if __name__ == "__main__":
    raise SystemExit(main())
