"""Resolve soccer's 'ambiguous' Kalshi series from ticker grammar (no network).

The soccer repo's discovery recorded 134 series with a bare 'Football' tag it did not sweep. Without exchange titles
the strongest offline evidence is the soccer family-token grammar (GAME/TOTAL/SPREAD/BTTS/TEAMTOTAL/ADVANCE/SCORE/FTTS/
1H*/MOV) on a competition body that has at least one sibling matching it. Output classes:
  SOCCER_BY_GRAMMAR   - soccer competition body + >=3 soccer family tokens among siblings (title unconfirmed)
  SOCCER_BY_NAME      - single series with an explicit soccer-league token (EPL...) 
  NOT_SOCCER_BY_NAME  - other sports/coach/novelty tokens (CFL, UFL, AFL, coach, retire, MVP ...)
  UNRESOLVED          - needs an exchange title/rules fetch (see sweep queue)"""
import json, re, sys

TOKENS = ("1HBTTS", "1HSPREAD", "1HTOTAL", "ADVANCE", "TEAMTOTAL", "SPREAD", "TOTAL", "BTTS", "SCORE", "FTTS", "GAME", "MOV", "MOF", "1H")
NOT = re.compile(r"COACH|RETIRE|MVP|NEXTTEAM|NEXTEAM|NEWCOACH|CFL|UFL|AFL|BABYNAME|RECORDNFL|START[A-Z]{2,}|DRAFTPICK|STADIUM|RELOCATION|GREYCUP|RANKLIST|SUPERBOWL|COLLEGEGAMEDAY|REALIGNMENT|ATTENDANCE|LEADERPINT|WPMOTY|DONATE|JOINCONF|COORD|PAVIA|PHILIPRIVERS|NEXTNFL|1STHOMEGAME|1HOMEGAME|HOMEGAME")
SOCCER_NAMES = re.compile(r"^KXEPL")


def resolve(tickers):
    out = {}
    bodies = {}
    for t in tickers:
        body = next((t[:-len(k)] for k in TOKENS if t.endswith(k) and len(t) > len(k) + 3), None)
        if body: bodies.setdefault(body, []).append(t)
    for t in tickers:
        if SOCCER_NAMES.match(t):
            out[t] = ("SOCCER_BY_NAME", "EPL token")
        elif NOT.search(t):
            out[t] = ("NOT_SOCCER_BY_NAME", NOT.search(t).group(0))
        else:
            body = next((b for b, ts in bodies.items() if t in ts), None)
            if body and len(bodies[body]) >= 3:
                out[t] = ("SOCCER_BY_GRAMMAR", f"body {body} with {len(bodies[body])} family-token siblings")
            elif t in bodies or any(t == b for b in bodies):
                out[t] = ("SOCCER_BY_GRAMMAR", "bare competition body of a soccer-grammar group")
            else:
                out[t] = ("UNRESOLVED", "no grammar or name evidence")
    return out


if __name__ == "__main__":
    idx = json.load(open(sys.argv[1]))
    tk = idx["counters"]["series_ambiguous_unswept_tickers"]
    res = resolve(tk)
    summary = {c: sorted(t for t, (cc, _) in res.items() if cc == c) for c in ("SOCCER_BY_GRAMMAR", "SOCCER_BY_NAME", "NOT_SOCCER_BY_NAME", "UNRESOLVED")}
    json.dump({"schema_version": "audit-1.0", "source": {"repo": "chmoses98/soccer-edge-finder", "path": "data/catalog/latest_index.json", "run_id": idx["counters"]["run_id"]},
               "total": len(tk), "counts": {k: len(v) for k, v in summary.items()}, "classes": summary,
               "reasons": {t: r for t, (_, r) in res.items()}, "note": "ticker-grammar evidence only; exchange titles/rules not fetched (network unavailable). UNRESOLVED and SOCCER_BY_* go to the sweep queue for confirmation."},
              open(sys.argv[2], "w"), indent=1)
    print({k: len(v) for k, v in summary.items()})
