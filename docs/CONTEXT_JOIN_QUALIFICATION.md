# Independent context and settlement source qualification (NBA + NHL)

The initial sparse quote tape reconstructs actual Kalshi board observations, but it cannot be declared **pregame** without a separately sourced game-start timestamp and a verified mapping from the exact Kalshi contract to that physical game. It also cannot be declared **settled correctly** merely because a ticker matches a result field.

This audit uses **six real immutable Git-blob-pinned public source files** from the existing NBA and NHL data archives: a schedule snapshot before the October 25 00:02/00:06 UTC market checkpoint, a later schedule snapshot (to adversarially prove as-of selection excludes future context), and a sampled post-checkpoint settlement file per sport. Each gzip has a strict source byte-length, Git blob checksum, total download budget, decompression budget and JSONL row cap. All files are read-only; no paid APIs or credentials.

Run the existing sparse tape first, then:

```sh
python3 -m unittest discover -s tests -p 'test_context_source_audit.py' -v
python3 -m alpha_engine.context_source_cli
```

The report **profiles the actual source schemas** and counts literal YES/NO results with exact ticker matches. It never infers results from a score, copies later schedule content into an earlier snapshot, or equates a ticker match with independently verified settlement rules. Until a defensible event/physical-game mapping is available, `physical_game_join` and `pregame_market_eligibility` remain `NOT_ESTABLISHED`.

**Next engineering gate:** inspect actual schema profiles and implement an exact, independently verified mapping from a source's physical game ID + scheduled start to the Kalshi event/contract with appropriate rule/version provenance. Quarantine uncertain series, conflicting identities, after-start captures and unmatched settlements. Only then calculate pregame calibration with independent-game denominators. No trading or ROI authorization.
