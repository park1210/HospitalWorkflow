# Challenge v4

Frozen synthetic process-discriminative challenge.

Evaluation set:
- 40 patients
- 40 independent visits
- 10 baseline
- 10 memory-critical
- 10 routing-critical
- 10 VoI-critical

Key design:
- baseline has explicit decisive objective evidence
- memory-critical needs current objective evidence plus longitudinal context
- routing-critical requires specialty-gated objective testing
- VoI-critical contrasts low-information and high-information tests
- global modeled memory action is excluded to avoid unsupported categorical memory observations
- decisive likelihoods are checked against the stopping threshold before generation

Synthetic and not clinically reviewed.
The test set must not be tuned after viewing final experimental results.
