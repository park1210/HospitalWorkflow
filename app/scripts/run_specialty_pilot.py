"""Explicit opt-in local specialist cue-probe collection; synthetic and unreviewed."""
import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from app.core.agent_registry import AgentRegistry
from app.core.routing_collection import collect_outcomes
from app.core.routing_utility import fit_utility
from app.scripts.compare_routing_baselines import compare
from app.llm.ollama_probe_client import OllamaProbeClient

ROOT = Path(__file__).resolve().parents[2]


def save(path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    temp.replace(path)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--execute", action="store_true")
    p.add_argument("--endpoint", default="http://localhost:11434")
    args = p.parse_args()
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=False)
    read = lambda name: json.loads((ROOT / name).read_text(encoding="utf-8"))
    names = ["Myasthenia gravis", "Benign Paroxysmal Positional Vertigo (BPPV)", "Tuberculosis", "Neonatal Respiratory Distress Syndrome (NRDS)"]
    files = ["app/data/high_signal_diagnosis_rules.json", "app/data/evidence_diagnosis_hints.json"]
    hints = {r["diagnosis"]: r for f in files for r in read(f)}
    probes = []
    for split_index, split in enumerate(("train", "validation", "test")):
        for index, name in enumerate(names):
            groups = hints[name]["keyword_groups"]
            # Alternate literal source clues, not clinician-authored patient records.
            clues = [g[split_index % len(g)] for g in groups]
            if split_index == 1:
                clues = list(reversed(clues))
            probes.append(dict(patient_id=f"specialty-cue-{split}-{index}", decision_id="assessment", split=split,
                diagnosis_catalog=names + ["Unresolved"], expected_diagnoses=[name],
                observation={"chief_complaint": "Fictional case: identify the most supported diagnosis from the recorded clinical clues.",
                    "history": [{"question": "What clues were recorded?", "answer": "; ".join(clues), "answer_status": "provided"}]}))
    save(out / "probes.json", probes)
    registry = read("app/data/research_synthetic_v1/registry_local.json")
    prices = read("app/data/research_synthetic_v1/prices_local_api_only.json")
    save(out / "registry.json", registry)
    save(out / "prices.json", prices)
    save(out / "provenance.json", dict(synthetic=True, review_status="unreviewed", patients=12, probes=12,
        source_sha256={f: hashlib.sha256((ROOT / f).read_bytes()).hexdigest() for f in files},
        limitations=["Source keyword-derived cue probes; not natural clinical vignettes", "Patient IDs disjoint, disease cue templates shared across splits",
                     "Diagnosis catalog shared across candidates", "4 probes per split is a pilot, not a clinical benchmark",
                     "CPU-only inference; cost is declared local API fee, not hardware/electricity", "Weights fixed before test: accuracy=1, cost=0, latency=0.001"]))
    print("Prepared 12 probes, 2 specialists, 24 calls; CPU-only. Synthetic unreviewed.", flush=True)
    if not args.execute:
        return
    with urlopen(args.endpoint.rstrip("/") + "/api/tags", timeout=10) as response:
        tags = json.load(response)
    installed = {m["name"]: m["digest"] for m in tags["models"]}
    for agent in registry["agents"]:
        model = agent["model"] if ":" in agent["model"] else agent["model"] + ":latest"
        if installed.get(model) != agent["version"]:
            raise ValueError("Installed model/version mismatch: " + model)
    save(out / "installed_models.json", tags)
    def checkpoint(rows):
        save(out / "outcomes.partial.json", rows)
        r = rows[-1]
        print(f"{len(rows)}/24 {r['agent_id']} {r['patient_id']} status={r['audit'][-1]['status']} correct={r['correct']}", flush=True)
    rows = collect_outcomes(probes, AgentRegistry(registry), OllamaProbeClient(args.endpoint, cpu=True, max_tokens=192), prices, checkpoint_callback=checkpoint)
    save(out / "outcomes.json", rows)
    by_split = {s: [r for r in rows if r["split"] == s] for s in ("train", "validation", "test")}
    for split, split_rows in by_split.items():
        save(out / (split + ".outcomes.json"), split_rows)
    utility = fit_utility(by_split["train"], AgentRegistry(registry), weights={"accuracy": 1., "cost": 0., "latency": .001})
    save(out / "utility.json", utility)
    fitted = AgentRegistry(registry, utility)
    for split in ("validation", "test"):
        save(out / (split + ".routing.json"), compare(by_split[split], fitted))
    summary = []
    for split, values in by_split.items():
        for agent in sorted({r["agent_id"] for r in values}):
            selected = [r for r in values if r["agent_id"] == agent]
            summary.append(dict(split=split, agent=agent, cases=len(selected), correct=sum(r["correct"] for r in selected),
                                failed=sum(r["answer"] is None for r in selected),
                                mean_latency=sum(r["latency_seconds"] for r in selected) / len(selected)))
    save(out / "summary.json", summary)
    print(json.dumps(summary), flush=True)


if __name__ == "__main__":
    main()
