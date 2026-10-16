"""Generate versioned vectors; lexical default is not a clinical semantic model."""
import argparse
import json
from pathlib import Path
from app.core.embedding_builder import build_embeddings


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--memory", type=Path, required=True)
    p.add_argument("--cases", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--model", default="lexical-hash-256")
    p.add_argument("--revision", default="v1")
    p.add_argument("--endpoint", help="Native Ollama base URL, e.g. http://localhost:11434")
    p.add_argument("--cpu", action="store_true", help="Disable GPU offload for native Ollama embeddings")
    args = p.parse_args()
    if args.output.exists():
        raise ValueError("Choose a new output file")
    memory = json.loads(args.memory.read_text(encoding="utf-8"))
    if memory.get("schema_version") != 1:
        raise ValueError("Unsupported memory schema")
    result = build_embeddings(memory["records"], json.loads(args.cases.read_text(encoding="utf-8")),
                              model=args.model, revision=args.revision, endpoint=args.endpoint, cpu=args.cpu)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
