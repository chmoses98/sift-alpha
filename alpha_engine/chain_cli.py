"""Real two-sport source delta chain verification. No trading."""
import json
from pathlib import Path
from .verified_chains import replay

if __name__ == "__main__":
    inp=json.loads(Path("research/verified_chain_pilot.json").read_text(encoding="utf-8"))
    outcome=replay(inp)
    target=Path("artifacts/verified_chain_pilot.json")
    target.parent.mkdir(exist_ok=True,parents=True)
    target.write_text(json.dumps(outcome,indent=2,sort_keys=True)+"\n",encoding="utf-8")
    for sport,v in sorted(outcome["sport_chains"].items()):
        print(sport,"market board",v["base_markets"],"to",v["final_market_count"],
              "verified delta ticks",v["delta_ticks"],"quote movers",v["n_unique_tickers_with_quote_movements"])
    print("Research only; no verified pregame or profitability claim.",target)
