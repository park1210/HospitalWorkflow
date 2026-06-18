from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from app.core.hospital_scene_builder import load_hospital_scene_layout


def _safe_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2)


def build_live_web_viewer_html(
    *,
    run_id: str,
    snapshot_filename: str = "live_visual_state.json",
    snapshot_endpoint: Optional[str] = None,
    asset_base_url: str = "/pixel-re-assets",
) -> str:
    layout = load_hospital_scene_layout()
    initial_layout = {
        "zone_slots": dict(layout.get("zone_slots", {}) or {}),
        "locations": dict(layout.get("locations", {}) or {}),
        "tile_size": int(layout.get("tile_size", 16) or 16),
    }
    resolved_snapshot_source = str(snapshot_endpoint).strip() or snapshot_filename
    resolved_asset_base_url = str(asset_base_url).strip() or "/pixel-re-assets"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Clinical AgentSim Live Web Viewer</title>
  <style>
    :root {{
      --bg: #0a1020;
      --bg-soft: #111b31;
      --panel: rgba(10, 16, 32, 0.82);
      --panel-strong: rgba(14, 22, 42, 0.94);
      --line: rgba(134, 160, 217, 0.28);
      --text: #f3f5fb;
      --muted: #aeb8d6;
      --accent: #87d4ff;
      --accent-strong: #54baf5;
      --gold: #f2d37a;
      --danger: #ff7c74;
      --warn: #ffbe6c;
      --ok: #98d47d;
      --shadow: 0 18px 50px rgba(0, 0, 0, 0.35);
      --radius-xl: 28px;
      --radius-lg: 22px;
      --radius-md: 16px;
      --content: 1480px;
    }}

    * {{
      box-sizing: border-box;
    }}

    html, body {{
      margin: 0;
      min-height: 100%;
      background:
        radial-gradient(circle at top left, rgba(101, 173, 255, 0.18), transparent 32%),
        radial-gradient(circle at top right, rgba(255, 216, 130, 0.12), transparent 28%),
        linear-gradient(180deg, #08101f 0%, #0f1a31 46%, #0a1020 100%);
      color: var(--text);
      font-family: "Segoe UI", "Noto Sans KR", sans-serif;
    }}

    body {{
      padding: 32px 22px 52px;
    }}

    .shell {{
      max-width: var(--content);
      margin: 0 auto;
    }}

    .hero {{
      position: relative;
      overflow: hidden;
      border: 1px solid var(--line);
      border-radius: 34px;
      padding: 36px 38px 28px;
      background:
        linear-gradient(135deg, rgba(18, 29, 56, 0.92), rgba(9, 14, 28, 0.94)),
        radial-gradient(circle at right top, rgba(135, 212, 255, 0.16), transparent 35%);
      box-shadow: var(--shadow);
      margin-bottom: 20px;
    }}

    .hero::after {{
      content: "";
      position: absolute;
      inset: auto -4% -42% 40%;
      height: 280px;
      background: radial-gradient(circle, rgba(135, 212, 255, 0.22), transparent 62%);
      pointer-events: none;
    }}

    .hero-top {{
      display: flex;
      justify-content: space-between;
      gap: 24px;
      align-items: flex-start;
      margin-bottom: 24px;
    }}

    .eyebrow {{
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 8px 12px;
      border-radius: 999px;
      border: 1px solid rgba(135, 212, 255, 0.24);
      background: rgba(135, 212, 255, 0.07);
      color: var(--accent);
      font-size: 12px;
      letter-spacing: 0.16em;
      text-transform: uppercase;
      font-weight: 700;
    }}

    h1 {{
      margin: 14px 0 12px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: clamp(2.25rem, 4vw, 4rem);
      line-height: 1.02;
      letter-spacing: -0.04em;
      max-width: 11ch;
    }}

    .hero-copy {{
      max-width: 760px;
      color: var(--muted);
      font-size: 16px;
      line-height: 1.75;
      margin: 0;
    }}

    .hero-actions {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 20px;
    }}

    .pill {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 10px 14px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.04);
      color: var(--text);
      font-size: 13px;
      text-decoration: none;
    }}

    .hero-metrics {{
      display: grid;
      grid-template-columns: repeat(3, minmax(120px, 1fr));
      gap: 12px;
      min-width: 320px;
    }}

    .metric-card {{
      padding: 16px;
      border-radius: 18px;
      border: 1px solid rgba(255, 255, 255, 0.06);
      background: rgba(255, 255, 255, 0.04);
      backdrop-filter: blur(10px);
    }}

    .metric-label {{
      font-size: 12px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.12em;
      margin-bottom: 8px;
    }}

    .metric-value {{
      font-size: 28px;
      font-weight: 700;
    }}

    .info-band {{
      display: grid;
      grid-template-columns: 1.25fr 1fr;
      gap: 18px;
      margin-bottom: 20px;
    }}

    .band-card {{
      border-radius: 24px;
      border: 1px solid var(--line);
      background: var(--panel);
      box-shadow: var(--shadow);
      padding: 22px 24px;
    }}

    .band-title {{
      margin: 0 0 10px;
      font-family: Georgia, "Times New Roman", serif;
      font-size: 24px;
    }}

    .band-text {{
      margin: 0;
      color: var(--muted);
      line-height: 1.72;
      font-size: 15px;
    }}

    .flow-steps {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-top: 18px;
    }}

    .flow-step {{
      padding: 14px;
      border-radius: 16px;
      background: rgba(255, 255, 255, 0.04);
      border: 1px solid rgba(255, 255, 255, 0.06);
    }}

    .flow-step strong {{
      display: block;
      color: var(--gold);
      margin-bottom: 4px;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.12em;
    }}

    .viewer-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.6fr) minmax(360px, 0.9fr);
      gap: 20px;
      align-items: start;
    }}

    .panel {{
      border-radius: var(--radius-xl);
      border: 1px solid var(--line);
      background: var(--panel-strong);
      box-shadow: var(--shadow);
      overflow: hidden;
    }}

    .panel-head {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      gap: 14px;
      padding: 18px 22px;
      border-bottom: 1px solid rgba(255, 255, 255, 0.06);
      background: linear-gradient(180deg, rgba(255,255,255,0.03), rgba(255,255,255,0));
    }}

    .panel-title {{
      margin: 0;
      font-size: 18px;
      font-weight: 700;
      letter-spacing: 0.01em;
    }}

    .panel-subtitle {{
      color: var(--muted);
      font-size: 13px;
    }}

    .scene-wrap {{
      padding: 20px;
      overflow: auto;
    }}

    .scene-stage {{
      position: relative;
      min-height: 760px;
      border-radius: 26px;
      border: 1px solid rgba(255,255,255,0.07);
      overflow: hidden;
      background: linear-gradient(180deg, rgba(238, 240, 246, 0.98), rgba(231, 234, 241, 0.98));
    }}

    .scene-stage::before {{
      display: none;
    }}

    .scene-canvas {{
      display: block;
      width: 100%;
      height: auto;
      image-rendering: pixelated;
      image-rendering: crisp-edges;
    }}

    .sidebar {{
      display: grid;
      gap: 18px;
    }}

    .stats-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 12px;
    }}

    .stat-box {{
      padding: 16px;
      border-radius: 18px;
      border: 1px solid rgba(255,255,255,0.07);
      background: rgba(255,255,255,0.04);
    }}

    .stat-box strong {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
      margin-bottom: 6px;
    }}

    .stat-box span {{
      font-size: 26px;
      font-weight: 700;
    }}

    .triage-strip {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      margin-top: 12px;
    }}

    .triage-chip {{
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.08em;
      color: #101623;
    }}

    .scroll-card {{
      padding: 18px 20px;
      max-height: 286px;
      overflow: auto;
    }}

    .scroll-card::-webkit-scrollbar {{
      width: 10px;
    }}

    .scroll-card::-webkit-scrollbar-thumb {{
      background: rgba(135, 212, 255, 0.18);
      border-radius: 999px;
    }}

    .patient-row {{
      padding: 14px 0;
      border-bottom: 1px solid rgba(255,255,255,0.06);
      cursor: pointer;
    }}

    .patient-row:last-child {{
      border-bottom: 0;
    }}

    .patient-row.active {{
      background: rgba(135, 212, 255, 0.08);
      margin: 0 -10px;
      padding-left: 10px;
      padding-right: 10px;
      border-radius: 14px;
    }}

    .patient-head {{
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
      margin-bottom: 6px;
    }}

    .patient-name {{
      font-weight: 700;
      font-size: 15px;
    }}

    .patient-zone {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.08em;
    }}

    .muted {{
      color: var(--muted);
    }}

    .case-detail {{
      display: grid;
      gap: 16px;
    }}

    .detail-block {{
      padding: 14px 16px;
      border-radius: 18px;
      border: 1px solid rgba(255,255,255,0.06);
      background: rgba(255,255,255,0.04);
    }}

    .detail-block h4 {{
      margin: 0 0 10px;
      color: var(--gold);
      font-size: 13px;
      text-transform: uppercase;
      letter-spacing: 0.1em;
    }}

    .detail-list, .event-list, .conversation-list {{
      display: grid;
      gap: 10px;
    }}

    .detail-item, .event-item, .conversation-item {{
      padding: 10px 12px;
      border-radius: 14px;
      background: rgba(255,255,255,0.04);
      border: 1px solid rgba(255,255,255,0.05);
      font-size: 13px;
      line-height: 1.55;
    }}

    .what-if-grid {{
      display: grid;
      gap: 10px;
    }}

    .what-if-option {{
      width: 100%;
      text-align: left;
      border: 1px solid rgba(135, 212, 255, 0.18);
      background: rgba(135, 212, 255, 0.08);
      color: var(--text);
      border-radius: 14px;
      padding: 12px 14px;
      cursor: pointer;
      transition: transform 120ms ease, border-color 120ms ease, background 120ms ease;
    }}

    .what-if-option:hover {{
      transform: translateY(-1px);
      border-color: rgba(135, 212, 255, 0.34);
      background: rgba(135, 212, 255, 0.12);
    }}

    .what-if-option strong {{
      display: block;
      margin-bottom: 4px;
      color: var(--accent);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}

    .what-if-result {{
      border: 1px solid rgba(242, 211, 122, 0.14);
      background: rgba(242, 211, 122, 0.06);
    }}

    .history-list {{
      display: grid;
      gap: 8px;
    }}

    .history-button {{
      width: 100%;
      text-align: left;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.04);
      color: var(--text);
      border-radius: 12px;
      padding: 10px 12px;
      cursor: pointer;
    }}

    .history-button.active {{
      border-color: rgba(242, 211, 122, 0.32);
      background: rgba(242, 211, 122, 0.10);
    }}

    .compare-grid {{
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
    }}

    .compare-card {{
      padding: 12px 14px;
      border-radius: 14px;
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.04);
    }}

    .compare-card h5 {{
      margin: 0 0 8px;
      color: var(--accent);
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}

    .compare-metrics {{
      display: grid;
      gap: 6px;
      font-size: 13px;
      line-height: 1.45;
    }}

    .compare-delta {{
      margin-top: 10px;
      padding: 10px 12px;
      border-radius: 12px;
      background: rgba(242, 211, 122, 0.08);
      border: 1px solid rgba(242, 211, 122, 0.14);
    }}

    .mode-tabs {{
      display: inline-flex;
      gap: 8px;
      margin-top: 10px;
      flex-wrap: wrap;
    }}

    .mode-tab {{
      border: 1px solid rgba(255,255,255,0.08);
      background: rgba(255,255,255,0.04);
      color: var(--muted);
      border-radius: 999px;
      padding: 7px 12px;
      font-size: 12px;
      cursor: pointer;
    }}

    .mode-tab.active {{
      color: var(--text);
      background: rgba(135, 212, 255, 0.14);
      border-color: rgba(135, 212, 255, 0.28);
    }}

    .conversation-item.current {{
      border-color: rgba(135, 212, 255, 0.28);
      background: rgba(135, 212, 255, 0.08);
    }}

    .conversation-item.selected {{
      border-color: rgba(242, 211, 122, 0.18);
    }}

    .conversation-meta {{
      color: var(--gold);
      font-size: 11px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 6px;
    }}

    .footer-note {{
      margin-top: 18px;
      color: var(--muted);
      font-size: 12px;
      text-align: right;
    }}

    @media (max-width: 1200px) {{
      .viewer-grid, .info-band {{
        grid-template-columns: 1fr;
      }}

      .hero-top {{
        flex-direction: column;
      }}

      .hero-metrics {{
        width: 100%;
      }}
    }}

    @media (max-width: 760px) {{
      body {{
        padding: 18px 14px 34px;
      }}

      .hero {{
        padding: 26px 22px;
      }}

      .flow-steps, .stats-grid {{
        grid-template-columns: 1fr;
      }}

      .scene-stage {{
        min-height: 560px;
      }}
    }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="hero-top">
        <div>
          <div class="eyebrow">Clinical AgentSim · Live Web Session</div>
          <h1>Temporal ER Simulation with Live Multi-Agent Visualization</h1>
          <p class="hero-copy">
            A browser-based hospital simulation viewer for emergency intake, ER prioritization,
            diagnostic testing, specialty dispatch, and counterfactual review. This page polls the
            latest structured simulation snapshot and renders the hospital state as a polished web experience.
          </p>
          <div class="hero-actions">
            <span class="pill">Run ID <strong id="heroRunId">{run_id}</strong></span>
            <span class="pill">Source <strong>{snapshot_filename}</strong></span>
            <span class="pill">Mode <strong>HTML Live Viewer</strong></span>
          </div>
        </div>
        <div class="hero-metrics">
          <div class="metric-card">
            <div class="metric-label">Current Minute</div>
            <div class="metric-value" id="metricMinute">0</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Completed Cases</div>
            <div class="metric-value" id="metricCompleted">0</div>
          </div>
          <div class="metric-card">
            <div class="metric-label">Waiting Cases</div>
            <div class="metric-value" id="metricWaiting">0</div>
          </div>
        </div>
      </div>
    </section>

    <section class="info-band">
      <article class="band-card">
        <h2 class="band-title">Simulation Narrative</h2>
        <p class="band-text">
          The current system models a hospital-wide temporal scheduler rather than a single serial case flow.
          Patients arrive, receive triage severity, occupy ER resources, wait for objective test results,
          escalate to specialty consultation when needed, and can later be replayed through what-if branches.
        </p>
        <div class="flow-steps">
          <div class="flow-step"><strong>Arrival</strong> Intake, queue, and triage severity assignment.</div>
          <div class="flow-step"><strong>ER Workup</strong> Prioritized interviews, tests, and reassessment.</div>
          <div class="flow-step"><strong>Consult & Replay</strong> Specialty review and counterfactual exploration.</div>
        </div>
      </article>
      <article class="band-card">
        <h2 class="band-title">Live Status</h2>
        <p class="band-text">
          This web page is designed to be served directly from a report folder or containerized static host.
          Open this viewer first, then start a fresh live ER run directly from the browser.
        </p>
        <div class="hero-actions" style="margin-top:14px;">
          <button class="hero-cta" id="startLiveSessionBtn" type="button">Start Live Demo</button>
          <button class="hero-cta" id="stopLiveSessionBtn" type="button">Stop Live Demo</button>
        </div>
        <div class="detail-block" style="margin-top:14px;">
          <h4>Browser Launch</h4>
          <div id="liveLaunchStatus" class="muted">Ready to start a new browser-driven live simulation.</div>
        </div>
        <div class="triage-strip">
          <span class="triage-chip" style="background:#4b5164;color:#f5f7ff;">BLACK</span>
          <span class="triage-chip" style="background:#ff7c74;">RED</span>
          <span class="triage-chip" style="background:#ffd36d;">YELLOW</span>
          <span class="triage-chip" style="background:#98d47d;">GREEN</span>
        </div>
      </article>
    </section>

    <section class="viewer-grid">
      <article class="panel">
        <div class="panel-head">
          <div>
            <h3 class="panel-title">Hospital Scene</h3>
            <div class="panel-subtitle">Live spatial board rendered from structured scene entities</div>
          </div>
          <div style="display:flex; flex-direction:column; align-items:flex-end; gap:10px;">
            <div class="panel-subtitle" id="scenePhase">Phase · initialized</div>
            <div class="mode-tabs" id="playbackControls">
              <button class="mode-tab active" id="btnReplay">Replay</button>
              <button class="mode-tab" id="btnLive">Live Follow</button>
              <button class="mode-tab" id="btnPause">Pause</button>
            </div>
            <div class="panel-subtitle" id="playbackStatus">Preparing replay…</div>
          </div>
        </div>
        <div class="scene-wrap">
          <div class="scene-stage" id="sceneStage">
            <canvas class="scene-canvas" id="sceneCanvas"></canvas>
          </div>
        </div>
      </article>

      <aside class="sidebar">
        <section class="panel">
          <div class="panel-head">
            <div>
              <h3 class="panel-title">Overview</h3>
              <div class="panel-subtitle">Parallel run telemetry</div>
            </div>
          </div>
          <div class="scroll-card">
            <div class="stats-grid">
              <div class="stat-box"><strong>Minute</strong><span id="ovMinute">0</span></div>
              <div class="stat-box"><strong>Resources</strong><span id="ovResources">0</span></div>
              <div class="stat-box"><strong>Completed</strong><span id="ovCompleted">0</span></div>
              <div class="stat-box"><strong>Waiting</strong><span id="ovWaiting">0</span></div>
            </div>
            <div class="detail-block" style="margin-top:14px;">
              <h4>ER Focus</h4>
              <div id="erFocusBlock" class="muted">No active ER assessment</div>
            </div>
          </div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div>
              <h3 class="panel-title">Patients</h3>
              <div class="panel-subtitle">Selectable active case roster</div>
            </div>
          </div>
          <div class="scroll-card" id="patientsList"></div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div>
              <h3 class="panel-title">Case Detail</h3>
              <div class="panel-subtitle">Focused longitudinal case state</div>
            </div>
          </div>
          <div class="scroll-card case-detail" id="caseDetail"></div>
        </section>

        <section class="panel">
          <div class="panel-head">
            <div>
              <h3 class="panel-title">Conversation & Events</h3>
              <div class="panel-subtitle">Latest dialogue and structured event feed</div>
            </div>
          </div>
          <div class="scroll-card">
            <div class="detail-block">
              <h4>Current Dialogue</h4>
              <div id="currentDialogue" class="conversation-list"></div>
            </div>
            <div class="detail-block" style="margin-top:14px;">
              <h4>Selected Case Timeline</h4>
              <div id="selectedConversation" class="conversation-list"></div>
            </div>
            <div class="detail-block" style="margin-top:14px;">
              <h4>Recent Events</h4>
              <div id="recentEvents" class="event-list"></div>
            </div>
          </div>
        </section>
      </aside>
    </section>

    <div class="footer-note">Designed for containerized browser deployment and report-folder serving.</div>
  </div>

  <script>
    const INITIAL_RUN_ID = "{run_id}";
    const SNAPSHOT_URL = "{resolved_snapshot_source}";
    const ASSET_BASE_URL = "{resolved_asset_base_url}";
    const INITIAL_LAYOUT = {_safe_json(initial_layout)};
    const TILE_PX = 26;
    const STAGE_PADDING = 36;
    let currentRunId = INITIAL_RUN_ID;
    let selectedCaseId = "";
    let latestSnapshot = null;
    let sceneHitboxes = [];
    let sceneCanvasBound = false;
    let sceneRenderPositions = {{}};
    let sceneAnimationFrame = 0;
    let whatIfResults = {{}};
    let caseViewModes = {{}};
    let playbackHistory = [];
    let playbackFrames = [];
    let playbackIndex = 0;
    let playbackTimer = 0;
    let livePollTimer = 0;
    let liveFrameQueue = [];
    let liveLastSnapshot = null;
    let liveLastSnapshotSignature = "";
    let playbackMode = "replay";
    let playbackPaused = false;
    const SCENE_WALK_SPEED = 0.6;
    const HISTORY_REPLAY_INTERVAL_MS = 1250;
    const DIALOGUE_RESPONSE_DELAY_MS = 2000;
    const LIVE_POLL_INTERVAL_MS = 2000;
    const MOVE_SETTLE_BUFFER_MS = 1600;
    const MIN_MOVEMENT_STAGE_MS = 1600;
    const MAX_MOVEMENT_STAGE_MS = 7600;
    const CHARACTER_PNG_SIZE = 42;
    const BED_PNG_WIDTH = 84;
    const BED_PNG_HEIGHT = 68;
    const CHARACTER_ROLE_ASSET = {{
      patient: "patient",
      er: "er_doctor",
      specialty: "specialty_doctor",
      nurse: "nurse",
    }};
    const FACING_TO_ASSET_DIRECTION = {{
      down: "front",
      up: "back",
      left: "left",
      right: "right",
    }};
    const externalSpriteImageCache = new Map();

    function joinAssetUrl(path) {{
      const base = String(ASSET_BASE_URL || "").replace(/\/+$/, "");
      const suffix = String(path || "").replace(/^\/+/, "");
      return base ? `${{base}}/${{suffix}}` : suffix;
    }}

    function getSnapshotUrl() {{
      if (String(currentRunId || "").trim()) {{
        return `/api/runs/${{encodeURIComponent(String(currentRunId).trim())}}/snapshot`;
      }}
      return SNAPSHOT_URL;
    }}

    function getHistoryUrl() {{
      const snapshotUrl = getSnapshotUrl();
      return String(snapshotUrl || "").startsWith("/api/runs/")
        ? String(snapshotUrl).replace(/\/snapshot$/, "/history")
        : "";
    }}

    function updateRunIdUi(runId) {{
      const normalized = String(runId || "").trim();
      if (!normalized) return;
      currentRunId = normalized;
      const heroRunId = document.getElementById("heroRunId");
      if (heroRunId) {{
        heroRunId.textContent = normalized;
      }}
    }}

    function setLiveLaunchStatus(message) {{
      const node = document.getElementById("liveLaunchStatus");
      if (node) {{
        node.textContent = String(message || "").trim();
      }}
    }}

    function loadExternalSprite(path) {{
      const assetPath = String(path || "").trim();
      if (!assetPath) return null;
      const url = joinAssetUrl(assetPath);
      if (externalSpriteImageCache.has(url)) {{
        return externalSpriteImageCache.get(url);
      }}
      const image = new Image();
      image.decoding = "async";
      image.loading = "eager";
      image.src = url;
      externalSpriteImageCache.set(url, image);
      return image;
    }}

    function drawExternalSprite(ctx, image, left, top, width, height) {{
      if (!image || !image.complete || !image.naturalWidth) return false;
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(image, left - width / 2, top - height / 2, width, height);
      ctx.imageSmoothingEnabled = true;
      return true;
    }}

    function getCharacterSpriteAssetPath(roleKey, facing, poseMode) {{
      const folder = CHARACTER_ROLE_ASSET[String(roleKey || "").trim()] || "";
      const direction = FACING_TO_ASSET_DIRECTION[String(facing || "").trim()] || "front";
      if (!folder) return "";
      const motion = poseMode === "walk" ? "step" : "idle";
      const frameKey = poseMode === "walk"
        ? (Math.floor(performance.now() / 180) % 2 === 0 ? "a" : "b")
        : (Math.floor(performance.now() / 700) % 2 === 0 ? "a" : "b");
      return `characters/${{folder}}/${{folder}}_${{direction}}_${{motion}}_${{frameKey}}.png`;
    }}

    function getFurnitureSpriteAssetPaths(kind) {{
      if (kind === "bed") {{
        return [
          "furniture/beds/hospital_bed_front_teal_shadow.png",
          "furniture/beds/hospital_bed_front_teal_base.png",
          "furniture/beds/hospital_bed_front_teal_overlay.png",
        ];
      }}
      return [];
    }}

    function deepClone(value) {{
      return value == null ? value : JSON.parse(JSON.stringify(value));
    }}

    function formatDialogueLine(step) {{
      const speaker = String(step?.speaker || "").trim();
      const text = String(step?.text || "").trim();
      if (!text) return "";
      return speaker ? `${{speaker}}: ${{text}}` : text;
    }}

    function dialogueSnapshot(baseSnapshot, step, lines) {{
      const snapshot = deepClone(baseSnapshot);
      snapshot.__scene_freeze = true;
      snapshot.__scene_freeze_entity_ids = [
        String(step?.speaker_entity_id || "").trim(),
        String(step?.listener_entity_id || "").trim(),
      ].filter(Boolean);
      snapshot.dialogue = {{
        ...(snapshot.dialogue || {{}}),
        lines: Array.isArray(lines) ? lines.slice() : [],
        bubble_text: String(step?.text || "").trim(),
        speaker_entity_id: String(step?.speaker_entity_id || "").trim(),
        listener_entity_id: String(step?.listener_entity_id || "").trim(),
        interaction_location_id: String(step?.interaction_location_id || snapshot?.dialogue?.interaction_location_id || "").trim(),
      }};
      return snapshot;
    }}

    function frozenDialogueSnapshot(previousSnapshot, currentSnapshot, step, lines) {{
      const snapshot = deepClone(previousSnapshot || currentSnapshot);
      snapshot.__scene_freeze = true;
      snapshot.__scene_freeze_entity_ids = [
        String(step?.speaker_entity_id || "").trim(),
        String(step?.listener_entity_id || "").trim(),
      ].filter(Boolean);
      snapshot.current_time_min = currentSnapshot?.current_time_min ?? snapshot.current_time_min;
      snapshot.phase = currentSnapshot?.phase ?? snapshot.phase;
      snapshot.action = currentSnapshot?.action ?? snapshot.action;
      snapshot.case_details = deepClone(currentSnapshot?.case_details || {{}});
      snapshot.patients = deepClone(currentSnapshot?.patients || []);
      snapshot.er_focus = deepClone(currentSnapshot?.er_focus || {{}});
      snapshot.dialogue = {{
        ...(deepClone(currentSnapshot?.dialogue || {{}})),
        lines: Array.isArray(lines) ? lines.slice() : [],
        bubble_text: String(step?.text || "").trim(),
        speaker_entity_id: String(step?.speaker_entity_id || "").trim(),
        listener_entity_id: String(step?.listener_entity_id || "").trim(),
        interaction_location_id: String(step?.interaction_location_id || currentSnapshot?.dialogue?.interaction_location_id || "").trim(),
      }};
      return snapshot;
    }}

    function movementSnapshot(snapshot) {{
      const clone = deepClone(snapshot);
      clone.dialogue = {{
        ...(deepClone(clone?.dialogue || {{}})),
        lines: [],
        bubble_text: "",
        speaker_entity_id: "",
        listener_entity_id: "",
        interaction_location_id: "",
      }};
      delete clone.__scene_freeze;
      delete clone.__scene_freeze_entity_ids;
      return clone;
    }}

    function estimateTravelDelayMs(currentSnapshot, previousSnapshot) {{
      if (!previousSnapshot) {{
        return HISTORY_REPLAY_INTERVAL_MS;
      }}
      const currentEntities = Array.isArray(currentSnapshot?.scene?.entities) ? currentSnapshot.scene.entities : [];
      const previousEntities = Array.isArray(previousSnapshot?.scene?.entities) ? previousSnapshot.scene.entities : [];
      const previousById = Object.fromEntries(previousEntities.map((entity) => [String(entity?.id || "").trim(), entity]));
      let maxDistancePx = 0;

      currentEntities.forEach((entity) => {{
        const entityId = String(entity?.id || "").trim();
        if (!entityId) return;
        const previousEntity = previousById[entityId];
        if (!previousEntity) return;
        const fromLocationId = String(previousEntity?.location_id || "").trim();
        const toLocationId = String(entity?.location_id || "").trim();
        if (!fromLocationId || !toLocationId || fromLocationId === toLocationId) return;
        const routePoints = routePointsForEntity(entity, currentSnapshot, fromLocationId, toLocationId);
        let distance = 0;
        let start = sceneEntityTargetPosition(previousEntity, previousSnapshot);
        routePoints.forEach((point) => {{
          const dx = Number(point?.x ?? start.x) - Number(start.x);
          const dy = Number(point?.y ?? start.y) - Number(start.y);
          distance += Math.hypot(dx, dy);
          start = {{ x: Number(point?.x ?? start.x), y: Number(point?.y ?? start.y) }};
        }});
        maxDistancePx = Math.max(maxDistancePx, distance);
      }});

      if (maxDistancePx <= 0.5) {{
        return HISTORY_REPLAY_INTERVAL_MS;
      }}
      const pixelsPerSecond = SCENE_WALK_SPEED * 60;
      const durationMs = ((maxDistancePx / Math.max(pixelsPerSecond, 0.01)) * 1000) * 1.35;
      return Math.max(MIN_MOVEMENT_STAGE_MS, Math.min(MAX_MOVEMENT_STAGE_MS, Math.round(durationMs + MOVE_SETTLE_BUFFER_MS)));
    }}

    function estimateIntrinsicTravelDelayMs(snapshot) {{
      const entities = Array.isArray(snapshot?.scene?.entities) ? snapshot.scene.entities : [];
      let maxDistancePx = 0;
      entities.forEach((entity) => {{
        const fromLocationId = entityCurrentLocationId(entity);
        const toLocationId = entityTargetLocationId(entity);
        if (!fromLocationId || !toLocationId || fromLocationId === toLocationId) return;
        const routePoints = routePointsForEntity(entity, snapshot, fromLocationId, toLocationId);
        let start = stagePosition(snapshot, fromLocationId);
        let distance = 0;
        routePoints.forEach((point) => {{
          const dx = Number(point?.x ?? start.left) - Number(start.left);
          const dy = Number(point?.y ?? start.top) - Number(start.top);
          distance += Math.hypot(dx, dy);
          start = {{ left: Number(point?.x ?? start.left), top: Number(point?.y ?? start.top) }};
        }});
        maxDistancePx = Math.max(maxDistancePx, distance);
      }});
      if (maxDistancePx <= 0.5) {{
        return HISTORY_REPLAY_INTERVAL_MS;
      }}
      const pixelsPerSecond = SCENE_WALK_SPEED * 60;
      const durationMs = ((maxDistancePx / Math.max(pixelsPerSecond, 0.01)) * 1000) * 1.35;
      return Math.max(MIN_MOVEMENT_STAGE_MS, Math.min(MAX_MOVEMENT_STAGE_MS, Math.round(durationMs + MOVE_SETTLE_BUFFER_MS)));
    }}

    function stateHoldDelayMs(snapshot) {{
      const action = String(snapshot?.action || snapshot?.phase || "").trim();
      if (action === "test_result_ready") {{
        return 3200;
      }}
      if (action === "review_results") {{
        return 1800;
      }}
      if (action === "request_specialty") {{
        return 1800;
      }}
      if (action === "consult_started") {{
        return 2000;
      }}
      if (action === "bed_assigned" || action === "perform_triage") {{
        return 1200;
      }}
      return HISTORY_REPLAY_INTERVAL_MS;
    }}

    function buildFramesForSnapshot(currentSnapshot, previousSnapshot = null) {{
      const frames = [];
      const current = deepClone(currentSnapshot);
      const previous = previousSnapshot ? deepClone(previousSnapshot) : null;
      const sequence = Array.isArray(current?.dialogue?.sequence)
        ? current.dialogue.sequence.filter((item) => String(item?.text || "").trim())
        : [];
      const hasIntrinsicMovement = Array.isArray(current?.scene?.entities)
        ? current.scene.entities.some((entity) => {{
            const fromLocationId = entityCurrentLocationId(entity);
            const toLocationId = entityTargetLocationId(entity);
            return Boolean(fromLocationId && toLocationId && fromLocationId !== toLocationId);
          }})
        : false;
      if (sequence.length) {{
        if (previous || hasIntrinsicMovement) {{
          frames.push({{
            snapshot: movementSnapshot(current),
            delayMs: previous ? estimateTravelDelayMs(current, previous) : estimateIntrinsicTravelDelayMs(current),
          }});
        }}
        const stagedLines = [];
        sequence.forEach((step, stepIndex) => {{
          const line = formatDialogueLine(step);
          if (line) stagedLines.push(line);
          frames.push({{
            snapshot: previous
              ? frozenDialogueSnapshot(current, current, step, stagedLines)
              : dialogueSnapshot(current, step, stagedLines),
            delayMs: Number(step?.delay_ms || (stepIndex === 0 && sequence.length > 1 ? DIALOGUE_RESPONSE_DELAY_MS : HISTORY_REPLAY_INTERVAL_MS)),
          }});
        }});
        frames.push({{
          snapshot: movementSnapshot(current),
          delayMs: Math.max(700, Math.round(stateHoldDelayMs(current) * 0.45)),
        }});
        return frames;
      }}

      if (previous && hasIntrinsicMovement) {{
        frames.push({{
          snapshot: movementSnapshot(current),
          delayMs: estimateTravelDelayMs(current, previous),
        }});
        frames.push({{
          snapshot: current,
          delayMs: stateHoldDelayMs(current),
        }});
        return frames;
      }}

      if (!previous && hasIntrinsicMovement) {{
        frames.push({{
          snapshot: movementSnapshot(current),
          delayMs: estimateIntrinsicTravelDelayMs(current),
        }});
        frames.push({{
          snapshot: current,
          delayMs: stateHoldDelayMs(current),
        }});
        return frames;
      }}

      frames.push({{
        snapshot: current,
        delayMs: stateHoldDelayMs(current),
      }});
      return frames;
    }}

    function buildPlaybackFrames(history) {{
      const frames = [];
      history.forEach((snapshot, index) => {{
        frames.push(...buildFramesForSnapshot(snapshot, index > 0 ? history[index - 1] : null));
      }});
      return frames;
    }}

    const zoneTitles = {{
      waiting_room: "Waiting",
      er_workup: "ER Beds",
      observation: "Observation",
      awaiting_results: "Diagnostics",
      specialty_review: "Consult Hall",
      completed: "Discharge"
    }};

    const severityPalette = {{
      1: "#ff7c74",
      2: "#ff7c74",
      3: "#ffd36d",
      4: "#98d47d",
      5: "#98d47d"
    }};

    function normalizeText(value, fallback = "-") {{
      const text = String(value ?? "").trim();
      return text || fallback;
    }}

    function getCaseDetailsMap(snapshot) {{
      return snapshot && snapshot.case_details ? snapshot.case_details : {{}};
    }}

    function getSelectedCase(snapshot) {{
      const details = getCaseDetailsMap(snapshot);
      if (selectedCaseId && details[selectedCaseId]) {{
        return selectedCaseId;
      }}
      const firstPatient = Array.isArray(snapshot?.patients) ? snapshot.patients[0] : null;
      selectedCaseId = firstPatient?.case_id || Object.keys(details)[0] || "";
      return selectedCaseId;
    }}

    function locationMap(snapshot) {{
      return snapshot?.scene?.locations || INITIAL_LAYOUT.locations || {{}};
    }}

    function zoneSlotMap(snapshot) {{
      return snapshot?.scene?.zone_slots || INITIAL_LAYOUT.zone_slots || {{}};
    }}

    function stageMetrics(snapshot) {{
      const locations = locationMap(snapshot);
      const values = Object.values(locations || {{}}).filter(Boolean);
      const maxX = Math.max(...values.map((p) => Number(p.x || 0)), 44);
      const maxY = Math.max(...values.map((p) => Number(p.y || 0)), 26);
      return {{
        width: (maxX + 4) * TILE_PX + STAGE_PADDING * 2,
        height: (maxY + 4) * TILE_PX + STAGE_PADDING * 2
      }};
    }}

    function zoneBounds(snapshot, zoneKey) {{
      const slots = zoneSlotMap(snapshot)[zoneKey] || [];
      const locations = locationMap(snapshot);
      const points = slots.map((slotId) => locations[slotId]).filter(Boolean);
      if (!points.length) {{
        return {{ left: 8, top: 8, width: 120, height: 120 }};
      }}
      const xs = points.map((p) => Number(p.x || 0));
      const ys = points.map((p) => Number(p.y || 0));
      const minX = Math.min(...xs);
      const maxX = Math.max(...xs);
      const minY = Math.min(...ys);
      const maxY = Math.max(...ys);
      return {{
        left: minX * TILE_PX + STAGE_PADDING - 30,
        top: minY * TILE_PX + STAGE_PADDING - 30,
        width: Math.max((maxX - minX + 1) * TILE_PX + 60, 180),
        height: Math.max((maxY - minY + 1) * TILE_PX + 60, 150)
      }};
    }}

    function stagePosition(snapshot, locationId) {{
      const loc = locationMap(snapshot)[locationId] || {{}};
      return {{
        left: Number(loc.x || 8) * TILE_PX + STAGE_PADDING,
        top: Number(loc.y || 8) * TILE_PX + STAGE_PADDING
      }};
    }}

    function entityRenderKey(entity) {{
      return String(entity?.id || entity?.case_id || "").trim();
    }}

    function entityCurrentLocationId(entity) {{
      return String(entity?.current_location_id || entity?.location_id || "").trim();
    }}

    function entityTargetLocationId(entity) {{
      return String(entity?.target_location_id || entity?.location_id || "").trim();
    }}

    function entityInteractionLocationId(entity) {{
      return String(entity?.interaction_location_id || "").trim();
    }}

    function sceneEntityTargetPosition(entity, snapshot) {{
      const pos = stagePosition(snapshot, entityTargetLocationId(entity));
      return {{ x: pos.left, y: pos.top }};
    }}

    const ROUTE_GRAPH = {{
      triage_desk: ["hallway_waiting_entry"],
      hallway_waiting_entry: ["triage_desk", "door_waiting_to_er"],
      door_waiting_to_er: ["hallway_waiting_entry", "hallway_er_lower"],
      hallway_er_lower: ["door_waiting_to_er", "hallway_er_center", "hallway_observation_entry", "hallway_diagnostics_lower"],
      hallway_er_center: ["hallway_er_lower", "hallway_er_upper", "door_er_to_observation"],
      hallway_er_upper: ["hallway_er_center", "door_er_to_diagnostics", "hallway_er_to_consult"],
      door_er_to_diagnostics: ["hallway_er_upper", "hallway_diagnostics_entry"],
      hallway_diagnostics_entry: ["door_er_to_diagnostics", "hallway_er_to_imaging", "hallway_diagnostics_lower"],
      hallway_diagnostics_lower: ["hallway_diagnostics_entry", "hallway_er_lower"],
      hallway_er_to_imaging: ["hallway_diagnostics_entry"],
      door_er_to_observation: ["hallway_er_center", "hallway_observation_entry"],
      hallway_observation_entry: ["door_er_to_observation", "hallway_er_lower"],
      hallway_er_to_consult: ["hallway_er_upper", "hallway_consult_upper"],
      hallway_consult_upper: ["hallway_er_to_consult", "hallway_consult_entry"],
      hallway_consult_entry: ["hallway_consult_upper", "door_consult_entry", "hallway_consult_lower", "hallway_consult_to_er"],
      hallway_consult_lower: ["hallway_consult_entry"],
      door_consult_entry: ["hallway_consult_entry"],
      hallway_consult_to_er: ["hallway_consult_entry", "hallway_er_center"],
    }};

    function anchorNodeForLocation(locationId) {{
      const id = String(locationId || "").trim();
      if (!id) return "";
      if (id.startsWith("hallway_") || id.startsWith("door_")) return id;
      if (id.startsWith("arrival_") || id.startsWith("triage_") || id.startsWith("waiting_")) return "hallway_waiting_entry";
      if (id === "triage_desk") return "triage_desk";
      if (id === "er_doctor_station" || id === "nurse_station" || id === "chart_desk_1" || id === "chart_desk_2") return "hallway_er_lower";
      if (id === "er_bed_1" || id === "er_bed_2" || id === "er_bedside_1" || id === "er_bedside_2" || id === "bedside_monitor_1" || id === "bedside_monitor_2") return "hallway_er_upper";
      if (id === "er_bed_3" || id === "er_bed_4" || id === "er_bedside_3" || id === "er_bedside_4" || id === "bedside_monitor_3" || id === "bedside_monitor_4") return "hallway_er_lower";
      if (id.startsWith("observation_")) return "hallway_observation_entry";
      if (id.startsWith("imaging_") || id === "imaging_machine" || id === "hallway_er_to_imaging") return "hallway_diagnostics_entry";
      if (id.startsWith("lab_") || id === "lab_station") return "hallway_diagnostics_lower";
      if (id === "specialty_consult_1" || id === "specialty_chair_1") return "hallway_consult_upper";
      if (id === "specialty_consult_2" || id === "specialty_chair_2") return "hallway_consult_entry";
      if (id === "specialty_consult_3" || id === "specialty_chair_3") return "hallway_consult_lower";
      if (id.startsWith("sidebar_") || id === "specialty_desk_1" || id === "specialty_desk_2" || id === "specialty_desk_3" || id === "specialty_desk_4") return "hallway_consult_upper";
      if (id === "specialty_desk_5" || id === "specialty_desk_6") return "hallway_consult_entry";
      if (id.startsWith("specialty_desk_") || id.startsWith("specialty_chair_")) return "hallway_consult_lower";
      if (id.startsWith("discharge_")) return "hallway_waiting_entry";
      return "";
    }}

    function shortestRouteNodes(startNode, endNode) {{
      const start = String(startNode || "").trim();
      const end = String(endNode || "").trim();
      if (!start || !end) return [];
      if (start === end) return [start];
      const queue = [[start]];
      const visited = new Set([start]);
      while (queue.length) {{
        const path = queue.shift();
        const node = path[path.length - 1];
        const neighbors = Array.isArray(ROUTE_GRAPH[node]) ? ROUTE_GRAPH[node] : [];
        for (const next of neighbors) {{
          if (visited.has(next)) continue;
          const nextPath = path.concat(next);
          if (next === end) {{
            return nextPath;
          }}
          visited.add(next);
          queue.push(nextPath);
        }}
      }}
      return [start, end];
    }}

    function explicitMovementPath(entity, fromLocationId, toLocationId) {{
      const raw = Array.isArray(entity?.movement_path) ? entity.movement_path : [];
      const cleaned = raw
        .map((item) => String(item || "").trim())
        .filter(Boolean);
      if (!cleaned.length) return [];

      const normalized = [];
      const fromId = String(fromLocationId || "").trim();
      const toId = String(toLocationId || "").trim();
      if (fromId && cleaned[0] !== fromId) {{
        normalized.push(fromId);
      }}
      cleaned.forEach((item) => {{
        if (!normalized.length || normalized[normalized.length - 1] !== item) {{
          normalized.push(item);
        }}
      }});
      if (toId && normalized[normalized.length - 1] !== toId) {{
        normalized.push(toId);
      }}
      return normalized;
    }}

    function waypointIdsForEntity(entity, fromLocationId, toLocationId) {{
      const fromId = String(fromLocationId || "").trim();
      const toId = String(toLocationId || "").trim();
      const explicitPath = explicitMovementPath(entity, fromId, toId);
      if (explicitPath.length) {{
        return explicitPath;
      }}
      if (!toId || fromId === toId) return [toId].filter(Boolean);
      const route = [];
      const fromAnchor = anchorNodeForLocation(fromId);
      const toAnchor = anchorNodeForLocation(toId);
      if (fromAnchor && fromId !== fromAnchor) {{
        route.push(fromAnchor);
      }}
      if (fromAnchor && toAnchor) {{
        const anchorPath = shortestRouteNodes(fromAnchor, toAnchor);
        route.push(...anchorPath.slice(route.length ? 1 : 0));
      }} else if (toAnchor) {{
        route.push(toAnchor);
      }}
      if (toId !== toAnchor) {{
        route.push(toId);
      }}
      return route.filter((item, index) => item && route.indexOf(item) === index);
    }}

    function routePointsForEntity(entity, snapshot, fromLocationId, toLocationId) {{
      const waypoints = waypointIdsForEntity(entity, fromLocationId, toLocationId);
      const expanded = [];
      let previousPoint = null;
      waypoints.forEach((locationId) => {{
        const pos = stagePosition(snapshot, locationId);
        const currentPoint = {{
          locationId,
          x: pos.left,
          y: pos.top,
        }};
        if (previousPoint) {{
          const dx = currentPoint.x - previousPoint.x;
          const dy = currentPoint.y - previousPoint.y;
          if (Math.abs(dx) > 0.1 && Math.abs(dy) > 0.1) {{
            expanded.push({{
              locationId: `${{String(previousPoint.locationId || "route").trim()}}__turn_x`,
              x: currentPoint.x,
              y: previousPoint.y,
            }});
          }}
        }}
        expanded.push(currentPoint);
        previousPoint = currentPoint;
      }});
      return expanded;
    }}

    function snapshotLocksMovement(snapshot) {{
      return Boolean(snapshot?.__scene_freeze);
    }}

    function frozenEntityIds(snapshot) {{
      return new Set(
        Array.isArray(snapshot?.__scene_freeze_entity_ids)
          ? snapshot.__scene_freeze_entity_ids.map((item) => String(item || "").trim()).filter(Boolean)
          : []
      );
    }}

    function dialogueInteractionPosition(snapshot) {{
      const locationId = String(snapshot?.dialogue?.interaction_location_id || "").trim();
      if (!locationId) return null;
      const pos = stagePosition(snapshot, locationId);
      return {{
        locationId,
        x: Number(pos.left || 0),
        y: Number(pos.top || 0),
      }};
    }}

    function syncSceneRenderTargets(snapshot) {{
      const entities = Array.isArray(snapshot?.scene?.entities) ? snapshot.scene.entities : [];
      const nextPositions = {{}};
      let shouldAnimate = false;
      const movementLocked = snapshotLocksMovement(snapshot);
      const lockedEntityIds = frozenEntityIds(snapshot);
      const interactionPosition = dialogueInteractionPosition(snapshot);
      entities.forEach((entity) => {{
        const key = entityRenderKey(entity);
        if (!key) return;
        const entityCurrentLocation = entityCurrentLocationId(entity);
        const entityTargetLocation = entityTargetLocationId(entity);
        const target = sceneEntityTargetPosition(entity, snapshot);
        const previous = sceneRenderPositions[key];
        if (previous) {{
          const fromLocationId = String(previous.targetLocationId || previous.locationId || entityCurrentLocation).trim();
          const toLocationId = entityTargetLocation;
          const dx = target.x - Number(previous.x ?? target.x);
          const dy = target.y - Number(previous.y ?? target.y);
          let facing = String(previous.facing || "down");
          if (Math.abs(dx) > Math.abs(dy) && Math.abs(dx) > 0.8) {{
            facing = dx >= 0 ? "right" : "left";
          }} else if (Math.abs(dy) > 0.8) {{
            facing = dy >= 0 ? "down" : "up";
          }}
          const entityLocked = movementLocked && lockedEntityIds.has(key);
          const freezeAtInteraction = entityLocked && interactionPosition;
          const effectiveLocationId = freezeAtInteraction
            ? String(interactionPosition.locationId || toLocationId || fromLocationId).trim()
            : (entityLocked ? fromLocationId : toLocationId);
          const lockedX = freezeAtInteraction ? Number(interactionPosition.x ?? target.x) : Number(previous.x ?? target.x);
          const lockedY = freezeAtInteraction ? Number(interactionPosition.y ?? target.y) : Number(previous.y ?? target.y);
          const routePoints = entityLocked
            ? []
            : fromLocationId !== toLocationId
              ? routePointsForEntity(entity, snapshot, fromLocationId, toLocationId)
              : [];
          nextPositions[key] = {{
            x: entityLocked ? lockedX : Number(previous.x ?? target.x),
            y: entityLocked ? lockedY : Number(previous.y ?? target.y),
            targetX: entityLocked ? lockedX : target.x,
            targetY: entityLocked ? lockedY : target.y,
            facing,
            locationId: effectiveLocationId,
            currentLocationId: entityCurrentLocation,
            targetLocationId: entityTargetLocation,
            interactionLocationId: entityInteractionLocationId(entity),
            routePoints,
            routeIndex: 0,
          }};
          if (!entityLocked && (Math.abs(previous.x - target.x) > 1 || Math.abs(previous.y - target.y) > 1)) {{
            shouldAnimate = true;
          }}
        }} else {{
          const startLocationId = entityCurrentLocation || entityTargetLocation;
          const start = startLocationId ? stagePosition(snapshot, startLocationId) : {{ left: target.x, top: target.y }};
          const initialRoutePoints = startLocationId && entityTargetLocation && startLocationId !== entityTargetLocation
            ? routePointsForEntity(entity, snapshot, startLocationId, entityTargetLocation)
            : [];
          nextPositions[key] = {{
            x: Number(start.left ?? target.x),
            y: Number(start.top ?? target.y),
            targetX: target.x,
            targetY: target.y,
            facing: "down",
            locationId: startLocationId || entityTargetLocation,
            currentLocationId: entityCurrentLocation,
            targetLocationId: entityTargetLocation,
            interactionLocationId: entityInteractionLocationId(entity),
            routePoints: initialRoutePoints,
            routeIndex: 0,
          }};
          if (initialRoutePoints.length) {{
            shouldAnimate = true;
          }}
        }}
      }});
      sceneRenderPositions = nextPositions;
      if (shouldAnimate) {{
        startSceneAnimation();
      }}
    }}

    function animateScenePositions() {{
      let hasMovingEntity = false;
      Object.values(sceneRenderPositions).forEach((position) => {{
        if (!position) return;
        const routePoints = Array.isArray(position.routePoints) ? position.routePoints : [];
        const routeIndex = Number(position.routeIndex || 0);
        const activePoint = routePoints[routeIndex] || {{ x: Number(position.targetX ?? position.x), y: Number(position.targetY ?? position.y) }};
        const dx = Number(activePoint.x ?? position.targetX ?? position.x) - Number(position.x ?? 0);
        const dy = Number(activePoint.y ?? position.targetY ?? position.y) - Number(position.y ?? 0);
        const distance = Math.hypot(dx, dy);
        if (distance <= SCENE_WALK_SPEED) {{
          position.x = Number(activePoint.x ?? position.targetX ?? position.x);
          position.y = Number(activePoint.y ?? position.targetY ?? position.y);
          if (routeIndex < routePoints.length - 1) {{
            position.routeIndex = routeIndex + 1;
            hasMovingEntity = true;
          }}
          return;
        }}
        if (Math.abs(dx) > Math.abs(dy)) {{
          position.facing = dx >= 0 ? "right" : "left";
        }} else if (Math.abs(dy) > 0.1) {{
          position.facing = dy >= 0 ? "down" : "up";
        }}
        position.x += (dx / distance) * SCENE_WALK_SPEED;
        position.y += (dy / distance) * SCENE_WALK_SPEED;
        hasMovingEntity = true;
      }});

      if (latestSnapshot) {{
        renderScene(latestSnapshot);
      }}

      if (hasMovingEntity) {{
        sceneAnimationFrame = window.requestAnimationFrame(animateScenePositions);
      }} else {{
        sceneAnimationFrame = 0;
      }}
    }}

    function startSceneAnimation() {{
      if (sceneAnimationFrame) return;
      sceneAnimationFrame = window.requestAnimationFrame(animateScenePositions);
    }}

    function renderedEntityPosition(entity, snapshot) {{
      const key = entityRenderKey(entity);
      const cached = sceneRenderPositions[key];
      const nurseEscortOffset = (() => {{
        if (entity?.role !== "nurse" || !String(entity?.case_id || "").trim()) return null;
        const status = String(entity?.status || "").trim().toLowerCase();
        if (!["escort", "assist", "observe"].includes(status)) return null;
        const patientId = `patient_${{String(entity.case_id || "").trim()}}`;
        const patientEntity = Array.isArray(snapshot?.scene?.entities)
          ? snapshot.scene.entities.find((item) => String(item?.id || "").trim() === patientId)
          : null;
        if (!patientEntity) return null;
        const patientKey = entityRenderKey(patientEntity);
        const patientCached = sceneRenderPositions[patientKey];
        if (patientCached) {{
          return {{
            left: Number(patientCached.x || 0) - 18,
            top: Number(patientCached.y || 0) + 8,
            facing: String(patientCached.facing || "down"),
            moving: Boolean(
              Array.isArray(patientCached.routePoints) &&
              patientCached.routePoints[Number(patientCached.routeIndex || 0)] &&
              (Math.abs(Number(patientCached.routePoints[Number(patientCached.routeIndex || 0)].x ?? patientCached.x) - Number(patientCached.x || 0)) > 0.5 ||
                Math.abs(Number(patientCached.routePoints[Number(patientCached.routeIndex || 0)].y ?? patientCached.y) - Number(patientCached.y || 0)) > 0.5)
            ),
          }};
        }}
        const patientBase = stagePosition(snapshot, patientEntity.location_id);
        return {{
          left: Number(patientBase.left || 0) - 18,
          top: Number(patientBase.top || 0) + 8,
          facing: "down",
          moving: false,
        }};
      }})();
      if (nurseEscortOffset) {{
        return nurseEscortOffset;
      }}
      if (cached) {{
        const activePoint = Array.isArray(cached.routePoints) ? cached.routePoints[Number(cached.routeIndex || 0)] : null;
        const moving = Boolean(
          activePoint &&
          (Math.abs(Number(activePoint.x ?? cached.x) - Number(cached.x || 0)) > 0.5 ||
            Math.abs(Number(activePoint.y ?? cached.y) - Number(cached.y || 0)) > 0.5)
        );
        return {{
          left: Number(cached.x || 0),
          top: Number(cached.y || 0),
          facing: String(cached.facing || "down"),
          moving,
        }};
      }}
      const base = stagePosition(snapshot, entity.location_id);
      return {{
        left: base.left,
        top: base.top,
        facing: "down",
        moving: false,
      }};
    }}

    function drawLatestResultSummary(ctx, x, y, caseDetail) {{
      const results = Array.isArray(caseDetail?.test_results) ? caseDetail.test_results : [];
      if (!results.length) return;
      const latest = results[results.length - 1] || {{}};
      const metrics = Array.isArray(latest?.metrics) ? latest.metrics.slice(0, 2) : [];
      if (!metrics.length) return;
      const width = 154;
      const lineHeight = 18;
      const height = 26 + metrics.length * lineHeight;
      const top = y - 118;
      const left = x - width / 2;
      drawRoundedRect(ctx, left, top, width, height, 14, "rgba(10,16,32,0.92)", "rgba(135,212,255,0.18)");
      ctx.fillStyle = "#87d4ff";
      ctx.font = "700 11px Segoe UI";
      ctx.fillText(normalizeText(latest?.test_name, "TEST"), left + 10, top + 15);
      metrics.forEach((metric, index) => {{
        const severity = String(metric?.severity || "normal").trim().toLowerCase();
        const color = severityColor(severity);
        const percent = metricBandPercent(metric);
        const rowTop = top + 24 + index * lineHeight;
        ctx.fillStyle = "#eef3ff";
        ctx.font = "10px Segoe UI";
        const label = `${{normalizeText(metric?.name, "metric")}} ${{normalizeText(metric?.value, "-")}}`;
        ctx.fillText(label.slice(0, 20), left + 10, rowTop + 9);
        ctx.fillStyle = "rgba(255,255,255,0.10)";
        ctx.fillRect(left + 86, rowTop + 2, 54, 8);
        ctx.fillStyle = color;
        ctx.fillRect(left + 86, rowTop + 2, Math.max(6, (54 * Math.max(0, Math.min(100, percent))) / 100), 8);
      }});
    }}

    function actionIconForEntity(entity) {{
      const action = String(entity?.last_action || entity?.status || "").trim().toLowerCase();
      if (!action) return "";
      if (action.includes("ask") || action.includes("interview") || action.includes("history")) return "?";
      if (action.includes("triage")) return "T";
      if (action.includes("test") || action.includes("lab") || action.includes("imaging")) return "+";
      if (action.includes("consult") || action.includes("specialty")) return "C";
      if (action.includes("final")) return "!";
      if (action.includes("wait")) return "...";
      return "*";
    }}

    function drawActionIcon(ctx, x, y, icon, fill = "#27314e", textColor = "#f3f5fb") {{
      if (!icon) return;
      drawRoundedRect(ctx, x - 11, y - 11, 22, 22, 7, fill, "rgba(255,255,255,0.14)");
      ctx.fillStyle = textColor;
      ctx.font = "700 11px Segoe UI";
      const width = ctx.measureText(icon).width;
      ctx.fillText(icon, x - width / 2, y + 4);
    }}

    function currentCaseViewMode(caseId) {{
      return String(caseViewModes[caseId] || "original").trim();
    }}

    function setCaseViewMode(caseId, mode) {{
      caseViewModes[caseId] = String(mode || "original").trim();
      if (latestSnapshot) {{
        renderAll(latestSnapshot);
      }}
    }}

    function activeWhatIfPayload(caseId) {{
      const state = whatIfResults[caseId] || null;
      if (!state) return null;
      if (state.payload) return state.payload;
      const histories = Array.isArray(state.histories) ? state.histories : [];
      const activeReplayRunId = String(state.activeReplayRunId || "").trim();
      if (!histories.length) return null;
      return histories.find((item) => String(item?.replay_run_id || "").trim() === activeReplayRunId) || histories[histories.length - 1] || null;
    }}

    function setActiveWhatIfHistory(caseId, replayRunId) {{
      const state = whatIfResults[caseId] || null;
      if (!state) return;
      state.activeReplayRunId = String(replayRunId || "").trim();
      if (latestSnapshot) {{
        renderAll(latestSnapshot);
      }}
    }}

    function whatIfBaseUrl() {{
      const snapshotUrl = getSnapshotUrl();
      if (!String(snapshotUrl || "").startsWith("/api/runs/")) return "";
      return String(snapshotUrl).replace(/\/snapshot$/, "");
    }}

    async function triggerWhatIf(caseId, snapshotId, actionType, actionTarget) {{
      const baseUrl = whatIfBaseUrl();
      if (!baseUrl) {{
        window.alert("What-if replay is available only through the live web server endpoint.");
        return;
      }}
      const requestUrl = `${{baseUrl}}/cases/${{encodeURIComponent(caseId)}}/what-if`;
      const previousState = whatIfResults[caseId] || {{ histories: [] }};
      whatIfResults[caseId] = {{
        ...previousState,
        loading: true,
        error: "",
        message: "Running what-if branch...",
      }};
      renderCaseDetail(latestSnapshot);
      try {{
        const response = await fetch(requestUrl, {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            snapshot_id: snapshotId,
            action_type: actionType,
            action_target: actionTarget,
            max_turns: 12,
          }}),
        }});
        const payload = await response.json();
        if (!response.ok) {{
          throw new Error(payload?.detail || `HTTP ${{response.status}}`);
        }}
        const histories = Array.isArray(previousState.histories) ? [...previousState.histories] : [];
        histories.push(payload);
        whatIfResults[caseId] = {{
          loading: false,
          error: "",
          message: "",
          histories,
          activeReplayRunId: String(payload?.replay_run_id || "").trim(),
        }};
        caseViewModes[caseId] = "what-if";
      }} catch (error) {{
        whatIfResults[caseId] = {{
          ...previousState,
          loading: false,
          error: String(error?.message || error || "Unknown error"),
        }};
      }}
      renderCaseDetail(latestSnapshot);
    }}

    function wrapText(ctx, text, maxWidth) {{
      const words = String(text || "").split(/\s+/).filter(Boolean);
      if (!words.length) return [""];
      const lines = [];
      let current = words[0];
      for (let index = 1; index < words.length; index += 1) {{
        const candidate = `${{current}} ${{words[index]}}`;
        if (ctx.measureText(candidate).width <= maxWidth) {{
          current = candidate;
        }} else {{
          lines.push(current);
          current = words[index];
        }}
      }}
      lines.push(current);
      return lines;
    }}

    function triageColor(level) {{
      const normalized = Number(level || 3);
      if (normalized <= 1) return "#ff6f66";
      if (normalized === 2) return "#ffd36d";
      if (normalized === 3) return "#8fd97f";
      return "#8fb0c9";
    }}

    function drawRoundedRect(ctx, x, y, width, height, radius, fill, stroke) {{
      ctx.beginPath();
      ctx.moveTo(x + radius, y);
      ctx.lineTo(x + width - radius, y);
      ctx.quadraticCurveTo(x + width, y, x + width, y + radius);
      ctx.lineTo(x + width, y + height - radius);
      ctx.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
      ctx.lineTo(x + radius, y + height);
      ctx.quadraticCurveTo(x, y + height, x, y + height - radius);
      ctx.lineTo(x, y + radius);
      ctx.quadraticCurveTo(x, y, x + radius, y);
      ctx.closePath();
      ctx.fillStyle = fill;
      ctx.fill();
      if (stroke) {{
        ctx.strokeStyle = stroke;
        ctx.lineWidth = 2;
        ctx.stroke();
      }}
    }}

    function drawZone(ctx, snapshot, zoneKey) {{
      const bounds = zoneBounds(snapshot, zoneKey);
      const fillMap = {{
        waiting_room: "#efe7d7",
        er_workup: "#e7edf8",
        observation: "#e7efe7",
        awaiting_results: "#e5ebf0",
        specialty_review: "#eef2f8",
        completed: "#dcebd8"
      }};
      const wallMap = {{
        waiting_room: "#d4c3a2",
        er_workup: "#c6d2e6",
        observation: "#bdd0bf",
        awaiting_results: "#c9d4dd",
        specialty_review: "#cfd9ea",
        completed: "#bad0b4"
      }};
      drawRoundedRect(ctx, bounds.left, bounds.top, bounds.width, bounds.height, 26, fillMap[zoneKey] || "#ebedf2", wallMap[zoneKey] || "rgba(120,131,164,0.28)");
      ctx.fillStyle = "rgba(255,255,255,0.28)";
      ctx.fillRect(bounds.left + 14, bounds.top + 14, bounds.width - 28, 20);
      ctx.fillStyle = "rgba(37, 48, 76, 0.92)";
      ctx.font = '700 24px Georgia';
      ctx.fillText(zoneTitles[zoneKey] || zoneKey, bounds.left + 20, bounds.top + 30);
      ctx.strokeStyle = "rgba(98, 110, 145, 0.22)";
      ctx.lineWidth = 1;
      for (let x = bounds.left + 24; x < bounds.left + bounds.width - 24; x += 54) {{
        ctx.beginPath();
        ctx.moveTo(x, bounds.top + 44);
        ctx.lineTo(x, bounds.top + bounds.height - 20);
        ctx.stroke();
      }}
    }}

    function drawGrid(ctx, width, height) {{
      ctx.strokeStyle = "rgba(140,148,168,0.16)";
      ctx.lineWidth = 1;
      for (let x = 0; x <= width; x += 44) {{
        ctx.beginPath();
        ctx.moveTo(x, 0);
        ctx.lineTo(x, height);
        ctx.stroke();
      }}
      for (let y = 0; y <= height; y += 44) {{
        ctx.beginPath();
        ctx.moveTo(0, y);
        ctx.lineTo(width, y);
        ctx.stroke();
      }}
    }}

    function drawFloorTiles(ctx, snapshot, width, height) {{
      const tile = TILE_PX;
      for (let y = 0; y < height; y += tile) {{
        for (let x = 0; x < width; x += tile) {{
          const isAlt = ((x / tile) + (y / tile)) % 2 === 0;
          ctx.fillStyle = isAlt ? "#eef1f6" : "#e8ecf3";
          ctx.fillRect(x, y, tile, tile);
        }}
      }}

      const waiting = zoneBounds(snapshot, "waiting_room");
      const er = zoneBounds(snapshot, "er_workup");
      const observation = zoneBounds(snapshot, "observation");
      const diagnostics = zoneBounds(snapshot, "awaiting_results");
      const specialty = zoneBounds(snapshot, "specialty_review");

      ctx.fillStyle = "rgba(218, 205, 176, 0.40)";
      ctx.fillRect(waiting.left + 14, waiting.top + 30, waiting.width - 28, waiting.height - 44);

      ctx.fillStyle = "rgba(205, 213, 228, 0.46)";
      [er, observation, diagnostics, specialty].forEach((bounds) => {{
        ctx.fillRect(bounds.left + 14, bounds.top + 30, bounds.width - 28, bounds.height - 44);
      }});
    }}

    function drawWallsAndCorridors(ctx, snapshot) {{
      const waiting = zoneBounds(snapshot, "waiting_room");
      const er = zoneBounds(snapshot, "er_workup");
      const observation = zoneBounds(snapshot, "observation");
      const specialty = zoneBounds(snapshot, "specialty_review");

      ctx.fillStyle = "rgba(156, 165, 188, 0.42)";
      ctx.fillRect(er.left - 14, er.top + 18, 18, er.height - 36);
      ctx.fillRect(observation.left - 14, observation.top + 18, 18, observation.height - 36);
      ctx.fillRect(specialty.left - 16, specialty.top + 18, 20, specialty.height - 36);

      ctx.fillStyle = "rgba(243, 246, 251, 0.90)";
      ctx.fillRect(er.left + 24, er.top + er.height - 88, er.width - 48, 18);
      ctx.fillRect(observation.left + 24, observation.top + 52, observation.width - 48, 18);
      ctx.fillRect(waiting.left + 18, waiting.top + waiting.height - 90, waiting.width - 36, 16);

      ctx.strokeStyle = "rgba(120,131,164,0.30)";
      ctx.lineWidth = 4;
      [waiting, er, observation, specialty].forEach((bounds) => {{
        ctx.strokeRect(bounds.left + 10, bounds.top + 40, bounds.width - 20, bounds.height - 52);
      }});
    }}

    const pixelFurnitureCache = new Map();

    function buildPixelFurnitureSprite(kind, paletteKey = "") {{
      const cacheKey = `${{kind}}|${{paletteKey}}`;
      if (pixelFurnitureCache.has(cacheKey)) return pixelFurnitureCache.get(cacheKey);
      const canvas = document.createElement("canvas");
      canvas.width = 16;
      canvas.height = 16;
      const sctx = canvas.getContext("2d");
      sctx.clearRect(0, 0, 16, 16);

      if (kind === "seat_waiting") {{
        spriteBlock(sctx, 2, 5, 12, 3, "#d6bd8a");
        spriteBlock(sctx, 3, 4, 10, 1, "#f0ddae");
        spriteBlock(sctx, 3, 8, 2, 5, "#8d6d46");
        spriteBlock(sctx, 11, 8, 2, 5, "#8d6d46");
      }} else if (kind === "seat_specialty") {{
        spriteBlock(sctx, 2, 5, 12, 3, "#7d859b");
        spriteBlock(sctx, 3, 4, 10, 1, "#a0abc5");
        spriteBlock(sctx, 3, 8, 2, 5, "#4f576f");
        spriteBlock(sctx, 11, 8, 2, 5, "#4f576f");
      }} else if (kind === "monitor") {{
        spriteBlock(sctx, 5, 2, 6, 5, "#466b9f");
        spriteBlock(sctx, 6, 3, 4, 3, "#8fe0ff");
        spriteBlock(sctx, 7, 7, 2, 4, "#4e556f");
        spriteBlock(sctx, 5, 11, 6, 2, "#4e556f");
      }} else if (kind === "door") {{
        spriteBlock(sctx, 4, 1, 8, 14, "#d7ccaa");
        spriteBlock(sctx, 5, 2, 6, 12, "#b79c67");
        spritePixel(sctx, 10, 8, "#6c522e");
      }} else if (kind === "cabinet") {{
        spriteBlock(sctx, 3, 2, 10, 12, "#edf1f6");
        spriteBlock(sctx, 4, 3, 8, 4, "#d9e2ef");
        spriteBlock(sctx, 4, 8, 8, 4, "#d9e2ef");
      }} else if (kind === "desk") {{
        spriteBlock(sctx, 1, 4, 14, 5, "#9b6a40");
        spriteBlock(sctx, 2, 5, 12, 2, "#bb8654");
        spriteBlock(sctx, 2, 9, 2, 5, "#623c20");
        spriteBlock(sctx, 12, 9, 2, 5, "#623c20");
      }} else if (kind === "bed") {{
        spriteBlock(sctx, 2, 4, 12, 8, "#8a99bf");
        spriteBlock(sctx, 3, 5, 10, 2, "#f8fbff");
        spriteBlock(sctx, 4, 7, 8, 4, "#d9e4f4");
      }} else if (kind === "consult") {{
        spriteBlock(sctx, 3, 5, 10, 4, "#f1e2b1");
        spriteBlock(sctx, 4, 9, 2, 4, "#9f7f4c");
        spriteBlock(sctx, 10, 9, 2, 4, "#9f7f4c");
      }} else if (kind === "lab") {{
        spriteBlock(sctx, 3, 3, 10, 8, "#c8d8ea");
        spriteBlock(sctx, 4, 4, 8, 3, "#f7fbff");
        spriteBlock(sctx, 5, 8, 6, 2, "#7faad4");
      }} else if (kind === "img") {{
        spriteBlock(sctx, 3, 2, 10, 10, "#6d8fc7");
        spriteBlock(sctx, 4, 3, 8, 4, "#2f5ba0");
        spriteBlock(sctx, 5, 8, 6, 2, "#9fd7ff");
      }}

      pixelFurnitureCache.set(cacheKey, canvas);
      return canvas;
    }}

    function drawPixelFurniture(ctx, left, top, kind, width = 42, height = 42, paletteKey = "") {{
      const layeredAssets = getFurnitureSpriteAssetPaths(kind);
      if (Array.isArray(layeredAssets) && layeredAssets.length) {{
        let drewExternal = false;
        for (const assetPath of layeredAssets) {{
          const image = loadExternalSprite(assetPath);
          drewExternal = drawExternalSprite(ctx, image, left, top, width, height) || drewExternal;
        }}
        if (drewExternal) {{
          return;
        }}
      }}
      const sprite = buildPixelFurnitureSprite(kind, paletteKey);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(sprite, left - width / 2, top - height / 2, width, height);
      ctx.imageSmoothingEnabled = true;
    }}

    function drawSeat(ctx, left, top, palette = "waiting") {{
      drawPixelFurniture(ctx, left, top, palette === "specialty" ? "seat_specialty" : "seat_waiting", 42, 42, palette);
    }}

    function drawMonitor(ctx, left, top) {{
      drawPixelFurniture(ctx, left, top, "monitor", 34, 34);
    }}

    function drawCabinet(ctx, left, top) {{
      drawPixelFurniture(ctx, left, top, "cabinet", 44, 44);
    }}

    function drawDoor(ctx, left, top) {{
      drawPixelFurniture(ctx, left, top, "door", 28, 42);
    }}

    function drawLocationDecor(ctx, locationId, location, left, top) {{
      const kind = String(location?.kind || "").trim();
      if (!kind) return;
      if (kind === "seat") {{
        drawSeat(ctx, left, top, locationId.startsWith("specialty_") ? "specialty" : "waiting");
        return;
      }}
      if (kind === "bed") {{
        drawFurniture(ctx, "bed", left, top);
        return;
      }}
      if (kind === "consult") {{
        drawFurniture(ctx, "consult", left, top);
        return;
      }}
      if (kind === "equipment") {{
        if (locationId.includes("monitor")) {{
          drawMonitor(ctx, left, top);
        }} else if (locationId.includes("machine")) {{
          drawFurniture(ctx, "img", left, top);
        }} else {{
          drawFurniture(ctx, "lab", left, top);
        }}
        return;
      }}
      if (kind === "desk" || kind === "staff_station") {{
        drawFurniture(ctx, "desk", left, top);
        return;
      }}
      if (kind === "sidebar") {{
        drawRoundedRect(ctx, left - 24, top - 16, 48, 28, 8, "#424c73", "#69779d");
        return;
      }}
      if (kind === "door") {{
        drawDoor(ctx, left, top);
        return;
      }}
      if (kind === "exit") {{
        drawRoundedRect(ctx, left - 16, top - 16, 32, 32, 6, "#abd495", "#6ba65c");
        ctx.fillStyle = "#448d43";
        ctx.fillRect(left - 6, top - 2, 12, 4);
        ctx.fillRect(left + 2, top - 8, 4, 12);
        return;
      }}
      if (kind === "queue") {{
        if (locationId.includes("entry")) {{
          ctx.fillStyle = "rgba(89, 149, 86, 0.65)";
          ctx.fillRect(left - 14, top - 14, 28, 28);
        }} else {{
          ctx.strokeStyle = "rgba(90, 112, 152, 0.40)";
          ctx.lineWidth = 2;
          ctx.strokeRect(left - 10, top - 10, 20, 20);
        }}
        return;
      }}
    }}

    function drawStaticSceneDecor(ctx, snapshot) {{
      const locations = locationMap(snapshot);
      Object.entries(locations).forEach(([locationId, location]) => {{
        if (!location) return;
        const pos = stagePosition(snapshot, locationId);
        drawLocationDecor(ctx, locationId, location, pos.left, pos.top);
      }});

      const waiting = zoneBounds(snapshot, "waiting_room");
      ctx.fillStyle = "#9ec0dc";
      ctx.fillRect(waiting.left + 38, waiting.top + 54, 48, 28);
      ctx.fillStyle = "#d1b8dd";
      ctx.fillRect(waiting.left + 116, waiting.top + 54, 48, 28);

      const specialty = zoneBounds(snapshot, "specialty_review");
      for (let index = 0; index < 4; index += 1) {{
        const y = specialty.top + 74 + index * 120;
        ctx.strokeStyle = "rgba(123, 133, 164, 0.30)";
        ctx.lineWidth = 3;
        ctx.beginPath();
        ctx.moveTo(specialty.left + 36, y);
        ctx.lineTo(specialty.left + specialty.width - 36, y);
        ctx.stroke();
      }}
    }}

    function drawFurniture(ctx, type, left, top) {{
      const sizeMap = {{
        desk: [70, 42],
        bed: [BED_PNG_WIDTH, BED_PNG_HEIGHT],
        consult: [54, 40],
        lab: [40, 34],
        img: [42, 36],
      }};
      const [width, height] = sizeMap[type] || sizeMap.desk;
      drawPixelFurniture(ctx, left, top, type, width, height, type);
    }}

    const pixelSpriteCache = new Map();

    function spritePixel(ctx, x, y, color) {{
      if (!color) return;
      ctx.fillStyle = color;
      ctx.fillRect(x, y, 1, 1);
    }}

    function spriteBlock(ctx, x, y, w, h, color) {{
      if (!color) return;
      ctx.fillStyle = color;
      ctx.fillRect(x, y, w, h);
    }}

    function buildPixelCharacterSprite(roleKey, facing, frame, poseMode, palette) {{
      const cacheKey = `${{roleKey}}|${{facing}}|${{frame}}|${{poseMode}}|${{palette.hair}}|${{palette.torso}}|${{palette.outline}}|${{palette.accent}}`;
      if (pixelSpriteCache.has(cacheKey)) {{
        return pixelSpriteCache.get(cacheKey);
      }}
      const canvas = document.createElement("canvas");
      canvas.width = 16;
      canvas.height = 16;
      const sctx = canvas.getContext("2d");
      sctx.clearRect(0, 0, 16, 16);
      const skin = palette.skin || "#ffd4bf";
      const coat = palette.coat || (roleKey === "patient" ? "#f7f9ff" : "#ffffff");
      const accent = palette.accent || "#87d4ff";
      const legA = palette.legA || "#3d4a69";
      const legB = palette.legB || "#2b3550";
      const prop = palette.prop || accent;
      const hairShade = palette.hairShade || palette.hair;
      const legShift = poseMode === "walk" && frame === 1 ? 1 : 0;

      if (facing === "down") {{
        spriteBlock(sctx, 4, 1, 8, 2, hairShade);
        spriteBlock(sctx, 4, 3, 8, 1, palette.hair);
        spriteBlock(sctx, 5, 3, 6, 3, skin);
        spritePixel(sctx, 6, 4, palette.outline);
        spritePixel(sctx, 9, 4, palette.outline);
        spriteBlock(sctx, 4, 6, 8, 4, palette.torso);
        spriteBlock(sctx, 5, 7, 6, 3, coat);
        spriteBlock(sctx, 6, 8, 4, 2, accent);
        spriteBlock(sctx, 5, 10, 2, 3, palette.outline);
        spriteBlock(sctx, 9, 10, 2, 3, palette.outline);
        spriteBlock(sctx, 5 - legShift, 13, 2, 2, legA);
        spriteBlock(sctx, 9 + legShift, 13, 2, 2, legB);
        spriteBlock(sctx, 3, 7, 1, 3, skin);
        spriteBlock(sctx, 12, 7, 1, 3, skin);
        if (poseMode === "typing") {{
          spriteBlock(sctx, 3, 8, 2, 1, prop);
          spriteBlock(sctx, 11, 8, 2, 1, prop);
        }} else if (poseMode === "reading") {{
          spriteBlock(sctx, 6, 6, 4, 1, "#edf4ff");
          spriteBlock(sctx, 6, 7, 4, 2, prop);
        }}
      }} else if (facing === "up") {{
        spriteBlock(sctx, 4, 1, 8, 2, hairShade);
        spriteBlock(sctx, 4, 3, 8, 2, palette.hair);
        spriteBlock(sctx, 4, 6, 8, 4, palette.torso);
        spriteBlock(sctx, 5, 7, 6, 3, coat);
        spriteBlock(sctx, 6, 8, 4, 2, accent);
        spriteBlock(sctx, 5, 10, 2, 3, palette.outline);
        spriteBlock(sctx, 9, 10, 2, 3, palette.outline);
        spriteBlock(sctx, 5 - legShift, 13, 2, 2, legA);
        spriteBlock(sctx, 9 + legShift, 13, 2, 2, legB);
        spriteBlock(sctx, 3, 7, 1, 3, skin);
        spriteBlock(sctx, 12, 7, 1, 3, skin);
        if (poseMode === "typing") {{
          spriteBlock(sctx, 3, 8, 2, 1, prop);
          spriteBlock(sctx, 11, 8, 2, 1, prop);
        }} else if (poseMode === "reading") {{
          spriteBlock(sctx, 6, 6, 4, 1, "#edf4ff");
          spriteBlock(sctx, 6, 7, 4, 2, prop);
        }}
      }} else {{
        const dir = facing === "right" ? 1 : -1;
        const headX = dir > 0 ? 8 : 3;
        spriteBlock(sctx, headX, 2, 4, 5, skin);
        spriteBlock(sctx, headX - (dir > 0 ? 1 : 0), 1, 5, 3, palette.hair);
        spriteBlock(sctx, 5, 6, 6, 4, palette.torso);
        spriteBlock(sctx, 6, 7, 4, 3, coat);
        spriteBlock(sctx, 6, 8, 3, 2, accent);
        spriteBlock(sctx, dir > 0 ? 11 : 4, 7, 2, 1, skin);
        spriteBlock(sctx, dir > 0 ? 3 : 11, 7, 2, 1, skin);
        spriteBlock(sctx, 6, 10, 2, 3, palette.outline);
        spriteBlock(sctx, 9, 10, 2, 3, palette.outline);
        spriteBlock(sctx, 6 - legShift, 13, 2, 2, legA);
        spriteBlock(sctx, 9 + legShift, 13, 2, 2, legB);
        if (poseMode === "typing") {{
          spriteBlock(sctx, dir > 0 ? 11 : 2, 8, 2, 1, prop);
        }} else if (poseMode === "reading") {{
          spriteBlock(sctx, 7, 6, 3, 2, prop);
          spriteBlock(sctx, 7, 5, 3, 1, "#edf4ff");
        }}
      }}

      pixelSpriteCache.set(cacheKey, canvas);
      return canvas;
    }}

    function entityPoseMode(entity, moving) {{
      const action = String(entity?.last_action || entity?.status || "").trim().toLowerCase();
      const locationId = String(entity?.location_id || "").trim().toLowerCase();
      if (moving) return "walk";
      if (action.includes("ask") || action.includes("interview") || action.includes("consult") || action.includes("assessment")) {{
        return "reading";
      }}
      if (action.includes("test") || action.includes("await")) {{
        return entity?.kind === "patient" ? "idle" : "typing";
      }}
      if (locationId.includes("desk") || locationId.includes("station") || locationId.includes("sidebar")) {{
        return "typing";
      }}
      return "idle";
    }}

    function rolePaletteForEntity(entity) {{
      if (entity.kind === "patient") {{
        return {{
          hair: "#6b4f40",
          hairShade: "#4f352a",
          torso: "#86c47c",
          coat: "#d9f0d3",
          accent: "#f7f9ff",
          outline: "#41643d",
          legA: "#5d6d93",
          legB: "#47567a",
          prop: "#f2d37a",
          skin: "#ffd4bf",
        }};
      }}
      if (entity.role === "er") {{
        return {{
          hair: "#3d516f",
          hairShade: "#26344a",
          torso: "#7ec8ff",
          coat: "#ffffff",
          accent: "#54baf5",
          outline: "#2c557d",
          legA: "#4f6184",
          legB: "#3d4d6e",
          prop: "#b7dfff",
          skin: "#ffd7c3",
        }};
      }}
      if (entity.role === "specialty") {{
        return {{
          hair: "#6a4b79",
          hairShade: "#4e3759",
          torso: "#ceb6ff",
          coat: "#fff6da",
          accent: "#f2d37a",
          outline: "#6d5192",
          legA: "#59528b",
          legB: "#464172",
          prop: "#fbe8a5",
          skin: "#ffd7c3",
        }};
      }}
      if (entity.role === "nurse") {{
        return {{
          hair: "#436562",
          hairShade: "#2f4a48",
          torso: "#7ed7b4",
          coat: "#f7fffc",
          accent: "#56c9a0",
          outline: "#2f6d63",
          legA: "#4c6e77",
          legB: "#3b5860",
          prop: "#c7f9ea",
          skin: "#ffd8c4",
        }};
      }}
      if (entity.role === "reception") {{
        return {{
          hair: "#57443a",
          hairShade: "#3f3028",
          torso: "#d8a882",
          coat: "#f6e6d7",
          accent: "#f2c29a",
          outline: "#8d5d3c",
          legA: "#6c5f78",
          legB: "#574d62",
          prop: "#ffdeb9",
          skin: "#ffd7c3",
        }};
      }}
      return {{
        hair: "#2b6155",
        hairShade: "#20483f",
        torso: "#98e0c7",
        coat: "#f8fffd",
        accent: "#5bd6b3",
        outline: "#2d7564",
        legA: "#4a6872",
        legB: "#394f58",
        prop: "#c5ffee",
        skin: "#ffd7c3",
      }};
    }}

    function drawCharacterBody(ctx, x, y, facing, palette, moving, roleKey, poseMode) {{
      const externalPath = getCharacterSpriteAssetPath(roleKey, facing, poseMode);
      const externalImage = loadExternalSprite(externalPath);
      if (drawExternalSprite(ctx, externalImage, x, y - 5, CHARACTER_PNG_SIZE, CHARACTER_PNG_SIZE)) {{
        return;
      }}
      const frame = poseMode === "walk" ? (Math.floor(performance.now() / 180) % 2) : 0;
      const sprite = buildPixelCharacterSprite(roleKey, facing, frame, poseMode, palette);
      ctx.imageSmoothingEnabled = false;
      ctx.drawImage(sprite, x - 24, y - 28, 48, 48);
      ctx.imageSmoothingEnabled = true;
    }}

    function drawEntity(ctx, entity, snapshot) {{
      const pos = renderedEntityPosition(entity, snapshot);
      const x = pos.left;
      const y = pos.top;
      const facing = String(pos.facing || "down");
      const moving = Boolean(pos.moving);
      const caseDetail = entity.kind === "patient"
        ? (getCaseDetailsMap(snapshot)[String(entity.case_id || "").trim()] || null)
        : null;
      let roleKey = "patient";
      if (entity.kind === "patient") {{
        roleKey = "patient";
      }} else if (entity.role === "er") {{
        roleKey = "er";
      }} else if (entity.role === "specialty") {{
        roleKey = "specialty";
      }} else if (entity.role === "nurse") {{
        roleKey = "nurse";
      }} else if (entity.role === "reception") {{
        roleKey = "reception";
      }} else {{
        roleKey = "staff";
      }}
      const palette = rolePaletteForEntity(entity);
      const poseMode = entityPoseMode(entity, moving);
      drawCharacterBody(ctx, x, y, facing, palette, moving, roleKey, poseMode);

      if (`${{entity.case_id || ""}}` === selectedCaseId && entity.kind === "patient") {{
        ctx.strokeStyle = "rgba(242,211,122,0.9)";
        ctx.lineWidth = 4;
        ctx.beginPath();
        ctx.arc(x, y + 2, 23, 0, Math.PI * 2);
        ctx.stroke();
      }}

      if (entity.kind === "patient") {{
        ctx.fillStyle = severityPalette[Number(entity.effective_triage_level || entity.triage_level || 3)] || "#ffd36d";
        ctx.beginPath();
        ctx.arc(x + 14, y - 15, 7, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "rgba(255,255,255,0.9)";
        ctx.lineWidth = 2;
        ctx.stroke();
      }}

      const label = entity.kind === "patient"
        ? `${{entity.case_id}}`
        : normalizeText(entity.department || entity.role || entity.id).replaceAll("_", " ").toUpperCase();
      ctx.font = "700 10px Segoe UI";
      const textWidth = ctx.measureText(label).width;
      drawRoundedRect(ctx, x - textWidth / 2 - 8, y + 31, textWidth + 16, 18, 9, "rgba(9,17,31,0.76)", "rgba(255,255,255,0.08)");
      ctx.fillStyle = "#eef3ff";
      ctx.fillText(label, x - textWidth / 2, y + 44);

      if (entity.kind === "patient") {{
        const triage = `T${{entity.effective_triage_level || entity.triage_level || "-"}}`;
        ctx.font = "700 11px Segoe UI";
        const triageWidth = ctx.measureText(triage).width;
        const chipWidth = triageWidth + 14;
        drawRoundedRect(
          ctx,
          x - chipWidth / 2,
          y - 34,
          chipWidth,
          18,
          9,
          triageColor(entity.effective_triage_level || entity.triage_level || 3),
          "rgba(255,255,255,0.22)"
        );
        ctx.fillStyle = "#101623";
        ctx.fillText(triage, x - triageWidth / 2, y - 21);
      }}

      if (entity.kind === "patient" && caseDetail) {{
        const diagnosis = String(caseDetail.predicted_diagnosis || "").trim();
        const hasResults = Array.isArray(caseDetail.test_results) && caseDetail.test_results.length > 0;
        const currentAction = String(caseDetail?.current_event?.action || "").trim();
        const zone = String(caseDetail?.zone || "").trim();
        const diagnosisRevealed = zone === "completed" || currentAction === "er_finalize" || currentAction === "specialty_finalize";
        const consultPending = currentAction === "request_specialty";
        const consultActive = currentAction === "consult_started" || currentAction === "specialty_consult" || String(entity?.last_action || "").trim() === "specialty_consult";
        const consultLabel = consultActive ? "SPECIALTY AT BEDSIDE" : (consultPending ? "CONSULT CALLED" : "");
        if (consultLabel) {{
          ctx.font = "700 11px Segoe UI";
          const consultWidth = ctx.measureText(consultLabel).width;
          drawRoundedRect(
            ctx,
            x - consultWidth / 2 - 8,
            y - 56,
            consultWidth + 16,
            18,
            9,
            "rgba(44, 28, 70, 0.94)",
            "rgba(188,155,255,0.32)"
          );
          ctx.fillStyle = "#d8c4ff";
          ctx.fillText(consultLabel, x - consultWidth / 2, y - 43);
        }}
        if (diagnosis && hasResults && diagnosisRevealed) {{
          ctx.font = "700 11px Segoe UI";
          const shortDiagnosis = diagnosis.length > 26 ? `${{diagnosis.slice(0, 23)}}...` : diagnosis;
          const diagnosisWidth = ctx.measureText(shortDiagnosis).width;
          drawRoundedRect(
            ctx,
            x - diagnosisWidth / 2 - 8,
            y - (consultLabel ? 78 : 56),
            diagnosisWidth + 16,
            18,
            9,
            "rgba(17, 26, 48, 0.92)",
            "rgba(135,212,255,0.24)"
          );
          ctx.fillStyle = "#f2d37a";
          ctx.fillText(shortDiagnosis, x - diagnosisWidth / 2, y - (consultLabel ? 65 : 43));
        }}
        if (hasResults && (zone === "awaiting_results" || currentAction === "test_result_ready" || currentAction === "review_results")) {{
          drawLatestResultSummary(ctx, x, y, caseDetail);
        }}
      }}

      const actionIcon = actionIconForEntity(entity);
      if (actionIcon) {{
        const iconFill = entity.kind === "patient"
          ? "rgba(59, 77, 112, 0.92)"
          : entity.role === "specialty"
            ? "rgba(97, 74, 132, 0.92)"
            : "rgba(42, 93, 113, 0.92)";
        drawActionIcon(ctx, x + 18, y - 28, actionIcon, iconFill);
      }}

      if (entity.kind === "patient" && entity.case_id) {{
        sceneHitboxes.push({{ case_id: entity.case_id, x: x - 18, y: y - 18, width: 36, height: 52 }});
      }}
    }}

    function drawBubble(ctx, snapshot, entities) {{
      const bubble = snapshot?.dialogue?.bubble_text;
      const speakerId = snapshot?.dialogue?.speaker_entity_id;
      if (!bubble || !speakerId) return;
      const speaker = entities.find((entity) => entity.id === speakerId);
      if (!speaker) return;
      const pos = renderedEntityPosition(speaker, snapshot);
      const actor = String(snapshot?.dialogue?.actor || "").trim().replaceAll("_", " ");
      ctx.font = "700 13px Segoe UI";
      const header = actor ? actor.toUpperCase() : "DIALOGUE";
      const bubbleLines = wrapText(ctx, bubble, 240);
      const headerWidth = ctx.measureText(header).width;
      ctx.font = "14px Segoe UI";
      const textWidth = Math.max(...bubbleLines.map((line) => ctx.measureText(line).width), 120, headerWidth) + 34;
      const width = Math.max(180, Math.min(300, textWidth));
      const height = 34 + bubbleLines.length * 20;
      const x = pos.left - width / 2;
      const y = pos.top - (height + 38);
      drawRoundedRect(ctx, x, y, width, height, 18, "rgba(255,255,255,0.98)", "rgba(104,122,169,0.18)");
      ctx.fillStyle = "#87d4ff";
      ctx.font = "700 12px Segoe UI";
      ctx.fillText(header, x + 16, y + 18);
      ctx.fillStyle = "#27314e";
      ctx.font = "14px Segoe UI";
      bubbleLines.forEach((line, index) => {{
        ctx.fillText(line, x + 16, y + 38 + index * 20);
      }});
      ctx.beginPath();
      ctx.moveTo(pos.left - 8, y + height - 2);
      ctx.lineTo(pos.left, y + height + 10);
      ctx.lineTo(pos.left + 8, y + height - 2);
      ctx.closePath();
      ctx.fillStyle = "rgba(255,255,255,0.97)";
      ctx.fill();
    }}

    function drawTestResultOverlay(ctx, snapshot, entities) {{
      const selectedId = getSelectedCase(snapshot);
      if (!selectedId) return;
      const details = getCaseDetailsMap(snapshot);
      const detail = details[selectedId] || null;
      if (!detail) return;
      const testResults = Array.isArray(detail.test_results) ? detail.test_results : [];
      if (!testResults.length) return;
      const currentEvent = detail.current_event || {{}};
      const isFreshResult = String(currentEvent.action || "").trim() === "test_result_ready";
      const recentEvents = Array.isArray(detail.recent_events) ? detail.recent_events : [];
      const latestResultEvent = recentEvents
        .filter((event) => String(event?.action || "").trim() === "test_result_ready")
        .slice(-1)[0] || null;
      const resultStillVisible = latestResultEvent
        ? Math.abs(Number(snapshot?.current_time_min || 0) - Number(latestResultEvent?.minute || 0)) <= 6
        : false;
      if (!isFreshResult && !resultStillVisible && String(detail.zone || "").trim() !== "awaiting_results") {{
        return;
      }}
      const patient = entities.find((entity) => String(entity?.case_id || "").trim() === String(selectedId).trim());
      if (!patient) return;
      const pos = renderedEntityPosition(patient, snapshot);
      const latestResult = testResults[testResults.length - 1] || {{}};
      const metrics = Array.isArray(latestResult.metrics) ? latestResult.metrics.slice(0, 3) : [];
      const width = 220;
      const height = 70 + metrics.length * 24;
      const x = Math.min(ctx.canvas.width - width - 24, pos.left + 36);
      const y = Math.max(26, pos.top - height - 26);
      drawRoundedRect(ctx, x, y, width, height, 16, "rgba(18, 25, 44, 0.94)", "rgba(135, 212, 255, 0.24)");
      ctx.fillStyle = "#f2d37a";
      ctx.font = "700 13px Segoe UI";
      ctx.fillText(normalizeText(latestResult.test_name, "Test Result"), x + 14, y + 20);
      ctx.fillStyle = "#dce7ff";
      ctx.font = "12px Segoe UI";
      const impressionLines = wrapText(ctx, normalizeText(latestResult.impression, ""), 184).slice(0, 2);
      impressionLines.forEach((line, index) => {{
        ctx.fillText(line, x + 14, y + 38 + index * 15);
      }});
      metrics.forEach((metric, index) => {{
        const color = severityColor(metric?.severity);
        const percent = metricBandPercent(metric);
        const rowY = y + 58 + index * 24;
        ctx.fillStyle = "#eef3ff";
        ctx.fillText(normalizeText(metric?.name, "metric"), x + 14, rowY);
        drawRoundedRect(ctx, x + 104, rowY - 11, 96, 10, 6, "#98d47d", "");
        drawRoundedRect(ctx, x + 136, rowY - 11, 32, 10, 0, "#ffd36d", "");
        drawRoundedRect(ctx, x + 168, rowY - 11, 32, 10, 0, "#ff7c74", "");
        ctx.fillStyle = "#f5f7ff";
        ctx.beginPath();
        ctx.arc(x + 104 + (96 * percent) / 100, rowY - 6, 4, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = color;
        ctx.lineWidth = 2;
        ctx.stroke();
      }});
    }}

    function drawBranchOverlay(ctx, snapshot) {{
      const caseId = getSelectedCase(snapshot);
      if (!caseId || currentCaseViewMode(caseId) !== "what-if") return;
      const branchState = activeWhatIfPayload(caseId);
      if (!branchState) return;
      const cardWidth = 280;
      const cardHeight = 112;
      const x = ctx.canvas.width - cardWidth - 26;
      const y = 26;
      drawRoundedRect(ctx, x, y, cardWidth, cardHeight, 18, "rgba(18, 25, 44, 0.90)", "rgba(135, 212, 255, 0.22)");
      ctx.fillStyle = "#87d4ff";
      ctx.font = "700 14px Segoe UI";
      ctx.fillText("WHAT-IF BRANCH", x + 16, y + 24);
      ctx.fillStyle = "#eef3ff";
      ctx.font = "12px Segoe UI";
      ctx.fillText(`Case: ${{normalizeText(caseId)}}`, x + 16, y + 48);
      ctx.fillText(`Action: ${{normalizeText(branchState.selected_action?.type)}} -> ${{normalizeText(branchState.selected_action?.target)}}`, x + 16, y + 68);
      ctx.fillText(`Replay: ${{normalizeText(branchState.replay?.predicted_department)}}`, x + 16, y + 88);
      ctx.fillText(`Reward delta: ${{normalizeText(branchState.comparison?.reward_delta)}}`, x + 16, y + 108);
    }}

    function bindCanvasSelection(canvas) {{
      if (sceneCanvasBound) return;
      canvas.addEventListener("click", (event) => {{
        const rect = canvas.getBoundingClientRect();
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        const px = (event.clientX - rect.left) * scaleX;
        const py = (event.clientY - rect.top) * scaleY;
        const hit = sceneHitboxes.find((item) =>
          px >= item.x && px <= item.x + item.width && py >= item.y && py <= item.y + item.height
        );
        if (hit) {{
          selectedCaseId = hit.case_id;
          renderAll(latestSnapshot);
        }}
      }});
      sceneCanvasBound = true;
    }}

    function renderScene(snapshot) {{
      const stage = document.getElementById("sceneStage");
      const canvas = document.getElementById("sceneCanvas");
      const ctx = canvas.getContext("2d");
      const metrics = stageMetrics(snapshot);
      stage.style.minHeight = `${{metrics.height}}px`;
      canvas.width = metrics.width;
      canvas.height = metrics.height;
      sceneHitboxes = [];
      bindCanvasSelection(canvas);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      drawFloorTiles(ctx, snapshot, canvas.width, canvas.height);
      drawGrid(ctx, canvas.width, canvas.height);
      document.getElementById("scenePhase").textContent = `Phase · ${{normalizeText(snapshot.phase)}} · m${{snapshot.current_time_min || 0}}`;

      Object.keys(zoneTitles).forEach((zoneKey) => {{
        drawZone(ctx, snapshot, zoneKey);
      }});
      drawWallsAndCorridors(ctx, snapshot);
      drawStaticSceneDecor(ctx, snapshot);

      const entities = Array.isArray(snapshot?.scene?.entities) ? snapshot.scene.entities : [];
      entities.forEach((entity) => {{
        drawEntity(ctx, entity, snapshot);
      }});
      drawBubble(ctx, snapshot, entities);
      drawTestResultOverlay(ctx, snapshot, entities);
      drawBranchOverlay(ctx, snapshot);
    }}

    function renderOverview(snapshot) {{
      document.getElementById("metricMinute").textContent = String(snapshot.current_time_min || 0);
      document.getElementById("metricCompleted").textContent = String(snapshot.completed_count || 0);
      document.getElementById("metricWaiting").textContent = String(snapshot.waiting_count || 0);
      document.getElementById("ovMinute").textContent = String(snapshot.current_time_min || 0);
      document.getElementById("ovCompleted").textContent = String(snapshot.completed_count || 0);
      document.getElementById("ovWaiting").textContent = String(snapshot.waiting_count || 0);
      document.getElementById("ovResources").textContent = String((snapshot.resource_occupancy || []).length);

      const focus = snapshot.er_focus || {{}};
      const focusBlock = document.getElementById("erFocusBlock");
      focusBlock.innerHTML = focus.case_id
        ? `
          <div><strong>${{focus.case_id}}</strong> · T${{focus.effective_triage_level || focus.triage_level || "-"}}</div>
          <div class="muted" style="margin-top:6px;">${{normalizeText(focus.zone)}} · ${{normalizeText(focus.action)}}</div>
          <div class="muted" style="margin-top:6px;">department: ${{normalizeText(focus.responsible_department || focus.working_diagnosis)}}</div>
        `
        : `<div class="muted">No active ER assessment</div>`;
    }}

    function renderPatients(snapshot) {{
      const list = document.getElementById("patientsList");
      list.innerHTML = "";
      const patients = Array.isArray(snapshot?.patients) ? snapshot.patients : [];
      patients.forEach((patient) => {{
        const row = document.createElement("div");
        row.className = "patient-row";
        if (`${{patient.case_id}}` === selectedCaseId) {{
          row.classList.add("active");
        }}
        row.addEventListener("click", () => {{
          selectedCaseId = patient.case_id;
          renderAll(latestSnapshot);
        }});
        row.innerHTML = `
          <div class="patient-head">
            <div class="patient-name">${{patient.case_id}}</div>
            <div class="patient-zone">T${{patient.effective_triage_level || patient.triage_level || "-"}}</div>
          </div>
          <div class="muted">${{normalizeText(patient.zone).replaceAll("_", " ")}}</div>
          <div class="muted" style="margin-top:6px;">${{normalizeText(patient.predicted_department || patient.assigned_staff || "no owner yet")}}</div>
        `;
        list.appendChild(row);
      }});
      if (!patients.length) {{
        list.innerHTML = `<div class="muted">No active patients</div>`;
      }}
    }}

    function severityColor(severity) {{
      const normalized = String(severity || "").trim().toLowerCase();
      if (normalized === "critical") return "#ff7c74";
      if (normalized === "warning") return "#ffd36d";
      return "#98d47d";
    }}

    function severityLabel(severity) {{
      const normalized = String(severity || "").trim().toLowerCase();
      if (normalized === "critical") return "Critical";
      if (normalized === "warning") return "Borderline";
      return "Normal";
    }}

    function metricDeviationText(metric) {{
      const value = Number(metric?.value);
      const min = Number(metric?.normal_min);
      const max = Number(metric?.normal_max);
      if (Number.isNaN(value) || Number.isNaN(min) || Number.isNaN(max)) {{
        return "";
      }}
      if (value < min) {{
        return `${{Math.abs(min - value).toFixed(1)}} below normal`;
      }}
      if (value > max) {{
        return `${{Math.abs(value - max).toFixed(1)}} above normal`;
      }}
      return "within normal range";
    }}

    function metricBandPercent(metric) {{
      const value = Number(metric?.value);
      const min = Number(metric?.normal_min);
      const max = Number(metric?.normal_max);
      if (Number.isNaN(value) || Number.isNaN(min) || Number.isNaN(max)) {{
        return 50;
      }}
      const span = Math.max(0.0001, max - min);
      const paddedMin = min - span;
      const paddedMax = max + span;
      const ratio = (value - paddedMin) / Math.max(0.0001, paddedMax - paddedMin);
      return Math.max(0, Math.min(100, ratio * 100));
    }}

    function renderTestResultsHtml(testResults) {{
      const items = Array.isArray(testResults) ? testResults : [];
      if (!items.length) {{
        return `<div class="muted">No test results yet</div>`;
      }}
      return items.map((result) => {{
        const metrics = Array.isArray(result?.metrics) ? result.metrics : [];
        const metricHtml = metrics.length
          ? metrics.map((metric) => {{
              const severity = String(metric?.severity || "normal").trim().toLowerCase();
              const color = severityColor(severity);
              const label = severityLabel(severity);
              const deviation = metricDeviationText(metric);
              const percent = metricBandPercent(metric);
              return `
                <div class="detail-item" style="margin-top:8px;">
                  <div style="display:flex;justify-content:space-between;gap:12px;align-items:center;">
                    <strong>${{normalizeText(metric?.name, "metric")}}</strong>
                    <div style="display:flex;align-items:center;gap:8px;">
                      <span style="padding:4px 8px;border-radius:999px;background:${{color}};color:#101623;font-size:11px;font-weight:700;">${{label}}</span>
                      <span>${{normalizeText(metric?.value, "-")}}</span>
                    </div>
                  </div>
                  <div class="muted" style="margin-top:4px;">normal: ${{normalizeText(metric?.normal_min, "-")}} - ${{normalizeText(metric?.normal_max, "-")}}</div>
                  <div class="muted" style="margin-top:2px;">${{normalizeText(deviation, "")}}</div>
                  <div style="position:relative;margin-top:8px;height:12px;border-radius:999px;background:linear-gradient(90deg,#98d47d 0%,#98d47d 33%,#ffd36d 33%,#ffd36d 66%,#ff7c74 66%,#ff7c74 100%);overflow:hidden;">
                    <div style="position:absolute;left:calc(${{percent}}% - 5px);top:1px;width:10px;height:10px;border-radius:999px;background:#f5f7ff;border:2px solid rgba(16,22,35,0.75);box-shadow:0 0 0 2px rgba(255,255,255,0.18);"></div>
                  </div>
                </div>
              `;
            }}).join("")
          : `<div class="muted">No structured metrics</div>`;
        return `
          <div class="detail-item">
            <strong>${{normalizeText(result?.test_name, "Test")}}</strong><br />
            <span class="muted">${{normalizeText(result?.impression, "No impression")}}</span>
            ${{metricHtml}}
          </div>
        `;
      }}).join("");
    }}

    function renderCaseDetail(snapshot) {{
      const wrap = document.getElementById("caseDetail");
      const details = getCaseDetailsMap(snapshot);
      const caseId = getSelectedCase(snapshot);
      const detail = details[caseId] || null;
      if (!detail) {{
        wrap.innerHTML = `<div class="muted">No case selected.</div>`;
        return;
      }}

      const questions = Array.isArray(detail.questions) ? detail.questions : [];
      const findings = Array.isArray(detail.objective_findings) ? detail.objective_findings : [];
      const tests = Array.isArray(detail.tests) ? detail.tests : [];
      const decisionPoints = Array.isArray(detail.decision_points) ? detail.decision_points : [];
      const latestDecisionPoint = decisionPoints.length ? decisionPoints[decisionPoints.length - 1] : null;
      const candidates = Array.isArray(detail.counterfactual_candidates) ? detail.counterfactual_candidates : [];
      const whatIfState = whatIfResults[caseId] || null;
      const viewMode = currentCaseViewMode(caseId);
      const activePayload = activeWhatIfPayload(caseId);
      const branchDetail = activePayload?.branch_detail || null;
      const comparison = activePayload?.comparison || null;
      const originalSummary = comparison?.original || null;
      const replaySummary = comparison?.replay || null;
      const historyItems = Array.isArray(whatIfState?.histories) ? whatIfState.histories.slice().reverse() : [];
      const activeQuestions = viewMode === "what-if" && branchDetail ? Array.isArray(branchDetail.questions) ? branchDetail.questions : [] : questions;
      const activeTests = viewMode === "what-if" && branchDetail ? Array.isArray(branchDetail.tests) ? branchDetail.tests : [] : tests;
      const activeFindings = viewMode === "what-if" && branchDetail ? Array.isArray(branchDetail.objective_findings) ? branchDetail.objective_findings : [] : findings;
      const activeTestResults = viewMode === "what-if" && branchDetail ? Array.isArray(branchDetail.test_results) ? branchDetail.test_results : [] : (Array.isArray(detail.test_results) ? detail.test_results : []);
      wrap.innerHTML = `
        <div class="detail-block">
          <h4>Summary</h4>
          <div class="detail-list">
            <div class="detail-item"><strong>${{detail.case_id}}</strong> · T${{detail.effective_triage_level || detail.triage_level || "-"}}</div>
            <div class="detail-item">zone: ${{normalizeText(detail.zone)}}</div>
            <div class="detail-item">risk: ${{normalizeText(detail.deterioration_risk)}}</div>
            <div class="detail-item">pending results: ${{detail.pending_results_count || 0}}</div>
            <div class="detail-item">department: ${{viewMode === "what-if" && activePayload ? normalizeText(activePayload.replay?.predicted_department) : normalizeText(detail.predicted_department)}}</div>
            <div class="detail-item">working diagnosis: ${{viewMode === "what-if" && activePayload ? normalizeText(activePayload.replay?.predicted_diagnosis) : normalizeText(detail.predicted_diagnosis)}}</div>
            <div class="mode-tabs">
              <button class="mode-tab ${{viewMode === "original" ? "active" : ""}}" data-case-mode="${{caseId}}" data-mode="original">Original</button>
              <button class="mode-tab ${{viewMode === "what-if" ? "active" : ""}}" data-case-mode="${{caseId}}" data-mode="what-if" ${{activePayload ? "" : "disabled"}}>What-If</button>
            </div>
          </div>
        </div>
        ${{
          activePayload ? `
            <div class="detail-block">
              <h4>Original vs What-If</h4>
              <div class="compare-grid">
                <div class="compare-card">
                  <h5>Original</h5>
                  <div class="compare-metrics">
                    <div><strong>Diagnosis</strong> ${{normalizeText(originalSummary?.diagnosis, detail.predicted_diagnosis)}}</div>
                    <div><strong>Department</strong> ${{normalizeText(originalSummary?.department, detail.predicted_department)}}</div>
                    <div><strong>Diagnosis Correct</strong> ${{String(Boolean(originalSummary?.diagnosis_correct))}}</div>
                    <div><strong>Department Correct</strong> ${{String(Boolean(originalSummary?.department_correct))}}</div>
                    <div><strong>Reward</strong> ${{normalizeText(originalSummary?.episode_reward, "-")}}</div>
                  </div>
                </div>
                <div class="compare-card">
                  <h5>What-If</h5>
                  <div class="compare-metrics">
                    <div><strong>Diagnosis</strong> ${{normalizeText(replaySummary?.diagnosis, activePayload.replay?.predicted_diagnosis)}}</div>
                    <div><strong>Department</strong> ${{normalizeText(replaySummary?.department, activePayload.replay?.predicted_department)}}</div>
                    <div><strong>Diagnosis Correct</strong> ${{String(Boolean(replaySummary?.diagnosis_correct ?? activePayload.replay?.diagnosis_correct))}}</div>
                    <div><strong>Department Correct</strong> ${{String(Boolean(replaySummary?.department_correct ?? activePayload.replay?.department_correct))}}</div>
                    <div><strong>Reward</strong> ${{normalizeText(replaySummary?.episode_reward, activePayload.replay?.episode_reward)}}</div>
                  </div>
                </div>
              </div>
              <div class="compare-delta">
                <strong>Selected branch</strong> ${{normalizeText(activePayload.selected_action?.type)}} -> ${{normalizeText(activePayload.selected_action?.target)}}<br />
                <strong>Reward delta</strong> ${{normalizeText(comparison?.reward_delta, "-")}}<br />
                <strong>Improved</strong> ${{comparison?.improved ? "yes" : "no"}}
              </div>
            </div>
          ` : ``
        }}
        <div class="detail-block">
          <h4>Questions</h4>
          <div class="detail-list">
            ${{activeQuestions.length ? activeQuestions.map((qa) => `<div class="detail-item"><strong>Q.</strong> ${{normalizeText(qa.question)}}<br /><strong>A.</strong> ${{normalizeText(qa.answer)}}</div>`).join("") : `<div class="muted">No interview yet</div>`}}
          </div>
        </div>
        <div class="detail-block">
          <h4>Tests</h4>
          <div class="detail-list">
            ${{activeTests.length ? activeTests.map((test) => `<div class="detail-item">${{normalizeText(test)}}</div>`).join("") : `<div class="muted">No requested tests</div>`}}
          </div>
        </div>
        <div class="detail-block">
          <h4>Test Results</h4>
          <div class="detail-list">
            ${{renderTestResultsHtml(activeTestResults)}}
          </div>
        </div>
        <div class="detail-block">
          <h4>Objective Findings</h4>
          <div class="detail-list">
            ${{activeFindings.length ? activeFindings.map((item) => `<div class="detail-item">${{normalizeText(item)}}</div>`).join("") : `<div class="muted">No objective findings yet</div>`}}
          </div>
        </div>
        <div class="detail-block">
          <h4>What-If Controls</h4>
          <div class="detail-list">
            <div class="detail-item">
              snapshot: ${{normalizeText(latestDecisionPoint?.snapshot_id, "not available")}}<br />
              node: ${{normalizeText(latestDecisionPoint?.node, "parallel_scheduler_decision")}}
            </div>
          </div>
          <div class="what-if-grid" style="margin-top:10px;">
            ${{
              latestDecisionPoint && candidates.length
                ? candidates.map((candidate, index) => `
                    <button
                      class="what-if-option"
                      data-what-if-case="${{detail.case_id}}"
                      data-what-if-snapshot="${{latestDecisionPoint.snapshot_id}}"
                      data-what-if-type="${{normalizeText(candidate.type, "")}}"
                      data-what-if-target="${{normalizeText(candidate.target, "")}}"
                    >
                      <strong>Option ${{index + 1}}</strong>
                      <div>${{normalizeText(candidate.type, "action")}} → ${{normalizeText(candidate.target, "-")}}</div>
                      <div class="muted" style="margin-top:4px;">${{normalizeText(candidate.rationale, "No rationale")}}</div>
                    </button>
                  `).join("")
                : `<div class="muted">No what-if alternatives available for this case yet</div>`
            }}
          </div>
          <div style="margin-top:12px;">
            ${{
              whatIfState?.loading
                ? `<div class="detail-item what-if-result">${{normalizeText(whatIfState.message, "Running what-if branch...")}}</div>`
                : whatIfState?.error
                  ? `<div class="detail-item what-if-result">Error: ${{normalizeText(whatIfState.error)}}</div>`
                  : activePayload
                    ? `
                      <div class="detail-item what-if-result">
                        <strong>Replay Run</strong> ${{normalizeText(activePayload.replay_run_id)}}<br />
                        <strong>Selected</strong> ${{normalizeText(activePayload.selected_action?.type)}} → ${{normalizeText(activePayload.selected_action?.target)}}<br />
                        <strong>Replay</strong> ${{normalizeText(activePayload.replay?.predicted_diagnosis)}} / ${{normalizeText(activePayload.replay?.predicted_department)}}<br />
                        <strong>Reward Δ</strong> ${{normalizeText(activePayload.comparison?.reward_delta)}}<br />
                        <strong>Improved</strong> ${{activePayload.comparison?.improved ? "yes" : "no"}}
                      </div>
                    `
                    : `<div class="muted">Choose an alternative to run a what-if branch</div>`
            }}
          </div>
        </div>
        ${{
          historyItems.length ? `
            <div class="detail-block">
              <h4>What-If History</h4>
              <div class="history-list">
                ${{historyItems.map((item) => `
                  <button
                    class="history-button ${{String(item?.replay_run_id || "").trim() === String(whatIfState?.activeReplayRunId || "").trim() ? "active" : ""}}"
                    data-history-case="${{caseId}}"
                    data-history-run="${{normalizeText(item?.replay_run_id, "")}}"
                  >
                    <strong>${{normalizeText(item?.replay_run_id)}}</strong><br />
                    ${{normalizeText(item?.selected_action?.type)}} → ${{normalizeText(item?.selected_action?.target)}}<br />
                    reward Δ ${{normalizeText(item?.comparison?.reward_delta)}} · improved ${{item?.comparison?.improved ? "yes" : "no"}}
                  </button>
                `).join("")}}
              </div>
            </div>
          ` : ``
        }}
      `;

      wrap.querySelectorAll("[data-what-if-case]").forEach((button) => {{
        button.addEventListener("click", () => {{
          triggerWhatIf(
            String(button.getAttribute("data-what-if-case") || "").trim(),
            String(button.getAttribute("data-what-if-snapshot") || "").trim(),
            String(button.getAttribute("data-what-if-type") || "").trim(),
            String(button.getAttribute("data-what-if-target") || "").trim(),
          );
        }});
      }});
      wrap.querySelectorAll("[data-case-mode]").forEach((button) => {{
        button.addEventListener("click", () => {{
          if (button.hasAttribute("disabled")) return;
          setCaseViewMode(
            String(button.getAttribute("data-case-mode") || "").trim(),
            String(button.getAttribute("data-mode") || "original").trim(),
          );
        }});
      }});
      wrap.querySelectorAll("[data-history-case]").forEach((button) => {{
        button.addEventListener("click", () => {{
          setActiveWhatIfHistory(
            String(button.getAttribute("data-history-case") || "").trim(),
            String(button.getAttribute("data-history-run") || "").trim(),
          );
        }});
      }});
    }}

    function renderConversation(snapshot) {{
      const current = document.getElementById("currentDialogue");
      const selectedCaseId = getSelectedCase(snapshot);
      const viewMode = currentCaseViewMode(selectedCaseId);
      const branchState = whatIfResults[selectedCaseId]?.payload || null;
      const branchTranscript = Array.isArray(branchState?.branch_detail?.transcript) ? branchState.branch_detail.transcript : [];
      const dialogue = viewMode === "what-if"
        ? branchTranscript.slice(-4).map((item) => `${{normalizeText(item.role, "agent")}}: ${{normalizeText(item.content, "")}}`)
        : (snapshot?.dialogue?.lines || []);
      current.innerHTML = dialogue.length
        ? dialogue.map((line) => `<div class="conversation-item current">${{normalizeText(line)}}</div>`).join("")
        : `<div class="muted">No live conversation at this minute</div>`;

      const selectedWrap = document.getElementById("selectedConversation");
      const history = Array.isArray(snapshot?.conversation_log_recent) ? snapshot.conversation_log_recent : [];
      const selectedHistory = viewMode === "what-if"
        ? branchTranscript.slice(-8).reverse().map((item, index) => ({{
            minute: index,
            actor: item.role,
            case_id: selectedCaseId,
            lines: [String(item.content || "").trim()],
          }}))
        : history.filter((item) => String(item?.case_id || "").trim() === String(selectedCaseId || "").trim());
      selectedWrap.innerHTML = selectedHistory.length
        ? selectedHistory.slice(-6).reverse().map((item) => {{
            const lines = Array.isArray(item?.lines) ? item.lines : [];
            return `
              <div class="conversation-item selected">
                <div class="conversation-meta">m${{item.minute ?? 0}} · ${{normalizeText(item.actor || item.action || "dialogue")}} · ${{normalizeText(item.case_id || "")}}</div>
                ${{lines.map((line) => `<div>${{normalizeText(line)}}</div>`).join("")}}
              </div>
            `;
          }}).join("")
        : `<div class="muted">No conversation history for the selected case yet</div>`;

      const eventsWrap = document.getElementById("recentEvents");
      const events = viewMode === "what-if"
        ? (Array.isArray(branchState?.branch_detail?.event_log) ? branchState.branch_detail.event_log.slice(-10).reverse() : [])
        : (Array.isArray(snapshot?.event_log_recent) ? snapshot.event_log_recent.slice(-10).reverse() : []);
      eventsWrap.innerHTML = events.length
        ? events.map((event) => `
            <div class="event-item">
              <strong>m${{event.minute ?? 0}}</strong> · ${{normalizeText(event.event_type || event.action)}}<br />
              <span class="muted">${{normalizeText(event.rationale || event.content || event.action)}}</span>
            </div>
          `).join("")
        : `<div class="muted">No events yet</div>`;
    }}

    function renderAll(snapshot) {{
      if (!snapshot) return;
      latestSnapshot = snapshot;
      syncSceneRenderTargets(snapshot);
      getSelectedCase(snapshot);
      renderOverview(snapshot);
      renderScene(snapshot);
      renderPatients(snapshot);
      renderCaseDetail(snapshot);
      renderConversation(snapshot);
    }}

    async function loadSnapshot(renderImmediately = true) {{
      try {{
        const response = await fetch(`${{getSnapshotUrl()}}?t=${{Date.now()}}`, {{ cache: "no-store" }});
        if (!response.ok) {{
          throw new Error(`HTTP ${{response.status}}`);
        }}
        const snapshot = await response.json();
        updateRunIdUi(snapshot?.run_id || currentRunId);
        if (renderImmediately) {{
          renderAll(snapshot);
        }}
        return snapshot;
      }} catch (error) {{
        console.error("Failed to load snapshot", error);
        return null;
      }}
    }}

    async function loadHistory() {{
      const historyUrl = getHistoryUrl();
      if (!historyUrl) return [];
      try {{
        const response = await fetch(`${{historyUrl}}?t=${{Date.now()}}`, {{ cache: "no-store" }});
        if (!response.ok) {{
          return [];
        }}
        const payload = await response.json();
        return Array.isArray(payload?.history) ? payload.history : [];
      }} catch (error) {{
        console.error("Failed to load history", error);
        return [];
      }}
    }}

    function setPlaybackStatus(message) {{
      const node = document.getElementById("playbackStatus");
      if (node) {{
        node.textContent = String(message || "").trim();
      }}
    }}

    function applyPlaybackModeUi() {{
      document.getElementById("btnReplay")?.classList.toggle("active", playbackMode === "replay" && !playbackPaused);
      document.getElementById("btnLive")?.classList.toggle("active", playbackMode === "live" && !playbackPaused);
      document.getElementById("btnPause")?.classList.toggle("active", playbackPaused);
    }}

    function clearPlaybackTimers() {{
      if (playbackTimer) {{
        window.clearTimeout(playbackTimer);
        playbackTimer = 0;
      }}
      if (livePollTimer) {{
        window.clearInterval(livePollTimer);
        livePollTimer = 0;
      }}
    }}

    function drainLiveFrameQueue() {{
      if (playbackPaused || playbackMode !== "live") return;
      if (!liveFrameQueue.length) {{
        playbackTimer = 0;
        return;
      }}
      const frame = liveFrameQueue.shift() || {{}};
      renderAll(frame.snapshot || latestSnapshot);
      setPlaybackStatus(`Live follow · minute ${{latestSnapshot?.current_time_min ?? 0}}`);
      playbackTimer = window.setTimeout(drainLiveFrameQueue, Number(frame.delayMs || HISTORY_REPLAY_INTERVAL_MS));
    }}

    function enqueueLiveSnapshot(snapshot) {{
      if (!snapshot) return;
      const signature = [
        String(snapshot.run_id || "").trim(),
        String(snapshot.current_time_min ?? ""),
        String(snapshot.phase || "").trim(),
        String(snapshot.action || "").trim(),
        String(snapshot.snapshot_written_at_unix || "").trim(),
      ].join("|");
      if (signature === liveLastSnapshotSignature) {{
        return;
      }}
      const frames = buildFramesForSnapshot(snapshot, liveLastSnapshot);
      liveLastSnapshot = deepClone(snapshot);
      liveLastSnapshotSignature = signature;
      liveFrameQueue.push(...frames);
      if (!playbackTimer) {{
        drainLiveFrameQueue();
      }}
    }}

    async function pollLiveSnapshot() {{
      const snapshot = await loadSnapshot(false);
      enqueueLiveSnapshot(snapshot);
    }}

    async function replayNextFrame() {{
      if (playbackPaused) return;
      if (playbackIndex < playbackFrames.length) {{
        const frame = playbackFrames[playbackIndex] || {{}};
        renderAll(frame.snapshot || latestSnapshot);
        playbackIndex += 1;
        setPlaybackStatus(`Replay minute ${{latestSnapshot?.current_time_min ?? 0}} · frame ${{playbackIndex}} / ${{playbackFrames.length}}`);
        playbackTimer = window.setTimeout(replayNextFrame, Number(frame.delayMs || HISTORY_REPLAY_INTERVAL_MS));
        return;
      }} else {{
        const refreshed = await loadHistory();
        if (refreshed.length > playbackHistory.length) {{
          playbackHistory = refreshed;
          playbackFrames = buildPlaybackFrames(playbackHistory);
        }} else if (latestSnapshot?.simulation_status === "completed") {{
          setPlaybackStatus("Replay completed");
          return;
        }} else {{
          setPlaybackStatus("Waiting for more live history…");
        }}
      }}
      playbackTimer = window.setTimeout(replayNextFrame, HISTORY_REPLAY_INTERVAL_MS);
    }}

    async function startReplayFromBeginning() {{
      clearPlaybackTimers();
      playbackMode = "replay";
      playbackPaused = false;
      applyPlaybackModeUi();
      playbackHistory = await loadHistory();
      if (!playbackHistory.length) {{
        await loadSnapshot();
        setPlaybackStatus("Live snapshot only · replay history not ready yet");
        return startLiveFollow();
      }}
      playbackFrames = buildPlaybackFrames(playbackHistory);
      playbackIndex = 0;
      setPlaybackStatus("Starting replay from minute 0…");
      replayNextFrame();
    }}

    function startLiveFollow() {{
      clearPlaybackTimers();
      playbackMode = "live";
      playbackPaused = false;
      liveFrameQueue = [];
      liveLastSnapshot = null;
      liveLastSnapshotSignature = "";
      applyPlaybackModeUi();
      setPlaybackStatus("Following latest live snapshot with staged playback");
      pollLiveSnapshot();
      livePollTimer = window.setInterval(pollLiveSnapshot, LIVE_POLL_INTERVAL_MS);
    }}

    function pausePlayback() {{
      playbackPaused = true;
      clearPlaybackTimers();
      applyPlaybackModeUi();
      setPlaybackStatus("Paused");
    }}

    async function startBrowserLiveSession() {{
      const startButton = document.getElementById("startLiveSessionBtn");
      const stopButton = document.getElementById("stopLiveSessionBtn");
      if (startButton) startButton.disabled = true;
      if (stopButton) stopButton.disabled = true;
      setLiveLaunchStatus("Starting a new live ER simulation...");
      try {{
        const response = await fetch("/api/live/start", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
          body: JSON.stringify({{
            fixed_demo: true,
            max_cases: 5,
            minute_limit: 120,
            min_demo_minutes: 20,
            step_delay_sec: 0.55,
          }}),
        }});
        const payload = await response.json();
        if (!response.ok) {{
          throw new Error(String(payload?.detail || payload?.message || `HTTP ${{response.status}}`).trim());
        }}
        const runId = String(payload?.run_id || "").trim();
        if (!runId) {{
          throw new Error("Live simulation started but no run_id was returned.");
        }}
        setLiveLaunchStatus(`Live simulation started for ${{runId}}. Redirecting now...`);
        window.location.href = `/?run_id=${{encodeURIComponent(runId)}}`;
      }} catch (error) {{
        console.error("Failed to start live session", error);
        setLiveLaunchStatus(`Failed to start live session: ${{error?.message || error}}`);
        if (startButton) startButton.disabled = false;
        if (stopButton) stopButton.disabled = false;
      }}
    }}

    async function stopBrowserLiveSession() {{
      const startButton = document.getElementById("startLiveSessionBtn");
      const stopButton = document.getElementById("stopLiveSessionBtn");
      if (startButton) startButton.disabled = true;
      if (stopButton) stopButton.disabled = true;
      setLiveLaunchStatus("Stopping the current live ER simulation...");
      try {{
        const response = await fetch("/api/live/stop", {{
          method: "POST",
          headers: {{ "Content-Type": "application/json" }},
        }});
        const payload = await response.json();
        if (!response.ok) {{
          throw new Error(String(payload?.detail || payload?.message || `HTTP ${{response.status}}`).trim());
        }}
        setLiveLaunchStatus(String(payload?.message || "Live simulation stopped."));
      }} catch (error) {{
        console.error("Failed to stop live session", error);
        setLiveLaunchStatus(`Failed to stop live session: ${{error?.message || error}}`);
      }} finally {{
        if (startButton) startButton.disabled = false;
        if (stopButton) stopButton.disabled = false;
      }}
    }}

    function bindLiveSessionControls() {{
      document.getElementById("startLiveSessionBtn")?.addEventListener("click", () => {{
        startBrowserLiveSession();
      }});
      document.getElementById("stopLiveSessionBtn")?.addEventListener("click", () => {{
        stopBrowserLiveSession();
      }});
    }}

    function bindPlaybackControls() {{
      document.getElementById("btnReplay")?.addEventListener("click", () => {{
        startReplayFromBeginning();
      }});
      document.getElementById("btnLive")?.addEventListener("click", () => {{
        startLiveFollow();
      }});
      document.getElementById("btnPause")?.addEventListener("click", () => {{
        pausePlayback();
      }});
    }}

    bindLiveSessionControls();
    bindPlaybackControls();
    startReplayFromBeginning();
  </script>
</body>
</html>
"""
