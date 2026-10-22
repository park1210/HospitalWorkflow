"""Call each registered specialty on offline probes; this command incurs model calls."""
import argparse
import json
from pathlib import Path
from app.config import settings
from app.core.agent_registry import AgentRegistry
from app.core.routing_collection import collect_outcomes
from app.llm.ollama_client import OllamaClient
from app.llm.ollama_probe_client import OllamaProbeClient


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("probes", "registry", "prices", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    p.add_argument("--native-endpoint", help="Optional native Ollama URL for explicit CPU probing")
    p.add_argument("--cpu", action="store_true")
    p.add_argument("--diagnosis-catalog", type=Path, help="One shared diagnosis list for every probe; Unresolved is added")
    args = p.parse_args()
    if args.output.exists():
        raise ValueError("Choose a new output file")
    read = lambda path: json.loads(path.read_text(encoding="utf-8"))
    if args.cpu and not args.native_endpoint:
        p.error("--cpu requires --native-endpoint")
    client = (OllamaProbeClient(args.native_endpoint, cpu=args.cpu) if args.native_endpoint else
              OllamaClient(base_url=settings.SPECIALTY_BASE_URL, api_key=settings.SPECIALTY_API_KEY))
    probes = read(args.probes)
    if args.diagnosis_catalog:
        catalog = read(args.diagnosis_catalog)
        if (not isinstance(catalog, list) or not catalog
                or any(not isinstance(s, str) or not s.strip() or len(s) > 80 for s in catalog)
                or len(set(catalog)) != len(catalog)):
            raise ValueError("Shared diagnosis catalog requires unique nonempty strings of at most 80 characters")
        catalog = list(catalog) + ([] if "Unresolved" in catalog else ["Unresolved"])
        for probe in probes:
            probe["diagnosis_catalog"] = list(catalog)
    rows = collect_outcomes(probes, AgentRegistry(read(args.registry)),
                            client, read(args.prices))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(rows, stream, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
