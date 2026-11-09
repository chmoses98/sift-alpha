# Proposed update for operating tracker #175 (TEXT ONLY - not posted)

Phase 5 (RESEARCH_ONLY, $0). Free-source mappings converted into replay- and independently-verified inputs, no predictive work.
- Verified coverage: FULL 54 (unchanged), PARTIAL 93 -> 119 (+26), PROXY 19 (unchanged). verified_computable 222 -> 248 of 1,649. Nothing was certified FULL.
- Gains by sport: NFL +15 (injuries_pit, snaps, 13 pbp), MLB +8 (pitch events 2021-2024), TENNIS +3 (retire/walkover/layoff). CFB/CBB/NBA/NHL/SOCCER +0 (SportsDataverse on HOLD, CFBD needs owner key, MoneyPuck terms unverified, StatsBomb open data is not a league history).
- Gates now fail closed: any missing or failed PIT/leakage/vacuity test = REPLAY_FAILED; promotion also needs a blind re-implementation that matches every column. Blind verifiers caught two real defects (NFL first-drive inconsistency, tennis ATP/WTA id collision); both fixed and re-checked. Agent verification only, not human expert verification.
- Rights: SportsDataverse HOLD (MIT vs CC BY conflict, upstream ESPN/NBA/NCAA/CFBD terms unverified). Open-Meteo and CFBD/CBBD: hosts blocked here, NEEDS_OWNER_ACTION (free non-commercial CC BY / owner-registered key). dailyfaceoff_raw stays disabled. MLB Stats API terms unverified: pitch data kept in scratch.
- Blockers: owner decisions on SportsDataverse upstream rights, Open-Meteo hosts, a CFBD key, MoneyPuck and MLB API terms; prospective capture for the 494 vintage-dependent inputs.
