# Web Pixel Asset Pipeline

## Goal

This viewer is moving from code-drawn prototype visuals to reusable sprite-based visuals.
The asset pipeline should support:

- browser delivery
- clean licensing tracking
- sprite replacement without renderer rewrites
- separate themes for ER, diagnostics, consult, and support spaces

## Proposed Folder Structure

```text
app/ui/web_viewer/assets/
├── manifest.json
├── licenses/
│   └── THIRD_PARTY_ASSETS.md
├── characters/
│   ├── doctors/
│   │   ├── er/
│   │   └── specialty/
│   ├── nurse/
│   ├── patient/
│   └── sheets/
├── tiles/
│   ├── floors/
│   ├── walls/
│   ├── doors/
│   └── shadows/
├── furniture/
│   ├── waiting/
│   ├── er/
│   ├── diagnostics/
│   ├── consult/
│   └── office/
├── props/
│   ├── medical/
│   ├── monitors/
│   ├── ui_icons/
│   └── effects/
└── ui/
    ├── bubbles/
    ├── badges/
    └── panels/
```

## Sprite Rules

- Tile baseline: `16x16` or `32x32`, scaled by CSS/canvas only.
- Character sheets should contain `down`, `left`, `right`, `up` rows.
- Each walking row should include at least `idle`, `step_a`, `idle`, `step_b`.
- Furniture should be delivered as layered sprites where possible:
  - base
  - shadow
  - decoration
- Doors and hallway markers should exist as separate tiles so movement routes stay readable.

## Manifest Fields

Each asset entry in `manifest.json` should provide:

- `id`
- `category`
- `theme`
- `path`
- `frame_width`
- `frame_height`
- `directions`
- `animations`
- `license`
- `author`
- `source_url`

## Immediate Replacement Priorities

1. `characters/doctors/er`
2. `characters/nurse`
3. `characters/patient`
4. `furniture/er`
5. `furniture/diagnostics`
6. `furniture/consult`
7. `tiles/floors`, `tiles/walls`, `tiles/doors`

## Licensing Note

Do not copy third-party art directly into the repo unless the license explicitly permits reuse and redistribution.
Track every imported asset in `licenses/THIRD_PARTY_ASSETS.md`.
