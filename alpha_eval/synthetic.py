"""Deterministic SYNTHETIC fixtures. They exercise every code path (all four statuses, every scoring type, alternates,
fills, independence flags). They are NOT evidence about any real model or market: every row is tagged and every example
report says so. Seeded; no network."""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from .schema import SCHEMA_VERSION

T0 = datetime(2026, 11, 1, 18, 0, tzinfo=timezone.utc)


def iso(d):
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def generate(seed: int = 7, n_events: int = 160):
    rng = random.Random(seed)
    F, O, Q, X = [], [], [], []
    base = dict(schema=SCHEMA_VERSION, evidence_class="BACKTEST", meta=dict(synthetic=True))
    for i in range(n_events):
        sport = ("NBA", "CBB", "NHL", "NFL")[i % 4]
        start = T0 + timedelta(days=i // 8, hours=(i % 8))
        gid = f"SYN-{sport}-{i}"
        true_p = min(max(rng.gauss(0.5, 0.18), 0.05), 0.95)
        y = int(rng.random() < true_p)
        mkt = min(max(true_p + rng.gauss(0, 0.04), 0.03), 0.97)           # market sees truth with small noise
        mod = min(max(true_p + rng.gauss(0, 0.06) + 0.03, 0.03), 0.97)    # model: noisier and +3pt biased
        for horizon_h in (24, 3):
            frozen = start - timedelta(hours=horizon_h)
            mid = f"KXSYN{sport}GAME-{gid}"
            fid = f"{mid}|{horizon_h}"
            F.append(dict(base, forecast_id=fid, sport=sport, event_id=gid, market_id=mid, native_family="game_winner" if sport != "NFL" else "GAME",
                          model_id="syn-sports-only", model_version="syn-v1", model_independence="sports_only", frozen_at=iso(frozen),
                          event_start=iso(start), scoring_type="BINARY", payload=dict(p_yes=round(mod, 4))))
            spread = 0.02
            Q.append(dict(schema=SCHEMA_VERSION, market_id=mid, observed_at=iso(frozen - timedelta(minutes=5)), yes_bid=round(mkt - spread / 2, 3), yes_ask=round(mkt + spread / 2, 3)))
        Q.append(dict(schema=SCHEMA_VERSION, market_id=mid, observed_at=iso(start - timedelta(minutes=20)), yes_bid=round(true_p - 0.01, 3), yes_ask=round(true_p + 0.01, 3)))
        O.append(dict(schema=SCHEMA_VERSION, market_id=mid, event_id=gid, state="final", observed_at=iso(start + timedelta(hours=3)), source="sports", value=y))
        if i % 10 == 0:                                                       # synthetic verified fill
            X.append(dict(schema=SCHEMA_VERSION, forecast_id=f"{mid}|24", market_id=mid, side="YES" if mod > mkt else "NO",
                          price=round(mkt + 0.01 if mod > mkt else 1 - mkt + 0.01, 2), count=10, fee=0.17, is_taker=True, filled_at=iso(start - timedelta(hours=23))))
        # alternate totals: correlated ladder from one latent total
        if sport in ("NBA", "CBB"):
            total = rng.gauss(150, 14)
            for k, line in enumerate((140.5, 145.5, 150.5, 155.5, 160.5)):
                lid = f"KXSYN{sport}TOTAL-{gid}-{line}"
                p_true = 1 / (1 + math.exp(-(total - line) / 8))
                F.append(dict(base, forecast_id=f"{lid}|6", sport=sport, event_id=gid, market_id=lid, native_family="total", line=line,
                              line_role="MAIN" if line == 150.5 else "ALTERNATE", model_id="syn-sports-only", model_version="syn-v1",
                              model_independence="sports_only", frozen_at=iso(start - timedelta(hours=6)), event_start=iso(start),
                              scoring_type="BINARY", payload=dict(p_yes=round(min(max(p_true + rng.gauss(0, .08), .02), .98), 4))))
                Q.append(dict(schema=SCHEMA_VERSION, market_id=lid, observed_at=iso(start - timedelta(hours=6, minutes=2)), yes_bid=round(p_true - .02, 3), yes_ask=round(p_true + .02, 3)))
                O.append(dict(schema=SCHEMA_VERSION, market_id=lid, event_id=gid, state="final", observed_at=iso(start + timedelta(hours=3)), source="sports", value=int(total > line)))
            # player points: ordinal pmf + continuous
            pts = max(0, round(rng.gauss(18, 6)))
            lam = 18
            pmf = {k: math.exp(-((k - lam) ** 2) / (2 * 36)) for k in range(0, 45)}
            z = sum(pmf.values())
            pmf = {k: v / z for k, v in pmf.items()}
            pid = f"KXSYN{sport}PTS-{gid}-P1"
            F.append(dict(base, forecast_id=f"{pid}|pmf", sport=sport, event_id=gid, market_id=pid, native_family="player_points", model_id="syn-sports-only",
                          model_version="syn-v1", model_independence="sports_only", frozen_at=iso(start - timedelta(hours=5)), event_start=iso(start),
                          scoring_type="ORDINAL_PMF", payload=dict(pmf={str(k): v for k, v in pmf.items()})))
            F.append(dict(base, forecast_id=f"{pid}|mean", sport=sport, event_id=gid, market_id=pid + "-M", native_family="player_points", model_id="syn-sports-only",
                          model_version="syn-v1", model_independence="sports_only", frozen_at=iso(start - timedelta(hours=5)), event_start=iso(start),
                          scoring_type="CONTINUOUS", payload=dict(mean=lam, quantiles={"0.1": 10, "0.5": 18, "0.9": 26})))
            O.append(dict(schema=SCHEMA_VERSION, market_id=pid, event_id=gid, state="final", observed_at=iso(start + timedelta(hours=3)), source="sports", value=pts))
            O.append(dict(schema=SCHEMA_VERSION, market_id=pid + "-M", event_id=gid, state="final", observed_at=iso(start + timedelta(hours=3)), source="sports", value=pts))
    # soccer 3-way: CATEGORICAL
    for i in range(20):
        start = T0 + timedelta(days=i // 4, hours=2)
        gid = f"SYN-SOCCER-{i}"
        probs = {"home": .45, "draw": .27, "away": .28}
        res = rng.choices(list(probs), weights=probs.values())[0]
        F.append(dict(base, forecast_id=f"{gid}|1x2", sport="SOCCER", event_id=gid, market_id=f"KXSYNSOCCER3WAY-{gid}", native_family="match_result_3way", model_id="syn-sports-only",
                      model_version="syn-v1", model_independence="sports_only", frozen_at=iso(start - timedelta(hours=8)), event_start=iso(start), scoring_type="CATEGORICAL", payload=dict(probs=probs)))
        O.append(dict(schema=SCHEMA_VERSION, market_id=f"KXSYNSOCCER3WAY-{gid}", event_id=gid, state="final", observed_at=iso(start + timedelta(hours=2)), source="sports", value=res))
    # edge cases: each must surface as a counted status with a reason
    s = T0 + timedelta(days=30)
    common = dict(base, sport="NBA", event_id="SYN-EDGE", model_id="syn-sports-only", model_version="syn-v1", model_independence="sports_only",
                  event_start=iso(s), scoring_type="BINARY", payload=dict(p_yes=.6), native_family="game_winner")
    F += [dict(common, forecast_id="edge-pending", market_id="KXSYNNBAGAME-PEND", frozen_at=iso(s - timedelta(hours=2))),
          dict(common, forecast_id="edge-late-freeze", market_id="KXSYNNBAGAME-LATE", frozen_at=iso(s + timedelta(minutes=5))),
          dict(common, forecast_id="edge-market-leak", market_id="KXSYNNBAGAME-LEAK", frozen_at=iso(s - timedelta(hours=2)), market_inputs_used=["kalshi_mid"]),
          dict(common, forecast_id="edge-combo", market_id="KXSYNMVE-1", native_family="parlay", frozen_at=iso(s - timedelta(hours=2))),
          dict(common, forecast_id="edge-binary-on-3way", sport="SOCCER", market_id="KXSYN3W-X", native_family="match_result_3way", scoring_type="CATEGORICAL", payload=dict(p_yes=.5), frozen_at=iso(s - timedelta(hours=2))),
          dict(common, forecast_id="edge-undeclared", market_id="KXSYNNBAGAME-UND", model_independence=None, frozen_at=iso(s - timedelta(hours=2))),
          dict(common, forecast_id="edge-noquote", market_id="KXSYNNBAGAME-NOQ", frozen_at=iso(s - timedelta(hours=2)))]
    for m in ("KXSYNNBAGAME-LATE", "KXSYNNBAGAME-LEAK", "KXSYNNBAGAME-UND", "KXSYNNBAGAME-NOQ"):
        O.append(dict(schema=SCHEMA_VERSION, market_id=m, event_id="SYN-EDGE", state="final", observed_at=iso(s + timedelta(hours=3)), source="sports", value=1))
    O.append(dict(schema=SCHEMA_VERSION, market_id="KXSYNNBAGAME-PEND", event_id="SYN-EDGE", state="pending", source="sports"))
    O.append(dict(schema=SCHEMA_VERSION, market_id="KXSYN3W-X", event_id="SYN-EDGE", state="final", observed_at=iso(s + timedelta(hours=3)), source="sports", value="home"))
    F.append(dict(F[0]))                                                      # duplicate id
    return F, O, Q, X
