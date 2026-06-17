# Live Pixel Viewer Transition Plan

## Goal

Move from:

- post-run JSON replay
- post-run HTML rendering

to:

- simulation-time state emission
- live pixel viewer polling the current state

This is still a **visual simulation**, not a game.

## Current Transition Step

The simulator now has a live observer path:

- `ERDepartmentAgent` emits an update after each ER action
- `run_single_case(...)` emits:
  - `case_started`
  - `specialty_step`
  - `case_completed`
- `MultiPatientERSimulator` can attach a live runtime writer

The live runtime writer currently saves:

- `live_visual_state.json`
- `live_visual_history.json`

under:

- `outputs/reports/<run_id>/`

## What This Enables

A pixel viewer can now poll `live_visual_state.json` while the simulation is running and render:

- waiting room
- ER workup
- observation
- awaiting results
- specialty review
- completed

with:

- current minute
- patient tiles
- active resource occupancy
- alert badges

## Remaining Gap

The current live bridge is **action-level**, not true sub-action continuous animation.

That means:

- updates happen after meaningful simulator actions
- not every visual animation frame

This is the right next structural step because it keeps simulator logic deterministic and traceable.

## Next Implementation Step

1. build a polling live renderer that reads `live_visual_state.json`
2. refresh the scene every few hundred milliseconds
3. later add smoother tile transitions between snapshots

## Current Renderer Choice

The project now prefers a Python-side live renderer first:

- `app/scripts/run_live_pixel_viewer.py`

Reason:

- simulator core is already Python
- live snapshot emission is already Python
- pixel-style visualization is easier to prototype without adding a separate frontend stack

## Current Usage

1. run the live simulation writer
   - `python -m app.scripts.run_live_visual_multi_patient`
2. open the live pixel viewer
   - `python -m app.scripts.run_live_pixel_viewer <run_id>`

If `pygame` is not installed:

- `python -m pip install pygame`
