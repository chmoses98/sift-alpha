"""Series-level resolution of the five families that had no truthful blueprint (NFL_MISC_UNCLASSIFIED, NBA UNMAPPED_SERIES,
CBB OTHER, NHL UNMAPPED_SERIES, MLB unknown). master_inventory.json is left untouched (stable ids, provenance); this overlay
says, for every constituent series, whether it maps to an existing market class, needs a new class (added), is a mapping error
(belongs to another family/sport), or is out of scope - and how strong the evidence is.
evidence level: RULES_TEXT = contract rules_primary text sampled from the archived snapshot; TITLE_ONLY = series/contract title only
(settlement text not seen - the spec is provisional and the missing evidence is named)."""
import json
from pathlib import Path

AUDIT = Path(__file__).resolve().parent.parent / "research" / "audit"
RT, TO = "RULES_TEXT", "TITLE_ONLY"


def _t(level, target, tickers, note=""):
    return [(t, "MAP", target, level, note) for t in tickers.split()]


RES = {
 "NBA/UNMAPPED_SERIES": _t(RT, "bb_futures_player", "KXNBAAWARDFIN KXNBACOTM KXNBADPOTM KXNBAEXEC KXNBAHUSTLE KXNBAPOTM KXNBAROTM KXNBASJC KXNBATEAMMATE", "season award / monthly award; voter-decided")
   + _t(RT, "bb_futures_player", "KXNBASTATAVG KXNBASTATLEADER KXNBAPLAYERHIGHSCORE KXNBAONE3PT", "season player stat threshold/leader/extreme over the regular season")
   + _t(RT, "bb_futures_team", "KXNBAFINALSOUTCOME KXNBAH2HWINS KXNBAPOSTASREC KXNBASEEDOU KXNBATEAMWINSTREAK KXNBAWINSTREAK KXNBAGAMEHIGHSCORE", "team/league season outcome or extreme")
   + _t(RT, "bb_news_event", "KXNBACITYEXPAND KXNBAEUROPEANNOUNCE KXNBAFRANCHISECOST KXNBAFRANCHISEOWNER KXNBATOJOINCBA", "off-court / business / transaction event")
   + [(t, "NEW_CLASS", "bb_player_escalator", RT, "scalar payout schedule on one player's game stat (not a binary strike)") for t in "KXNBAESCALATOR3PT KXNBAESCALATORPTS".split()],
 "CBB/OTHER": _t(RT, "bb_futures_team", "KXNCAAMBBIG12REGTOP KXNCAAMBBIGEASTREGTOP KXNCAAMBBIGTENREGTOP KXNCAAMBKENPOMTOP KXNCAAMBUNDEFEATED", "season outcome (KenPom top-25 depends on a paywalled rating)")
   + _t(RT, "bb_news_event", "KXNCAAMBNEXTCOACH", "coaching hire")
   + _t(RT, "bb_overtime", "KXNCAAMBOT", "single-game overtime occurs") + _t(RT, "bb_first_event", "KXNCAAMBRACE", "first team to 10 points"),
 "NHL/UNMAPPED_SERIES": _t(RT, "hk_futures", "KXNHLLINDSAY KXNHLPSEASONGOALS", "season award / season player goal threshold"),
 "NFL/NFL_MISC_UNCLASSIFIED": _t(TO, "fb_news_event", "KXATLCOACH KXNEWCOACHCHIBEARS KXNEWCOACHDAL KXNEWCOACHJAX KXNEWCOACHLV KXNEWCOACHNE KXNEWCOACHNO KXNEWCOACHNYJ KXNYGCOACH KXTENNCOACH", "head-coach hire")
   + _t(TO, "fb_news_event", "KXARODGRETIRE KXKELCERETIRE KXBRADY KXPHILIPRIVERSNFL", "retirement / comeback")
   + _t(TO, "fb_news_event", "KXNEXTEAMTYREEK KXNEXTTEAMTYREEK KXNEXTTEAMMCLAURIN KXNEXTTEAMMICAH KXNEXTTEAMNFL", "player next-team transaction (KXNEXTTEAMNFL alone had 290 open markets)")
   + _t(TO, "fb_news_event", "KXNFLCOMBINE KXNFLCOMBINE40 KXNFLLASTPICKPOS KXNFLTEAM1POS", "combine / draft event")
   + _t(TO, "fb_news_event", "KXFIRSTSUPERBOWLSONG KXRAINNOSB KXSWIFTATTEND KXSWIFTATTENDEVENT KXTUSHPUSH KXNFLHOFINDUCTEES", "Super Bowl / league novelty or policy event")
   + _t(TO, "fb_news_event", "KXNFLOWNERSTAKE KXNFLSELLOUT KXNFLSFPRACFIELD KXNFLSTADIUM KXNFLROLE KXNFLPROBOWL KXNFLPROBOWLWIN", "business / venue / Pro Bowl event: title is ambiguous, rules text needed")
   + _t(TO, "fb_futures_player", "KXESPYNFL KXWPMOTY KXLEADERPINT KXNFLLEADERPINT", "award / season stat leader")
   + _t(TO, "fb_futures_team", "KXAFC KXNFC KXRECORDNFLBEST KXRECORDNFLWORST", "conference champion / best-worst record")
   + _t(TO, "fb_availability", "KXSTARTCIN KXSTARTNYJ", "starting-QB designation for a named week")
   + [("KXMCMADDEN26", "OUT_OF_SCOPE", None, TO, "Madden video-game tournament, not an NFL outcome")],
 "MLB/unknown": [("KXEBASKETBALLGAME", "OUT_OF_SCOPE", None, TO, "eBasketball esports game (player handles in the title), not MLB"),
                 ("KXEFOOTBALLGAME", "OUT_OF_SCOPE", None, TO, "eFootball esports game, not MLB"),
                 ("KXMLSTEAMTOTAL", "REROUTE", "SOCCER/team_total", TO, "MLS contract mis-filed under MLB; same series is already in SOCCER/team_total (duplicate)"),
                 ("KXMLSTOTAL", "REROUTE", "SOCCER/total_goals", TO, "MLS contract mis-filed under MLB; already in SOCCER/total_goals (duplicate)"),
                 ("KXNHL3PSPREAD", "REROUTE", "NHL/period_spread", TO, "NHL third-period spread mis-filed under MLB; already in NHL/period_spread (duplicate)"),
                 ("KXMLSFIRSTGOAL", "REROUTE", "SOCCER/player_goalscorer", TO, "MLS first goalscorer: NOT present in the SOCCER inventory -> inventory omission, new family added"),
                 ("KXMLSGOAL", "REROUTE", "SOCCER/player_goalscorer", TO, "MLS player 1+ goals (anytime scorer): NOT present in the SOCCER inventory -> inventory omission")],
}
FAMILY_STATUS = {"NBA/UNMAPPED_SERIES": "SPECIFIED_BY_SERIES_SPLIT", "CBB/OTHER": "SPECIFIED_BY_SERIES_SPLIT", "NHL/UNMAPPED_SERIES": "SPECIFIED_BY_SERIES_SPLIT",
                 "NFL/NFL_MISC_UNCLASSIFIED": "SPECIFIED_BY_SERIES_SPLIT", "MLB/unknown": "MISMAPPED_REROUTED"}
# families the master inventory omitted, discovered through the mis-filed series (additive overlay; master_inventory.json untouched)
ADDED_FAMILIES = {"SOCCER/player_goalscorer": {"sport": "SOCCER", "native_family": "player_goalscorer", "kind": "player_scorer", "specs": ["sc_player"],
                  "series": ["KXMLSFIRSTGOAL", "KXMLSGOAL"], "markets_observed": 28, "as_of": "2026-10-28 (MLB discovery file, one slate)",
                  "note": "found under MLB/unknown; Kalshi soccer first-goalscorer / anytime-scorer contracts exist (MLS observed); other leagues not yet checked"}}


def build(inv):
    """inv: {sport: parsed inventory/<SPORT>.json}"""
    fams = {f["id"]: f for d in inv.values() for f in d["families"]}
    out = {"schema_version": "resolution-1.0", "note": "Overlay on master_inventory.json. TITLE_ONLY resolutions are provisional: settlement text still has to be sampled.",
           "families": {}, "added_families": ADDED_FAMILIES}
    for fid, rows in RES.items():
        have = {s["ticker"]: s for s in fams[fid]["series"]}
        got = {r[0] for r in rows}
        if got != set(have):
            raise SystemExit(f"{fid}: resolution drift; unresolved={sorted(set(have) - got)} stale={sorted(got - set(have))}")
        ser = []
        for t, act, tgt, lvl, note in rows:
            ser.append({"ticker": t, "title": have[t].get("title"), "markets_now": have[t].get("markets_now"), "action": act, "target": tgt, "evidence": lvl, "note": note})
        mapped = [s for s in ser if s["action"] in ("MAP", "NEW_CLASS")]
        out["families"][fid] = {"status": FAMILY_STATUS[fid], "series": ser,
                                "classes": sorted({s["target"] for s in mapped}),
                                "n_series": len(ser), "series_title_only": sum(s["evidence"] == TO for s in ser),
                                "missing_evidence": "rules_primary text for TITLE_ONLY series (open-set snapshots carry no titles or rules)" if any(s["evidence"] == TO for s in ser) else None}
    return out


if __name__ == "__main__":
    inv = {sp: json.loads((AUDIT / "inventory" / f"{sp}.json").read_text()) for sp in ("NFL", "NBA", "CBB", "NHL", "MLB")}
    (AUDIT / "resolutions" / "unresolved_families.json").write_text(json.dumps(build(inv), indent=1))
