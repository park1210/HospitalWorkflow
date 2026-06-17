# Event-Driven Temporal Refactor Plan

## Goal

Move the project from:

- summary-oriented live snapshots
- presentation-synthesized beats

to:

- event-driven world state
- direct playback from temporal event logs

This is the path toward a hospital-like live simulation where the viewer reflects the actual running workflow instead of a post-hoc reconstruction only.

## Event Schema

Core code scaffold:

- `app/core/event_schema.py`

Main objects:

- `EventActor`
- `EventTarget`
- `ClinicalEvent`
- `make_clinical_event(...)`

Required fields:

- `event_id`
- `run_id`
- `case_id`
- `minute`
- `tick`
- `phase`
- `actor`
- `target`
- `event_type`
- `action`
- `location_id`
- `resource_kind`
- `rationale`
- `payload`
- `state_delta`
- `meta`

Recommended event types:

- `case_started`
- `arrival_entered`
- `triage_queued`
- `triage_started`
- `triage_completed`
- `patient_moved`
- `question_asked`
- `answer_received`
- `test_ordered`
- `test_started`
- `test_completed`
- `result_received`
- `consult_requested`
- `specialist_dispatched`
- `specialist_arrived`
- `consult_started`
- `consult_note_added`
- `diagnosis_finalized`
- `discharge_started`
- `case_completed`
- `deterioration_triggered`
- `what_if_branch_started`
- `what_if_branch_completed`

## Reasoning State Changes

`app/core/state.py` now contains:

- `event_log: list[dict[str, Any]]`
- `record_clinical_event(...)`

This is only the foundation.
The next step is to emit structured events from simulator and agent decisions, not just keep trajectory summaries.

## Target `live_visual_state` Structure

The current snapshot is still summary-heavy.
The target structure should look like:

```json
{
  "run_id": "20260609_150808",
  "minute": 12,
  "simulation_status": "running",
  "world": {
    "actors": [],
    "rooms": [],
    "resources": [],
    "queues": [],
    "cases": []
  },
  "event_log_recent": [],
  "conversation_log_recent": [],
  "decision_points": {},
  "what_if": {}
}
```

### `world.actors`

Includes:

- patients
- ER doctor
- specialists
- nurse
- reception

Each actor should expose:

- `id`
- `role`
- `location_id`
- `status`
- `assigned_case_id`
- `facing`
- `moving`
- `eta_min`

### `world.rooms`

Each room should expose:

- `room_id`
- `room_type`
- `activity_label`
- `occupants`
- `active_case_ids`

Examples:

- waiting
- triage
- ER beds
- imaging
- lab
- consult
- observation
- discharge

### `world.resources`

Each resource should expose:

- `resource_kind`
- `resource_id`
- `busy`
- `case_id`
- `action`
- `release_minute`

### `world.queues`

Each queue should expose:

- `queue_id`
- `case_ids`
- `priority_mode`
- `last_updated_minute`

Examples:

- arrival queue
- triage queue
- imaging wait
- lab wait
- consult wait

### `world.cases`

Each case should expose:

- `case_id`
- `zone`
- `triage_level`
- `effective_triage_level`
- `current_owner`
- `current_location_id`
- `pending_tests`
- `pending_results`
- `questions`
- `objective_findings`
- `predicted_department`
- `predicted_diagnosis`
- `finalized`

## Viewer Migration Direction

Current viewer path:

- raw snapshot
- synthetic beat generation
- presentation playback

Target viewer path:

- world snapshot
- recent event playback
- optional presentation embellishment only when needed

That means:

1. render current world directly
2. animate the latest event or short event window
3. use synthetic beats only as fallback

## Refactor Order

### Phase 1: Data Contract

1. Finalize `ClinicalEvent` schema.
2. Emit structured events from simulator decisions.
3. Store `event_log` on `ReasoningState`.

### Phase 2: State Assembly

4. Refactor `app/core/live_visual_runtime.py` to build:
   - `world`
   - `event_log_recent`
   - `conversation_log_recent`
   - `decision_points`
   - `what_if`
5. Keep existing fields temporarily for backward compatibility.

### Phase 3: Viewer Migration

6. Refactor `presentation_timeline.py` to consume event logs first.
7. Keep current synthetic beat builder only as fallback while migrating.
8. Update `entity_renderer.py` and `panel_renderer.py` to read event-derived actor and case state.

### Phase 4: What-If Branch World

9. Extend replay output to include branch event log and branch world snapshots.
10. Let viewer switch between original timeline and branch timeline directly.

### Phase 5: Presentation Polish

11. Improve room-specific icons and path animation.
12. Improve branching overlays and comparison highlighting.

## File-by-File Priority

Priority 1:

- `app/core/event_schema.py`
- `app/core/state.py`
- `app/core/simulator.py`
- `app/agents/er_department_agent.py`
- `app/agents/specialty_agent.py`

Priority 2:

- `app/core/live_visual_runtime.py`
- `app/core/what_if_replay.py`

Priority 3:

- `app/ui/pixel_viewer/presentation_timeline.py`
- `app/ui/pixel_viewer/runtime.py`
- `app/ui/pixel_viewer/entity_renderer.py`
- `app/ui/pixel_viewer/panel_renderer.py`

Priority 4:

- `app/data/hospital_scene_layout.json`

## Recommended Immediate Next Step

Implement structured event emission at the simulator/agent layer for:

- triage
- patient questions
- patient answers
- test ordering
- consult requests
- final diagnosis

Once these six are stable, the viewer can begin migrating away from synthetic replay logic.
