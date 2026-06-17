## Parallel ER Scheduler Refactor Plan

### Progress Snapshot (2026-06-10)

- Phase 1 `scheduler foundation`: completed
- Phase 2 `ER parallel execution`: mostly completed
- Phase 3 `specialty parallel execution`: partially completed
- Phase 4 `what-if scheduler branch`: partially completed
- Phase 5 `viewer polish`: in progress

#### Implemented so far

- Shared scheduler state, resource registry, queues, and tick loop
- Arrival -> triage -> bed -> ER -> test -> consult -> discharge flow under one scheduler
- ER queue reuse while test results are pending
- Specialty queue and consult-room transition support
- Parallel live visual export for the pixel viewer
- Scheduler snapshots are now persisted for parallel live runs
- Core scheduler decision snapshots are now persisted per case
- Parallel what-if replay now branches from scheduler snapshot context instead of only final-state summary
- Scheduler now exposes a branch-action entry point and branch run loop for what-if replay
- ER clinical next-step logic has been extracted into a dedicated clinical policy layer
- Specialty consult planning/finalization has also been extracted into a dedicated specialty policy layer
- Parallel scheduler events now carry `run_id` and are emitted through the shared clinical-event schema
- The live parallel visual runtime now reads structured scheduler events directly instead of re-synthesizing actor/event fields ad hoc
- The legacy single-case reasoning path now also preserves `zone/run_id/meta/actor/target` consistently when storing and exporting clinical events
- In-scene preview/replay overlays exist in the pixel viewer
- Case runtime now preserves explicit movement state (`current/target/interaction location`, `movement_path`, `pending_interaction`)
- ER assessment dispatch and specialty consult dispatch are now split from bedside interaction timing, so arrival can be staged separately from dialogue
- Web viewer scene entities now carry scheduler movement metadata and begin route playback from explicit `current -> target` locations instead of only snapshot-to-snapshot location jumps

#### Still missing

- Full scheduler-state branch cloning is partially implemented, but still needs deeper policy/resource replay fidelity
- Scheduler and policy are now separated at both the ER and specialty layers, and both the parallel and legacy single-case paths now preserve the shared event schema at storage/export time, but the remaining viewer/runtime layers still need to converge on one common event-reading utility
- Deeper resource-capacity realism across all hospital resources
- Final presentation-grade viewer art/layout polish
- Viewer-side route playback still needs to consume the new scheduler movement state more strictly, so all bedside dialogue starts only after both actors have fully arrived

### 1. Target Structure

The intended hospital workflow is:

1. A patient arrives at the ER entrance.
2. The hospital performs triage and assigns severity.
3. After triage, the patient is moved to an ER bed if capacity exists.
4. Additional patients repeat the same entry flow independently.
5. The ER doctor chooses the next patient based on severity, wait time, and current urgency.
6. The ER doctor interviews the patient and orders tests if needed.
7. While one patient's tests are pending, the ER doctor can move to another patient.
8. If ER-level evidence is insufficient, the ER calls a specialty doctor.
9. The specialty doctor travels from the specialty area into the ER/consult area.
10. The specialty doctor interviews and decides.
11. What-if branches replay the simulation from a branch point under the same temporal scheduler.

### 2. Current Structure

The current implementation is only partially aligned with the target structure.

#### What already matches

- Arrival and waiting-room visualization exist.
- Triage/severity exists at queue construction time.
- ER interview, test ordering, pending results, and specialty consult flows exist.
- Specialty call and travel are visualized.
- What-if replay exists.

#### What does not match yet

- Multi-patient execution is still case-serial.
- `MultiPatientERSimulator.run_batch()` selects one case and fully executes `run_single_case()` before moving to the next.
- ER doctor concurrency is not modeled.
- Test waiting does not free the ER doctor to truly continue another case under one shared scheduler loop.
- Bed occupancy is mostly visual, not the governing execution model.
- Specialty doctors are visualized as available agents, but they are not yet scheduled by a shared hospital-wide event loop.
- Triage is effectively decided before real in-hospital flow rather than being treated as a live in-simulation stage.

### 3. Main Gap

The biggest mismatch is:

- Current: `case-by-case simulator`
- Target: `hospital-wide temporal scheduler`

The refactor must move execution ownership away from `run_single_case()` and toward a shared minute/tick scheduler.

### 4. Required New Core Model

#### 4.1 Global hospital state

Add a new global scheduler state, separate from a single-case `ReasoningState`.

Suggested structure:

```python
HospitalSchedulerState = {
    "current_minute": 0,
    "tick": 0,
    "cases": {
        case_id: {
            "case_id": "...",
            "arrival_time_min": 0,
            "zone": "arrival|triage_queue|er_bed|awaiting_results|specialty_review|completed",
            "workflow_state": "not_arrived|waiting_triage|waiting_bed|waiting_er|in_er_interview|testing|waiting_results|waiting_specialty|in_specialty|completed",
            "triage_level": 3,
            "effective_priority": 3,
            "assigned_bed": "",
            "assigned_er_doctor": "",
            "assigned_specialist": "",
            "pending_results": [],
            "objective_findings": [],
            "question_history": [],
            "consult_history": [],
            "decision_snapshots": [],
            "latest_rationale": "",
        }
    },
    "resources": {
        "triage_nurses": [],
        "er_doctors": [],
        "er_beds": [],
        "lab_slots": [],
        "imaging_slots": [],
        "specialists": [],
        "consult_rooms": [],
    },
    "queues": {
        "arrival_queue": [],
        "triage_queue": [],
        "bed_queue": [],
        "er_queue": [],
        "specialty_queue": [],
    },
    "scheduled_events": [],
}
```

#### 4.2 Resource state

Each resource should become an actual execution constraint:

```python
{
    "resource_id": "doctor_er_0",
    "resource_type": "er_doctor",
    "status": "idle|busy|walking|waiting_result|off_scene",
    "available_minute": 0,
    "assigned_case_id": "",
    "location_id": "",
}
```

### 5. Refactor Principles

#### 5.1 Keep existing LLM logic where possible

The refactor should not immediately replace:

- ER questioning logic
- specialty reasoning logic
- what-if replay branching logic

Instead, the scheduler should decide **when** those modules run.

#### 5.2 Split "decision logic" from "time ownership"

Currently, `run_single_case()` owns both:

- clinical next-step logic
- temporal progression

That should be split into:

- `clinical_policy`: decides next action for a case
- `hospital_scheduler`: decides when that action can happen

### 6. Concrete Mismatch Checklist

#### Target step 1-4: multiple arrivals and bed placement

Current mismatch:

- arrivals are queued, but not processed in parallel under a live scheduler.
- ER bed allocation is not the main execution gate.

Needed change:

- simulate arrivals as time-based events.
- triage completion pushes cases into a real bed-wait queue.
- beds are globally assigned.

#### Target step 5-7: ER doctor prioritization and interleaving

Current mismatch:

- one case blocks execution until that case's single-case routine completes.

Needed change:

- ER doctor resource must always select from the current global ER-ready queue.
- pending-test patients must leave the active ER-doctor slot.
- after ordering a test, the ER doctor becomes free for another patient.

#### Target step 8-10: specialty dispatch

Current mismatch:

- specialty dispatch is mostly a visual consequence of a finished ER case flow.

Needed change:

- consult request should enqueue a specialty job.
- specialist availability and travel time should be modeled explicitly.
- specialist interview should run as a scheduled activity, not only as a downstream serial handoff.

#### Target step 11: what-if replay

Current mismatch:

- replay exists, but it still relies on the older per-case execution flow.

Needed change:

- what-if replay must branch from a scheduler snapshot containing:
  - global current minute
  - case states
  - resource occupancies
  - queue contents
  - pending result timers

### 7. Immediate UI Fixes Requested By User

These are valid and should be implemented, but they are secondary to the scheduler refactor:

1. Move the live control box below the main scene instead of covering the top-left view.
2. Shorten or redesign character labels so the sprite remains visible.
3. Replace the prototype background with a richer tile-based ER layout closer to the provided references.
4. Convert the execution model to true parallel ER flow.
5. Increase character scale while preserving hitboxes and label spacing.
6. Show severity directly beside each patient using a clearer `BLACK/RED/YELLOW/GREEN` indicator.

### 8. Additional Required Fixes

These should be added to the task list because they are required for the target structure:

7. Add a global ER scheduler loop.
8. Add bed-capacity-driven admission logic.
9. Add explicit ER doctor availability and patient handoff rules.
10. Add explicit test lifecycle:
   - ordered
   - transported
   - running
   - waiting result
   - result ready
11. Add specialty-dispatch queue and travel ETA logic.
12. Make current priority dynamic at the hospital level, not only at initial queue build time.
13. Make discharge remove the patient cleanly from active ER routing.
14. Move selection/focus state into the scene so the active case is always visually obvious.

### 9. Refactor Order

#### Phase 1: scheduler foundation

1. Add `HospitalSchedulerState`
2. Add global resource registry
3. Add global queues
4. Add minute/tick execution loop

#### Phase 2: ER parallel execution

5. Convert arrival -> triage -> bed assignment into scheduled transitions
6. Convert ER doctor assignment into a shared queue consumer
7. Let test waiting release ER doctor immediately

#### Phase 3: specialty parallel execution

8. Convert consult requests into specialty queue items
9. Add specialist travel and consult-room assignment
10. Run specialty questioning/diagnosis as scheduled work

#### Phase 4: what-if scheduler branch

11. Snapshot global scheduler state
12. Replay from a scheduler branch point
13. Compare original vs replay timelines at the scheduler level

#### Phase 5: viewer polish

14. Move HUD/control layout
15. Improve background and tile set
16. Improve severity markers, names, and sprite readability
17. Improve scene-side selection and parallel status visibility

### 10. First Coding Target

The first actual code change should be:

- create a new scheduler-oriented core module instead of further expanding `run_single_case()`

Suggested new files:

- `app/core/hospital_scheduler_state.py`
- `app/core/hospital_parallel_scheduler.py`
- `app/core/hospital_resource_registry.py`
- `app/core/hospital_case_runtime.py`

The first milestone is not full replacement.
The first milestone is:

- represent multiple cases, resources, and pending timers in one shared state object
- run a minimal tick loop that can:
  - admit arrivals
  - assign triage
  - assign beds
  - assign one ER doctor action
  - keep test results pending asynchronously
