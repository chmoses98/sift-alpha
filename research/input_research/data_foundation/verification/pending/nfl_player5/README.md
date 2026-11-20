# Pending certification: NFL player-prop batch 5 (nfl_player_ext5)

Six inputs: nfl.carries, nfl.targets, nfl.rz_share, nfl.td_rates, nfl.target_competition, nfl.player_stat_variance.

- **Replay:** full replay passes every check for all six (`NFL_nfl_player5.json`, run on 2026-11-20).
- **Blind brief:** `../../blind_briefs/briefs_nfl_player5.md`. A blind re-implementation is in progress.

The replay JSON is held here, outside `replay_ext/`, so the ledger cannot read it before a blind exact match exists. Promotion is
an explicit move into `replay_ext/` + `independent/` followed by `regenerate --apply`.
