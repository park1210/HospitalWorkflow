"""One-command offline 7/9/10 demonstration and cost-sensitivity experiment."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from app.core.agent_registry import AgentRegistry
from app.core.longitudinal_runner import run_longitudinal
from app.core.routing_utility import fit_utility
from app.core.routing_evaluation import decisions_from_outcomes, evaluate_routing
from app.core.voi_evaluation import evaluate_voi

ROOT = Path(__file__).resolve().parents[2]


class OfflineOnly:
    def chat(self, *args, **kwargs):
        raise RuntimeError("Offline demo reached an unexpected LLM call; inspect the saved checkpoint.")


def save(path, value):
    with path.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)


def run_demo(output):
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    sources = {}

    def read(folder, name):
        path = ROOT / "app" / "data" / folder / (name + ".json")
        content = path.read_bytes()
        sources[str(path.relative_to(ROOT))] = hashlib.sha256(content).hexdigest()
        return json.loads(content)

    cases = read("voi_synthetic", "cases")
    memory = read("voi_synthetic", "memory")
    labels = read("voi_synthetic", "labels")
    model = read("voi_synthetic", "model")
    expensive = deepcopy(model)
    expensive["revision"] += ":cost-sensitivity"
    # Explicit synthetic scenario, not an estimate of clinical prices.
    for action in expensive["actions"]:
        if action["type"] == "request_test":
            action["cost"]["money"] = .4
        elif action["type"] in {"ask_patient", "consult_specialty"}:
            action["cost"]["money"] = 1.0
    profiles = [("cheap_test", "full_history", model),
                ("costly_test_no_memory", "none", expensive),
                ("costly_test_with_memory", "full_history", expensive)]
    summary = {"schema_version": 1, "status": "running", "synthetic": True,
               "review_status": "unreviewed", "new_llm_calls": 0,
               "scope": "7+10 simulator execution; 9 separate replay of recorded specialist probes",
               "profiles": [], "source_sha256": sources}
    save(output / "summary.json", summary)
    for name, mode, artifact in profiles:
        save(output / (name + ".model.json"), artifact)
        report = run_longitudinal(deepcopy(cases), mode=mode, memory_source="fixed",
                                  initial_memory=deepcopy(memory["records"]), voi_model=artifact,
                                  client=OfflineOnly(), minute_limit=30,
                                  checkpoint_callback=lambda value, n=name: save(output / (n + ".checkpoint.json"), value))
        save(output / (name + ".report.json"), report)
        evaluation = evaluate_voi(report, labels)
        save(output / (name + ".evaluation.json"), evaluation)
        traces = []
        for visit in report["visits"]:
            state = next(iter(visit["final_state"]["cases"].values()))
            selected = [r for r in state.get("voi_state", {}).get("history", []) if r.get("status") == "selected"]
            traces.append({"identity": visit["identity"], "actions": [r["selected_action"] for r in selected],
                           "rationales": [r["rationale"] for r in selected],
                           "memory_ids": [r["memory_id"] for r in state["memory_context"].get("records", [])]})
        row = {"name": name, "memory_mode": mode, "status": report["status"],
               "accuracy": evaluation["accuracy"], "mean_brier": evaluation["mean_brier"],
               "llm_calls": sum(r["llm_calls"] for r in evaluation["visits"]),
               "tests": sum(r["tests"] for r in evaluation["visits"]),
               "modeled_action_cost": sum(r["modeled_action_cost"] for r in evaluation["visits"]),
               "traces": traces}
        summary["profiles"].append(row)
        save(output / "summary.json", summary)
        expected = (["retrieve_memory", "request_test", "diagnose"] if name.endswith("with_memory")
                    else ["request_test", "diagnose"])
        if (report["status"] != "completed" or evaluation["accuracy"] != 1 or row["llm_calls"] != 0
                or len(traces) != len(cases) or any(t["actions"] != expected for t in traces)):
            raise RuntimeError(f"Unexpected demo trajectory in {name}; inspect report/checkpoint")
        print(f"{name}: {len(traces)} visits, accuracy={row['accuracy']}, LLM calls={row['llm_calls']}")

    manifest = read("research_synthetic_v1", "registry_local")
    training = read("research_synthetic_v1", "routing_train_bounded")
    heldout = read("research_synthetic_v1", "routing_test_bounded")
    utility = fit_utility(training, AgentRegistry(manifest), weights={"accuracy": 1., "cost": 0., "latency": .001})
    registry = AgentRegistry(manifest, utility)
    decisions = decisions_from_outcomes(heldout, registry)
    routing = evaluate_routing(decisions, registry.utility)
    departments = [a["department"] for a in manifest["agents"] if a["role"] == "specialty"]
    routing["routes"] = [{"patient_id": r["patient_id"], "decision_id": r["decision_id"],
                           **registry.route(r["observation"], departments, mode="adaptive")}
                          for r in heldout if r["agent_id"] == heldout[0]["agent_id"]]
    routing["scope"] = "Recorded LLM responses; no new specialist or patient generation"
    save(output / "routing.utility.json", utility)
    save(output / "routing.decisions.json", decisions)
    save(output / "routing.evaluation.json", routing)
    if routing["coverage"] != 1:
        raise RuntimeError("Incomplete routing replay coverage")
    summary.update(status="completed", routing=routing, elapsed_seconds=round(time.perf_counter() - started, 3))
    save(output / "summary.json", summary)
    lines = ["# 7·9·10 빠른 데모 결과", "", "합성·미검수 데이터. 7+10 실제 엔진 실행 / 9 저장된 LLM 응답 재평가.", "",
             "| 조건 | 기억 | 정확도 | LLM 호출 | 검사 수 | 모형 비용 합계 |", "|---|---|---:|---:|---:|---:|"]
    for row in summary["profiles"]:
        lines.append(f"| {row['name']} | {row['memory_mode']} | {row['accuracy']} | {row['llm_calls']} | {row['tests']} | {row['modeled_action_cost']:.3f} |")
    lines += ["", "## 의사결정 흐름", ""]
    for row in summary["profiles"]:
        lines.append(f"- {row['name']}: " + " → ".join(row["traces"][0]["actions"]))
    lines += ["", "## 9번 재평가", "", f"- Coverage: {routing['coverage']}; mean regret: {routing['mean_regret']}",
              "- 학습·평가 환자를 분리한 저장 응답 재현이며 새 LLM 실험이 아닙니다.", "",
              "## 해석", "", "- 비교 대상은 비용 조건과 기억 사용 여부입니다. VoI 미사용 대비 효과 실험이 아닙니다.",
              "- costly_test 두 조건은 같은 모형에서 기억 사용만 변경했습니다.",
              "- cheap_test와 costly_test는 검사·문진·협진 비용을 함께 변경한 시나리오입니다.",
              "- 기억 조회가 추가되어도 검사가 필수이면 전체 비용이 증가할 수 있습니다.",
              "- 정확도 1.0은 두 개의 설계된 합성 방문 결과이며 임상 성능 근거가 아닙니다.",
              "- 확률·효용, 입력 해시, 결정 근거, 원본 보고서는 같은 폴더의 JSON에 보존됩니다."]
    (output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=None, help="New directory; existing directories are rejected")
    args = parser.parse_args()
    output = args.output_dir or ROOT / "outputs" / "research_demo" / datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    try:
        result = run_demo(output)
    except Exception as exc:
        parser.exit(1, f"Demo failed: {exc}\nInspect partial artifacts: {output}\n")
    print(f"Completed in {result['elapsed_seconds']}s: {output / 'report.md'}")


if __name__ == "__main__":
    main()
