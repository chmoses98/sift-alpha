"""Soccer league builders from the OpenFootball public-domain (CC0 1.0) fixtures-and-results files (RESEARCH_ONLY): Dixon-Coles low-score dependence by league.

Raw data: git clones of github.com/openfootball/{england,deutschland,espana,italy} (Football.TXT files; CC0 1.0 Universal, so no source-use restriction). England tiers 1-5 from 2000-01, the other three countries 2010-11 onward
(whatever the repositories hold). Output table ``team`` keyed (game_id, team): every value for a match uses only league matches on STRICTLY EARLIER DATES. No odds, lines or prices exist in the source.
"""
from __future__ import annotations

import math
import re
from pathlib import Path

import numpy as np
import pandas as pd

from .core import FeatureSpec

S = "SOCCER"
REPOS = {"england": ["1-premierleague.txt", "2-championship.txt", "3-league1.txt", "4-league2.txt", "5-nationalleague.txt"], "deutschland": ["1-bundesliga.txt", "2-bundesliga2.txt"],
         "espana": ["1-liga.txt", "2-liga2.txt"], "italy": ["1-seriea.txt", "2-serieb.txt"]}
MON = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
DATE_RE = re.compile(r"^\s*(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun)\s+([A-Z][a-z]{2})\s+(\d{1,2})(?:\s+(\d{4}))?\s*$")
MATCH_RE = re.compile(r"^\s+(?:\d{1,2}[:.]\d{2}\s+)?(\S.*?)\s+(\d+)-(\d+)(?:\s+\((\d+)-(\d+)\))?\s+(?!\()(\S.*?)\s*$")
MATCH_V_RE = re.compile(r"^\s+(?:\d{1,2}[:.]\d{2}\s+)?(\S.*?)\s+v\s+(\S.*?)\s+(\d+)-(\d+)(?:\s+\((\d+)-(\d+)\))?\s*$")
WINDOW_DAYS, HALF_LIFE_DAYS, SHRINK_K, MIN_MATCHES = 1095, 365.0, 10.0, 200
RHOS = np.round(np.arange(-300, 301) / 1000.0, 3)          # grid -0.300 ... 0.300 step 0.001
CONTENT = ["hg", "ag"]


def load_raw(root) -> dict:
    root = Path(root); rows = []
    for repo, files in REPOS.items():
        for sd in sorted(p for p in (root / repo).iterdir() if re.fullmatch(r"\d{4}-\d{2}", p.name)):
            y0 = int(sd.name[:4])
            for fn in files:
                f = sd / fn
                if not f.exists(): continue
                cur = None
                for line in f.read_text(encoding="utf-8").splitlines():
                    m = DATE_RE.match(line)
                    if m:
                        mon = MON[m.group(1)]; cur = pd.Timestamp(year=int(m.group(3)) if m.group(3) else (y0 if mon >= 7 else y0 + 1), month=mon, day=int(m.group(2))); continue
                    mv = MATCH_V_RE.match(line)
                    if mv and cur is not None:
                        rows.append((f"{repo}/{fn.split('-')[0]}", sd.name, cur, mv.group(1).strip(), mv.group(2).strip(), int(mv.group(3)), int(mv.group(4)))); continue
                    m = MATCH_RE.match(line)
                    if m and cur is not None:
                        rows.append((f"{repo}/{fn.split('-')[0]}", sd.name, cur, m.group(1).strip(), m.group(6).strip(), int(m.group(2)), int(m.group(3))))
    d = pd.DataFrame(rows, columns=["league", "season", "date", "home", "away", "hg", "ag"])
    d = d.drop_duplicates(["league", "season", "date", "home", "away"]).reset_index(drop=True)
    d["game_id"] = np.arange(len(d)); d["game_date"] = d.date
    return {"matches": d[["game_id", "league", "season", "game_date", "home", "away", "hg", "ag"]]}


def _fit(tr: pd.DataFrame, d: pd.Timestamp) -> dict | None:
    w = 0.5 ** ((d - tr.game_date).dt.days.to_numpy() / HALF_LIFE_DAYS); sw = w.sum()
    if len(tr) < MIN_MATCHES: return None
    hbar = (w * tr.hg).sum() / sw; abar = (w * tr.ag).sum() / sw; g = (hbar + abar) / 2
    codes, uniq = pd.factorize(pd.concat([tr.home, tr.away], ignore_index=True)); n_m = len(tr); ch, ca = codes[:n_m], codes[n_m:]; K = len(uniq)
    hg, ag = tr.hg.to_numpy(float), tr.ag.to_numpy(float)
    n = np.bincount(ch, w, K) + np.bincount(ca, w, K)
    gf = np.bincount(ch, w * hg, K) + np.bincount(ca, w * ag, K); ga = np.bincount(ch, w * ag, K) + np.bincount(ca, w * hg, K)
    att = ((gf + SHRINK_K * g) / (n + SHRINK_K)) / g; dfn = ((ga + SHRINK_K * g) / (n + SHRINK_K)) / g
    lam = hbar * att[ch] * dfn[ca]; mu = abar * att[ca] * dfn[ch]
    x, y = tr.hg.to_numpy(), tr.ag.to_numpy()
    low = (x <= 1) & (y <= 1)
    def tau(r):
        t = np.ones((len(r), len(x)))
        t = np.where(((x == 0) & (y == 0))[None, :], 1 - lam[None, :] * mu[None, :] * r[:, None], t)
        t = np.where(((x == 0) & (y == 1))[None, :], 1 + lam[None, :] * r[:, None], t)
        t = np.where(((x == 1) & (y == 0))[None, :], 1 + mu[None, :] * r[:, None], t)
        t = np.where(((x == 1) & (y == 1))[None, :], 1 - r[:, None], t)
        return t
    T = tau(RHOS)
    with np.errstate(divide="ignore", invalid="ignore"):
        ll = np.where(T > 0, np.log(np.where(T > 0, T, 1.0)), -np.inf)
    ll = (ll * w[None, :]).sum(axis=1); rho = float(RHOS[int(np.argmax(ll))])
    out = {"rho": rho}
    for name, (a, b) in (("00", (0, 0)), ("10", (1, 0)), ("01", (0, 1)), ("11", (1, 1))):
        fam = {"00": 1 - lam * mu * rho, "10": 1 + mu * rho, "01": 1 + lam * rho, "11": 1 - rho * np.ones_like(lam)}[name]
        p = fam * np.exp(-lam) * lam ** a / math.factorial(a) * np.exp(-mu) * mu ** b / math.factorial(b)
        out[f"gap_{name}"] = float((w * ((x == a) & (y == b))).sum() / sw - (w * p).sum() / sw)
    return out


def compute(raw: dict) -> dict:
    m = raw["matches"].sort_values(["game_date", "game_id"], kind="mergesort").reset_index(drop=True); parts = []
    for lg, g in m.groupby("league", sort=True):
        dd = g.game_date.to_numpy("datetime64[D]"); vals = {}
        for d in sorted(g.game_date.unique()):
            lo = np.searchsorted(dd, np.datetime64(d, "D") - np.timedelta64(WINDOW_DAYS, "D"), side="left"); hi = np.searchsorted(dd, np.datetime64(d, "D"), side="left")
            tr = g.iloc[lo:hi]; vals[d] = _fit(tr, d) if len(tr) else None
        for side in ("home", "away"):
            x = g[["game_id", side, "game_date", "season"]].rename(columns={side: "team", "game_date": "date"}); x["season"] = x.season.str[:4].astype(int)   # season start year
            f = [vals[d] for d in x.date]
            for k, c in (("rho", "dc_rho_pre"), ("gap_00", "dc_gap_00_pre"), ("gap_10", "dc_gap_10_pre"), ("gap_01", "dc_gap_01_pre"), ("gap_11", "dc_gap_11_pre")):
                x[c] = [v[k] if v else np.nan for v in f]
            parts.append(x)
    t = pd.concat(parts, ignore_index=True).sort_values(["date", "game_id", "team"], kind="mergesort").reset_index(drop=True)
    return {"team": t}


def specs() -> list[FeatureSpec]:
    return [FeatureSpec(S, "soc.dixon_coles_low_score", "team", ["dc_rho_pre", "dc_gap_00_pre", "dc_gap_10_pre", "dc_gap_01_pre", "dc_gap_11_pre"], "PARTIAL",
                        "per league and match date: Dixon-Coles dependence rho by profile likelihood over a grid (-0.3..0.3, step 0.001) with exponential time decay (half-life 365 days) on the league's matches of the previous 1095 days (>= 200 matches), "
                        "team attack/defence strengths from shrunk (k = 10) decayed goal rates and league home/away means (non-iterative); plus decayed empirical minus fitted frequencies of 0-0, 1-0, 0-1, 1-1",
                        ["rho by maximum likelihood with exponential time decay", "per league on a 3-season window", "empirical vs fitted frequencies for 0-0, 1-0, 0-1, 1-1"],
                        ["joint maximum-likelihood strengths (strengths here are non-iterative estimates)", "conditioning of the frequency check on lambda tertiles", "bivariate-Poisson alternative"], ["openfootball_league_results"], "pregame_rolling")]
