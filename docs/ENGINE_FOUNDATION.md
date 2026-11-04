# Alpha Research Engine — First Real Milestone

This is the **foundation**, not a completed autonomous research institution.

## Why start here

SIFT Alpha's goal is to discover and rigorously validate deep, sport-specific mechanisms that could produce better forecasts and eventually profitable after-fee trading. We cannot get there by using an AI to fabricate investigations every hour.

The first useful component is a **deterministic research director** that selects a clearly scoped task from a diverse, registered queue. The next component is a rigorous data integrity gate. This milestone introduces both without enabling expensive or unsafe automation.

## What is executable now

```shell
python3 -m unittest discover -s tests -p 'test_engine*.py' -v
python3 -m alpha_engine.cli
```

The planning CLI writes JSON to stdout only. It identifies which sport-specific question has a clear mechanism and which missing source qualification is blocking it. It cannot place bets, call APIs, start models, fabricate observations, or incur any API charges.

The registry is deliberately **unverified** because a GitHub repository or a public website is not proof of lawful access, clean data, timestamped historical availability or zero metered cost. The first real decision should be *data qualification*, not pretend a pitch-mix discovery happened.

### Cost and data integrity

- By default, a source is blocked until its free-use terms, charge mode, licensing, point-in-time availability and data contract are explicitly checked.
- A source marked `metered`, `unknown`, or with an absent `cost_verified` flag fails closed.
- `audit_prediction_rows` rejects duplicated decisions, non-UTC timestamps, features observed after prediction cutoff and decisions at/after event start.
- These are **necessary, not sufficient** checks. They do not establish sample representativeness, opponent adjustment, correct outcomes, reproducible full experimentation, independence, or statistical significance.

## What must come next

1. Build verified source adapters and reproducible data QA for a few real sports, starting where available evidence supports it. Verify free legal access and correct timestamps rather than accepting a repo README as a quality certificate.
2. Build a properly preregistered experiment protocol: hypothesis, observational unit, target, confounders, baseline, data windows, holdout, scoring and provenance.
3. Implement a blinded independent evaluator and intentionally hostile leakage/selection tests.
4. Complete at least two genuine deep, independent sport studies end to end, with immutable datasets and source hashes.
5. Only then enable scheduled/resumable autonomous job progression and natural hypothesis generation. Log negative, null and data-limited findings.
6. Any commercial/proprietary betting logic or private account information stays outside this public codebase.

**No runner schedule has been enabled in this milestone.** That is intentional: an automatic job doing nothing scientifically meaningful is not the autonomous R&D operation the owner asked for.

Tracking: [quality and $0 policy](https://github.com/chmoses98/sift-alpha/issues/2).
