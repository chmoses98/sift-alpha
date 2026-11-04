# Resting limit-buy vs closing-ask (research only; no orders, no API, nothing pushed)

**Scope: NFL week 4 only** (16 games, 30 decisions = owner-placed pregame clv_eligible wagers, deduped per contract+side; NO verified recommendation linkage). Week 6 was dropped: its closes exist, but a second week of trade tape would break the ~1.5 GB budget measured in raw blob size.

## Data (market-data branch, blobs read on demand)
- Trades: 569 runs inside the 48h-before-kickoff windows, 1.235 GB raw, filtered to the 30 decision tickers, deduped on trade_id, block trades excluded.
- Quotes+books: 64 quote runs and 58 book runs, 0.346 GB raw (incl. week 6 runs that went unused).
- Pack growth on disk: about +200 MB, which includes ~190 MB of incidental fetches from two size probes that downloaded blobs. Raw total about 1.6 GB, slightly over target.

## Method (sim.py; fetch.py produces extracts; stdlib only; `python3 -I`)
Placement quote = nearest run at-or-before kickoff-H (<=30 min stale) for H in 48/24/12/6/1h. Prices follow the four rules on the side's own bid/ask (NO bid = no_bid_dollars). Resting orders stay live to kickoff. Variant `reprice1h`: cancel at the 1h quote and cross at its ask.
**Fill model.** YES buy at p fills on taker_side='no' trades with yes_price<=p; NO buy fills on taker_side='yes' trades with no_price<=p. Verified on data: taker 'yes' trades print at the yes ask (91% within 1c), taker 'no' trades at the yes bid (85% within 1c).
- UPPER: queue ahead 0, any qualifying trade fills, partial fills allowed.
- LOWER: back of queue. Queue = displayed book size at p (0 if p is inside the spread). Same-price trades first drain the queue. Trades through p fill fully. No cancellation credit. Needs a book within 10 min of the quote: otherwise the lower bound is UNKNOWN (59 of 120 placement instants have none; 71 have a book).
- UNCERTAIN if the unfilled outcome cannot be called because of a tape gap (>180 s uncovered). Observed: zero gaps, so none are uncertain; the only unknowns are the missing books.
- Fees: maker 0.0175*C*P*(1-P), taker 0.07*C*P*(1-P), ceil to cent per fill. Some series may carry no maker fee; if so maker net values here are slightly understated.
- Value (cents per contract, settlement-free proxy, no outcomes used) = close_mid(side) - fill - fee. Unfilled counts as 0, or as a cross at the 1h ask (variant). Bootstrap: 2000 resamples of the 16 games. Baselines: buy the close ask (taker fee), and the owner's actual VWAP (taker fee assumed).
- `breakeven_edge_cents`: the thesis edge (vs close mid) below which resting beats the close-ask baseline. The proxy omits the edge lost on unfilled bets, so this number matters.

## Exclusions
Missing quote at placement: H48 10, H24 7, H12 8, H6 4, H1 1 (of 30 each); 120 instants evaluated. No decision lost to close validity (all CLOSE_OK, <=3600 s, before kickoff).

## Limits
One week and 16 games, so wide intervals. The tape shows only prints, not cancellations or queue growth. We assume we do not move the market. results.json holds aggregates only; decisions_private.json and ext/ (tickers, contract counts) are private extracts.


> Reproduction note: `prep.py`/`fetch.py` hard-code the session scratch directory and read the PRIVATE owner ledger (never committed); adjust the paths. Only `results.json` aggregates are published (`reports/clv_recalc/execution_summary_2026-11-04.json`).
