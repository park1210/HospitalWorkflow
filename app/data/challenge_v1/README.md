# Longitudinal challenge benchmark

12 patients / 24 visits; 4 patients per split. Synthetic, unreviewed.

| Test group | Mode | k | Precision (macro) | Recall (macro) | Stale selected |
|---|---|---:|---:|---:|---:|
| distractors | none | 1 | None | 0.0 | 0 |
| distractors | full_history | 1 | 0.25 | 1.0 | 0 |
| distractors | selective | 1 | 1.0 | 1.0 | 0 |
| distractors | selective | 3 | 1.0 | 1.0 | 0 |
| superseded | none | 1 | None | 0.0 | 0 |
| superseded | full_history | 1 | 0.225 | 1.0 | 1 |
| superseded | selective | 1 | 1.0 | 1.0 | 0 |
| superseded | selective | 3 | 1.0 | 1.0 | 0 |
| conflict | none | 1 | None | 0.0 | 0 |
| conflict | full_history | 1 | 0.5 | 1.0 | 0 |
| conflict | selective | 1 | 1.0 | 0.3333333333333333 | 0 |
| conflict | selective | 3 | 1.0 | 1.0 | 0 |
| paraphrase | none | 1 | None | 0.0 | 0 |
| paraphrase | full_history | 1 | 0.25 | 1.0 | 0 |
| paraphrase | selective | 1 | None | 0.0 | 0 |
| paraphrase | selective | 3 | None | 0.0 | 0 |

No model calls in memory audit. NA is represented by None. This measures retrieval, not diagnosis or clinical benefit.
Run plan_test.json for B0-B4; plan_test_costly.json changes test/interview/consult costs to exercise memory acquisition.
Do not tune on test. Use validation plan for pipeline debugging. See docs/challenge_benchmark.md.
