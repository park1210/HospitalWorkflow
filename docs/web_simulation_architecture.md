# Web Simulation Architecture

## Goal

Move the current viewer stack from:

- Python simulator
- Pygame local renderer

to:

- Python simulator backend
- web API server
- browser simulation UI

This follows the same high-level separation used by MedAgentSim:

- simulation runner
- frontend server
- browser-based visual simulation

Reference:

- MedAgentSim README: https://github.com/MAXNORM8650/MedAgentSim

## Current Target Structure

### 1. Simulation core

These modules remain the source of truth:

- `app/core/hospital_parallel_scheduler.py`
- `app/core/live_parallel_visual_runtime.py`
- `app/core/parallel_what_if_replay.py`

Responsibilities:

- temporal hospital scheduling
- structured event generation
- live snapshot emission
- what-if branch replay

### 2. Web server layer

New server-side web entry:

- `app/webapp/server.py`
- `app/webapp/report_store.py`

Responsibilities:

- serve browser UI
- expose live JSON snapshot APIs
- expose run list and case detail APIs
- later expose what-if execution APIs

### 3. Browser UI layer

Current browser UI source:

- `app/ui/web_viewer/builder.py`

Responsibilities:

- render hospital scene in browser
- poll live snapshot endpoint
- render patient panels / dialogue / event feed

This is currently DOM-based, but it is intentionally structured so it can be replaced by:

- Phaser scene renderer
- canvas-based sprite animation

without changing the simulation backend schema

## Current API Surface

- `/`
- `/api/health`
- `/api/runs`
- `/api/runs/{run_id}/snapshot`
- `/api/runs/{run_id}/history`
- `/api/runs/{run_id}/summary`
- `/api/runs/{run_id}/cases/{case_id}`

## Next Refactor Steps

### Phase 1

- stabilize FastAPI server path
- keep browser UI synced to `live_visual_state.json`
- add run selector and case selector interactions

### Phase 2

- replace DOM scene renderer with Phaser/canvas renderer
- map existing `scene.entities` directly to sprite entities
- add walk cycles and direction-aware characters

### Phase 3

- expose what-if API route
- allow browser buttons to trigger replay branches
- stream replay results into case detail panels

### Phase 4

- package as Docker web service
- optionally split simulator worker and frontend API

## Why This Structure

This keeps the most important constraint intact:

- the clinical simulator remains deterministic and Python-owned

while moving presentation into the browser where:

- deployment is easier
- demos are easier
- remote access is easier
- future Docker hosting is straightforward
