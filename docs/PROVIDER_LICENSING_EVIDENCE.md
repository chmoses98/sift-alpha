# Provider licensing evidence review (RESEARCH_ONLY — evidence only, no decisions)

Reviewed 2026-11-13 on `claude/provider-licensing-research-k7d0tj` (based on Phase 14 @ `88b0a77`).
Nothing in this file approves a licence, edits `rights_registry.json`, or authorises collection. Every provider stays blocked
exactly as the registry records it. No sports/API data was fetched, no account or key was used, no probe was run.

## How evidence was gathered, and its grade

| Grade | Meaning | Usable for a rights decision? |
|---|---|---|
| `PRIMARY_READ` | The licence/terms document itself was read from the publisher's own host (GitHub repo of the publisher) in this session | Yes, as evidence for the owner |
| `PRIMARY_UNREACHABLE` | The official terms URL failed from this container (DNS `ENOTFOUND` = host outside the environment's network policy, or HTTP error) | No — nothing asserted |
| `SEARCH_EXCERPT` | Fragment of the official page as returned by a web-search index; not the page itself; may be stale or truncated | No — leads only; owner must read the live page |
| `SECONDARY` | Third-party summary (blogs, trackers, forums) | No |

Network: the environment's policy denies most provider hosts. DNS failures this session: `collegefootballdata.com`, `collegebasketballdata.com`,
`disneytermsofuse.com`, `www.espn.com`, `www.mlb.com`, `gdx.mlb.com`, `www.nhl.com`, `nflreadr.nflverse.com`, `www.nflfastr.com`, `ftnfantasy.com`,
`www.football-data.org`, `kalshi.com`, `moneypuck.com`, `www.retrosheet.org`, `www.weather.gov`, `open-meteo.com`, `foundation.wikimedia.org`,
`www.wikidata.org`. HTTP errors: `statsapi.mlb.com` 406, `api-web.nhle.com/` 404 (root only; no data endpoint was called), `github.com/JeffSackmann/tennis_atp` 404.
GitHub (`github.com`, `raw.githubusercontent.com`) was reachable and was used only for licence files, READMEs and data dictionaries (metadata).
The network policy was not changed; widening it is an owner decision.

## 1. CollegeFootballData (CFBD) / CollegeBasketballData (CBBD)

| Item | Evidence | Grade |
|---|---|---|
| Terms URL | https://collegefootballdata.com/terms — `ENOTFOUND` (also in Phases 10–12: proxy 403 / DNS) | `PRIMARY_UNREACHABLE` |
| Effective date | "Terms of Use (effective August 12, 2026)" | `SEARCH_EXCERPT` |
| Commercial use | Commercial use permitted; the subscription tier sets API quota, not commercial permission; no separate commercial tier; commercial defined broadly (paid, ad-supported, affiliate, internal business) | `SEARCH_EXCERPT` |
| Model training | Permitted uses include "historical analysis, backtesting, feature engineering, and model training" | `SEARCH_EXCERPT` |
| Caching | Permitted to "privately cache, store, normalize, and retain API responses" | `SEARCH_EXCERPT` |
| Derived outputs | May publish/commercialise independently created "analyses, models, model weights, predictions, projections, rankings, visualizations, and other Derived Outputs" | `SEARCH_EXCERPT` |
| Redistribution (prohibited) | Redistribution = providing API Data "as a standalone dataset, bulk download, raw feed, database mirror, substitute API, or substantially equivalent data service" | `SEARCH_EXCERPT` |
| Shared quota | Tiers "primarily determine the shared API quota pool"; CBBD free key requested at collegebasketballdata.com/key; quota shared with the CFBD Patreon tiers | `SEARCH_EXCERPT` (terms) + `SECONDARY` (tier figures conflict: Academic 3,000 vs 500k calls/mo) |
| Key handling | May not give third parties direct or programmatic access to the key | `SEARCH_EXCERPT` |
| Attribution | "appreciated but not required" | `SEARCH_EXCERPT` |
| Separate product | Gumroad "Model Training Pack": personal use by original purchaser only; redistribution prohibited — a different licence, not the API terms | `SECONDARY` |

Consistent with the owner-reported reading already in the registry (`cfbd_cbbd_direct_api`, tier `CLEARED_PROVIDER_TERMS_DIRECT_API`, `collection_allowed=false`).

Unresolved:
- **Third-party rights are not addressed in anything read.** CFBD aggregates data that originates elsewhere (play-by-play and box scores from
  league/stat feeds, recruiting rankings, poll ballots, sportsbook lines). No excerpt says CFBD holds, or warrants, the rights to the underlying data,
  or that its licence covers betting lines. Keep `cfb.pbp_cfbd`'s line/odds columns out of scope, as in Phase 11 (market columns never loaded).
- Does "Derived Outputs" cover a model whose outputs are sold or traded on, rather than published? The excerpt says "publish and commercialize".
- Whether the August 2026 text supersedes the owner-reported version the registry cites (date of the owner's reading is not recorded).
- Whether the CBBD terms are the same document (only CFBD's URL was indexed; `collegebasketballdata.com/terms` unreachable).
- Registry gap: source id `cfbd` (map) has no tokenised registry entry (`cfbd_direct_api` / `cbbd_direct_api` only) → fails closed. Unchanged here.

## 2. nflverse / FTN (dataset and column level)

Primary documents read (GitHub):

| Document | URL | What it says | Grade |
|---|---|---|---|
| nflverse-data `LICENSE.md` | https://github.com/nflverse/nflverse-data/blob/main/LICENSE.md (sha256 `2a82ac9b…9111`) | Full CC BY 4.0 International text; no copyright-holder line | `PRIMARY_READ` |
| nflverse-pbp `LICENSE.md` | https://github.com/nflverse/nflverse-pbp | CC BY 4.0 (same text) | `PRIMARY_READ` |
| nflfastR `LICENSE.md` | https://github.com/nflverse/nflfastR | MIT, "Copyright (c) 2020 Sebastian Carl; Ben Baldwin" — **code only** | `PRIMARY_READ` |
| nflreadr `README.md` (commit `23f915a5`, 2026-09-17) | https://github.com/nflverse/nflreadr | Code MIT; "NFL data accessed by this package belong to their respective owners, and are governed by their terms of use." | `PRIMARY_READ` |
| `R/load_ftn_charting.R` | same repo | "released under the CC-BY-SA 4.0 Creative Commons license and attribution must be made to **FTN Data via nflverse**"; data 2022+ | `PRIMARY_READ` (nflverse's statement of FTN's grant) |
| `R/load_participation.R` | same repo | Pre-2023 "from NFL NGS"; 2023+ "courtesy of FTN", CC-BY-SA 4.0, attribution "FTN Data via nflverse" (2023+) or "NFL NextGenStats via nflverse" (≤2022) | `PRIMARY_READ` |
| `NEWS.md` | same repo | Depth charts source "changed from NFL Data Exchange to ESPN" | `PRIMARY_READ` |
| ffopportunity README "Terms of Use" | https://github.com/ffverse/ffopportunity | Code GPL v3; "models and expected points data … licensed under Creative Commons Attribution-ShareAlike 4.0" | `PRIMARY_READ` |
| nflverse-data releases page 1 | https://github.com/nflverse/nflverse-data/releases | ftn_charting: "Charting data provided by https://FTNFantasy.com/data"; weekly_rosters: "via NFL Shield v2 API"; schedules/trades: "maintained in Lee Sharpe's nfldata" | `PRIMARY_READ` |
| nfldata licence | `raw.githubusercontent.com/nflverse/nfldata/master/LICENSE{,.md}` → 404 | No licence file found | `PRIMARY_READ` (absence) |
| FTN's own terms | ftnfantasy.com / ftndata.com | `ENOTFOUND` — **FTN's own licence statement not read; the CC BY-SA grant is known only through nflverse's documentation** | `PRIMARY_UNREACHABLE` |
| NFL terms | nfl.com | not attempted (NFL hosts outside the policy) | — |

Column-level audit: `research/provider_licensing/nflverse_column_audit.csv` (1,392 fields across 23 nflreadr dictionaries at commit `23f915a5`;
dictionary SHA-256s in `nflverse_column_audit_summary.json`; reproducible with `nflverse_column_audit.py`).

| Lane | Licence position | Datasets / columns |
|---|---|---|
| A. nflverse-computed (CC BY 4.0) | Wrapper licence applies to nflverse's own computations; values are computed from NFL feed data, so the upstream caveat still applies to inputs | 63 pbp model columns (`ep`, `epa`, `wp`, `wpa`, `cp`, `cpoe`, `xyac_*`, `xpass`, `pass_oe`, `*_prob`, …); id crosswalk built by nflverse |
| B. FTN (CC BY-SA 4.0, ShareAlike) | Explicit licence via nflverse; ShareAlike obliges derived **datasets** to be CC BY-SA if shared; FTN's own text unread | `ftn_charting` (29 fields, 2022+), `participation` 2023+ (26 fields, mixed with NGS ≤2022) |
| B2. ffverse (CC BY-SA 4.0) | Explicit; model trained on nflverse pbp (NFL upstream) | `ff_opportunity` (218 fields) |
| C. NFL upstream — **UNRESOLVED** | Redistributed under the CC BY 4.0 wrapper, but nflreadr itself says NFL data is governed by its owners' terms; a wrapper cannot license what it does not own | 295 pbp feed fields; player/team stats (286); injuries (16); rosters/status (56); Next Gen Stats (51); participation ≤2022 |
| D. Pro-Football-Reference — **UNRESOLVED** | Sports Reference data-use terms not read | 8 pbp context columns (`roof`, `surface`, `temp`, `wind`, `stadium_id`, coaches); PFR advanced (28), snap counts (16), combine (17), draft picks (36) |
| E. Other upstream — **UNRESOLVED** | OverTheCap, ESPN (QBR; depth charts 2025+), FantasyPros/DynastyProcess, nfldata (no licence file) | contracts (50), espn_qbr (23), depth_charts (12), ff_rankings/ff_playerids (60), schedules (37), trades (11) |
| F. Betting lines — **UNRESOLVED** | `spread_line`/`total_line` "(Source: Pro-Football-Reference)"; schedules moneyline/odds columns have no stated source | 6 pbp (`spread_line`, `total_line`, `vegas_*`), 8 schedules odds columns. Market-derived; exclude from predictive use regardless |

Effect on slots (need-level; see the plan): of the 74 slots that clearing nflverse would complete, **0** can be completed from lanes B/B2 alone,
**73** need lane C (NFL-upstream) datasets and **68** need `nfl.pbp` specifically; only 2 depend on PFR-upstream datasets.
So the only explicitly licensed nflverse material (FTN, CC BY-SA) unlocks nothing by itself; the NFL-upstream question decides nflverse.

## 3. ESPN (Disney)

| Item | Evidence | Grade |
|---|---|---|
| Terms URLs | https://disneytermsofuse.com/english/, https://www.espn.com/espn/news/story?page=help/terms, http://www.espn.com/apis/devcenter/ — all `ENOTFOUND` | `PRIMARY_UNREACHABLE` |
| Automated access | Disney+ terms clause (via tracker): may not "access, monitor, copy, or extract the Services using a robot, spider, script or other automated means, including … for the purposes of creating or developing any AI Tool, data mining or web scraping" | `SECONDARY` (conductatlas.com) |
| Older Disney terms (2014, Spanish) | prohibits robots/spiders/scrapers without express written consent | `SEARCH_EXCERPT` (disneytermsofuse.com PDF) |
| TDM / AI | Disney regional "AI opt-out" pages: does not permit text-and-data mining or use of content to train AI | `SEARCH_EXCERPT` (disney.co.uk/ai-opt-out) |
| ESPN content and ML | tracker record: prohibited from using "Hulu, Disney+, or ESPN content … to train, test, fine-tune, or benchmark any artificial intelligence or machine learning system" | `SECONDARY` |

Assessment: no grant found; every indication is restrictive (automated extraction, TDM and ML use). The ESPN endpoints in the archives are undocumented.
Whether the clauses reach bare facts (scores, box-score numbers) rather than "content" is a legal question; nothing read resolves it. **Stays UNRESOLVED / blocked.**

## 4. MLB Advanced Media

| Item | Evidence | Grade |
|---|---|---|
| Terms URLs | https://www.mlb.com/official-information/terms-of-use and http://gdx.mlb.com/components/copyright.txt — `ENOTFOUND`; statsapi.mlb.com root HTTP 406 | `PRIMARY_UNREACHABLE` |
| copyright.txt (cited by every Stats API response) | "Only individual, non-commercial, non-bulk use of the Materials is permitted and any other use of the Materials is prohibited without prior written authorization from MLBAM." and "Authorized users of the Materials are prohibited from using the Materials in any commercial manner other than as expressly authorized by MLBAM." | `SECONDARY` (quoted in a GitHub issue and a forum post) |
| MLB.com Terms of Use (mlb.com/tou) | prohibits "(xi) use automated scripts to collect information from or otherwise interact with the MLB Digital Properties"; only one copy for "personal, non-commercial home use" | `SEARCH_EXCERPT` |

Assessment: what was indexed is explicitly **individual, non-commercial, non-bulk**. Bulk archives (pitch/PA events, box scores) conflict with "non-bulk" on its face.
**Stays blocked**; no research carve-out was found.

## 5. NHL

| Item | Evidence | Grade |
|---|---|---|
| Terms URL | https://www.nhl.com/info/terms-of-service — `ENOTFOUND`; api-web.nhle.com has no published terms | `PRIMARY_UNREACHABLE` |
| Current terms | "Last Updated: October 29, 2025"; lists unauthorized "spidering, scraping, harvesting" of content or data as prohibited conduct | `SEARCH_EXCERPT` |
| Team-site terms (e.g. Devils, Jan 15 2025) | bar spiders/robots/automated tools | `SEARCH_EXCERPT` |
| History | 2020-era report of NHL terms updated over commercial use of NHL.com data | `SECONDARY` |

Assessment: restrictive; no API licence exists. **Stays blocked.**

## 6. Open-data and other alternatives

| Source | Evidence | Grade | Position |
|---|---|---|---|
| openfootball `football.json` | LICENSE.md CC0 1.0: "for any purpose whatsoever, including without limitation commercial…"; club leagues only | `PRIMARY_READ` | Already `CLEARED_OPEN_LICENCE` (4 country repos read verbatim, Phase 8) |
| openfootball `worldcup` | sidebar "CC0-1.0"; README covers World Cup 1930–2026 incl. qualifiers; LICENSE.md not opened | `PRIMARY_READ` (sidebar) | Candidate; verbatim LICENSE read still needed |
| openfootball `euro` | sidebar "CC0-1.0"; directories 1960–2028 | `PRIMARY_READ` (sidebar) | Candidate, as above |
| openfootball org | 36 repos; no Copa América / Nations League / friendlies repo seen in the 10 listed; others unchecked | `PRIMARY_READ` (partial) | Coverage gap for friendlies |
| Chadwick register | "Open Data Commons Attribution License" (ODC-By 1.0) | `PRIMARY_READ` | Candidate open licence (attribution); not in registry |
| football-data.org | Terms unreachable; indexed 2018 General Terms: attribution clause 7.1 "Football data provided by the Football-Data.org API"; clause 9.1 no reference to data after subscription ends; free-tier commercial/redistribution not addressed | `SEARCH_EXCERPT` | Unresolved; key = new account (not done) |
| Kalshi | Developer Agreement PDF (v1.1, KalshiEx LLC): use of the API = acceptance; mentions "Kalshi Data"; one source says membership required; redistribution clause not seen | `SEARCH_EXCERPT` / `SECONDARY` | Unresolved; read the PDF verbatim |
| MoneyPuck, Retrosheet, NOAA/NWS, Open-Meteo, Wikimedia, Wikidata | all `ENOTFOUND` | `PRIMARY_UNREACHABLE` | Unchanged |
| Sackmann tennis | repo URL 404 this session; registry evidence (CC BY-NC-SA 4.0, Phase 10b) unchanged | — | Unchanged |

## Open questions an owner (or counsel) must resolve

1. CFBD: read the live terms (Aug 12 2026 text) and record the clause numbers; confirm that third-party-originated fields (lines, recruiting, polls) are excluded or covered.
2. nflverse: does the owner accept NFL-feed fields (lane C) for internal research under the CC BY 4.0 wrapper despite nflreadr's own "governed by their terms of use" notice? If not, nflverse unlocks ~0 slots.
3. FTN: obtain FTN's own statement of the CC BY-SA grant (ftnfantasy.com/data), and decide whether ShareAlike is acceptable for anything that might be shared.
4. ESPN / MLBAM / NHL: the indexed text is restrictive (automated access, non-bulk, non-commercial). A research use would need written permission, not a terms reading.
5. Kalshi: read the Developer Agreement PDF verbatim (kalshi-public-docs S3) for retention/analysis of market data by a member.
