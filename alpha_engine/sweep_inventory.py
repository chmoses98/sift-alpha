"""Turn exhaustive sweep results (kalshi_sweep, all four statuses per series) into validated family rows.

Classification is by series -> family map AND validated against the exchange's own sample title / settlement rules
(`expect` regex). A mismatch is reported as TITLE_MISMATCH instead of being trusted. Series with zero markets in every
status are 'EMPTY' (verified empty on the sweep date, not nonexistent forever). Usage: python -m alpha_engine.sweep_inventory"""
import json, re
from pathlib import Path

R = Path(__file__).resolve().parents[1] / "research" / "audit"
H = r"[A-Z][^:]*: \d+\+ "
MLB = {  # series: (family, expect-regex on title+rules)
 "KXMLBHRR": ("hitter_hits_runs_rbis", r"hits \+ runs \+ RBIs"), "KXMLBTB": ("hitter_total_bases", r"total bases"), "KXMLBHIT": ("hitter_hits", r": \d+\+ hits"),
 "KXMLBRBI": ("hitter_rbis", r"RBIs"), "KXMLBHR": ("hitter_home_runs", r"home runs"), "KXMLBSB": ("hitter_stolen_bases", r"stolen bases"),
 "KXMLBKS": ("pitcher_strikeouts", r"strikeouts"), "KXMLBHA": ("pitcher_hits_allowed", r"hits allowed"), "KXMLBERA": ("pitcher_earned_runs", r"earned runs"),
 "KXMLBWA": ("pitcher_walks_allowed", r"walks allowed"), "KXMLBOUTS": ("pitcher_outs", r"Outs Recorded"),
 "KXMLBINNINGWIN": ("inning_result", r"inning"), "KXMLBINNINGTOTAL": ("inning_total", r"inning"), "KXMLBF3": ("inning_result", r"first 3 innings"), "KXMLBF5": ("inning_result", r"first 5 innings"),
 "KXMLBF7": ("inning_result", r"first 7 innings"), "KXMLBF5TOTAL": ("first5_total", r"First 5 innings"), "KXMLBF5SPREAD": ("first5_spread", r"first 5 innings"),
 "KXMLBTEAMTOTAL": ("team_total", r"score over"), "KXMLBTOTAL": ("game_total", r"runs scored"), "KXMLBSPREAD": ("game_spread", r"wins by over"), "KXMLBGAME": ("game_result", r"wins"),
 "KXMLBEXTRAS": ("extra_innings", r"extra innings"), "KXMLBRFI": ("first_inning_runs", r"1st inning"), "KXMLBDELAY": ("game_delay", r"delayed"), "KXMLBMENTION": ("announcer_mentions", r"announcers"),
 "KXMLBWALKOFFS": ("season_specials", r"walk-offs"), "KXMLBSTAT": ("season_specials", r"pitch"), "KXMLBSTATCOUNT": ("season_specials", r"record at least"), "KXMLBFASTPITCH": ("season_specials", r"MPH"),
 "KXMLBTEAMSTAT": ("season_specials", r"most strikeouts"), "KXMLBPLAYOFFHRS": ("season_specials", r"home runs"), "KXMLBPLAYOFFHOST": ("season_specials", r"hosts"), "KXMLBSEASONGAMES": ("season_specials", r"games be played"),
 "KXMLBOPENINGDAY": ("season_specials", r"first regular season game"), "KXMLBSEASONHR": ("season_player_stat", r"home runs"), "KXMLBDEBUT": ("player_participation", r"play in a game"),
 "KXMLBSTART": ("player_participation", r"start for"), "KXMLBPITCH": ("player_participation", r"pitch in"),
 "KXNEXTTEAMMLB": ("transactions", r"next team"), "KXMLBNEXTTEAM": ("transactions", r"next team"), "KXCOACHOUTMLB": ("coaching", r"Managers"), "KXCOACHOUTMLBDATE": ("coaching", r"out before"),
 "KXMLBCBA": ("business_other", r"CBA"), "KXCITYMLBEXPAND": ("business_other", r"expansion"), "KXMLBTEAMSALE": ("business_other", r"sold"), "KXCONGRESSBASEBALL": ("non_baseball", r"Congressional"),
 "KXMLB": ("postseason_futures", r"Championship"), "KXMLBAL": ("postseason_futures", r"American"), "KXMLBNL": ("postseason_futures", r"National"), "KXMLBSEEDWIN": ("postseason_futures", r"Seed"),
 "KXMLBCHAMPDIVISION": ("postseason_futures", r"Division|West|East|Central"), "KXMLBCHAMPLEAGUE": ("postseason_futures", r"NL|AL"), "KXMLBWSOUTCOME": ("postseason_futures", r"beats"), "KXTEAMSINWS": ("postseason_futures", r"matchup"),
 "KXMLBALCSQUAL": ("postseason_futures", r"qualifies"), "KXMLBNLCSQUAL": ("postseason_futures", r"qualifies"), "KXMLBPLAYOFFS": ("postseason_futures", r"Playoff"), "KXMLBMATCHUP": ("postseason_futures", r"Matchup"),
 "KXMLBALEAST": ("division_winner", r"Division"), "KXMLBALCENT": ("division_winner", r"Division"), "KXMLBALWEST": ("division_winner", r"Division"), "KXMLBNLEAST": ("division_winner", r"Division"), "KXMLBNLCENT": ("division_winner", r"Division"), "KXMLBNLWEST": ("division_winner", r"Division"),
 "KXMLBSERIES": ("postseason_series", r"Series"), "KXMLBSERIESSCORE": ("postseason_series", r"Series"), "KXMLBSERIESSPREAD": ("postseason_series", r"Series"), "KXMLBSERIESGAMES": ("postseason_series", r"Series"), "KXMLBSERIESHR": ("postseason_series", r"home runs"),
 "KXMLBBESTRECORD": ("team_season_records", r"record|streak"), "KXMLBWORSTRECORD": ("team_season_records", r"record"), "KXMLBLSTREAK": ("team_season_records", r"streak"), "KXMLBWSTREAK": ("team_season_records", r"streak"), "KXMLB100LOSS": ("team_season_records", r"losses"),
 "KXLMBGAME": ("other_league_game_result", r"wins"), "KXMLBBGAME": ("UNRESOLVED_TITLE", r"."),
}
for s in ("KXMLBGG", "KXMLBSS", "KXMLBWSMVP", "KXMLBAWARDFIN", "KXMLBNLMVP", "KXMLBALMVP", "KXMLBNLHAARON", "KXMLBALHAARON", "KXMLBNLCY", "KXMLBALCY", "KXMLBALROTY", "KXMLBNLROTY", "KXMLBALRELOTY", "KXMLBNLRELOTY",
          "KXMLBNLMOTY", "KXMLBALMOTY", "KXMLBNLCPOTY", "KXMLBALCPOTY", "KXMLBEOTY", "KXMLBALCSMVP", "KXMLBNLCSMVP", "KXMLBAWARDCOMBO", "KXMLBTRIPLECROWN"):
    MLB[s] = ("awards", r"win|select|MVP|Award|Gold Glove|Silver Slugger|Cy Young|ROTY|Year|Triple Crown")
for s in ("KXLEADERMLB" + x for x in ("DOUBLES", "HITS", "RBI", "RUNS", "WINS", "WAR", "AVG", "ERA", "STEALS", "OPS", "TRIPLES", "HR", "KS")) :
    MLB[s] = ("season_leaders", r"lead Pro Baseball")
MLB["KXMLBLEADERPLAYOFF"] = ("season_leaders", r"lead")


def mlb_family(series):
    if series in MLB:
        return MLB[series]
    if series.startswith("KXMLBWINS-"):
        return ("team_season_wins", r"win at least \d+ games")
    return None


def build():
    out = {}
    d = json.loads((R / "sweep_results" / "mlb.json").read_text())
    fam = {}
    mismatch, unmapped, empty = [], [], []
    for r in d["series"]:
        s = r["s"]; n = {k: r[k]["markets"] for k in ("open", "unopened", "closed", "settled")}
        if sum(n.values()) == 0:
            empty.append(s); continue
        m = mlb_family(s); smp = r.get("sample") or {}
        text = (smp.get("title") or "") + " " + (smp.get("rules") or "")
        if not m:
            unmapped.append(s); continue
        f, rx = m
        ok = bool(re.search(rx, text, re.I))
        if not ok:
            mismatch.append({"series": s, "family": f, "title": smp.get("title")})
        e = fam.setdefault(f, {"series": [], "open": 0, "closed": 0, "settled": 0, "first_open": None, "last_open": None})
        e["series"].append({"ticker": s, "title": smp.get("title"), "markets": n, "events_settled": r["settled"].get("event_count"), "title_validated": ok,
                            "rules_sample": (smp.get("rules") or "")[:200]})
        for k in ("open", "closed", "settled"):
            e[k] += n[k]
            for ts, f2, fn in ((r[k].get("open_time_min"), "first_open", min), (r[k].get("open_time_max"), "last_open", max)):
                if ts:
                    e[f2] = ts if e[f2] is None else fn(e[f2], ts)
    out["MLB"] = {"requests_total": d["meta"]["requests_total"], "series_swept": len(d["series"]), "series_with_markets": len(d["series"]) - len(empty), "empty_series": sorted(empty),
                  "unmapped_with_markets": unmapped, "title_mismatch": mismatch, "families": fam}
    s = json.loads((R / "sweep_results" / "soccer.json").read_text())
    cls = {}
    for r in s["series"]:
        sm = r.get("sample") or {}; n = {k: r[k]["markets"] for k in ("open", "closed", "settled")}
        text = (sm.get("title") or "") + " " + (sm.get("rules") or "")
        if sum(n.values()) == 0:
            c = "EMPTY_NO_MARKETS_UNCONFIRMED"
        elif re.search(r"soccer|AFCON|Africa Cup|Asian Cup|AFC Champions", text, re.I):
            c = "SOCCER_CONFIRMED_BY_TITLE"
        else:
            c = "NOT_SOCCER_BY_TITLE"
        cls[r["s"]] = {"class": c, "markets": n, "title": sm.get("title"), "rules": (sm.get("rules") or "")[:200], "first_open": min([r[k]["open_time_min"] for k in ("open", "closed", "settled") if r[k].get("open_time_min")] or [None]) if sum(n.values()) else None,
                       "last_open": max([r[k]["open_time_max"] for k in ("open", "closed", "settled") if r[k].get("open_time_max")] or [None]) if sum(n.values()) else None}
    out["SOCCER"] = {"requests_total": s["meta"]["requests_total"], "classes": cls}
    (R / "sweep_results" / "validated_families.json").write_text(json.dumps({"schema_version": "audit-1.0", **out}, indent=1))
    return out


if __name__ == "__main__":
    o = build()
    m = o["MLB"]; c = {}
    for v in o["SOCCER"]["classes"].values(): c[v["class"]] = c.get(v["class"], 0) + 1
    print("MLB families", len(m["families"]), "series with markets", m["series_with_markets"], "empty", len(m["empty_series"]), "unmapped", m["unmapped_with_markets"], "mismatch", m["title_mismatch"])
    print("SOCCER", c)
