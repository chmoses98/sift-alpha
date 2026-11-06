"""Input research: which inputs predict each Kalshi market family, by how much, and does the combination beat the market.

Layers (all research-only; nothing here places orders or is a betting claim):
  catalog.py   deep candidate-input catalog per sport/blueprint, validated against the committed registry
  linker.py    joins the catalog to the verification engine's availability / lineage / model-use evidence
  stats.py     chronological validation, market-benchmark scoring, importance and interaction tests, multiple-testing control
  nfl_game.py  NFL game winner / spread / total path on nflverse history vs near-close sportsbook lines
  qb_passing.py NFL QB passing-yards path (learned importance vs baselines; market comparison blocked)
  publish.py   assembles research/audit/input_research/*.json for the dashboard
"""
