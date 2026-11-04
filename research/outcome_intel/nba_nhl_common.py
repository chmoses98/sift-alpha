"""Shared helpers for the NBA / NHL market-first evidence audit (RESEARCH_ONLY; never trades, never touches execution code).

Everything here is sport-agnostic: Kalshi board replay (checkpoint + chained deltas), time-valid quote lookup, horizon windows,
selection of one prediction per (contract, horizon), cell evaluation through ``incremental.py`` (chronological holdout,
game-cluster bootstrap, Holm over every cell tried, negative + positive control).
"""
from __future__ import annotations
import bisect, glob, gzip, hashlib, json, math, os, re, sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import numpy as np
import incremental as I

# ----------------------------------------------------------------------------- basics
def sha256_file(p, buf=1 << 20):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(buf), b""):
            h.update(b)
    return h.hexdigest()


def ts(s):
    """ISO8601 string -> epoch seconds (UTC). None/'' -> None."""
    if not s:
        return None
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


def iso(t):
    return None if t is None else datetime.fromtimestamp(t, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_jsonl_gz(pattern):
    for f in sorted(glob.glob(pattern)):
        with gzip.open(f, "rt") as fh:
            for line in fh:
                if line.strip():
                    yield f, json.loads(line)


def file_digests(root, patterns):
    """sha256 over every file matched (used as 'sha256 of input files'); returns {relpath: sha} and a roll-up digest."""
    out = {}
    for pat in patterns:
        for f in sorted(glob.glob(os.path.join(root, pat), recursive=True)):
            if os.path.isfile(f):
                out[os.path.relpath(f, root)] = sha256_file(f)
    roll = hashlib.sha256("\n".join(f"{k} {v}" for k, v in sorted(out.items())).encode()).hexdigest()
    return out, roll


_SNAP_TS = re.compile(r"_(\d{8}T\d{6}Z)_")


def snapshot_ts_from_path(s):
    """Timestamp embedded in an archive file name (kalshi_markets_20261012T120222Z_<run>.jsonl.gz) -> epoch or None."""
    m = _SNAP_TS.findall(str(s))
    return max(datetime.strptime(x, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc).timestamp() for x in m) if m else None


# ----------------------------------------------------------------------------- horizons (fixed before looking at outcomes)
# (label, target hours before scheduled start, lo, hi). One prediction per (contract, horizon): the one closest to the target time.
HORIZONS = (("T_24H", 24.0, 20.0, 28.0), ("T_6H", 6.0, 4.5, 7.5), ("T_1H", 1.0, 0.5, 1.5), ("CLOSING", 0.15, 0.0, 0.5))


def horizon_of(hours_before, horizons=HORIZONS):
    for lab, tgt, lo, hi in horizons:
        if lo <= hours_before < hi:
            return lab, tgt
    return None, None


def select_per_horizon(preds, horizons=HORIZONS):
    """preds: iterable of dict(ticker, t, start, ...). Returns {(ticker, horizon): pred} choosing, per (ticker, horizon), the prediction whose
    hours-to-start is closest to the horizon target (ties -> earlier). Pure function of pregame facts (no outcome used)."""
    best = {}
    for p in preds:
        hb = (p["start"] - p["t"]) / 3600.0
        if hb <= 0:
            continue
        lab, tgt = horizon_of(hb, horizons)
        if lab is None:
            continue
        k = (p["ticker"], lab)
        d = abs(hb - tgt)
        if k not in best or (d, p["t"]) < (best[k][0], best[k][1]["t"]):
            best[k] = (d, p)
    return {k: v[1] for k, v in best.items()}


# ----------------------------------------------------------------------------- Kalshi board replay
TRACK = ("yes_bid_dollars", "yes_ask_dollars", "no_bid_dollars", "no_ask_dollars", "last_price_dollars", "yes_bid_size_fp", "yes_ask_size_fp",
         "volume_fp", "open_interest_fp", "status", "floor_strike", "cap_strike", "occurrence_datetime", "result")


def _slim(rec):
    return {k: rec[k] for k in TRACK if k in rec}


def _num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def quote(slim):
    """-> dict yes_bid, yes_ask (probabilities), sizes, two_sided flag; None when no usable quote."""
    if not slim:
        return None
    yb, ya = _num(slim.get("yes_bid_dollars")), _num(slim.get("yes_ask_dollars"))
    nb, na = _num(slim.get("no_bid_dollars")), _num(slim.get("no_ask_dollars"))
    # use the yes book; derive the missing side from the no book (yes_bid = 1 - no_ask, yes_ask = 1 - no_bid)
    if (yb is None or yb <= 0) and na is not None and na > 0:
        yb = 1 - na
    if (ya is None or ya <= 0) and nb is not None and nb > 0:
        ya = 1 - nb
    two = yb is not None and ya is not None and yb > 0 and ya > 0 and ya >= yb
    return dict(yes_bid=yb, yes_ask=ya, two_sided=bool(two), spread=(ya - yb) if two else None, mid=((ya + yb) / 2) if two else None,
                bid_size=_num(slim.get("yes_bid_size_fp")), ask_size=_num(slim.get("yes_ask_size_fp")), last=_num(slim.get("last_price_dollars")),
                volume=_num(slim.get("volume_fp")), status=slim.get("status"), result=slim.get("result"))


def list_boards(root):
    """[(captured_epoch, checkpoint_path, [delta_paths sorted by seq])] in time order; deltas grouped by their base_path."""
    cps = sorted(glob.glob(os.path.join(root, "kalshi/markets/dt=*/*.jsonl.gz")), key=lambda p: os.path.basename(p))
    dl = {}
    for f in sorted(glob.glob(os.path.join(root, "kalshi/markets_delta/dt=*/*.json.gz"))):
        with gzip.open(f, "rt") as fh:
            d = json.load(fh)
        dl.setdefault(d["base_path"], []).append((d["seq"], d["captured_at_utc"], f))
    out = []
    for cp in cps:
        rel = os.path.relpath(cp, root)
        out.append((rel, cp, [x[2] for x in sorted(dl.get(rel, []))]))
    return out


def replay(root):
    """Generator over every board in time order: (t, kind, state, info, old). ``state`` is the live dict ticker -> slim record (mutated in place,
    do not retain); for deltas ``old`` maps each touched ticker to its previous slim record (None if absent). Checkpoint = full board; delta = added/changed/
    cleared/removed relative to the previous board of the same chain; chain integrity (parent sha) and n_markets_after are checked."""
    for rel, cp, deltas in list_boards(root):
        state = {}
        t0 = None
        for l in gzip.open(cp, "rt"):
            if not l.strip():
                continue
            rec = json.loads(l)
            state[rec["ticker"]] = _slim(rec)
            t0 = t0 or ts(rec.get("_observed_at_utc"))
        t0 = t0 or snapshot_ts_from_path(cp)
        yield t0, "checkpoint", state, dict(path=rel, n=len(state)), None
        prev_sha = None
        for f in deltas:
            with gzip.open(f, "rt") as fh:
                d = json.load(fh)
            touched = set(d["added"]) | set(d["changed"]) | set(d["removed"]) | set(d["cleared"] or {})
            old = {t: (dict(state[t]) if t in state else None) for t in touched}
            for t, rec in d["added"].items():
                state[t] = _slim(rec)
            for t, patch in d["changed"].items():
                cur = state.setdefault(t, {})
                for k, v in patch.items():
                    if k in TRACK:
                        cur[k] = v
            for t, ks in (d["cleared"] or {}).items():
                for k in ks:
                    state.get(t, {}).pop(k, None)
            for t in d["removed"]:
                state.pop(t, None)
            info = dict(path=os.path.relpath(f, root), seq=d["seq"], chain_ok=(prev_sha is None or d["parent_board_sha256"] == prev_sha),
                        count_ok=(d["n_markets_after"] == len(state)), n=len(state))
            prev_sha = d["board_sha256"]
            yield ts(d["captured_at_utc"]), "delta", state, info, old


def board_sweep(root, lookups, starts=None, want=None):
    """Resolve each lookup (ticker, t, key) to the quote on the latest board captured at or before t, and accumulate pregame
    price-history coverage per ticker in ``want`` (using ``starts``: ticker -> scheduled start epoch).

    Implementation: keep a per-ticker 'last known slim' for wanted tickers that is updated on every board; before applying a board
    at time T every lookup with t < T is answered from the previous values, so a quote observed after t can never be used."""
    lk = sorted(lookups, key=lambda x: x[1])
    nxt = 0
    want = set(want) if want is not None else {x[0] for x in lk}
    last = {}  # ticker -> slim (as of previous board)
    resolved, cov = {}, {}
    integ = dict(n_checkpoints=0, n_deltas=0, chain_broken=0, count_mismatch=0, first_board=None, last_board=None, nonmonotonic=0)
    prev_t = None
    prev_cp_state_ref = None
    for t, kind, state, info, old in replay(root):
        # answer lookups that fall before this board
        while nxt < len(lk) and lk[nxt][1] < t:
            tk, tt, key = lk[nxt]
            nxt += 1
            resolved[key] = dict(board_t=prev_t if (prev_t is not None and tt >= prev_t) else None, slim=last.get(tk) if prev_t is not None else None)
        if prev_t is not None and t < prev_t:
            integ["nonmonotonic"] += 1
        # update `last` for wanted tickers from the new state
        if kind == "checkpoint":
            integ["n_checkpoints"] += 1
            for tk in list(last):
                if tk not in state:
                    last.pop(tk)
            for tk in want:
                if tk in state:
                    last[tk] = dict(state[tk])
        else:
            integ["n_deltas"] += 1
            integ["chain_broken"] += 0 if info["chain_ok"] else 1
            integ["count_mismatch"] += 0 if info["count_ok"] else 1
            for tk in old:
                if tk in want:
                    if tk in state:
                        last[tk] = dict(state[tk])
                    else:
                        last.pop(tk, None)
        integ["first_board"] = integ["first_board"] or t
        integ["last_board"] = t
        prev_t = t
        # coverage accounting (pregame boards only)
        if starts is not None:
            tick = want if kind == "checkpoint" else [x for x in old if x in want]
            if kind == "checkpoint":
                tick = [x for x in want if x in state]
            for tk in tick:
                st = starts.get(tk)
                if st is None or t >= st:
                    continue
                q = quote(last.get(tk))
                c = cov.setdefault(tk, dict(n_boards=0, n_two_sided=0, first_t=t, last_pre_t=t, last_two_sided_t=None, max_bid_size=0.0, max_ask_size=0.0))
                c["last_pre_t"] = t
                fs = (last.get(tk) or {}).get("floor_strike")
                if fs is not None:
                    c["floor_strike"] = fs
                if q and q["two_sided"]:
                    c["n_two_sided"] += 1
                    c["last_two_sided_t"] = t
                    c["max_bid_size"] = max(c["max_bid_size"], q["bid_size"] or 0.0)
                    c["max_ask_size"] = max(c["max_ask_size"], q["ask_size"] or 0.0)
                c["n_boards"] += 1  # counts boards at which the ticker was present (checkpoint) or changed (delta) -> change events
    while nxt < len(lk):
        tk, tt, key = lk[nxt]
        nxt += 1
        resolved[key] = dict(board_t=prev_t if (prev_t is not None and tt >= prev_t) else None, slim=last.get(tk))
    return resolved, cov, integ


# ----------------------------------------------------------------------------- orderbook archive coverage
def orderbook_coverage(root, tickers):
    """Which of ``tickers`` appear in the orderbook archive (checkpoints + deltas) and the max depth seen. Cheap: reads keys only."""
    want = set(tickers)
    seen = {}
    for f in sorted(glob.glob(os.path.join(root, "kalshi/orderbooks/dt=*/*.jsonl.gz"))):
        for l in gzip.open(f, "rt"):
            if not l.strip():
                continue
            r = json.loads(l)
            if r["ticker"] in want:
                c = seen.setdefault(r["ticker"], dict(n=0, first=None, last=None, max_levels=0))
                c["n"] += 1
                tt = ts(r.get("_observed_at_utc"))
                c["first"] = tt if c["first"] is None else min(c["first"], tt)
                c["last"] = tt if c["last"] is None else max(c["last"], tt)
                c["max_levels"] = max(c["max_levels"], len(r.get("yes") or []) + len(r.get("no") or []))
    n_delta = 0
    for f in sorted(glob.glob(os.path.join(root, "kalshi/orderbooks_delta/dt=*/*.json.gz"))):
        with gzip.open(f, "rt") as fh:
            d = json.load(fh)
        tt = ts(d["captured_at_utc"])
        n_delta += 1
        for k in list(d.get("added", {})) + list(d.get("changed", {})):
            if k in want:
                c = seen.setdefault(k, dict(n=0, first=None, last=None, max_levels=0))
                c["n"] += 1
                c["first"] = tt if c["first"] is None else min(c["first"], tt)
                c["last"] = tt if c["last"] is None else max(c["last"], tt)
    return seen, n_delta


# ----------------------------------------------------------------------------- cells
def q_alone_metrics(rows_holdout):
    q = np.clip(np.array([r["q"] for r in rows_holdout], float), 1e-6, 1 - 1e-6)
    y = np.array([r["y"] for r in rows_holdout], float)
    return dict(logloss=float(I.ll(q, y).mean()), brier=float(((q - y) ** 2).mean()), n=int(len(y)))


def positive_control(rows, seed=3, leak=0.35, **kw):
    """Deliberately leaky challenger: q = mid + leak*(y - mid). Look-ahead by construction -> the harness MUST detect it if the cell has power."""
    fake = [dict(r, q=float(min(0.98, max(0.02, r["mid"] + leak * (r["y"] - r["mid"]))))) for r in rows]
    return I.incremental_test(fake, **kw)


MATERIAL_GAIN = 0.002  # nats of logloss per row: below this a statistically positive gain is economically negligible


def run_cell(rows, **kw):
    """-> dict with incremental result + controls. rows: dicts game,t,mid,q,y."""
    res = I.incremental_test(rows, **kw)
    if res["status"] != "OK":
        res["negative_control"] = None
        res["positive_control"] = None
        res["q_alone_holdout"] = None
        return res
    nc = I.negative_control(rows, **kw)
    pc = positive_control(rows, **kw)
    res["negative_control"] = nc.get("gain_vs_calibrated_market_logloss")
    res["positive_control"] = pc.get("gain_vs_calibrated_market_logloss")
    _, te = I.split_games(rows)
    res["q_alone_holdout"] = q_alone_metrics([r for r in rows if r["game"] in te])
    q = np.array([r["q"] for r in rows], float)
    m = np.array([r["mid"] for r in rows], float)
    lq, lm = I.logit(q), I.logit(m)
    res["q_vs_mid"] = dict(mean_abs_diff=float(np.mean(np.abs(q - m))), corr_logit=float(np.corrcoef(lq, lm)[0, 1]) if len(q) > 2 and lq.std() > 0 and lm.std() > 0 else None,
                           note="corr near 1 and tiny mean_abs_diff would mean the challenger is not independent of the market")
    return res


def classify(res, holm_p, min_holdout_games=30, alpha=0.05, n_tested=None, min_promising_games=20):
    """Status rule (fixed in advance):
    UNDERPOWERED (too little train/holdout) -> INCONCLUSIVE_UNDERPOWERED; CI above 0 while the cell's own shuffled negative control also shows a gain -> INVALID_EVIDENCE;
    VALIDATED_IMPROVEMENT  = Holm p <= alpha AND CI lower bound > 0 AND holdout games >= min_holdout_games AND positive control detected AND negative control not significant;
    PROMISING_INSUFFICIENT = CI lower bound > 0 (uncorrected) but not validated;
    NO_DEMONSTRATED_IMPROVEMENT = enough holdout games and CI upper bound <= 0.002 logloss (can exclude a gain larger than that) OR point estimate <= 0 with
                                  holdout games >= min_holdout_games;
    otherwise INCONCLUSIVE_UNDERPOWERED."""
    if res.get("status") != "OK":
        return "INCONCLUSIVE_UNDERPOWERED", f"holdout/training too small ({res.get('train_games')} train / {res.get('holdout_games')} holdout games, {res.get('n_holdout')} rows)"
    g = res["gain_vs_calibrated_market_logloss"]
    pc = res.get("positive_control")
    pc_ok = bool(pc and pc["lo"] > 0)
    nc = res.get("negative_control")
    nc_ok = not (nc and nc["lo"] > 0)
    if holm_p is not None and holm_p <= alpha and g["lo"] > 0 and res["holdout_games"] >= min_holdout_games and pc_ok and nc_ok:
        return "VALIDATED_IMPROVEMENT", "Holm-adjusted p<=0.05, game-cluster CI above 0, controls behave"
    if g["lo"] > 0 and not nc_ok:
        return "INVALID_EVIDENCE", (f"uncorrected CI [{g['lo']:.4f},{g['hi']:.4f}] is above 0 but the game-shuffled negative control ALSO shows a spurious gain in this cell "
                                    f"({nc['mean']:.4f}, CI [{nc['lo']:.4f},{nc['hi']:.4f}]), so the interval cannot be trusted at this sample size")
    if g["lo"] > 0 and g["mean"] < MATERIAL_GAIN:
        return "NO_DEMONSTRATED_IMPROVEMENT", (f"uncorrected CI [{g['lo']:.4f},{g['hi']:.4f}] is above 0 but the gain ({g['mean']:.4f} nats) is below the {MATERIAL_GAIN} materiality floor "
                                               f"(Holm p={holm_p if holm_p is None else round(holm_p, 3)}); not a usable improvement")
    if g["lo"] > 0 and res["holdout_games"] >= min_promising_games:
        return "PROMISING_INSUFFICIENT", (f"uncorrected game-cluster CI [{g['lo']:.4f},{g['hi']:.4f}] above 0 ({res['holdout_games']} holdout games) but Holm-adjusted p={holm_p if holm_p is None else round(holm_p, 3)}"
                                          f" across {n_tested} tested cells fails the validation gate; a few such cells are expected by chance at that multiplicity")
    if g["lo"] > 0:
        return "INCONCLUSIVE_UNDERPOWERED", f"uncorrected CI [{g['lo']:.4f},{g['hi']:.4f}] above 0 but only {res['holdout_games']} holdout games (<{min_promising_games}); not treated as a finding"
    if g["hi"] < 0:
        return "NO_DEMONSTRATED_IMPROVEMENT", f"model is reliably WORSE than the calibrated market in holdout: gain {g['mean']:.4f}, CI [{g['lo']:.4f},{g['hi']:.4f}] entirely below 0 ({res['holdout_games']} holdout games)"
    if res["holdout_games"] >= min_holdout_games and g["hi"] <= 0.002:
        return "NO_DEMONSTRATED_IMPROVEMENT", f"holdout {res['holdout_games']} games; CI upper bound {g['hi']:.4f} excludes a logloss gain above 0.002"
    if res["holdout_games"] >= min_holdout_games and g["mean"] <= 0:
        return "NO_DEMONSTRATED_IMPROVEMENT", f"holdout {res['holdout_games']} games; point estimate {g['mean']:.4f} <= 0, CI [{g['lo']:.4f},{g['hi']:.4f}] not excluding small gains"
    return "INCONCLUSIVE_UNDERPOWERED", f"holdout only {res['holdout_games']} games (<{min_holdout_games}) / CI [{g['lo']:.4f},{g['hi']:.4f}] too wide to rule in or out"
