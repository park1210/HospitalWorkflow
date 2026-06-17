# Project Operating Principles

This project is an ER-style multi-agent clinical simulator.
All future development should satisfy the following priorities.

## Core Goals

1. Minimize LLM calls.
The simulator should use the fewest possible model calls per case.
Prefer deterministic logic, cached decisions, and simple control rules before calling an LLM.

2. Stop early when evidence is decisive.
If objective evidence strongly supports a single diagnosis or department, finalize immediately.
Do not continue interviewing, testing, or consulting once the answer is already sufficiently supported.

3. Escalate when uncertainty remains.
If the diagnosis is not yet sufficiently supported, the system must move to the next useful stage.
Do not stay in repetitive questioning loops.
Preferred escalation order:
- targeted interview
- targeted exam or test
- specialty consult
- final decision

4. Record rationale for every decision.
Every `ask`, `test`, `consult`, and `diagnose` decision must include an explicit rationale.
Rationales should explain why the chosen next step is justified by currently available evidence.

## Development Rules

- Avoid hard-coded disease-specific branching unless it is strictly necessary as a safety fallback.
- Hard-coded department taxonomy is allowed and preferred.
  - Department labels should come from one shared catalog.
  - Free-form department names from LLM output should always be normalized into that catalog.
- Prefer general evidence-driven rules over disease-name rules.
- Prefer low-cost signals first:
  - repeated patient answers
  - unchanged uncertainty
  - objective evidence count
  - whether one diagnosis is clearly supported
- Add structure before adding more LLM calls.
- If an LLM output is ambiguous, normalize it into the project schema before use.
- If a simpler deterministic rule can replace an LLM call, prefer the deterministic rule.

## Review Checklist

Before merging a change, verify:

- Did this change reduce, preserve, or unnecessarily increase LLM calls?
- If evidence is decisive, does the case terminate early?
- If evidence is insufficient, does the flow advance to the next stage instead of repeating?
- Does each routing decision leave a rationale in state or transcript?
- Did we avoid introducing new unnecessary hard-coded disease rules?

## Preferred Direction

When choosing between two implementations, prefer the one that is:

- simpler
- cheaper in token usage
- easier to explain
- more deterministic
- more traceable in logs
