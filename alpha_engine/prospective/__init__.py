"""Prospective (point-in-time vintage) capture for the inputs that history cannot supply. RESEARCH_ONLY. DISABLED by default.

Nothing in this package schedules, deploys or activates anything. A capture runs only when ALL of these hold (vintage.activation_check):
  1. the environment variable SIFT_PROSPECTIVE_ENABLED == "1";
  2. the feed is listed in an owner-written activation file (path in SIFT_PROSPECTIVE_ACTIVATION) with an owner name and date;
  3. the feed's source has collection_allowed == true in research/input_research/data_foundation/rights_registry.json.
Every ESPN / MLB Stats API / NHL API source is collection_allowed == false today, so those feeds refuse to run even if 1 and 2 are set. See docs/PROSPECTIVE_CAPTURE.md.
"""
