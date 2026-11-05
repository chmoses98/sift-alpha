# SIFT Alpha — $0 Operating Budget Policy

**Status:** Active project requirement. Applies to SIFT Alpha research, CI, automated experiments, deployment and integrations.

## The rule

**SIFT Alpha has a hard target of $0 in incremental operating costs until the owner explicitly authorizes a change.** Research quality and scientific rigor must not be reduced to create an illusion of progress under this limit.

- Do not enable paid plans, metered billing, paid APIs, commercial tracking-data licenses, billable hosting, GPU runners, or usage-based AI inference by default.
- No engineer or autonomous agent may create a paid resource, enable automatic billing, add a payment method, or spend money on the project's behalf without **advance, explicit owner approval for a specific expense**. A general approval to build Alpha is **not** spending approval.
- Never make a silent paid fallback when a free service reaches a quota or becomes unavailable. Pause or degrade the affected task gracefully and report the limitation.
- Costs that could be incurred through an existing account/subscription count as costs for this policy; "already connected" is not sufficient permission to consume a paid quota.
- Every new infrastructure/data dependency must document its license, free-tier constraints, any overage behavior, and how to disable or stop it safely before implementation.

## Preferred free architecture

1. Reuse open-source statistical and machine-learning tooling and the existing SIFT sport research repositories where allowed.
2. Prefer credible, legally usable free data sources with documented provenance and quality checks. **Do not fabricate substitutes** for tracking data that is unavailable.
3. Use the public repository's eligible free **standard GitHub-hosted runners** for small, bounded scheduled research jobs and CI; do not assume free runner minutes imply unlimited concurrency, storage, network use or guaranteed schedules. Never opt into larger/paid runners.
4. Keep jobs resumable and bounded; use per-job timeouts, concurrency limits, quotas, checkpointing and retention limits. Check workflow logs, artifact retention and billing periodically.
5. Use local / offline / open-source calculations wherever feasible. Paid AI inference, paid persistent workers and commercial sport data require a separately approved exception.

## New-resource / workflow checklist

Before merging any change that adds automation, cloud compute, external API access, data storage or AI services, document:

- **Expected incremental monthly cost:** $0.
- **Service and plan:** exact free offering used and applicable limits.
- **Overage behavior:** whether usage stops or can become billable; avoid configurations that permit unapproved charges.
- **Research quality:** source validity, data rights, missing-data behavior, and scientific evaluation plan.
- **Safety:** timeout, rate limit, max concurrency, persistence/checkpoints, safe failure/disable switch, and who notices a failure.

If the above cannot be satisfied for $0, **do not activate that component**. Record it as blocked with a free alternative or an owner decision needed.

## Exception process

If a worthwhile capability genuinely cannot be delivered within the free limits, present a specific proposal first: the capability, why a free alternative is inadequate, price/cap and billing mechanism, expected value, and how to cancel. **The owner decides whether to authorize it; otherwise the $0 rule remains in force.** No implied or retroactive authorization.

## Boundaries and truthfulness

- "$0 budget" does **not** guarantee zero cost if an external service is misconfigured or its billing terms change. Monitor settings, quotas and usage.
- A public GitHub repository does **not** make confidential data public-safe. No secrets, private strategies, bankroll/position details or restricted licensed datasets in source, Actions logs or artifacts.
- The current research desk is not a continuously operating research engine. This policy governs future automation; it does not claim autonomous research has been implemented.
- The aim is **high-quality, self-directed, scientifically validated sports research** across all eligible sports, not maximum experiment count at any cost.

Related foundational requirements: [Quality-gated autonomous research](https://github.com/chmoses98/sift-alpha/issues/2).
