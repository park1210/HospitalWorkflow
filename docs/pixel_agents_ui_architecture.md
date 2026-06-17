# Pixel Viewer UI Architecture

This document describes the current `pixel-agents`-inspired viewer structure for the ER hospital simulation.

The goal is to keep the UI:
- scene-first
- event/state driven
- renderer responsibilities separated
- compatible with the existing Python simulation core

## High-Level Layers

### 1. Simulation Core

The simulation core remains responsible for clinical and operational logic.

Main responsibilities:
- ER questioning, testing, and handoff decisions
- specialty consultation and diagnosis
- temporal progression
- pending test result release
- queue ordering and reprioritization
- resource occupancy

Primary modules:
- `app/core/simulator.py`
- `app/core/multi_patient_simulator.py`
- `app/core/time_engine.py`
- `app/core/resource_manager.py`
- `app/core/queue_manager.py`
- `app/agents/er_department_agent.py`
- `app/agents/specialty_agent.py`

### 2. UI Bridge

The UI bridge converts simulation state into UI-facing snapshot data.

Main responsibilities:
- convert simulation state into scene entities
- build live conversation payloads
- build selected-case details
- emit `live_visual_state.json`
- append `live_visual_history.json`

Primary modules:
- `app/core/live_visual_runtime.py`
- `app/core/hospital_scene_builder.py`

### 3. Pixel Viewer Package

The viewer is now organized as a package under:

- `app/ui/pixel_viewer/`

This package contains separated runtime and rendering responsibilities.

Current modules:

- `app/ui/pixel_viewer/__main__.py`
  - package module entrypoint
- `app/ui/pixel_viewer/app.py`
  - package-level runner wrapper
- `app/ui/pixel_viewer/runtime.py`
  - main pygame loop
  - snapshot polling
  - top-level orchestration
- `app/ui/pixel_viewer/background_renderer.py`
  - sprite atlas build/load
  - static background build/load
- `app/ui/pixel_viewer/animation_controller.py`
  - entity render-position updates
  - movement interpolation
- `app/ui/pixel_viewer/entity_renderer.py`
  - scene/entity drawing
  - speech bubbles
  - focus highlight
  - staff/patient appearance helpers
- `app/ui/pixel_viewer/panel_renderer.py`
  - overview/patient/case-detail/conversation panels
  - right-column layout
- `app/ui/pixel_viewer/input_controller.py`
  - selected-case defaulting
  - patient hitboxes

### 4. Compatibility Launcher

The old script entrypoint still exists for compatibility:

- `app/scripts/run_live_pixel_viewer.py`

This file is now intentionally thin and delegates to:

- `app.ui.pixel_viewer.app`

## Current Execution Flow

### Live Simulation Session

Recommended end-to-end launch:

```powershell
python -m app.scripts.run_live_pixel_session --max-cases 2
```

This starts:
- the live multi-patient simulator
- the live viewer pipeline

### Viewer Only

You can run the viewer directly in two equivalent ways:

```powershell
python -m app.ui.pixel_viewer
```

or

```powershell
python -m app.scripts.run_live_pixel_viewer
```

The package path is now the preferred structure-aware entrypoint.

## Renderer Responsibility Split

### Background Renderer

`background_renderer.py` owns:
- static furniture sprite generation/loading
- reference sprite cropping from external assets
- pixel atlas caching
- static hospital background rendering

It should not decide:
- case selection
- dialogue
- queue logic

### Animation Controller

`animation_controller.py` owns:
- per-entity render position state
- target position updates
- interpolation between positions
- movement flags and animation tick metadata

It should not draw sprites directly.

### Entity Renderer

`entity_renderer.py` owns:
- patient sprite drawing
- doctor/staff sprite drawing
- speech bubble drawing
- pairings/focus/resource overlay drawing

It now reads already-prepared movement state from the animation controller.
It should remain primarily draw-focused.

### Panel Renderer

`panel_renderer.py` owns:
- geometry of right-side panel rectangles
- shared text/panel/badge helpers
- overview panel
- patient list panel
- selected case detail panel
- conversation panel

### Input Controller

`input_controller.py` owns:
- default selected case choice
- patient hitbox generation

It should remain small and deterministic.

## Scene Philosophy

The viewer is inspired by `pixel-agents` in the following ways:
- the scene is primary
- information panels are secondary
- agents exist in a persistent space
- state changes appear as movement and overlays

The hospital structure remains domain-specific to this project:
- waiting
- ER beds
- observation
- consult hall
- specialty wing

## Selected Case UX

The selected case is now a first-class UI concept.

A selected case can come from:
- ER focus case
- dialogue case
- first visible patient
- user click on patient sprite
- user click on patient list entry

Selected case data shown in the UI currently includes:
- triage and effective triage
- zone
- risk
- pending results count
- prior questions
- requested tests
- objective findings
- recent ER/specialty conversation blocks

## Current Strengths

- modular viewer package exists
- runtime loop is no longer mixed with panel and scene rendering code
- atlas/background generation is isolated
- movement interpolation is isolated
- panel logic is isolated
- compatibility launcher remains available

## Remaining Refactor Targets

The viewer package is now stable enough for feature work, but further cleanup is still possible.

Future improvements:
- reduce remaining helper density inside `entity_renderer.py`
- add richer event-driven animation triggers beyond interpolation
- refine specialty wing composition
- improve selected-case interaction affordances
- unify session launcher and package entrypoint documentation
