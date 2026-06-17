# What-If Operating Guide

## Purpose

This project does **not** use what-if to simulate arbitrary physician mistakes.

Instead, the current what-if system is intended to answer a narrower question:

- When the simulator is still **ambiguous**
- and there are already **plausible alternative actions**
- how sensitive is the downstream outcome to choosing one alternative over another?

In other words, the current what-if layer is best understood as:

- **policy sensitivity analysis**
- **simulator brittleness analysis**
- **plausible alternative replay**

not as a broad error-injection tool.

## Reality Constraint

To stay clinically plausible, what-if should only open when all of the following are true:

1. The current decision is still ambiguous.
2. The simulator already has at least one plausible alternative in its shortlist.
3. The case has not already become decisively supported by objective evidence.

This is why the current direction is:

- avoid arbitrary branch changes
- avoid unrealistic reroutes
- avoid opening what-if on obviously decisive cases
- restrict replay to **shortlisted, already-plausible** alternatives

## Current Structure

The simulator currently has two what-if layers.

### 1. Routing what-if

This asks:

- if ER had chosen a different plausible specialty handoff,
- would the downstream diagnosis and department outcome change?

Current replay action:

- `handoff_department`

Current practical interpretation:

- recovery of **wrong specialty routing**

### 2. Specialty what-if

This asks:

- within the same department,
- should the specialty service finalize now,
- or refine once more?

Current replay actions:

- `diagnose_now`
- `refine_again`

Current practical interpretation:

- recovery of **same-department exact diagnosis misses**

## Snapshot Nodes

Current replayable nodes:

- `er_next_step`
- `er_routing`
- `specialty_next_step`
- `specialty_finalize`

In practice, the most useful nodes are:

- `er_routing`
- `specialty_next_step`
- `specialty_finalize`

`er_next_step` is still kept, but it has mostly produced efficiency-only gains rather than major outcome changes.

## Operating Rule

The project now uses a bucketed recommendation style rather than replaying everything.

There is also a combined recommendation layer that merges routing and specialty suggestions into a single top-level queue.

Main recommendation config:

- `app/data/what_if_recommendation_config.json`

This file now controls:

- routing recommendation thresholds
- specialty recommendation thresholds
- combined ranking priority across routing and specialty

### Routing buckets

Recommendation file:

- `outputs/what_if/recommendations/routing_replay_recommendations_20260526_234422_tuned_v3.json`

Current buckets:

- `priority_replay`
- `review_candidate`

Current review subbuckets:

- `review_high`
- `review_low`

Current threshold values come from:

- `app/data/what_if_recommendation_config.json`

Current recommended meaning:

- `priority_replay`
  - safe to replay automatically
  - currently based on:
    - generic working diagnosis
    - objective evidence already present
    - small routing score gap
    - strong prior replay success for that transition
- `review_candidate`
  - plausible, but not strong enough for automatic replay
  - should be inspected before use
  - internally split into:
    - `review_high`
      - stronger manual candidates
    - `review_low`
      - weaker, lower-priority manual candidates

### Specialty buckets

Recommendation file:

- `outputs/what_if/recommendations/specialty_replay_recommendations_20260526_234422_tuned_v2.json`

Current buckets:

- `priority_replay`
- `review_candidate`

Current review subbuckets:

- `review_high`
- `review_low`

Current threshold values come from:

- `app/data/what_if_recommendation_config.json`

Current recommended meaning:

- `priority_replay`
  - immediately replayable
- `review_candidate`
  - worth checking manually
  - internally split into:
    - `review_high`
      - stronger manual candidates
    - `review_low`
      - weaker, lower-priority manual candidates

## Current Evidence

### Routing

Priority routing replay summary:

- `outputs/what_if/batch_summaries/routing_recommendation_priority_v4_summary.json`

Current result:

- `3 / 3` improved

These priority transitions were:

- `nephrology -> obstetrics_gynecology`
- `pulmonology -> obstetrics_gynecology`
- `hematology -> gastroenterology`

Interpretation:

- routing priority replay is now precise enough to use as a practical sensitivity-analysis tool
- `review_high` is useful as the first manual-inspection queue
- `review_low` should be treated as a lower-yield backlog

### Specialty

Priority specialty replay summary:

- `outputs/what_if/batch_summaries/specialty_recommendation_tuned_summary.json`

Current result:

- `1 / 1` improved

Current tuned recommendation state:

- `priority_replay = 1`
- `review_candidate = 1`
- current `review_candidate` is also `review_high`

Interpretation:

- specialty replay is useful, but should still be treated as a recommendation-driven analysis layer rather than fully automated policy
- the tuned specialty recommender is intentionally conservative, with the strongest current automatic target concentrated in one `priority_replay` case
- `review_high` is a useful first manual queue for same-department exact-diagnosis recovery checks

## What We Should Claim

The system should currently be described as:

- a **counterfactual replay tool for ambiguous cases**
- restricted to **plausible alternatives already surfaced by the simulator**
- used to measure **decision sensitivity**, not arbitrary physician error

Good phrasing:

- "We analyze outcome sensitivity when multiple clinically plausible next actions remain."
- "We only open what-if on ambiguity-gated decision points."
- "We use replay to identify brittle simulator policies and promising refinement opportunities."

Avoid phrasing like:

- "We simulate common physician mistakes."
- "We assume doctors frequently misroute patients."
- "We explore arbitrary wrong decisions."

## Immediate Use Policy

Use the current what-if system like this:

1. Run the baseline simulator.
2. Generate recommendation files.
3. Replay only:
   - routing `priority_replay`
   - specialty `priority_replay`
4. Inspect `review_candidate` buckets manually.
5. Use results as:
   - sensitivity evidence
   - debugging evidence
   - policy improvement evidence

## Commands

### Combined recommendation list

```powershell
python -m app.scripts.recommend_combined_what_if_cases --routing-path outputs\what_if\recommendations\routing_replay_recommendations_20260526_234422_tuned_v3.json --specialty-path outputs\what_if\recommendations\specialty_replay_recommendations_20260526_234422_tuned_v2.json --output-name combined_what_if_recommendations_20260526_234422_v2.json
python -m app.scripts.print_combined_what_if_recommendations --recommendation-path outputs\what_if\recommendations\combined_what_if_recommendations_20260526_234422_v2.json --limit 10 --markdown-out docs\reports\combined_what_if_recommendations.md
```

Combined ranking order also comes from:

- `app/data/what_if_recommendation_config.json`

### Routing priority replay

```powershell
python -m app.scripts.run_routing_recommendation_batch --recommendation-path outputs\what_if\recommendations\routing_replay_recommendations_20260526_234422_tuned_v3.json --replay-prefix routing_recommendation_priority_v4 --bucket priority_replay
```

### Routing review_high replay

```powershell
python -m app.scripts.run_routing_recommendation_batch --recommendation-path outputs\what_if\recommendations\routing_replay_recommendations_20260526_234422_tuned_v3.json --replay-prefix routing_recommendation_review_high_v2 --bucket review_candidate --review-subbucket review_high --limit 2
```

### Specialty priority replay

```powershell
python -m app.scripts.run_specialty_recommendation_batch --recommendation-path outputs\what_if\recommendations\specialty_replay_recommendations_20260526_234422_tuned_v2.json --replay-prefix specialty_recommendation_tuned --bucket priority_replay
```

### Specialty review_high replay

```powershell
python -m app.scripts.run_specialty_recommendation_batch --recommendation-path outputs\what_if\recommendations\specialty_replay_recommendations_20260526_234422_tuned_v2.json --replay-prefix specialty_recommendation_review_high_v2 --bucket review_candidate --review-subbucket review_high --limit 1
```

## Current Limitation

The system is still stronger as an **analysis tool** than as a fully absorbed policy layer.

That is especially true for specialty:

- replay often reveals valuable alternatives
- but the same gains do not always transfer directly into base-policy automation

So the current best use is:

- analyze
- recommend
- selectively replay
- then use successful transitions to guide later policy refinement

## Hard-Coding Status

Recent cleanup intentionally removed the old `high_signal` diagnosis path from active specialty decision logic.

Current state:

- `app/data/high_signal_diagnosis_rules.json`
  - remains in the repository as a **legacy artifact / reference file**
- active `specialty_agent` decision paths
  - no longer use those rules for candidate seeding, exact-diagnosis forcing, or LLM post-hoc override

Interpretation:

- the file is kept for traceability and rollback safety
- the active simulator should now be understood as relying on:
  - objective evidence
  - catalog search
  - department ownership rules
  - generic specialty policy config

So the project has moved from:

- disease-specific exact-diagnosis triggers

to:

- evidence-driven and policy-configured specialty reasoning
