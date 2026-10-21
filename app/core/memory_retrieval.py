"""Offline vector retrieval with explicit artifact provenance, no model calls."""
import hashlib
import json
import math
from copy import deepcopy


class MemoryEmbeddings:
    def __init__(self, payload):
        if not isinstance(payload, dict) or set(payload) != {"model_id", "revision", "records", "queries"}:
            raise ValueError("Embedding artifact requires model_id, revision, records, queries")
        if any(not isinstance(payload[k], str) or not payload[k].strip() for k in ("model_id", "revision")):
            raise ValueError("Embedding model provenance is required")
        if not isinstance(payload["records"], dict) or not isinstance(payload["queries"], dict):
            raise ValueError("Embedding records and queries must be mappings")
        self.payload = deepcopy(payload)
        for group in (payload["records"], payload["queries"]):
            for key, row in group.items():
                if (not isinstance(key, str) or not key or not isinstance(row, dict)
                        or set(row) != {"text_sha256", "vector"}
                        or not isinstance(row["text_sha256"], str) or len(row["text_sha256"]) != 64):
                    raise ValueError("Embedding entries require a text hash and vector")
        vectors = [v["vector"] for group in (payload["records"], payload["queries"]) for v in group.values()]
        dimension = None
        for vector in vectors:
            if not isinstance(vector, list) or not vector or any(type(x) not in (int, float) or not math.isfinite(x) for x in vector):
                raise ValueError("Embedding must contain finite numeric values")
            dimension = dimension or len(vector)
            if len(vector) != dimension or not math.isfinite(math.hypot(*vector)) or math.hypot(*vector) == 0:
                raise ValueError("Embedding dimensions/norm invalid")
        self.fingerprint = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    @staticmethod
    def text_hash(text):
        return hashlib.sha256(text.encode()).hexdigest()

    def scores(self, records, query, key):
        # State-expanded queries may have several versions during one encounter.
        query_row = self.payload["queries"].get(self.text_hash(query), self.payload["queries"].get(key))
        if query_row is None or query_row.get("text_sha256") != self.text_hash(query):
            raise ValueError("Missing or mismatched query embedding")
        q = query_row["vector"]
        q_norm = math.hypot(*q)
        scores = {}
        for row in records:
            item = self.payload["records"].get(row["memory_id"])
            if item is None or item.get("text_sha256") != self.text_hash(row["text"]):
                raise ValueError("Missing or mismatched memory embedding")
            v = item["vector"]
            v_norm = math.hypot(*v)
            scores[row["memory_id"]] = sum((a / q_norm) * (b / v_norm) for a, b in zip(q, v))
        return scores
