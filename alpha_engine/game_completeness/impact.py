"""Join archive gaps to the approved Market & Input Map (read-only).

The map (research/input_research/market_input_map/map.json) already records which registered dataset satisfies
which catalog input, and which input each market archetype needs.  This module only LOOKS UP those edges for the
map dataset ids a DatasetSpec names; it never adds, re-scores or re-classifies an input.
"""
import json
from collections import defaultdict
from pathlib import Path

MAP = Path(__file__).resolve().parents[2] / "research" / "input_research" / "market_input_map" / "map.json"


class InputMap:
    def __init__(self, path=MAP):
        m = json.loads(Path(path).read_text())
        self.inputs = m["inputs"]
        self.datasets = m["datasets"]
        dc, ec = m["dataset_edge_cols"], m["edge_cols"]
        self.by_dataset = defaultdict(set)                      # dataset id -> input keys it SATISFIES
        for row in m["dataset_edges"]:
            r = dict(zip(dc, row))
            if r["edge_type"] == "SATISFIED_BY":
                self.by_dataset[r["dataset"]].add(r["input"])
        self.markets = defaultdict(lambda: defaultdict(set))    # input key -> role -> archetypes
        self.pred = set()
        for row in m["edges"]:
            r = dict(zip(ec, row))
            self.markets[r["input"]][r["role"]].add(r["archetype"])
            if r["class"] == "PREDICTIVE":
                self.pred.add(r["input"])
        self.n_inputs = len(self.inputs)

    def impact(self, map_dataset_ids):
        """-> dependent inputs and market archetypes for these registered datasets (existing edges only)."""
        unknown = sorted(d for d in map_dataset_ids if d not in self.datasets)
        inputs = sorted({i for d in map_dataset_ids for i in self.by_dataset.get(d, ())})
        primary, any_role = set(), set()
        for i in inputs:
            for role, arch in self.markets.get(i, {}).items():
                any_role |= arch
                if role == "primary":
                    primary |= arch
        buckets = defaultdict(int)
        for i in inputs:
            buckets[self.inputs[i].get("completeness_category") or self.inputs[i].get("bucket") or "UNKNOWN"] += 1
        return {"map_datasets": sorted(map_dataset_ids), "unknown_map_datasets": unknown,
                "n_inputs": len(inputs), "n_predictive_inputs": sum(i in self.pred for i in inputs),
                "inputs_by_map_category": dict(sorted(buckets.items())),
                "n_markets": len(any_role), "n_markets_primary": len(primary),
                "markets_primary": sorted(primary), "inputs": inputs}
