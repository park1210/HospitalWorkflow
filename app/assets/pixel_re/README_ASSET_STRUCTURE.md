# Pixel RE Asset Structure

이 폴더는 병원 시뮬레이션용 픽셀 자산을 역할별로 정리하는 표준 구조입니다.

## 표준 폴더 구조

```text
app/assets/pixel_re/
├── characters/
│   ├── patient/
│   ├── er_doctor/
│   ├── specialty_doctor/
│   └── nurse/
├── furniture/
│   ├── beds/
│   ├── stretchers/
│   ├── desks/
│   │   ├── triage/
│   │   ├── chart/
│   │   ├── observation/
│   │   └── workstation/
│   ├── seating/
│   │   ├── waiting_chair/
│   │   └── waiting_bench/
│   ├── tables/
│   ├── reception/
│   └── cabinets/
├── equipment/
│   ├── monitors/
│   │   └── bedside/
│   ├── diagnostics/
│   │   ├── ct/
│   │   └── imaging/
│   └── lab/
├── tiles/
│   ├── floors/
│   │   ├── plain/
│   │   ├── speckled/
│   │   ├── teal/
│   │   └── vents/
│   ├── walkways/
│   ├── walls/
│   ├── partitions/
│   │   ├── glass/
│   │   ├── curtain/
│   │   └── low/
│   └── doors/
│       ├── swing/
│       ├── sliding/
│       └── entrance/
├── rooms/
│   └── modules/
├── source_sets/
│   └── raw_exports/
└── ui/
    ├── monitors/
    └── icons/
```

## 캐릭터 파일명 규칙

캐릭터는 아래 형식을 권장합니다.

```text
<role>_<direction>_<pose>_<variant>.png
```

예시:

- `patient_front_idle_a.png`
- `patient_front_step_a.png`
- `er_doctor_back_idle_b.png`
- `specialty_doctor_left_step_b.png`
- `nurse_right_idle_a.png`

### direction

- `front`
- `back`
- `left`
- `right`

### pose

- `idle`
- `step`

### variant

- `a`
- `b`

보통 한 캐릭터 세트는 아래 16장으로 구성합니다.

- `front_idle_a`
- `front_step_a`
- `front_idle_b`
- `front_step_b`
- `back_idle_a`
- `back_step_a`
- `back_idle_b`
- `back_step_b`
- `left_idle_a`
- `left_step_a`
- `left_idle_b`
- `left_step_b`
- `right_idle_a`
- `right_step_a`
- `right_idle_b`
- `right_step_b`

## 자산 배치 규칙

### characters

- `patient_*` -> `characters/patient/`
- `er_doctor_*` -> `characters/er_doctor/`
- `specialty_doctor_*` -> `characters/specialty_doctor/`
- `nurse_*` -> `characters/nurse/`

### furniture

- `hospital_bed_*` -> `furniture/beds/`
- `stretcher_*` -> `furniture/stretchers/`
- `triage_desk_*` -> `furniture/desks/triage/`
- `chart_desk_*` -> `furniture/desks/chart/`
- `observation_desk_*` -> `furniture/desks/observation/`
- `compact_workstation_*` -> `furniture/desks/workstation/`
- `waiting_chair_*` -> `furniture/seating/waiting_chair/`
- `three_seat_waiting_bench_*` -> `furniture/seating/waiting_bench/`
- `side_table_*` -> `furniture/tables/`
- `reception_counter_*` -> `furniture/reception/`
- `small_supply_cabinet_*` -> `furniture/cabinets/`

### equipment

- `bedside_monitor_*` -> `equipment/monitors/bedside/`
- `ct_*`, `ct_scanner_*`, `ct_table_*` -> `equipment/diagnostics/ct/`
- `imaging_workstation_*`, `xray_stand_*`, `blood_draw_*` -> `equipment/diagnostics/imaging/`
- `lab_*`, `medical_cart_*`, `portable_monitor_device*`, `small_lab_device*` -> `equipment/lab/`

### ui

- `ui_monitor_*`, `ui_vitals_panel*` -> `ui/monitors/`
- `ui_icon_*` -> `ui/icons/`

### tiles

- `floor_plain_*` -> `tiles/floors/plain/`
- `floor_speckled_*` -> `tiles/floors/speckled/`
- `floor_teal_*` -> `tiles/floors/teal/`
- `floor_vent_*` -> `tiles/floors/vents/`
- `path_*` -> `tiles/walkways/`
- `wall_*` -> `tiles/walls/`
- `glass_partition_*` -> `tiles/partitions/glass/`
- `curtain_partition_*` -> `tiles/partitions/curtain/`
- `low_partition_*` -> `tiles/partitions/low/`
- `door_single_*`, `door_double_*` -> `tiles/doors/swing/`
- `door_sliding_*` -> `tiles/doors/sliding/`
- `door_hospital_entrance_*` -> `tiles/doors/entrance/`

## 운영 원칙

- 파일명은 가능한 한 유지하고, 폴더를 의미적으로 분리합니다.
- 새 자산은 배경 투명 PNG를 권장합니다.
- 같은 오브젝트의 `base`, `shadow`, `overlay`는 같은 폴더에 함께 둡니다.
- 큰 원본 시트는 우선 `source_sets/raw_exports/` 에 보관하고, 실제 사용 단위 PNG만 각 역할 폴더로 분리하는 것을 권장합니다.
