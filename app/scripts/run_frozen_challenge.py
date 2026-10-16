"""Run a declared fixed validation/test protocol sequentially, without tuning on test."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.request import urlopen

from app.core.embedding_builder import build_embeddings
from app.scripts.run_paper_experiments import prepare

ROOT = Path(__file__).resolve().parents[2]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--protocol", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--validation-embeddings", type=Path, required=True)
    p.add_argument("--endpoint", default="http://localhost:11434")
    p.add_argument("--execute", action="store_true")
    args = p.parse_args()
    read = lambda f: json.loads(Path(f).read_text(encoding="utf-8"))
    protocol = read(args.protocol)
    print("Fixed protocol: validation 1 repeat; test 3 repeats; semantic k=1; no retries.", flush=True)
    if (protocol["repeats_validation"], protocol["repeats_test"], protocol["top_k"], protocol["conditions"]) != (1, 3, 1, ["B0", "B1", "B2", "B3", "B4"]):
        raise ValueError("This pilot launcher requires the declared 1/3-repeat k=1 protocol")
    if not args.execute:
        return
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    save = lambda f, x: Path(f).write_text(json.dumps(x, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    save(out / "protocol.json", protocol)
    with urlopen(args.endpoint.rstrip("/") + "/api/tags", timeout=10) as stream:
        installed = json.load(stream)
    save(out / "installed_models.json", installed)
    actual = {m["name"]: m["digest"] for m in installed["models"]}
    if actual.get(protocol["embedding_model"]) != protocol["embedding_digest"]:
        raise ValueError("Embedding digest mismatch")
    registry = read(ROOT / "app/data/challenge_v1/registry.json")
    for agent in registry["agents"]:
        name = agent["model"] if ":" in agent["model"] else agent["model"] + ":latest"
        if actual.get(name) != agent["version"]:
            raise ValueError("Installed agent digest mismatch: " + name)
    validation_vectors = read(args.validation_embeddings)
    if validation_vectors["model_id"] != protocol["embedding_model"] or validation_vectors["revision"] != protocol["embedding_digest"]:
        raise ValueError("Validation embeddings differ from frozen model")
    save(out / "embeddings_validation.json", validation_vectors)
    memory = read(ROOT / "app/data/challenge_v1/memory.json")
    cases = read(ROOT / "app/data/challenge_v1/cases_test.json")
    print("Building test embeddings (no labels sent)...", flush=True)
    vectors = build_embeddings(memory["records"], cases, model=protocol["embedding_model"], revision=protocol["embedding_digest"], endpoint=args.endpoint)
    save(out / "embeddings_test.json", vectors)
    env = os.environ.copy()
    env.update(OLLAMA_BASE_URL=args.endpoint.rstrip("/") + "/v1", SPECIALTY_BASE_URL=args.endpoint.rstrip("/") + "/v1",
               TEMPERATURE=str(protocol["temperature"]), LLM_MAX_OUTPUT_TOKENS=str(protocol["max_output_tokens"]))
    def command(module, *arguments):
        return subprocess.run([sys.executable, "-u", "-m", module, *map(str, arguments)], cwd=ROOT, env=env).returncode
    code = command("app.scripts.compare_memory_retrieval", "--cases", ROOT / "app/data/challenge_v1/cases_test.json",
        "--memory", ROOT / "app/data/challenge_v1/memory.json", "--annotations", ROOT / "app/data/challenge_v1/annotations_test.json",
        "--scenarios", ROOT / "app/data/challenge_v1/scenarios.json", "--embeddings", out / "embeddings_test.json", "--top-k", 1,
        "--output-dir", out / "memory_test")
    if code:
        raise RuntimeError("Test retrieval validation failed")
    statuses = []
    for split, repeats in (("validation", 1), ("test", 3)):
        source = ROOT / f"app/data/challenge_v1/plan_{split}.json"
        plan = read(source)
        plan["inputs"] = {k: str((source.parent / v).resolve()) for k, v in plan["inputs"].items()}
        plan["inputs"]["embeddings"] = str(out / f"embeddings_{split}.json")
        plan.update(retrieved_mode="semantic", top_k=protocol["top_k"], repeats=repeats, minute_limit=protocol["minute_limit"])
        if Path(plan["inputs"]["voi_model"]).resolve() != (ROOT / protocol["voi_model"]).resolve() or Path(plan["inputs"]["routing_utility"]).resolve() != (ROOT / protocol["routing_utility"]).resolve():
            raise ValueError("Plan model differs from frozen protocol")
        target = out / f"plan_{split}.json"
        save(target, plan)
        prepare(target)
        print(f"Running {split}: 8 visits x 5 conditions x {repeats} repeats", flush=True)
        code = command("app.scripts.run_paper_experiments", "--plan", target, "--execute", "--output-dir", out / split)
        statuses.append(dict(split=split, exit_code=code, plan_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
        save(out / "stages.json", statuses)
    print(json.dumps(statuses), flush=True)
    if any(r["exit_code"] for r in statuses):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
