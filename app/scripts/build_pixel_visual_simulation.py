from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.logger import get_latest_run_id, get_run_dir


ZONE_LABELS = {
    "waiting_room": "Waiting Room",
    "er_workup": "ER Workup",
    "observation": "Observation",
    "awaiting_results": "Awaiting Results",
    "specialty_review": "Specialty Review",
    "completed": "Completed",
}


def _load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _html_template(payload: dict[str, Any]) -> str:
    embedded = json.dumps(payload, ensure_ascii=False)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Pixel Visual ER Simulation</title>
  <style>
    :root {{
      --bg: #1a1c2c;
      --bg-soft: #242741;
      --panel: #2c3155;
      --panel-2: #353b66;
      --line: #515a93;
      --text: #f2f3f8;
      --muted: #b6bddb;
      --accent: #70d6ff;
      --accent-2: #ffd670;
      --danger: #ff6b6b;
      --ok: #95d46b;
      --obs: #c8a2ff;
      --pending: #ffb86b;
      --pixel-shadow: 0 0 0 2px #111422, 0 4px 0 2px #111422;
      --tile-size: 78px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--text);
      background:
        linear-gradient(180deg, rgba(112,214,255,0.08), transparent 20%),
        linear-gradient(180deg, #161827 0%, #121420 100%);
      font-family: "Courier New", Consolas, monospace;
      image-rendering: pixelated;
    }}
    .shell {{
      max-width: 1520px;
      margin: 0 auto;
      padding: 20px;
    }}
    .header {{
      background: var(--panel);
      border: 2px solid var(--line);
      box-shadow: var(--pixel-shadow);
      padding: 18px;
      margin-bottom: 18px;
    }}
    .header h1 {{
      margin: 0 0 10px;
      font-size: 28px;
      letter-spacing: 1px;
    }}
    .header p {{
      margin: 0;
      color: var(--muted);
      line-height: 1.5;
    }}
    .meta-row {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 14px;
    }}
    .pixel-pill {{
      padding: 8px 10px;
      background: var(--panel-2);
      border: 2px solid var(--line);
      color: var(--text);
      font-size: 12px;
      box-shadow: var(--pixel-shadow);
    }}
    .layout {{
      display: grid;
      grid-template-columns: 1.2fr 360px;
      gap: 18px;
    }}
    .board, .sidebar {{
      display: grid;
      gap: 16px;
    }}
    .panel {{
      background: var(--panel);
      border: 2px solid var(--line);
      box-shadow: var(--pixel-shadow);
    }}
    .panel-header {{
      padding: 10px 12px;
      background: rgba(255,255,255,0.04);
      border-bottom: 2px solid var(--line);
      font-size: 14px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 10px;
    }}
    .panel-body {{
      padding: 12px;
    }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
    }}
    .summary-card {{
      background: var(--panel-2);
      border: 2px solid var(--line);
      padding: 12px;
      min-height: 92px;
    }}
    .summary-card .label {{
      color: var(--muted);
      font-size: 11px;
      margin-bottom: 8px;
      text-transform: uppercase;
    }}
    .summary-card .value {{
      font-size: 24px;
      color: var(--accent);
    }}
    .summary-card .sub {{
      font-size: 11px;
      color: var(--muted);
      margin-top: 8px;
      line-height: 1.4;
    }}
    .controls {{
      display: grid;
      gap: 10px;
    }}
    .timeline-row {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }}
    input[type="range"] {{
      width: 100%;
      accent-color: var(--accent);
    }}
    .zones {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}
    .zone {{
      background: var(--bg-soft);
      border: 2px solid var(--line);
      min-height: 210px;
      display: grid;
      grid-template-rows: auto 1fr;
    }}
    .zone-header {{
      padding: 8px 10px;
      border-bottom: 2px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 8px;
      font-size: 12px;
      text-transform: uppercase;
      color: var(--accent-2);
      background: rgba(255,255,255,0.04);
    }}
    .zone-grid {{
      padding: 10px;
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(var(--tile-size), 1fr));
      gap: 10px;
      align-content: start;
    }}
    .tile {{
      background: #3b4271;
      border: 2px solid #7482d6;
      box-shadow: inset 0 0 0 2px rgba(17,20,34,0.45);
      min-height: 78px;
      padding: 8px;
      display: grid;
      gap: 6px;
      align-content: start;
    }}
    .tile.danger {{ border-color: var(--danger); }}
    .tile.pending {{ border-color: var(--pending); }}
    .tile.observation {{ border-color: var(--obs); }}
    .tile.reprioritized {{ border-color: var(--accent-2); }}
    .tile .case-id {{
      font-size: 12px;
      color: var(--text);
    }}
    .tile .dept {{
      font-size: 11px;
      color: var(--muted);
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .badge-row {{
      display: flex;
      gap: 4px;
      flex-wrap: wrap;
    }}
    .badge {{
      font-size: 10px;
      line-height: 1;
      padding: 4px 5px;
      background: rgba(255,255,255,0.08);
      border: 1px solid rgba(255,255,255,0.12);
      color: var(--text);
    }}
    .resource-list, .patient-list {{
      display: grid;
      gap: 8px;
    }}
    .resource-item, .patient-item {{
      background: var(--panel-2);
      border: 2px solid var(--line);
      padding: 10px;
      font-size: 12px;
      line-height: 1.5;
    }}
    .legend {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }}
    .legend .badge {{
      border-width: 2px;
    }}
    @media (max-width: 1180px) {{
      .layout {{ grid-template-columns: 1fr; }}
      .summary-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .zones {{ grid-template-columns: 1fr; }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="header">
      <h1>Pixel Visual ER Simulation</h1>
      <p>This is a pixel-style simulation viewer for validating temporal queue flow, pending tests, resource occupancy, and specialty transitions. It is a visual replay tool, not a game interface.</p>
      <div class="meta-row">
        <span class="pixel-pill" id="runPill"></span>
        <span class="pixel-pill" id="policyPill"></span>
        <span class="pixel-pill" id="framePill"></span>
      </div>
    </section>

    <div class="layout">
      <main class="board">
        <section class="panel">
          <div class="panel-header">Run Summary</div>
          <div class="panel-body">
            <div class="summary-grid" id="summaryGrid"></div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-header">Timeline Controls <span id="minuteLabel"></span></div>
          <div class="panel-body controls">
            <div class="timeline-row">
              <button type="button" class="pixel-pill" id="prevBtn">Prev</button>
              <button type="button" class="pixel-pill" id="playBtn">Play</button>
              <button type="button" class="pixel-pill" id="nextBtn">Next</button>
            </div>
            <input type="range" id="frameSlider" min="0" max="0" value="0" />
            <div class="legend">
              <span class="badge">normal</span>
              <span class="badge" style="border-color: var(--accent-2);">reprioritized</span>
              <span class="badge" style="border-color: var(--pending);">pending</span>
              <span class="badge" style="border-color: var(--obs);">observation</span>
              <span class="badge" style="border-color: var(--danger);">deterioration</span>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-header">ER Scene</div>
          <div class="panel-body">
            <div class="zones" id="zones"></div>
          </div>
        </section>
      </main>

      <aside class="sidebar">
        <section class="panel">
          <div class="panel-header">Active Resources</div>
          <div class="panel-body resource-list" id="resourceList"></div>
        </section>

        <section class="panel">
          <div class="panel-header">Patients</div>
          <div class="panel-body patient-list" id="patientList"></div>
        </section>
      </aside>
    </div>
  </div>

  <script>
    const payload = {embedded};
    const frames = payload.frames || [];
    const zoneLabels = payload.zone_labels || {{}};
    const patients = payload.patients || [];
    const summary = payload.summary || {{}};
    let frameIndex = 0;
    let timer = null;

    function fmtMinute(value) {{
      if (value === null || value === undefined) return "-";
      return `${{value}}m`;
    }}

    function pct(value) {{
      return `${{Math.round((value || 0) * 100)}}%`;
    }}

    function renderHeader() {{
      document.getElementById("runPill").textContent = `run: ${{payload.run_id}}`;
      document.getElementById("policyPill").textContent = payload.queue_policy || "queue policy";
      document.getElementById("framePill").textContent = `${{frames.length}} frames`;
    }}

    function renderSummary() {{
      const items = [
        ["Diagnosis Accuracy", pct(summary.diagnosis_accuracy), `${{summary.diagnosis_correct_count || 0}} correct`],
        ["Department Accuracy", pct(summary.department_accuracy), `${{summary.department_correct_count || 0}} correct`],
        ["Average Wait", fmtMinute(summary.average_queue_wait_time_min), `max ${{fmtMinute(summary.max_queue_wait_time_min)}}`],
        ["Priority Changes", `${{summary.reprioritized_case_count || 0}}`, `${{summary.pending_wait_case_count || 0}} pending waits`],
      ];
      document.getElementById("summaryGrid").innerHTML = items.map(([label, value, sub]) => `
        <div class="summary-card">
          <div class="label">${{label}}</div>
          <div class="value">${{value}}</div>
          <div class="sub">${{sub}}</div>
        </div>
      `).join("");
    }}

    function tileClass(patient) {{
      const alerts = new Set(patient.alerts || []);
      if (alerts.has("deterioration")) return "tile danger";
      if (alerts.has("pending_result")) return "tile pending";
      if (alerts.has("observation")) return "tile observation";
      if (alerts.has("reprioritized")) return "tile reprioritized";
      return "tile";
    }}

    function renderZones(frame) {{
      const container = document.getElementById("zones");
      container.innerHTML = (payload.zones || []).map((zoneKey) => {{
        const zonePatients = (frame.zones || {{}})[zoneKey] || [];
        const tiles = zonePatients.map((patient) => `
          <div class="${{tileClass(patient)}}">
            <div class="case-id">${{patient.case_id}}</div>
            <div class="dept">${{patient.predicted_department || "pending"}}</div>
            <div class="badge-row">
              <span class="badge">T${{patient.triage_level}}→${{patient.effective_triage_level}}</span>
              ${{(patient.alerts || []).map((alert) => `<span class="badge">${{alert}}</span>`).join("")}}
            </div>
          </div>
        `).join("");
        return `
          <section class="zone">
            <div class="zone-header">
              <span>${{zoneLabels[zoneKey] || zoneKey}}</span>
              <span>${{zonePatients.length}}</span>
            </div>
            <div class="zone-grid">
              ${{tiles || `<div class="badge">empty</div>`}}
            </div>
          </section>
        `;
      }}).join("");
    }}

    function renderResources(frame) {{
      const container = document.getElementById("resourceList");
      const items = frame.resource_occupancy || [];
      container.innerHTML = items.length ? items.map((item) => `
        <div class="resource-item">
          <strong>${{item.resource_kind}}</strong><br />
          ${{item.case_id}} · ${{item.action}}${{item.target ? ` · ${{item.target}}` : ""}}<br />
          ${{fmtMinute(item.start_time_min)}} - ${{fmtMinute(item.end_time_min)}}
        </div>
      `).join("") : `<div class="resource-item">No active resources at this minute.</div>`;
    }}

    function renderPatients(frame) {{
      const zoneMap = new Map();
      for (const zoneKey of Object.keys(frame.zones || {{}})) {{
        for (const patient of frame.zones[zoneKey] || []) {{
          zoneMap.set(patient.case_id, patient);
        }}
      }}
      const container = document.getElementById("patientList");
      container.innerHTML = patients.map((patient) => {{
        const active = zoneMap.get(patient.case_id);
        const queue = patient.queue_metrics || {{}};
        const temporal = patient.temporal_metrics || {{}};
        return `
          <div class="patient-item">
            <strong>${{patient.case_id}}</strong><br />
            zone: ${{active ? active.zone : "not_visible"}}<br />
            triage: ${{queue.triage_level ?? "-"}} → ${{(queue.dynamic_priority || {{}}).effective_triage_level ?? queue.triage_level ?? "-"}}<br />
            wait: ${{fmtMinute(queue.queue_wait_time_min)}}<br />
            final dx time: ${{fmtMinute(temporal.time_to_final_diagnosis_min)}}<br />
            diagnosis: ${{patient.predicted_diagnosis || "-"}}
          </div>
        `;
      }}).join("");
    }}

    function renderFrame(index) {{
      const frame = frames[index];
      if (!frame) return;
      document.getElementById("minuteLabel").textContent = `minute ${{frame.minute}}`;
      document.getElementById("frameSlider").value = String(index);
      renderZones(frame);
      renderResources(frame);
      renderPatients(frame);
    }}

    function togglePlay() {{
      const btn = document.getElementById("playBtn");
      if (timer) {{
        clearInterval(timer);
        timer = null;
        btn.textContent = "Play";
        return;
      }}
      btn.textContent = "Pause";
      timer = setInterval(() => {{
        frameIndex = (frameIndex + 1) % frames.length;
        renderFrame(frameIndex);
      }}, 800);
    }}

    function setupControls() {{
      const slider = document.getElementById("frameSlider");
      slider.max = String(Math.max(frames.length - 1, 0));
      slider.addEventListener("input", (event) => {{
        frameIndex = Number(event.target.value || 0);
        renderFrame(frameIndex);
      }});
      document.getElementById("prevBtn").addEventListener("click", () => {{
        frameIndex = Math.max(frameIndex - 1, 0);
        renderFrame(frameIndex);
      }});
      document.getElementById("nextBtn").addEventListener("click", () => {{
        frameIndex = Math.min(frameIndex + 1, frames.length - 1);
        renderFrame(frameIndex);
      }});
      document.getElementById("playBtn").addEventListener("click", togglePlay);
    }}

    renderHeader();
    renderSummary();
    setupControls();
    renderFrame(0);
  </script>
</body>
</html>
"""


def build_pixel_visual_simulation(run_id: str) -> Path:
    state_path = settings.REPORTS_DIR / run_id / "visual_simulation_state.json"
    state = _load_json(state_path)
    payload = {
        **state,
        "zone_labels": ZONE_LABELS,
    }
    html = _html_template(payload)
    run_dir = get_run_dir(settings.REPORTS_DIR, run_id)
    output_path = run_dir / "pixel_visual_simulation.html"
    output_path.write_text(html, encoding="utf-8")
    return output_path


def main() -> None:
    import sys

    run_id = str(sys.argv[1]).strip() if len(sys.argv) >= 2 else get_latest_run_id(
        settings.REPORTS_DIR,
        required_file="visual_simulation_state.json",
    )

    output_path = build_pixel_visual_simulation(run_id)
    print(f"[PIXEL-VIS] {output_path}")


if __name__ == "__main__":
    main()
