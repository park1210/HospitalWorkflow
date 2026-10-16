"""Chapters 7/8: reproducible finite-cohort experiments and honest readiness reports."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import platform
import random
import re
import subprocess
from typing import Any

from app.core.hospital_evaluation import distribution, paired_comparison
from app.core.hospital_flow import flow_config, schedule_arrivals
from app.core.hospital_parallel_runner import run_parallel_scheduler_preview


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def provenance(root: Path) -> dict[str, Any]:
    paths = sorted(p for p in (root / "app").rglob("*") if p.is_file() and p.suffix in {".py", ".json"})
    paths += [p for p in (root / "requirements.txt", root / "AGENTS.md") if p.is_file()]
    files = {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    def git(*args):
        try:
            result = subprocess.run(["git", *args], cwd=str(root), text=True, capture_output=True, timeout=10)
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None
    return {"python": platform.python_version(), "platform": platform.platform(),
            "git_head": git("rev-parse", "HEAD"), "git_status": git("status", "--short"),
            "source_digest": digest(files), "source_file_sha256": files,
            "policy_id": "parallel_demo_policy", "llm_calls": 0,
            "scope": "app Python/JSON + requirements + AGENTS; no environment secrets captured"}


def validate_plan(plan: dict[str, Any]) -> dict[str, Any]:
    allowed = {"schema_version", "case_counts", "seeds", "minute_limit", "arrival_conditions", "resource_conditions"}
    if not isinstance(plan, dict) or set(plan) != allowed or plan["schema_version"] != 1:
        raise ValueError("Experiment plan requires the documented schema_version=1 fields")
    for field, positive in (("case_counts", True), ("seeds", False)):
        values = plan[field]
        if not isinstance(values, list) or not values or any(isinstance(v, bool) or not isinstance(v, int)
            or (positive and v <= 0) for v in values) or len(values) != len(set(values)):
            raise ValueError(f"Invalid unique integer list: {field}")
    if isinstance(plan["minute_limit"], bool) or not isinstance(plan["minute_limit"], int) or plan["minute_limit"] <= 0:
        raise ValueError("minute_limit must be positive")
    for field in ("arrival_conditions", "resource_conditions"):
        rows = plan[field]
        if not isinstance(rows, list) or not rows:
            raise ValueError(f"{field} must be a nonempty list")
        names = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("name"), str) or not re.fullmatch(r"[A-Za-z0-9_-]+", row["name"]):
                raise ValueError("Condition names must be safe identifiers")
            if row["name"] in names:
                raise ValueError("Duplicate condition name")
            names.add(row["name"])
            if field == "arrival_conditions":
                if set(row) != {"name", "arrival"} or not isinstance(row["arrival"], dict) or "seed" in row["arrival"]:
                    raise ValueError("Arrival condition needs arrival configuration; seed comes from seeds")
                flow_config({"arrival": row["arrival"]})
            else:
                if set(row) != {"name", "flow_config"} or not isinstance(row["flow_config"], dict):
                    raise ValueError("Resource condition needs flow_config")
                if set(row["flow_config"]) - {"capacities", "simulation"}:
                    raise ValueError("Resource experiment may change only capacities or resource_mode")
                flow_config(row["flow_config"])
    return deepcopy(plan)


def readiness(cases: list[dict[str, Any]], counts: list[int]) -> dict[str, Any]:
    requirements = {"gold_diagnosis": [], "gold_department": [], "required_tests": [],
                    "considered_tests": [], "acceptable_consultations": [], "critical_actions": [],
                    "critical_patient": [], "deterioration_at_risk": [], "at_risk_deterioration_model": []}
    for case in cases:
        cid, gold = case["case_id"], case.get("gold_label", {})
        annotation = case.get("evaluation", {})
        for label in ("diagnosis", "department"):
            if not gold.get(label):
                requirements["gold_" + label].append(cid)
        for field in ("required_tests", "considered_tests", "acceptable_consultations", "critical_actions"):
            if field not in annotation.get("workflow", {}):
                requirements[field].append(cid)
        for field in ("critical_patient", "deterioration_at_risk"):
            if field not in annotation:
                requirements[field].append(cid)
        if annotation.get("deterioration_at_risk") is True and not case.get("temporal_profile", {}).get("flow_deterioration"):
            requirements["at_risk_deterioration_model"].append(cid)
    return {"available_case_count": len(cases), "missing_annotations": requirements,
        "unavailable_case_counts": [n for n in counts if n > len(cases)],
        "chapter7_experiments": {
            "1_static_vs_sequential": {"status": "blocked", "reason": "Need matched static QA outputs and an independent sequential policy; not simulated here"},
            "2_base_vs_lora": {"status": "blocked", "reason": "This runner has no Base/LoRA inference adapter or independently evaluated model outputs"},
            "3_process_quality": {"status": "partial", "reason": "Chapter 5 metrics exist; multi-LLM controlled runs and gold workflows still required"},
            "4_multi_patient": {"status": "executable_demo", "reason": "Finite-cohort load experiment, not Medical LLM robustness evidence"},
            "5_resource_constraint": {"status": "executable_demo", "reason": "Finite-cohort no-contention reference vs constrained pools"}},
        "research_claims": {"independent_clinical_accuracy": False, "lora_improvement": False,
                            "clinical_safety_validated": False, "chapter4_extensions_added": False}}


def run_experiments(cases: list[dict[str, Any]], plan: dict[str, Any]) -> dict[str, Any]:
    plan = validate_plan(plan)
    if not cases:
        raise ValueError("A nonempty case dataset is required")
    # Validate all source cases before any run; never fill labels from demo hints.
    cases = schedule_arrivals(cases, flow_config())
    ready = readiness(cases, plan["case_counts"])
    runs, comparisons, skipped = [], [], []
    for seed in plan["seeds"]:
        cohort = deepcopy(cases)
        random.Random(seed).shuffle(cohort)
        for count in plan["case_counts"]:
            if count > len(cohort):
                skipped.append({"seed": seed, "case_count": count, "reason": "insufficient_unique_cases"})
                continue
            for arrival in plan["arrival_conditions"]:
                paired_runs = []
                for resource in plan["resource_conditions"]:
                    config = deepcopy(resource["flow_config"])
                    config["arrival"] = {**arrival["arrival"], "seed": seed}
                    run_id = f"n{count}_{arrival['name']}_seed{seed}_{resource['name']}"
                    run = run_parallel_scheduler_preview(deepcopy(cohort[:count]),
                        minute_limit=plan["minute_limit"], run_id=run_id, config=config, retain_snapshots=False)
                    run["run_id"] = run_id
                    run["experiment"] = {"case_count": count, "seed": seed,
                        "arrival_condition": arrival["name"], "resource_condition": resource["name"],
                        "case_ids": [c["case_id"] for c in run["source_cases"]],
                        "realized_case_digest": digest(run["source_cases"]),
                        "condition_digest": digest({"flow_config": run["flow_config"], "minute_limit": plan["minute_limit"]}),
                        "replay_digest": digest(run["final_state"])}
                    runs.append(run)
                    paired_runs.append(run)
                for right in paired_runs[1:]:
                    left = paired_runs[0]
                    comparisons.append({"left_run_id": left["run_id"], "right_run_id": right["run_id"],
                        "controlled_factors": "identical cohort/arrivals/annotations, durations, priority and policy; only resource configuration changes",
                        "comparison": paired_comparison(left["evaluation_metrics"], right["evaluation_metrics"])})
    summaries = []
    for count in plan["case_counts"]:
        for arrival in plan["arrival_conditions"]:
            for resource in plan["resource_conditions"]:
                matched = [r for r in runs if r["experiment"]["case_count"] == count
                           and r["experiment"]["arrival_condition"] == arrival["name"]
                           and r["experiment"]["resource_condition"] == resource["name"]]
                if not matched:
                    continue
                metrics = {}
                for group, entries in matched[0]["evaluation_metrics"]["groups"].items():
                    for name in entries:
                        values = [r["evaluation_metrics"]["groups"][group][name]["value"] for r in matched]
                        metrics[name] = {"available_runs": sum(v is not None for v in values), "total_runs": len(values),
                            "run_value_distribution": distribution([v for v in values if v is not None])}
                metrics["wte"] = {"available_runs": sum(r["flow_metrics"]["wte"] is not None for r in matched),
                    "total_runs": len(matched), "run_value_distribution": distribution(
                        [r["flow_metrics"]["wte"] for r in matched if r["flow_metrics"]["wte"] is not None])}
                operational = {}
                for section, field in (("resource_groups", "utilization"), ("queues", "mean_queue_length")):
                    names = set().union(*(r["flow_metrics"][section] for r in matched))
                    operational[section] = {name: distribution([
                        r["flow_metrics"][section][name][field] for r in matched
                        if name in r["flow_metrics"][section] and r["flow_metrics"][section][name][field] is not None])
                        for name in sorted(names)}
                summaries.append({"case_count": count, "arrival_condition": arrival["name"],
                    "resource_condition": resource["name"], "runs": len(matched),
                    "completed_runs": sum(r["flow_metrics"]["termination"] == "completed" for r in matched),
                    "distinct_realized_cohorts": len({r["experiment"]["realized_case_digest"] for r in matched}),
                    "metrics": metrics, "operational_distributions": operational})
    return {"schema_version": 1, "plan": plan, "plan_digest": digest(plan), "dataset_digest": digest(cases),
            "readiness": ready, "runs": runs, "paired_resource_comparisons": comparisons,
            "condition_summaries": summaries, "skipped": skipped,
            "interpretation": "descriptive finite demo runs; no significance, independence, optimality or clinical claims; no composite score"}


def render_summary(result: dict[str, Any]) -> str:
    lines = ["# 7장 실험 실행 결과", "", "병렬 데모 흐름 실험입니다. 독립적인 LLM·임상 성능 평가가 아닙니다.", "",
             f"실행 {len(result['runs'])}개, 생략 {len(result['skipped'])}개. 종합 점수·유의성 검정을 생성하지 않습니다.", "",
             "| 환자 수 | 도착 조건 | 자원 조건 | 완료 실행/전체 | 평균 최초 대기* | 평균 진단시간* |",
             "|---|---|---|---|---|---|"]
    for row in result["condition_summaries"]:
        def value(name):
            metric = row["metrics"][name]
            val = metric["run_value_distribution"]["mean"]
            return f"{val:.3f} ({metric['available_runs']}/{metric['total_runs']})" if val is not None else "N/A"
        lines.append(f"| {row['case_count']} | {row['arrival_condition']} | {row['resource_condition']} | "
                     f"{row['completed_runs']}/{row['runs']} | {value('mwt')} | {value('ttd')} |")
    lines += ["", "* 계산 가능한 실행의 지표 평균(분). 괄호는 계산 가능한 실행 수/전체입니다. 누락 실행을 0으로 처리하지 않습니다.",
              "", "## 부족한 데이터", ""]
    for field, ids in result["readiness"]["missing_annotations"].items():
        if ids:
            lines.append(f"- {field}: {len(ids)}명 — {', '.join(ids)}")
    lines += ["", "## 실행하지 않은 조건", ""]
    lines += [f"- 환자 {s['case_count']}명, seed {s['seed']}: {s['reason']}" for s in result["skipped"]] or ["- 없음"]
    lines += ["", "## 연구 범위", "", "- 정적 QA/순차 진료 및 Base/LoRA의 공정 비교는 별도 모델 실행·정답 분리·정답 워크플로가 필요합니다.",
              "- cohort_unconstrained는 주어진 환자 수만큼 자원을 제공하는 논리 기준선입니다. 무한 수요나 실제 병원의 무제한 자원을 뜻하지 않습니다.",
              "- 원문 9장의 문헌 서지·DOI 검증은 이 실행기의 검증 범위가 아닙니다."]
    return "\n".join(lines) + "\n"
