"""Write a factual research pilot summary from completed saved experiments."""
import argparse
import json
from pathlib import Path


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--longitudinal-dir", type=Path, required=True)
    p.add_argument("--memory-validation", type=Path, required=True)
    p.add_argument("--memory-test", type=Path, required=True)
    p.add_argument("--specialty-dir", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    read = lambda f: json.loads(f.read_text(encoding="utf-8"))
    longitudinal = read(args.longitudinal_dir / "results.json")
    manifest = read(args.longitudinal_dir / "manifest.json")
    expected_runs = {f"{condition}_r{repeat + 1:02d}" for condition in manifest["conditions"]
                     for repeat in range(manifest["plan"]["repeats"])}
    if {r["run"] for r in longitudinal["runs"]} != expected_runs:
        raise ValueError("Experiment still running or missing planned runs; do not summarize as final")
    memories = {"validation": read(args.memory_validation), "test": read(args.memory_test)}
    specialty = read(args.specialty_dir / "summary.json")
    routes = {s: read(args.specialty_dir / (s + ".routing.json")) for s in ("validation", "test")}
    cases = read(args.specialty_dir / "test.outcomes.json")
    training = read(args.specialty_dir / "train.outcomes.json")
    weights = read(args.specialty_dir / "utility.json")["weights"]
    fixed_scores = {}
    for agent in sorted({r["agent_id"] for r in training}):
        selected = [r for r in training if r["agent_id"] == agent]
        if any(r["cost"] is None for r in selected):
            raise ValueError("Fixed-specialist baseline needs complete training costs")
        fixed_scores[agent] = sum(weights["accuracy"] * r["correct"] - weights["cost"] * r["cost"]
                                  - weights["latency"] * r["latency_seconds"] for r in selected) / len(selected)
    fixed_agent = min(fixed_scores, key=lambda a: (-fixed_scores[a], a))
    fixed_cases = [r for r in cases if r["agent_id"] == fixed_agent]
    fixed_baseline = dict(agent=fixed_agent, selection="highest training mean utility; never selected using test",
                          training_mean_utility=fixed_scores, test_cases=len(fixed_cases),
                          test_accuracy=sum(r["correct"] for r in fixed_cases) / len(fixed_cases))
    outcomes = {}
    for r in cases:
        outcomes.setdefault((r["patient_id"], r["decision_id"]), {})[r["agent_id"]] = r["correct"]
    failed = []
    for file in sorted(args.longitudinal_dir.glob("*.report.json")):
        for visit in read(file)["visits"]:
            for state in visit["final_state"]["cases"].values():
                for row in state.get("llm_audit", []):
                    if row["status"] == "error":
                        failed.append(dict(run=file.stem, identity=visit["identity"], role=row["role"],
                                           category=row.get("failure_category"), error=row.get("validation_error", row.get("error_type"))))
    result = dict(longitudinal_status=longitudinal["status"], longitudinal_table=longitudinal["table"],
                  memory={s: [r for r in m["summary"] if r["group"] == "ALL"] for s, m in memories.items()},
                  specialty=specialty, routing=routes, failures=failed,
                  fixed_specialist_baseline=fixed_baseline,
                  specialist_test_pairs=[dict(patient=p, decision=d, correct=v) for (p, d), v in outcomes.items()])
    args.output_dir.mkdir(parents=True, exist_ok=False)
    (args.output_dir / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    fmt = lambda v: "NA" if v is None else f"{v:.3f}"
    lines = ["# 고정 설정 연구 파일럿 결과", "", "합성·미검수 자료. 임상 성능 검증이나 통계적 비열등성 입증이 아닙니다.",
             "", "## 실제 임베딩 검색", "", "| Split | 검색 | k | Precision | Recall | Precision coverage |", "|---|---|---:|---:|---:|---:|"]
    for split, rows in result["memory"].items():
        for r in rows:
            lines.append(f"| {split} | {r['method']} | {r['top_k']} | {fmt(r['precision'])} | {fmt(r['recall'])} | {fmt(r['precision_coverage'])} |")
    lines += ["", "검증 자료에서 precision/정보량을 고려해 semantic top-k=1을 선택한 후 test에 적용했습니다. 충돌 사례의 정보 누락 가능성은 남습니다.",
              "", "## 전문과 단서 평가", "", "| Split | 모델 | 정답/사례 | 호출 실패 | 평균 지연(초) |", "|---|---|---:|---:|---:|"]
    for r in specialty:
        lines.append(f"| {r['split']} | {r['agent']} | {r['correct']}/{r['cases']} | {r['failed']} | {r['mean_latency']:.3f} |")
    lines += ["", "후보 모델에는 동일한 관측과 진단 목록을 제공했습니다. 단서 템플릿은 split 간 공유되어 외부 일반화 근거가 아닙니다.",
              "", "### Test 라우팅", "", "| Router | Seed | Coverage | Regret | 선택 정답률 |", "|---|---:|---:|---:|---:|"]
    for r in routes["test"]["results"]:
        lines.append(f"| {r['mode']} | {r['seed']} | {fmt(r['evaluation']['coverage'])} | {fmt(r['evaluation']['mean_regret'])} | {fmt(r['selected_accuracy'])} |")
    lines += ["", f"학습 평균 효용으로 선택한 고정 전문과: {fixed_agent}; test 정답률 {fixed_baseline['test_accuracy']:.3f}. 적응형 라우팅의 이득은 이 기준선과도 비교해야 합니다."]
    lines += ["", "전문과 평가는 CPU 실행이며 로딩 지연도 포함됩니다. 비용은 로컬 API 단가 기준입니다. 이 라우터를 무관한 합성 A/B 과제에 전이하지 않았습니다.",
              "", "## B0–B4 test 반복", "", "| 조건 | 방문×반복 | 완료율 | 전체 정답률 | 완료 방문 정답률 | 행동/방문 | 호출/방문 |", "|---|---:|---:|---:|---:|---:|---:|"]
    for r in longitudinal["table"]:
        lines.append(f"| {r['condition']} | {r['planned_visit_runs']} | {fmt(r['completed'])} | {fmt(r['correct_all_planned'])} | {fmt(r['correct_completed'])} | {fmt(r['actions'])} | {fmt(r['llm_calls'])} |")
    lines += ["", "평균의 결측 coverage와 환자 단위 paired 구간은 원본 table.csv/results.json을 함께 확인하세요. 실패·미실행은 전체 정답률 분모에 남깁니다.",
              "", "## 호출 실패", ""]
    lines += [f"- {r['run']} / {r['identity']['patient_id']} / {r['identity']['visit_id']}: {r['category']} — {r['error']}" for r in failed] or ["- 저장된 보고서의 호출 실패 없음."]
    lines += ["", "## 논문 해석 한계", "", "- Test는 4명·8방문이며 반복 3회가 독립 환자를 늘리지는 않습니다.",
              "- 진단 후보는 두 개이고 검사 T가 강한 단서를 제공합니다. VoI의 일반적인 진단 우위를 입증하지 않습니다.",
              "- 전문과 비교는 별도의 4개 질환 단서 과제입니다. 전체 다회 방문 임상 협진 효용과 동일하지 않습니다.",
              "- Stale 오용과 임상 라벨·확률·비용은 전문가 검수가 필요합니다."]
    (args.output_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(args.output_dir / "report.md")


if __name__ == "__main__":
    main()
