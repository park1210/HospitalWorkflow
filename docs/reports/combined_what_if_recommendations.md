# Combined What-If Recommendations

- source_run_id: `20260526_234422`
- case_recommendation_count: `19`

| case_id | type | bucket | score | predicted_dept | action | note |
|---|---|---|---:|---|---|---|
| case_0009 | routing | priority_replay | 8.00 | nephrology | handoff_department:obstetrics_gynecology | A concrete alternative specialty is already present in the ER routing shortlist. | The ER working diagnosis is still generic. |
| case_0024 | routing | priority_replay | 8.00 | pulmonology | handoff_department:obstetrics_gynecology | A concrete alternative specialty is already present in the ER routing shortlist. | The ER working diagnosis is still generic. |
| case_0025 | routing | priority_replay | 8.00 | hematology | handoff_department:gastroenterology | A concrete alternative specialty is already present in the ER routing shortlist. | The ER working diagnosis is still generic. |
| case_0055 | specialty | priority_replay | 5.00 | dermatology | refine_again: | Multiple specialty candidates remain at finalize, so one more refinement pass may recover an exact diagnosis. | Current specialty diagnosis is still generic. |
| case_0070 | routing | review_candidate/review_high | 6.00 | infectious_disease | handoff_department:dermatology | A concrete alternative specialty is already present in the ER routing shortlist. | The ER working diagnosis is still generic. |
| case_0005 | specialty | review_candidate/review_high | 3.75 | orthopedics | refine_again: | A divergent exact specialty candidate remains unresolved at finalize. | Objective evidence is already substantial. |
| case_0034 | routing | review_candidate/review_low | 6.00 | infectious_disease | handoff_department:dermatology | A concrete alternative specialty is already present in the ER routing shortlist. | The ER working diagnosis is still generic. |
| case_0049 | routing | review_candidate/review_low | 5.50 | hematology | handoff_department:infectious_disease | A concrete alternative specialty is already present in the ER routing shortlist. | The ER working diagnosis is still generic. |
| case_0057 | routing | review_candidate/review_low | 5.50 | hematology | handoff_department:psychiatry | A concrete alternative specialty is already present in the ER routing shortlist. | The ER working diagnosis is still generic. |
| case_0090 | routing | review_candidate/review_low | 5.50 | infectious_disease | handoff_department:neurology | A concrete alternative specialty is already present in the ER routing shortlist. | The ER working diagnosis is still generic. |