# Memory retrieval comparison

Saved embeddings are supplied artifacts. Retrieval relevance depends on supplied gold annotations. Full history is reported separately from fixed Top-K strategies. Semantic retrieval retains the existing positive-cosine filter. Scores do not establish clinical validity.

Embedding model: embeddinggemma
New model calls: 0

| Group | Method | K | P@K | R@K | MRR | Hit@K |
|---|---|---:|---:|---:|---:|---:|
| ALL | none | 1 | 0.0 | 0.0 | 0.0 | 0.0 |
| ALL | full_history | None | 0.30625 | 1.0 | 0.9 | 1.0 |
| ALL | lexical | 1 | 0.75 | 0.5833333333333333 | 0.75 | 0.75 |
| ALL | saved_model_vectors | 1 | 1.0 | 0.8333333333333333 | 1.0 | 1.0 |
| ALL | lexical | 3 | 0.41666666666666663 | 0.75 | 0.75 | 0.75 |
| ALL | saved_model_vectors | 3 | 0.5 | 1.0 | 1.0 | 1.0 |
| ALL | lexical | 5 | 0.25 | 0.75 | 0.75 | 0.75 |
| ALL | saved_model_vectors | 5 | 0.30000000000000004 | 1.0 | 1.0 | 1.0 |
| unspecified | none | 1 | 0.0 | 0.0 | 0.0 | 0.0 |
| unspecified | full_history | None | 0.30625 | 1.0 | 0.9 | 1.0 |
| unspecified | lexical | 1 | 0.75 | 0.5833333333333333 | 0.75 | 0.75 |
| unspecified | saved_model_vectors | 1 | 1.0 | 0.8333333333333333 | 1.0 | 1.0 |
| unspecified | lexical | 3 | 0.41666666666666663 | 0.75 | 0.75 | 0.75 |
| unspecified | saved_model_vectors | 3 | 0.5 | 1.0 | 1.0 | 1.0 |
| unspecified | lexical | 5 | 0.25 | 0.75 | 0.75 | 0.75 |
| unspecified | saved_model_vectors | 5 | 0.30000000000000004 | 1.0 | 1.0 | 1.0 |
