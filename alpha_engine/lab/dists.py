"""Predictive distributions and proper scoring for integer outcomes.  A model produces (mean, dispersion) per observation; the distribution turns that into fair
probabilities for ANY threshold, and the log score of the realised integer outcome is the yardstick (no prices involved)."""
from __future__ import annotations
import numpy as np
from scipy import stats as sps
from scipy.special import ndtr

EPS = 1e-9


def _cdf(kind, x, mu, disp):
    if kind == "normal":
        return ndtr((x - mu) / disp)
    if kind == "t5":
        return sps.t.cdf((x - mu) / disp, df=5)
    if kind == "nbinom":                      # disp = r (size); var = mu + mu^2 / r ; x integer-valued (cdf at floor)
        mu = np.maximum(mu, 1e-3)
        return sps.nbinom.cdf(np.floor(x), disp, disp / (disp + mu))
    if kind == "poisson":
        return sps.poisson.cdf(np.floor(x), np.maximum(mu, 1e-3))
    raise ValueError(kind)


def prob_gt(kind, mu, disp, floor):
    """P(Y > floor).  For integer Y and a half-integer floor (Kalshi strikes are x.5) this is P(Y >= floor + 0.5) exactly; for the normal/t families the
    continuous cdf is evaluated AT the floor (integer outcomes sit at +/- 0.5 of it, so the half-integer strike is the natural continuity boundary)."""
    return 1.0 - _cdf(kind, floor, mu, disp)


def int_logscore(kind, y, mu, disp):
    """Log probability mass of the realised integer outcome y (higher is better)."""
    y = np.asarray(y, float)
    if kind in ("normal", "t5"):
        p = _cdf(kind, y + 0.5, mu, disp) - _cdf(kind, y - 0.5, mu, disp)
    elif kind == "nbinom":
        m = np.maximum(mu, 1e-3)
        p = sps.nbinom.pmf(y, disp, disp / (disp + m))
    else:
        p = sps.poisson.pmf(y, np.maximum(mu, 1e-3))
    return np.log(np.maximum(p, EPS))


def nb_size(mu_train, resid_sq_mean):
    """Method-of-moments NB size r from the training mean and mean squared residual: var = mu + mu^2/r  =>  r = mu^2 / (var - mu); capped to stay finite."""
    mu_bar = float(np.mean(mu_train))
    over = max(float(resid_sq_mean) - mu_bar, 1e-6)
    return float(np.clip(mu_bar ** 2 / over, 0.2, 500.0))
