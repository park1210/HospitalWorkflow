# Pixel Visual Simulation Plan

## Goal

This UI is **not** a game.
The goal is to render the ER simulator as a **pixel-style visual simulation viewer** so that:

- multiple patients can be seen at once
- queueing and reprioritization are visible
- pending tests and specialty handoffs are visible
- deterioration and observation/reassessment are visible
- what-if branches can later be shown on the same visual timeline

## Visual Roadmap

### Phase 1. Inspection Dashboard

Already implemented:

- run summary cards
- case list
- time/resource tables
- deterioration / pending-result inspection

This phase is for validating simulator behavior, not for scene-style visualization.

### Phase 2. Visual Simulation State Export

Goal:

- convert one run into a timeline-oriented UI payload
- expose patient `zone` transitions over time
- expose resource occupancy over time
- expose alerts and badges for each patient

Core output:

- `visual_simulation_state.json`

Minimum fields:

- `frames`
- `patients`
- `resources`
- `events`
- `zones`

This phase is the bridge between simulator internals and pixel rendering.

### Phase 3. Pixel Scene Viewer

Goal:

- render the ER as a pixel scene, not a table
- use the exported visual state

Scene zones:

- `waiting_room`
- `er_workup`
- `observation`
- `imaging_queue`
- `specialty_review`
- `completed`

Each patient should appear as a small tile/sprite-like block with:

- case id
- triage/effective triage
- waiting badge
- risk badge
- pending-test badge
- deterioration badge

### Phase 4. Timeline Playback

Goal:

- play the run over time
- move patients between zones
- show resource occupancy changes

Viewer controls:

- play / pause
- next frame
- previous frame
- scrub by minute

### Phase 5. Branch Comparison View

Goal:

- compare original vs what-if or alternate scheduling
- visualize:
  - different queue order
  - different test timing
  - different handoff timing

This is where the visual simulation becomes a strong explanation tool for the counterfactual system.

## File-Level Plan

### Implemented / in progress

- `app/core/multi_patient_reporting.py`
  - run-level summary for dashboard validation
- `app/scripts/build_multi_patient_dashboard.py`
  - static HTML inspection dashboard

### Next core files

- `app/core/visual_simulation_state.py`
  - convert run outputs into timeline frames and zone states
- `app/scripts/export_visual_simulation_state.py`
  - save one run as `visual_simulation_state.json`

### Next UI files

- `app/scripts/build_pixel_visual_simulation.py`
  - build a pixel-style HTML viewer from `visual_simulation_state.json`

Possible later split:

- `ui/visual-sim/index.html`
- `ui/visual-sim/styles.css`
- `ui/visual-sim/app.js`

## Design Rules

- Use pixel style only for visualization, not for gameplay.
- Prefer deterministic frame generation from logs over inventing UI state.
- Every pixel scene transition should be traceable to:
  - `time_events`
  - `resource_events`
  - `queue_metrics`
  - `deterioration_events`
- Keep the first viewer static and replayable before adding richer animation.
- Avoid coupling simulator logic to rendering logic.

## Current Immediate Next Step

1. export a run into `visual_simulation_state.json`
2. use that state to render patients into named visual zones
3. render a time-slider HTML scene viewer
