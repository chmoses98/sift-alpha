"""Phase 15 shared forecast-quality evaluation (research only; imports nothing from pricing, trading or settlement code).

Every sport workstream scores game- and period-level forecasts with these functions so the Predictive Confidence Matrix
compares like with like.

Forecast representation: for each game and segment (FG, 1H, 2H, Q1..Q4, P1..P3, F5, ...) a joint PMF over integer
(home, away) scores, or the two marginal PMFs plus a joint PMF of the margin. `ScorePMF` holds the joint grid and derives
every contract type Kalshi lists from it, so winner, spread, total and team-total probabilities are coherent by
construction.

Kalshi sign convention (verified from rules_primary): "<Team> wins by more than X" = P(team score - opponent score > X);
strikes are half-points, so there are no pushes; ties in a segment settle NO for both "wins" contracts and YES on the
tie contract (KXMLBF5, KXNCAAF1Q ... '..tie..'); totals/team totals are "more than X" (strike_type greater).
Full-game totals and margins include overtime / extra innings unless the series says otherwise (KXNHL1P.. are periods).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

EPS = 1e-6


# ------------------------------------------------------------------------------------------------ distributions
@dataclass
class ScorePMF:
    """Joint PMF p[h, a] over home score h = 0..H-1 and away score a = 0..A-1."""
    p: np.ndarray

    def __post_init__(self):
        self.p = np.clip(np.asarray(self.p, float), 0, None)
        self.p /= self.p.sum()
        H, A = self.p.shape
        self._h = np.arange(H)[:, None]
        self._a = np.arange(A)[None, :]

    def p_margin_gt(self, x: float) -> float:
        """P(home - away > x)."""
        return float(self.p[(self._h - self._a) > x].sum())

    def p_total_gt(self, x: float) -> float:
        return float(self.p[(self._h + self._a) > x].sum())

    def p_home_gt(self, x: float) -> float:
        return float(self.p.sum(axis=1)[np.arange(self.p.shape[0]) > x].sum())

    def p_away_gt(self, x: float) -> float:
        return float(self.p.sum(axis=0)[np.arange(self.p.shape[1]) > x].sum())

    def p_tie(self) -> float:
        return float(self.p[(self._h - self._a) == 0].sum())

    def margin_pmf(self):
        m = (self._h - self._a).ravel()
        v = self.p.ravel()
        lo = int(m.min())
        out = np.bincount(m - lo, weights=v)
        return lo, out

    def total_pmf(self):
        return 0, np.bincount((self._h + self._a).ravel(), weights=self.p.ravel())


def pmf_from_normal_pair(mu_h: float, mu_a: float, sd_h: float, sd_a: float, rho: float, n: int = 220) -> ScorePMF:
    """Discretised bivariate normal for high-scoring sports (basketball, football): P(h, a) on integer cells."""
    from scipy.stats import norm
    h = np.arange(n)
    # conditional construction: a | h ~ N(mu_a + rho sd_a/sd_h (h - mu_h), sd_a sqrt(1 - rho^2))
    ph = norm.cdf(h + 0.5, mu_h, sd_h) - norm.cdf(h - 0.5, mu_h, sd_h)
    cm = mu_a + rho * sd_a / sd_h * (h - mu_h)
    cs = sd_a * np.sqrt(max(1 - rho ** 2, 1e-6))
    pa = norm.cdf(h[None, :] + 0.5, cm[:, None], cs) - norm.cdf(h[None, :] - 0.5, cm[:, None], cs)
    return ScorePMF(ph[:, None] * pa)


def pmf_from_margin_total(mu_m: float, sd_m: float, mu_t: float, sd_t: float, rho_mt: float = 0.0, n: int = 220) -> ScorePMF:
    """Same family parameterised by margin and total (home = (T + M)/2)."""
    sd_h2 = 0.25 * (sd_t ** 2 + sd_m ** 2 + 2 * rho_mt * sd_t * sd_m)
    sd_a2 = 0.25 * (sd_t ** 2 + sd_m ** 2 - 2 * rho_mt * sd_t * sd_m)
    cov = 0.25 * (sd_t ** 2 - sd_m ** 2)
    sh, sa = np.sqrt(sd_h2), np.sqrt(sd_a2)
    return pmf_from_normal_pair((mu_t + mu_m) / 2, (mu_t - mu_m) / 2, sh, sa, float(np.clip(cov / (sh * sa), -0.95, 0.95)), n)


def pmf_from_counts(lam_h: float, lam_a: float, disp: float | None = None, n: int = 25, tie_inflation: float = 0.0) -> ScorePMF:
    """Independent Poisson (or negative binomial with size `disp`) scores for low-scoring sports, optional tie inflation
    (multiplies the diagonal by 1 + tie_inflation, renormalised)."""
    from scipy.stats import nbinom, poisson
    k = np.arange(n)
    if disp is None:
        ph, pa = poisson.pmf(k, lam_h), poisson.pmf(k, lam_a)
    else:
        ph = nbinom.pmf(k, disp, disp / (disp + lam_h))
        pa = nbinom.pmf(k, disp, disp / (disp + lam_a))
    p = ph[:, None] * pa[None, :]
    if tie_inflation:
        p[np.diag_indices(n)] *= 1 + tie_inflation
    return ScorePMF(p)


# ------------------------------------------------------------------------------------------------ scores
def brier(p, y):
    p, y = np.asarray(p, float), np.asarray(y, float)
    return (p - y) ** 2


def logloss(p, y):
    p, y = np.clip(np.asarray(p, float), EPS, 1 - EPS), np.asarray(y, float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def crps_pmf(lo: int, pmf: np.ndarray, y: float) -> float:
    """CRPS of an integer PMF starting at `lo` against outcome y (sum over integer grid of (F - 1{y<=k})^2)."""
    k = lo + np.arange(len(pmf))
    F = np.cumsum(pmf) / pmf.sum()
    return float(((F - (y <= k)) ** 2).sum())


def crps_normal(mu, sd, y):
    from scipy.stats import norm
    mu, sd, y = (np.asarray(v, float) for v in (mu, sd, y))
    z = (y - mu) / sd
    return sd * (z * (2 * norm.cdf(z) - 1) + 2 * norm.pdf(z) - 1 / np.sqrt(np.pi))


def calibration_slope(p, y) -> float:
    """Slope of logit(y) on logit(p) (1 = calibrated; < 1 over-confident; > 1 under-confident)."""
    p = np.clip(np.asarray(p, float), 1e-4, 1 - 1e-4)
    x = np.log(p / (1 - p))
    y = np.asarray(y, float)
    X = np.column_stack([np.ones_like(x), x])
    b = np.zeros(2)
    for _ in range(30):
        q = 1 / (1 + np.exp(-X @ b))
        H = X.T @ (X * (q * (1 - q))[:, None]) + 1e-9 * np.eye(2)
        b += np.linalg.solve(H, X.T @ (y - q))
    return float(b[1])


def reliability(p, y, bands=(0, .1, .2, .3, .4, .5, .6, .7, .8, .9, 1.0001)):
    """Observed frequency by forecast band: list of (lo, hi, n, mean_p, freq)."""
    p, y = np.asarray(p, float), np.asarray(y, float)
    out = []
    for lo, hi in zip(bands[:-1], bands[1:]):
        m = (p >= lo) & (p < hi)
        if m.sum():
            out.append([lo, round(hi, 2), int(m.sum()), round(float(p[m].mean()), 4), round(float(y[m].mean()), 4)])
    return out


def cluster_ci(values, clusters, n_boot: int = 2000, seed: int = 0):
    """Mean and 95% percentile CI resampling whole clusters (game or date)."""
    v = np.asarray(values, float)
    c = np.asarray(clusters)
    u, inv = np.unique(c, return_inverse=True)
    s = np.bincount(inv, weights=v)
    n = np.bincount(inv)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(u), (n_boot, len(u)))
    boots = s[idx].sum(axis=1) / n[idx].sum(axis=1)
    return [round(float(v.mean()), 5), [round(float(np.percentile(boots, 2.5)), 5), round(float(np.percentile(boots, 97.5)), 5)]]


def paired_delta(new, old, clusters, **kw):
    """Mean of (new - old) loss with a cluster bootstrap CI. Negative = new is better for a loss."""
    return cluster_ci(np.asarray(new, float) - np.asarray(old, float), clusters, **kw)


def holm(pvals: dict[str, float]) -> dict[str, float]:
    """Holm-adjusted p-values across a family of comparisons (multiple-testing guard)."""
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m, run, out = len(items), 0.0, {}
    for i, (k, p) in enumerate(items):
        run = max(run, min(1.0, (m - i) * p))
        out[k] = run
    return out


def boot_p(values, clusters, n_boot: int = 4000, seed: int = 1) -> float:
    """Two-sided cluster-bootstrap p-value for mean(values) == 0."""
    v = np.asarray(values, float)
    c = np.asarray(clusters)
    u, inv = np.unique(c, return_inverse=True)
    s, n = np.bincount(inv, weights=v), np.bincount(inv)
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(u), (n_boot, len(u)))
    b = s[idx].sum(axis=1) / n[idx].sum(axis=1)
    b0 = b - b.mean()
    return float(min(1.0, 2 * min((b0 >= abs(v.mean())).mean(), (b0 <= -abs(v.mean())).mean()) + 1 / n_boot))


# ------------------------------------------------------------------------------------------------ ladder scoring
def ladder_rows(pmfs: list[ScorePMF], outcomes: list[tuple[int, int]], kind: str, strikes, side: str = "home"):
    """Per (game, strike) probability and outcome for one contract family.

    kind: 'spread' (side wins by more than k; k may be negative for alt spreads on the other side), 'total', 'team_total',
    'winner' (strikes ignored; P(side strictly wins)), 'tie'.
    """
    P, Y, K, G = [], [], [], []
    for g, (pm, (h, a)) in enumerate(zip(pmfs, outcomes)):
        sgn = 1 if side == "home" else -1
        if kind in ("winner", "tie"):
            ks = [0.0]
        else:
            ks = strikes
        for k in ks:
            if kind == "spread":     # P(side score - other score > k); away: P(home - away < -k)
                p = pm.p_margin_gt(k) if side == "home" else float(pm.p[(pm._h - pm._a) < -k].sum())
                y = sgn * (h - a) > k
            elif kind == "total":
                p, y = pm.p_total_gt(k), (h + a) > k
            elif kind == "team_total":
                p = pm.p_home_gt(k) if side == "home" else pm.p_away_gt(k)
                y = (h if side == "home" else a) > k
            elif kind == "winner":
                p = pm.p_margin_gt(0.5) if side == "home" else float(pm.p[(pm._h - pm._a) < -0.5].sum())
                y = sgn * (h - a) > 0
            else:
                p, y = pm.p_tie(), h == a
            P.append(p); Y.append(float(y)); K.append(k); G.append(g)
    return np.array(P), np.array(Y), np.array(K), np.array(G)


def strike_window(center: float, half_width: float, step: float = 1.0):
    """Half-point strikes around a centre (e.g. model mean) - the region where Kalshi lists most volume."""
    lo = np.floor(center - half_width) + 0.5
    return list(np.arange(lo, center + half_width + 1e-9, step))


# ------------------------------------------------------------------------------------------------ confidence matrix row
def matrix_row(sport: str, family: str, segment: str, model: str, baseline: str, n_games: int, metrics: dict, verdict: str,
               drivers: list[str], notes: str = "") -> dict:
    """One Predictive Confidence Matrix row.

    verdict: RELIABLE (calibrated, beats baseline with CI excluding 0 or matches a strong baseline, slope 0.85-1.15),
             USABLE (calibrated but no demonstrated gain, or gain with mild miscalibration), ABSTAIN (miscalibrated, unstable
             across seasons, or too little data).
    """
    return {"sport": sport, "family": family, "segment": segment, "model": model, "baseline": baseline, "n_games": int(n_games),
            "metrics": metrics, "verdict": verdict, "drivers": drivers, "notes": notes}


def write_rows(rows: list[dict], path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(rows, indent=1, default=float))
