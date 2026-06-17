# ER Spatial Scene Plan

## Target Direction

The live viewer should no longer feel like a zone dashboard.
It should feel like a hospital floor where:

- patients occupy beds, waiting chairs, and queues
- the ER doctor moves through the ER
- specialty doctors wait on the right sidebar
- a specialty doctor is summoned and appears in the consult area when needed

The target experience is:

- the ER is the main visible floor
- specialty doctors wait on the right sidebar
- patients lie in beds or wait in chairs/queues
- the ER doctor and specialty doctor appear to be working in the same shared environment

## Core Structure

### 1. Main ER Scene

The main scene contains:

- waiting chairs
- triage desk
- ER beds
- nurse / ER doctor station
- imaging / lab equipment area
- observation beds
- discharge / completed area

### 2. Specialty Sidebar

The right sidebar contains specialty agents waiting by department.

When a case enters specialty review:

- the responsible specialty agent is marked active
- the specialty doctor moves from the sidebar to a consult slot

### 3. Patient Severity Display

When a patient occupies a bed:

- triage level is displayed
- effective triage level is displayed
- deterioration / pending / observation alerts are displayed

### 4. ER to Specialty Handoff

When ER escalates to specialty:

- the patient remains in the specialty consult area
- the matching specialty agent is activated from the sidebar
- the specialty doctor is visually co-located with that patient

## Additional Required Design Elements

The user requirements imply several extra components that should be modeled explicitly.

### A. Entity Types

- ER doctor
- specialty doctors
- patients
- optional later:
  - nurse
  - imaging technician

### B. Location Types

- waiting seat
- bed
- desk
- equipment
- consult slot
- exit/discharge

### C. Movement States

Needed next:

- waiting
- being assessed
- moved to bed
- waiting for test
- under observation
- specialty consult active
- completed / discharged

### D. Bed Assignment Logic

Needed next:

- which free ER bed a patient occupies
- which observation bed a patient occupies
- what happens when all beds are full

### E. Equipment Occupancy

Needed next:

- which imaging queue slot a patient waits in
- which equipment is busy
- which case is attached to each occupied resource

### F. Specialty Arrival Logic

Needed next:

- optional summon delay before specialty arrives
- active specialty consult slot assignment

## What Has Been Added Now

The runtime snapshot now includes:

- `scene.layout_id`
- `scene.tile_size`
- `scene.zone_slots`
- `scene.locations`
- `scene.entities`

This is the first spatial layer needed for a hospital-map renderer.

The Pygame viewer has also been shifted away from zone panels and toward:

- a hospital floor scene
- fixed chair/bed/equipment positions
- a specialty sidebar
- patient and doctor entities rendered on top of those positions

The runtime scene layer now also tracks:

- ER bed assignment
- observation bed assignment
- awaiting-result slot assignment
- specialty consult slot assignment
- discharge slot assignment
- ER doctor to patient pairing
- specialty summon / consulting state

## Immediate Next Rendering Step

Use `scene.locations` and `scene.entities` in the Pygame renderer instead of zone panels.

That renderer should:

- draw the hospital floor
- draw beds/chairs/desks/equipment from map coordinates
- draw patients at their assigned location
- draw the ER doctor and specialty doctors as separate entities
- keep the specialty sidebar visible on the right

## Next Required Logic Layer

To make the scene feel more like real work rather than static placement, the next logic to add is:

1. explicit bed assignment state
2. explicit patient movement targets
3. specialty summon delay / arrival state
4. equipment occupancy rendered at the machine itself
5. doctor-to-patient pairing visualization during assessment and consult

Progress:

- 1. explicit bed assignment state: started
- 2. explicit patient movement targets: initial target ids added
- 3. specialty summon delay / arrival state: started
- 5. doctor-to-patient pairing visualization: runtime pairing state added

Remaining major work:

- make the Pygame renderer visibly use pairing and summon states
- render equipment occupancy directly on machines / queue points
- add interpolation so patients and doctors appear to move between positions
