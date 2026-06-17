from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.logger import get_latest_run_id, get_run_dir


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _load_case_details(run_id: str, case_ids: list[str]) -> list[dict[str, Any]]:
    details: list[dict[str, Any]] = []
    results_dir = settings.RESULTS_DIR / run_id
    for case_id in case_ids:
        result_path = results_dir / f"{case_id}_result.json"
        if not result_path.exists():
            continue
        result = _load_json(result_path)
        reasoning_state = dict(result.get("reasoning_state", {}) or {})
        details.append(
            {
                "case_id": case_id,
                "predicted_diagnosis": str(result.get("predicted_diagnosis", "")).strip(),
                "predicted_department": str(result.get("predicted_department", "")).strip(),
                "ground_truth": str(result.get("ground_truth", "")).strip(),
                "ground_truth_department": str(result.get("ground_truth_department", "")).strip(),
                "diagnosis_correct": bool(result.get("diagnosis_correct", False)),
                "department_correct": bool(result.get("department_correct", False)),
                "episode_reward": float(result.get("episode_reward", 0.0) or 0.0),
                "queue_metrics": dict(result.get("queue_metrics", {}) or {}),
                "temporal_metrics": dict(result.get("temporal_metrics", {}) or {}),
                "resource_metrics": dict(result.get("resource_metrics", {}) or {}),
                "time_events": list(reasoning_state.get("time_events", []) or []),
                "resource_events": list(reasoning_state.get("resource_events", []) or []),
                "deterioration_events": list(reasoning_state.get("deterioration_events", []) or []),
                "decision_history": list(reasoning_state.get("decision_history", []) or []),
                "pending_results": list(reasoning_state.get("pending_results", []) or []),
                "observation_status": str(reasoning_state.get("observation_status", "")).strip(),
                "next_reassessment_time_min": reasoning_state.get("next_reassessment_time_min"),
            }
        )
    return details


def _html_template(payload: dict[str, Any]) -> str:
    embedded = json.dumps(payload, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>ER Temporal Dashboard</title>
  <style>
    :root {{
      --ink: #11202b;
      --muted: #5f7280;
      --line: #d7dee3;
      --paper: #f7f4ed;
      --panel: #fffdf8;
      --teal: #2e6f72;
      --amber: #c47a2c;
      --rose: #ad4f4f;
      --olive: #617a3a;
      --shadow: 0 18px 50px rgba(17, 32, 43, 0.08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Georgia, "Times New Roman", serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(46,111,114,0.12), transparent 32%),
        linear-gradient(180deg, #f8f2e7 0%, var(--paper) 45%, #f3efe7 100%);
    }}
    .shell {{
      max-width: 1360px;
      margin: 0 auto;
      padding: 28px 22px 48px;
    }}
    .masthead {{
      display: grid;
      grid-template-columns: 1.5fr 1fr;
      gap: 18px;
      margin-bottom: 20px;
    }}
    .hero, .summary-card, .case-list, .case-panel {{
      background: rgba(255,255,255,0.88);
      backdrop-filter: blur(6px);
      border: 1px solid rgba(17,32,43,0.08);
      box-shadow: var(--shadow);
    }}
    .hero {{
      border-radius: 28px;
      padding: 26px 28px;
    }}
    .hero h1 {{
      margin: 0 0 8px;
      font-size: 2.1rem;
      line-height: 1.05;
      letter-spacing: -0.03em;
    }}
    .hero p {{
      margin: 0;
      color: var(--muted);
      font-size: 1rem;
      line-height: 1.5;
    }}
    .hero .meta {{
      margin-top: 16px;
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
    }}
    .pill {{
      padding: 8px 12px;
      border-radius: 999px;
      background: #f2ede2;
      border: 1px solid rgba(17,32,43,0.08);
      font-size: 0.92rem;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 12px;
    }}
    .summary-card {{
      border-radius: 22px;
      padding: 18px;
      min-height: 124px;
    }}
    .summary-card .label {{
      color: var(--muted);
      font-size: 0.86rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .summary-card .value {{
      margin-top: 8px;
      font-size: 2rem;
      line-height: 1;
    }}
    .summary-card .sub {{
      margin-top: 10px;
      color: var(--muted);
      font-size: 0.94rem;
    }}
    .workspace {{
      display: grid;
      grid-template-columns: 360px 1fr;
      gap: 18px;
      align-items: start;
    }}
    .case-list {{
      border-radius: 24px;
      overflow: hidden;
      position: sticky;
      top: 18px;
    }}
    .case-list header, .case-panel header {{
      padding: 16px 18px;
      border-bottom: 1px solid var(--line);
      background: rgba(247,244,237,0.88);
    }}
    .case-list header h2, .case-panel header h2 {{
      margin: 0;
      font-size: 1rem;
      letter-spacing: 0.02em;
    }}
    .case-items {{
      display: grid;
      gap: 1px;
      background: var(--line);
    }}
    .case-item {{
      background: var(--panel);
      padding: 14px 16px;
      border: 0;
      text-align: left;
      cursor: pointer;
      transition: background 120ms ease, transform 120ms ease;
    }}
    .case-item:hover {{ background: #f9f4e8; }}
    .case-item.active {{
      background: linear-gradient(135deg, rgba(46,111,114,0.16), rgba(196,122,44,0.10));
    }}
    .case-item .top {{
      display: flex;
      justify-content: space-between;
      gap: 10px;
      font-size: 0.96rem;
      margin-bottom: 8px;
    }}
    .case-item .meta {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      color: var(--muted);
      font-size: 0.85rem;
    }}
    .case-panel {{
      border-radius: 24px;
      overflow: hidden;
    }}
    .panel-body {{
      padding: 20px;
      display: grid;
      gap: 18px;
    }}
    .stats-row {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 12px;
    }}
    .stat-tile {{
      background: #faf6ee;
      border: 1px solid rgba(17,32,43,0.08);
      border-radius: 18px;
      padding: 14px;
    }}
    .stat-tile .k {{
      color: var(--muted);
      font-size: 0.82rem;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}
    .stat-tile .v {{
      margin-top: 7px;
      font-size: 1.35rem;
    }}
    .section {{
      background: #fffef9;
      border: 1px solid rgba(17,32,43,0.08);
      border-radius: 20px;
      overflow: hidden;
    }}
    .section header {{
      background: #f8f3e8;
    }}
    .section-body {{
      padding: 14px 16px 16px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 0.92rem;
    }}
    th, td {{
      padding: 9px 8px;
      border-bottom: 1px solid var(--line);
      vertical-align: top;
      text-align: left;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
    .tag {{
      display: inline-block;
      padding: 5px 9px;
      border-radius: 999px;
      font-size: 0.82rem;
      border: 1px solid rgba(17,32,43,0.08);
      background: #f7f3ea;
      margin-right: 6px;
      margin-bottom: 6px;
    }}
    .ok {{ color: var(--olive); }}
    .warn {{ color: var(--amber); }}
    .bad {{ color: var(--rose); }}
    .timeline {{
      display: grid;
      gap: 10px;
    }}
    .event {{
      border-left: 4px solid var(--teal);
      padding: 10px 12px;
      background: #fbf8f2;
      border-radius: 0 14px 14px 0;
    }}
    .event .t {{
      font-size: 0.82rem;
      color: var(--muted);
      margin-bottom: 5px;
    }}
    .event .a {{
      font-size: 0.96rem;
    }}
    @media (max-width: 1080px) {{
      .masthead, .workspace, .stats-row {{
        grid-template-columns: 1fr;
      }}
      .case-list {{
        position: static;
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="masthead">
      <div class="hero">
        <h1>Temporal ER Simulation Dashboard</h1>
        <p>Queueing, reprioritization, pending test waits, and observation/reassessment are shown from one run so we can validate simulator behavior before building the playable UI.</p>
        <div class="meta">
          <span class="pill" id="runIdPill"></span>
          <span class="pill" id="queuePolicyPill"></span>
          <span class="pill" id="caseCountPill"></span>
        </div>
      </div>
      <div class="summary-grid" id="summaryGrid"></div>
    </section>

    <section class="workspace">
      <aside class="case-list">
        <header><h2>Case Queue</h2></header>
        <div class="case-items" id="caseItems"></div>
      </aside>
      <article class="case-panel">
        <header><h2 id="panelTitle">Case detail</h2></header>
        <div class="panel-body">
          <div class="stats-row" id="statsRow"></div>

          <section class="section">
            <header><h2>Clinical Summary</h2></header>
            <div class="section-body" id="clinicalSummary"></div>
          </section>

          <section class="section">
            <header><h2>Queue and Temporal Markers</h2></header>
            <div class="section-body">
              <table>
                <thead>
                  <tr><th>Field</th><th>Value</th></tr>
                </thead>
                <tbody id="queueTable"></tbody>
              </table>
            </div>
          </section>

          <section class="section">
            <header><h2>Time Events</h2></header>
            <div class="section-body">
              <div class="timeline" id="timeEvents"></div>
            </div>
          </section>

          <section class="section">
            <header><h2>Resource Events</h2></header>
            <div class="section-body">
              <table>
                <thead>
                  <tr><th>Action</th><th>Resource</th><th>Wait</th><th>Service</th><th>Window</th></tr>
                </thead>
                <tbody id="resourceTable"></tbody>
              </table>
            </div>
          </section>

          <section class="section">
            <header><h2>Deterioration and Pending State</h2></header>
            <div class="section-body" id="pendingAndDeterioration"></div>
          </section>
        </div>
      </article>
    </section>
  </div>

  <script>
    const payload = {embedded};
    const report = payload.report;
    const details = payload.case_details;
    const detailMap = Object.fromEntries(details.map(item => [item.case_id, item]));

    const fmtBool = (value) => value ? "Yes" : "No";
    const fmtMinute = (value) => value === null || value === undefined ? "—" : `${{value}}m`;
    const fmtAccuracy = (value) => `${{Math.round((value || 0) * 100)}}%`;

    function renderSummary() {{
      document.getElementById("runIdPill").textContent = `run: ${{report.run_id}}`;
      document.getElementById("queuePolicyPill").textContent = report.queue_policy;
      document.getElementById("caseCountPill").textContent = `${{report.case_count}} cases`;

      const summary = report.summary || {{}};
      const items = [
        ["Diagnosis Accuracy", fmtAccuracy(summary.diagnosis_accuracy), `${{summary.diagnosis_correct_count}} / ${{report.case_count}} cases`],
        ["Department Accuracy", fmtAccuracy(summary.department_accuracy), `${{summary.department_correct_count}} / ${{report.case_count}} cases`],
        ["Average Queue Wait", fmtMinute(summary.average_queue_wait_time_min), `Max ${{fmtMinute(summary.max_queue_wait_time_min)}}`],
        ["Temporal Signals", `${{summary.reprioritized_case_count}} reprioritized`, `${{summary.observation_case_count}} observed · ${{summary.pending_wait_case_count}} pending waits`],
      ];
      document.getElementById("summaryGrid").innerHTML = items.map(([label, value, sub]) => `
        <div class="summary-card">
          <div class="label">${{label}}</div>
          <div class="value">${{value}}</div>
          <div class="sub">${{sub}}</div>
        </div>
      `).join("");
    }}

    function renderCaseList(activeCaseId) {{
      const container = document.getElementById("caseItems");
      container.innerHTML = report.rows.map(row => {{
        const correctClass = row.diagnosis_correct ? "ok" : "bad";
        const activeClass = row.case_id === activeCaseId ? "active" : "";
        return `
          <button class="case-item ${{activeClass}}" data-case-id="${{row.case_id}}">
            <div class="top">
              <strong>${{row.case_id}}</strong>
              <span class="${{correctClass}}">${{row.predicted_department}}</span>
            </div>
            <div class="meta">
              <span>Q${{row.queue_position}}</span>
              <span>Triage ${{row.triage_level}}→${{row.effective_triage_level}}</span>
              <span>Wait ${{row.queue_wait_time_min}}m</span>
              <span>Risk ${{row.deterioration_risk}}</span>
            </div>
          </button>
        `;
      }}).join("");
      for (const btn of container.querySelectorAll(".case-item")) {{
        btn.addEventListener("click", () => selectCase(btn.dataset.caseId));
      }}
    }}

    function renderCase(caseId) {{
      const row = report.rows.find(item => item.case_id === caseId);
      const detail = detailMap[caseId];
      if (!row || !detail) return;

      document.getElementById("panelTitle").textContent = `${{caseId}} | ${{detail.predicted_diagnosis}}`;

      const statItems = [
        ["Queue Wait", fmtMinute(row.queue_wait_time_min)],
        ["Care Time", fmtMinute(row.care_elapsed_time_min)],
        ["Effective Triage", `${{row.effective_triage_level}}`],
        ["Reward", `${{Math.round((row.episode_reward || 0) * 100) / 100}}`],
      ];
      document.getElementById("statsRow").innerHTML = statItems.map(([k, v]) => `
        <div class="stat-tile">
          <div class="k">${{k}}</div>
          <div class="v">${{v}}</div>
        </div>
      `).join("");

      const summaryTags = [
        `<span class="tag">Pred: ${{detail.predicted_diagnosis}}</span>`,
        `<span class="tag">Dept: ${{detail.predicted_department}}</span>`,
        `<span class="tag">Gold: ${{detail.ground_truth}}</span>`,
        `<span class="tag">Gold dept: ${{detail.ground_truth_department}}</span>`,
        `<span class="tag">${{detail.diagnosis_correct ? "Diagnosis correct" : "Diagnosis mismatch"}}</span>`,
        `<span class="tag">${{detail.department_correct ? "Department correct" : "Department mismatch"}}</span>`,
      ];
      const reassessmentNote = (
        detail.next_reassessment_time_min !== null && detail.next_reassessment_time_min !== undefined
      )
        ? `(next reassessment: ${{detail.next_reassessment_time_min}}m)`
        : "";
      document.getElementById("clinicalSummary").innerHTML = `
        <div>${{summaryTags.join("")}}</div>
        <p><strong>Observation status:</strong> ${{detail.observation_status || "none"}} ${{reassessmentNote}}</p>
      `;

      const queueRows = [
        ["Arrival time", fmtMinute(row.arrival_time_min)],
        ["Scheduler start", fmtMinute(row.scheduler_start_time_min)],
        ["Base triage", row.triage_level],
        ["Effective triage", row.effective_triage_level],
        ["Deterioration risk", row.deterioration_risk],
        ["Wait escalation steps", row.wait_escalation_steps],
        ["First objective step", fmtMinute(row.time_to_first_objective_step_min)],
        ["Handoff", fmtMinute(row.time_to_handoff_min)],
        ["Final diagnosis", fmtMinute(row.time_to_final_diagnosis_min)],
        ["Observation intervals", row.observation_intervals],
        ["Reassessments", row.reassessment_count],
        ["Await-result intervals", row.await_test_result_intervals],
      ];
      document.getElementById("queueTable").innerHTML = queueRows.map(([k, v]) => `
        <tr><td>${{k}}</td><td>${{v}}</td></tr>
      `).join("");

      document.getElementById("timeEvents").innerHTML = (detail.time_events || []).map(event => `
        <div class="event">
          <div class="t">${{fmtMinute(event.start_time_min)}} → ${{fmtMinute(event.end_time_min)}} · ${{event.resource_kind || "system"}}</div>
          <div class="a"><strong>${{event.action}}</strong>${{event.target ? ` · ${{event.target}}` : ""}}</div>
          <div>${{event.rationale || ""}}</div>
        </div>
      `).join("") || "<div class=\"event\"><div class=\"a\">No time events recorded.</div></div>";

      document.getElementById("resourceTable").innerHTML = (detail.resource_events || []).map(event => `
        <tr>
          <td>${{event.action}}</td>
          <td>${{event.resource_kind}}</td>
          <td>${{fmtMinute(event.wait_min)}}</td>
          <td>${{fmtMinute(event.service_time_min)}}</td>
          <td>${{fmtMinute(event.actual_start_min)}} → ${{fmtMinute(event.end_time_min)}}</td>
        </tr>
      `).join("") || "<tr><td colspan=\"5\">No resource events recorded.</td></tr>";

      const pendingTags = (detail.pending_results || []).map(item => `<span class="tag warn">${{item.resolved_name}} ready @ ${{item.ready_time_min}}m</span>`);
      const deteriorationTags = (detail.deterioration_events || []).map(item => `<span class="tag bad">${{item.event_type || "deterioration"}} @ ${{item.minute || item.end_time_min || "?"}}m</span>`);
      document.getElementById("pendingAndDeterioration").innerHTML = `
        <div><strong>Pending results:</strong> ${{
          pendingTags.length ? pendingTags.join("") : "<span class='tag'>none</span>"
        }}</div>
        <div style="margin-top:10px;"><strong>Deterioration events:</strong> ${{
          deteriorationTags.length ? deteriorationTags.join("") : "<span class='tag'>none</span>"
        }}</div>
      `;
    }}

    function selectCase(caseId) {{
      renderCaseList(caseId);
      renderCase(caseId);
    }}

    renderSummary();
    selectCase(report.rows[0]?.case_id || details[0]?.case_id || "");
  </script>
</body>
</html>
"""


def build_dashboard(run_id: str) -> Path:
    report_path = settings.REPORTS_DIR / run_id / "multi_patient_run_summary.json"
    report = _load_json(report_path)
    case_ids = [str(row.get("case_id", "")).strip() for row in list(report.get("rows", []) or []) if str(row.get("case_id", "")).strip()]
    case_details = _load_case_details(run_id, case_ids)
    html = _html_template({"report": report, "case_details": case_details})

    run_dir = get_run_dir(settings.REPORTS_DIR, run_id)
    output_path = run_dir / "multi_patient_dashboard.html"
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main() -> None:
    import sys

    run_id = str(sys.argv[1]).strip() if len(sys.argv) >= 2 else get_latest_run_id(
        settings.REPORTS_DIR,
        required_file="multi_patient_run_summary.json",
    )

    output_path = build_dashboard(run_id)
    print(f"[DASHBOARD] {output_path}")


if __name__ == "__main__":
    main()
