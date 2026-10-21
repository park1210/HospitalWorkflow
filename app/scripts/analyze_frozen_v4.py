"""Read-only post-hoc analysis. No simulator, model client, or network calls."""
import argparse
import csv
import hashlib
import json
import random
from collections import Counter
from pathlib import Path

from app.core.paper_evaluation import aggregate, episode_rows, mean, paired
from app.core.memory_evaluation import visit_key


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def write_csv(path, rows):
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({k: dump(v) if isinstance(v, (list, dict)) else v for k, v in r.items()} for r in rows)


def ci(values, samples, seed=42):
    rng = random.Random(seed)
    draws = sorted(mean(rng.choices(values, k=len(values))) for _ in range(samples))
    return draws[int(.025 * (samples - 1))], draws[int(.975 * (samples - 1))]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("outputs/paper_test_v4_r1"))
    parser.add_argument("--b3-source", type=Path, default=Path("outputs/paper_test_v4_B3_retry"))
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/analysis_v4"))
    parser.add_argument("--bootstrap-samples", type=int, default=5000)
    args = parser.parse_args()
    if args.bootstrap_samples < 100:
        parser.error("bootstrap-samples must be >= 100")
    if args.output_dir.exists():
        parser.error("Output directory exists; choose a new directory to preserve existing results.")
    sources = {b: (args.b3_source if b == "B3" else args.source) for b in ["B0", "B1", "B2", "B3", "B4"]}
    files = sorted({p for root in sources.values() for p in root.rglob("*") if p.is_file()})
    hashes = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    inputs = args.source / "inputs"
    cases, labels, annotations, scenarios = [read(inputs / (n + ".json")) for n in ["cases", "labels", "annotations", "scenarios"]]
    groups = {visit_key(s): s["group"] for s in scenarios}
    case_map = {visit_key(c["longitudinal"]): c for c in cases}
    if len(cases) != 40 or len({c['longitudinal']['patient_id'] for c in cases}) != 40:
        raise ValueError("This analysis requires 40 independent patients / visits")
    if Counter(groups.values()) != dict.fromkeys(["baseline", "memory_critical", "routing_critical", "voi_critical"], 10):
        raise ValueError("Unexpected scenario groups")
    manifests = [read(root / "manifest.json") for root in [args.source, args.b3_source]]
    comparison = {k: manifests[0].get(k) == manifests[1].get(k) for k in ["input_sha256", "model_settings", "code_sha256"]}
    if not all(comparison.values()) or any(k not in manifests[0] for k in comparison):
        raise ValueError("Original and retry manifest inputs/settings/code must match")
    reports, visits, states, rows, indexed = {}, {}, {}, [], {}
    for b, root in sources.items():
        reports[b] = read(root / (b + "_r01.report.json"))
        visits[b] = {visit_key(v['identity']): v for v in reports[b]['visits']}
        if set(visits[b]) != set(case_map) or len(reports[b]['visits']) != 40:
            raise ValueError("Missing or duplicate visits: " + b)
        states[b] = {k: next(iter(v['final_state']['cases'].values())) for k, v in visits[b].items()}
        current = episode_rows(cases, labels, reports[b], b, 0)
        for row in current:
            key = visit_key(row)
            row['scenario_group'] = groups[key]
            row['source_report'] = str(root / (b + "_r01.report.json"))
            indexed[b, key] = row
        rows.extend(current)
        # Cross-check the existing runner's exported metrics without trusting them as inputs.
        with (root / 'episodes.csv').open(encoding='utf-8-sig', newline='') as stream:
            saved = {visit_key(r): r for r in csv.DictReader(stream) if r['condition'] == b}
        for row in current:
            for metric in ['completed', 'correct_all_planned', 'actions', 'llm_calls', 'tests', 'consults']:
                if float(saved[visit_key(row)][metric]) != row[metric]:
                    raise ValueError('Existing export disagrees: ' + b + ' ' + metric)
    overall = aggregate(rows)
    for row in overall:
        row['accuracy_ci95_low'], row['accuracy_ci95_high'] = ci([r['correct_all_planned'] for r in rows if r['condition'] == row['condition']], args.bootstrap_samples)
    subgroup = [dict(r, scenario_group=g) for g in sorted(set(groups.values())) for r in aggregate([r for r in rows if r['scenario_group'] == g])]
    transitions, transition_counts = [], []
    for a, b in [('B1', 'B2'), ('B2', 'B3'), ('B3', 'B4')]:
        for before, after in [(1, 0), (0, 1)]:
            tag = f'{a}_{"correct" if before else "wrong"}_{b}_{"correct" if after else "wrong"}'
            selected = [k for k in case_map if indexed[a, k]['correct_all_planned'] == before and indexed[b, k]['correct_all_planned'] == after]
            transition_counts.append({'transition': tag, 'count': len(selected), 'patient_ids': [json.loads(k)[0] for k in selected]})
            for k in selected:
                transitions.append({'transition': tag, 'patient_id': json.loads(k)[0], 'visit_id': json.loads(k)[1], 'scenario_group': groups[k], 'from_diagnosis': states[a][k]['assessment_summary'], 'to_diagnosis': states[b][k]['assessment_summary'], 'label': labels[k], 'from_source': indexed[a, k]['source_report'], 'to_source': indexed[b, k]['source_report']})
    memory = []
    for b in sources:
        for k, s in states[b].items():
            if groups[k] != 'memory_critical':
                continue
            records = visits[b][k]['memory_context'].get('records', [])
            relevant = set(annotations[k]['relevant_memory_ids'])
            retrieved = {r['memory_id'] for r in records}
            audits = [a for a in s['llm_audit'] if a.get('status') == 'success'] + [h for h in s.get('voi_state', {}).get('history', []) if h.get('status') == 'selected']
            cited = {i for a in audits for i in a.get('memory_citations', {}).get('ids', [])}
            rationale = ' | '.join(a.get('decision', {}).get('rationale', a.get('rationale', '')) for a in audits)
            # Explicit surface evidence only; citations alone do not establish correct interpretation.
            mentioned = any(t in rationale.lower() for t in ['pattern alpha', 'pattern beta', 'previous documented', 'longitudinal pattern'])
            correct = indexed[b, k]['correct_all_planned']
            category = 'correct_use' if mentioned and bool(cited & relevant) and correct else 'insufficient_context' if not relevant <= retrieved else 'insufficient_reasoning' if not correct else 'unknown_from_logs'
            memory.append({'condition': b, 'patient_id': json.loads(k)[0], 'visit_id': json.loads(k)[1], 'relevant_memory_retrieved': relevant <= retrieved, 'retrieved_ids': sorted(retrieved), 'relevant_ids': sorted(relevant), 'visible_in_saved_runtime': relevant <= {r['memory_id'] for r in s.get('memory_context', {}).get('records', [])}, 'prompt_visibility': 'inferred_from_runtime_and_clinical_observation_code; full_prompt_not_saved', 'relevant_memory_cited': bool(cited & relevant), 'explicit_memory_rationale': mentioned, 'correctly_interpreted': 'consistent_with_explicit_trace' if category == 'correct_use' else 'unknown_from_logs', 'influence': 'explicit_rationale_link' if category == 'correct_use' else 'unknown_from_logs', 'final_correct': correct, 'failure_type': category, 'classification_scope': 'recorded_trace_only; no hidden-reasoning claim', 'rationale': rationale, 'source_report': indexed[b, k]['source_report'], 'json_locator': 'visits[identity.patient_id=' + json.loads(k)[0] + '].final_state.cases.*.llm_audit'})
    full = []
    for k in case_map:
        if not (indexed['B1', k]['correct_all_planned'] and not indexed['B2', k]['correct_all_planned']):
            continue
        a = visits['B1'][k]['memory_context']['records']
        b = visits['B2'][k]['memory_context']['records']
        ids = {r['memory_id'] for r in b}
        missing = [r for r in a if r['memory_id'] not in ids]
        relevant = set(annotations[k].get('relevant_memory_ids', []))
        full.append({'patient_id': json.loads(k)[0], 'scenario_group': groups[k], 'B1_records': a, 'B2_records': b, 'missing_from_B2': missing, 'annotated_relevant_missing': sorted(relevant - ids), 'failure_type': 'retrieval_miss' if relevant - ids else 'unclear', 'interpretation': 'No annotated relevant record lost; omitted context is not proven necessary. Utilization/interpretation or stochastic variation cannot be separated.' if not relevant - ids else 'Annotated relevant record absent.', 'B1_rationales': [d['rationale'] for d in states['B1'][k]['decision_snapshots']], 'B2_rationales': [d['rationale'] for d in states['B2'][k]['decision_snapshots']]})
    routing, margins = [], []
    for k, s in states['B3'].items():
        case = case_map[k]
        specialty_tests = {t: ds for t, ds in case.get('test_access', {}).items() if 'er' not in ds}
        intended_tests = [t for t in specialty_tests if ' supports ' in case['hidden_test_results'][t]['result']]
        intended = sorted({d for t in intended_tests for d in specialty_tests[t]})
        events = []
        for i, audit in enumerate(s['llm_audit']):
            route = audit.get('routing')
            if not route:
                continue
            utilities = route.get('utility_estimates', {})
            ranked = sorted((v['utility'], d) for d, v in utilities.items() if isinstance(v, dict) and v.get('utility') is not None)
            margin = ranked[-1][0] - ranked[-2][0] if len(ranked) >= 2 else None
            allowed = route.get('allowed_departments', [])
            event = {'patient_id': json.loads(k)[0], 'scenario_group': groups[k], 'audit_index': i, 'role': audit.get('role'), 'candidate_specialties': route.get('candidate_departments'), 'allowed_specialties': allowed, 'utility_estimates': utilities, 'top1_top2_margin': margin, 'low_margin_hard_route': margin is not None and margin < .01 and len(allowed) == 1, 'decision': audit.get('decision'), 'source_report': indexed['B3', k]['source_report']}
            events.append(event)
            margins.append(event)
        initial = events[0]['allowed_specialties'] if events else []
        route_correct = bool(intended and initial and set(initial) <= set(intended))
        acquired = [t for t in s['completed_tests'] if t in specialty_tests]
        correct = indexed['B3', k]['correct_all_planned']
        category = ('correct_route_correct_outcome' if correct else 'correct_route_wrong_outcome') if route_correct else 'wrong_route' if intended and initial else 'unclear'
        routing.append({'patient_id': json.loads(k)[0], 'scenario_group': groups[k], 'initial_allowed_specialties': initial, 'benchmark_intended_specialties': intended, 'intended_basis': 'frozen synthetic specialty-only test with discriminative result; evaluator-only, not clinical gold', 'initial_route_correct': route_correct if intended else None, 'consult_executed': bool(s['consult_history']), 'consult_departments': [c['department'] for c in s['consult_history']], 'specialty_call_roles': [a['role'] for a in s['llm_audit'] if a['role'] != 'er'], 'specialty_tests_acquired': acquired, 'intended_tests_acquired': [t for t in acquired if t in intended_tests], 'test_results': s['test_results'], 'final_correct': correct, 'failure_type': category, 'low_margin_hard_route': any(e['low_margin_hard_route'] for e in events), 'potential_over_routing': groups[k] == 'baseline' and bool(s['consult_history']), 'downstream_integration_failure': bool(acquired) and not correct, 'final_rationale': s['latest_rationale'], 'source_report': indexed['B3', k]['source_report']})
        routing[-1].update({
            'classification_scope': 'initial_menu_and_final_outcome_only; not whole_trajectory_success',
            'later_off_target_menu': bool(intended) and any(set(e['allowed_specialties']) - set(intended) for e in events[1:]),
            'off_target_consult': bool(intended) and any(c['department'] not in intended for c in s['consult_history']),
            'information_acquisition_gap': bool(intended_tests) and not any(t in acquired for t in intended_tests),
            'downstream_integration_failure': 'consistent_with_trace_not_causal_proof' if any(t in acquired for t in intended_tests) and not correct else 'not_established',
            'final_diagnosis': s['assessment_summary'],
            'executing_agents': [a.get('routing', {}).get('executing_agent', {}) for a in s['llm_audit']],
        })
    voi = []
    for k in case_map:
        if groups[k] != 'voi_critical':
            continue
        a, b = states['B3'][k], states['B4'][k]
        row = {'patient_id': json.loads(k)[0]}
        for condition in ['B3', 'B4']:
            for metric in ['correct_all_planned', 'actions', 'tests', 'consults', 'llm_calls', 'completion_minutes', 'llm_latency_seconds', 'expected_ig_nats']:
                row[condition + '_' + metric] = indexed[condition, k][metric]
            row[condition + '_sequence'] = [s['proposed_action'] for s in states[condition][k]['decision_snapshots']]
        selections = [h for h in b['voi_state']['history'] if h.get('action_id') and h['status'] == 'selected']
        chosen = [next(c for c in h['candidates'] if c['action_id'] == h['action_id']) for h in selections]
        row.update({'same_tests': a['completed_tests'] == b['completed_tests'], 'same_action_types': [s['proposed_action']['type'] for s in a['decision_snapshots']] == [s['proposed_action']['type'] for s in b['decision_snapshots']], 'same_full_sequence': row['B3_sequence'] == row['B4_sequence'], 'B4_zero_calls': not b['llm_audit'], 'selected_highest_IG': all(c['information_gain_nats'] == max(x['information_gain_nats'] for x in h['candidates']) for h, c in zip(selections, chosen)) if chosen else None, 'selected_highest_VoI': all(c['voi'] == max(x['voi'] for x in h['candidates']) for h, c in zip(selections, chosen)) if chosen else None, 'modeled_candidates': [h['candidates'] for h in selections], 'B4_stop_reason': b['voi_state']['history'][-1].get('stop_reason'), 'source_B3': indexed['B3', k]['source_report'], 'source_B4': indexed['B4', k]['source_report']})
        voi.append(row)
    failures = []
    for domain, data in [('memory', memory), ('routing', routing)]:
        counts = Counter((r.get('condition', 'B3'), r['failure_type']) for r in data)
        for (b, category), count in sorted(counts.items()):
            failures.append({'domain': domain, 'condition': b, 'category': category, 'count': count, 'denominator': sum(r.get('condition', 'B3') == b for r in data), 'note': 'Trace categories are descriptive; correct_use is not a failure.'})
    for flag in ['potential_over_routing', 'low_margin_hard_route', 'information_acquisition_gap', 'off_target_consult']:
        failures.append({'domain': 'routing_observed_flag', 'condition': 'B3', 'category': flag, 'count': sum(bool(r[flag]) for r in routing), 'denominator': 40, 'note': 'Nonexclusive observed flag, not a causal failure diagnosis'})
    pairs = [paired(rows, a, b, 'correct_all_planned', samples=args.bootstrap_samples) for a, b in [('B1', 'B2'), ('B2', 'B3'), ('B3', 'B4')]]
    original_b3 = aggregate(episode_rows(cases, labels, read(args.source / 'B3_r01.report.json'), 'B3_original_incomplete', 0))
    if hashes != {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}:
        raise RuntimeError('Source files changed during analysis; aborting publication')
    args.output_dir.mkdir(parents=True)
    tables = {'overall_summary': overall, 'subgroup_summary': subgroup, 'patient_transitions': transitions, 'transition_counts': transition_counts, 'memory_utilization': memory, 'full_history_vs_retrieval': full, 'routing_failure_analysis': routing, 'routing_margin_analysis': margins, 'voi_efficiency': voi, 'failure_summary': failures, 'paired_accuracy': pairs, 'original_B3_incomplete': original_b3, 'episodes': rows}
    for name, data in tables.items():
        write_csv(args.output_dir / (name + '.csv'), data)
    provenance = {'source_hashes': hashes, 'source_unchanged_at_end': True, 'manifest_comparison': comparison, 'selected_sources': {b: str(p) for b, p in sources.items()}, 'bootstrap_samples': args.bootstrap_samples, 'bootstrap_seed': 42, 'low_margin_threshold': .01, 'low_margin_note': 'post-hoc descriptive threshold, not calibrated confidence', 'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (args.output_dir / 'provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding='utf-8')
    report = build_report(overall, subgroup, transition_counts, memory, full, routing, margins, voi, pairs, original_b3, args)
    (args.output_dir / 'analysis_report.md').write_text(report, encoding='utf-8')
    print(report)


def build_report(overall, subgroup, transitions, memory, full, routing, margins, voi, pairs, original, args):
    lines = ['# Frozen v4 process / failure analysis', '', '## 분석 범위와 출처', '',
             f'- B0/B1/B2/B4: `{args.source}`; B3: `{args.b3_source}`.',
             '- 원본과 B3 재실행의 manifest 입력·모델 설정·코드 해시가 일치한다. B3는 별도 실행이며 실행 시점·확률적 응답 차이를 통제한 인과 실험으로 해석하지 않는다.',
             f'- 원래 B3는 계획 40건 중 completion={original[0]["completed"]:.3f}; 삭제하지 않고 original_B3_incomplete.csv에 분리했다.',
             '- 40명 / 40회 방문, 그룹별 10명, 반복 1회. 미검수 합성 process-discriminative benchmark이며 임상 성능 증거가 아니다.',
             '- 원본 파일 SHA-256을 분석 전후 대조했다. 시뮬레이터 변경 및 새 LLM 호출 없음.', '', '## 전체 결과', '',
             '|조건|정확도|환자 bootstrap 95% CI|완료율|행동|검사|협진|LLM 호출|가상 완료시간(분)|기록된 LLM 지연(초)|', '|---|---:|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in overall:
        lines.append(f'|{r["condition"]}|{r["correct_all_planned"]:.3f}|[{r["accuracy_ci95_low"]:.3f}, {r["accuracy_ci95_high"]:.3f}]|{r["completed"]:.3f}|{r["actions"]:.2f}|{r["tests"]:.2f}|{r["consults"]:.2f}|{r["llm_calls"]:.2f}|{r["completion_minutes"]:.3f}|{r["llm_latency_seconds"]:.3f}|')
    lines += ['', '가상 완료시간과 실제 모델 호출 지연은 다른 지표이다. LLM 지연은 호출 기록 합계이며 전체 프로그램 wall time이 아니다.', '', '## 그룹별 정확도', '', '|그룹|B0|B1|B2|B3|B4|', '|---|---:|---:|---:|---:|---:|']
    for g in sorted({r['scenario_group'] for r in subgroup}):
        lines.append('|' + g + '|' + '|'.join(f'{r["correct_all_planned"]:.3f}' for r in subgroup if r['scenario_group'] == g) + '|')
    lines += ['', '## 환자별 전이', '']
    for r in transitions:
        lines.append(f'- {r["transition"]}: {r["count"]}명 — ' + ', '.join(r['patient_ids']))
    lines += ['', 'Paired difference는 뒤 조건 − 앞 조건이며 환자를 재표집한다. 반복 측정 불확실성이나 임상 모집단 불확실성을 추정하지 않는다.', '']
    for r in pairs:
        lines.append(f'- {r["baseline"]} → {r["candidate"]}: {r["difference"]:+.3f}, 95% CI {r["ci95"]}')
    m = [r for r in memory if r['condition'] == 'B2']
    lines += ['', '## Memory: 검색과 활용의 분리', '',
              f'- B2 memory-critical 10명: 관련 기록 검색 {sum(r["relevant_memory_retrieved"] for r in m)}/10, 정답 {sum(r["final_correct"] for r in m)}/10, 관련 ID 인용 {sum(r["relevant_memory_cited"] for r in m)}/10, 명시적 기억 설명 {sum(r["explicit_memory_rationale"] for r in m)}/10.',
              '- memory_utilization.csv는 B0–B4 × 10명 전부를 포함한다. 인용 여부와 rationale의 명시적 설명을 분리했다. 인용만으로 해석의 정확성을 인정하지 않는다.',
              '- saved runtime과 clinical_observation.py의 longitudinal_memory 전달 경로로 가시성을 추론할 수 있지만 전체 실제 prompt는 저장되지 않아 전송된 문자열 자체를 검증할 수 없다.',
              '- 정답·관련 인용·명시적 기억 설명이 함께 있는 경우에만 correct_use(기록상 일관성)를 부여했다. 충분한 기억이 있는데 오답이면 insufficient_reasoning으로 기술하되 무시·오해·현재 근거 우선 중 어느 것이 원인인지는 확정하지 않는다.',
              f'- B1 정답/B2 오답 {len(full)}건의 누락 레코드 원문을 full_history_vs_retrieval.csv에 저장했다. 관련 주석 레코드 누락 건수: {sum(bool(r["annotated_relevant_missing"]) for r in full)}.',
              '- 이 비교만으로 주변 문맥의 필수성이나 제거의 인과 효과를 입증할 수 없다. recorded trace에서 활용 확인 안 됨은 내부적으로 생각하지 않았다는 뜻이 아니다.', '', '## Routing: 메뉴 선택 → 협진 → 검사 → 최종 판단', '']
    critical = [r for r in routing if r['scenario_group'] == 'routing_critical']
    lines += [f'- routing-critical 10명: 초기 추천이 합성 벤치마크 의도와 일치 {sum(bool(r["initial_route_correct"]) for r in critical)}/10, 실제 협진 {sum(r["consult_executed"] for r in critical)}/10, 전문과 검사 획득 {sum(bool(r["specialty_tests_acquired"]) for r in critical)}/10, 정답 {sum(r["final_correct"] for r in critical)}/10.',
              f'- 정답 구분에 필요한 intended test 획득은 {sum(bool(r["intended_tests_acquired"]) for r in critical)}/10. 전문과 검사를 받은 3명(p025/p027/p029)은 neurology → pulmonology로 이동해 비결정적 T_PULM을 받았다. 7명은 T_SCREEN만 받았다. 초기 추천 성공과 전체 경로 성공은 다르다.',
              '- routing-critical 최종 진단은 전부 Synthetic A였다. 정답 5/10은 두 라벨을 구분하는 의사결정의 성공을 의미하지 않는다. correct_route_correct_outcome 분류도 초기 메뉴와 최종 정답만 뜻하며 중간 과정의 타당성을 보장하지 않는다.',
              '- 추천 allowed_departments는 협진 가능 메뉴다. 실제 실행과 같지 않으며, final target_department만으로 경로 성공을 판단하지 않았다.',
              '- 전문과 정답 기준은 frozen case의 specialty-only discriminative test로부터 평가자가 도출했다. 실행되지 않은 검사 결과는 기준 정의에만 사용하고 실제 획득 정보로 세지 않았다.',
              f'- baseline의 potential over-routing: {sum(r["potential_over_routing"] for r in routing)}/10. 다른 조건에서 전부 정답인데 협진 비용이 추가된 관찰이며 불필요성이 증명된 것은 아니다.',
              f'- margin < 0.01 및 단일 메뉴: {sum(r["low_margin_hard_route"] for r in margins)}/{len(margins)} routing 로그; 해당 환자 {sum(r["low_margin_hard_route"] for r in routing)}/40. 임계값은 사후 기술용이며 확률/신뢰도로 해석하지 않는다.',
              '- routing_margin_analysis.csv는 모든 호출별 후보·효용·margin·행동을 보존한다. 낮은 margin 하나를 전체 실패의 원인으로 일반화하지 않는다.', '', '## VoI: 정보 획득 효율', '',
              f'- voi-critical B3/B4: 같은 검사 {sum(r["same_tests"] for r in voi)}/10; 같은 행동 종류 순서 {sum(r["same_action_types"] for r in voi)}/10; 진단 target까지 같은 순서 {sum(r["same_full_sequence"] for r in voi)}/10.',
              f'- B4 live LLM 0회 {sum(r["B4_zero_calls"] for r in voi)}/10; 후보 중 최대 모델 IG 선택 {sum(bool(r["selected_highest_IG"]) for r in voi)}/10; 최대 VoI 선택 {sum(bool(r["selected_highest_VoI"]) for r in voi)}/10.',
              '- 실제 검사 선택은 B3 전원 T_LOW, B4 전원 T_HIGH이다. 같은 검사 횟수를 유지하며 검사 종류와 정보가치가 바뀌었다. 같은 검사를 호출 없이 재현했다는 주장은 부정확하다.',
              '- 후보별 IG·비용·VoI, 실제 action/target 순서와 stop_reason을 voi_efficiency.csv에서 대조할 수 있다. IG는 관찰로 검증된 정보량이 아니라 명시적 확률 모델의 기대값이다.',
              '- 이 그룹에서는 행동 2회·검사 1회·가상시간 9분을 유지하면서 호출이 평균 2회 → 0회다. 행동 수나 가상 대기시간이 감소했다는 주장은 지원하지 않는다.', '', '## 논문에서 가능한 주장과 한계', '',
              '- 가능: 이 합성 표본에서는 검색 성공과 최종 정답이 일치하지 않았고, 전문과 추천의 적합성도 필요한 정보 획득을 보장하지 않았다.',
              '- 가능: 명시적 VoI 모델은 이 조건에서 live LLM 의존도를 줄였다. retrieval → recorded utilization → routing → information acquisition → diagnosis의 단계별 관찰이 최종 정확도만으로 놓치는 실패를 드러낸다.',
              '- 불가: 숨겨진 chain-of-thought, 선택하지 않은 경로의 결과, 한 모듈만이 정확도 변화의 유일한 원인이라는 주장, 임상 효과 또는 통계적 우월성 일반화.',
              '- small synthetic sample: 전체 40명·그룹별 10명·반복 1회이며 전문가 검수 없음. bootstrap은 이 표본의 기술적 불확실성이다. B3 별도 재실행의 지연 비교는 실행 환경/시점 영향을 받을 수 있다.', '', '## 재현과 판정 규칙', '',
              '`python -m app.scripts.analyze_frozen_v4 --output-dir outputs/analysis_v4_repeat`', '',
              '- 기존 출력 폴더가 있으면 중단한다. JSON provenance에 원본 전체 해시와 분석 스크립트 해시를 저장한다.',
              '- 기존 episode_rows/aggregate/paired를 재사용하고 원 CSV의 완료·정답·행동·호출·검사·협진 수와 일치하는지 검증한다.',
              '- failure_summary는 기술적 trace 분류이며 모든 행이 실패는 아니다. ignored_relevant_memory, misinterpreted_memory, overridden_by_current_evidence, unnecessary_consult 등 강한 인과 판정은 근거 부족으로 강제 부여하지 않았다.',
              '- CSV의 리스트/객체 셀은 JSON이다. 빈 수치는 미관측/적용 불가이며 0으로 대체하지 않는다. 원 보고서의 test_results.synthetic=false는 공급 방식 플래그로, benchmark 전체의 합성 출처를 뒤집지 않는다.', '']
    return '\n'.join(lines)


if __name__ == '__main__':
    main()
