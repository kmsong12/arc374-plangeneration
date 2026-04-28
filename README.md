# ARC374 Final Project – Floor Plan Generator
**Team:** Chaemin Lim (cl5456) · Joshua Song (js8604) · Ahania Soni (as7918)

A Tkinter-based interactive floor plan generator. The UI is now a three-stage wizard: **author rooms → generate a plan → finalize & export**. Each stage has its own sidebars, canvas, and tools.

---

## Quick start

```bash
git clone <your-repo-url>
cd <repo-folder>

python main.py
```

**Python 3.9+** required (Tkinter ships with Python).

> Pillow is only needed if you want PNG export via external conversion; the built-in export writes PostScript (`.ps`).

---

## The 3-stage wizard

### Stage 1 · Room Author
Design reusable room blueprints.
- **Left sidebar**: categorized furniture catalog (Beds, Bath, Seating, Storage, Display, Openings, Preset bathrooms) with a colour well. Click an item to arm it, click on the canvas to drop it. `+ New Furniture…` opens a mini-editor where you compose rect / square / circle / triangle / line primitives into a named custom furniture piece.
- **Canvas**: dedicated authoring surface with its own local grid. The room starts as a rectangle with orange vertex handles.
  - **Drag** a handle to reshape.
  - **Double-click** an edge to insert a new vertex.
  - **Right-click** a vertex to remove it (min 3 verts).
- **Right sidebar**: full room-template library. Click **edit** to load a copy for editing, **copy** to duplicate for a fresh copy, **del** to remove. Colour wells at the top change fill/border for the working room.
- **Save Room…** prompts for a title and a *roomtype* (free-form; defaults include `bedroom`, `public room`, `bathroom`, ...). The new template is added to the shared library, persisted to `room_library.json`.

### Stage 2 · Generation
Three fully independent sub-modes that each own a fresh `Plan`. Switching sub-modes discards the current plan unless you save it.
- **Random** – sliders for total rooms, padding, bedroom bias, bush density, and seed. Roomtype toggles filter which templates are eligible.
- **Zoning** – draw zones on the canvas, click a zone to select it, pick a specific template (from the left list) or roomtype (combo on the right), set the *max rooms*, then **Generate**. The room list scrolls so items above/below slide out of view as you scroll.
- **LLM** – prompt-only frontend. The text area captures your description; the backend will be wired up later.

A shared **Clear All** wipes the working plan, and **Clear Landscape** preserves rooms but removes bushes/paths/benches. **Send to Finalize →** hands the current plan off to Stage 3.

### Stage 3 · Finalize & Export
- **Drag a room** to move it. If it would overlap another room (polygon SAT) or leave the site, it snaps back to its previous location.
- **Rotate 90°**, **Change Color**, **Toggle Pin**, and **Delete Room** from the right sidebar (or press `R` to rotate, `Delete` to remove).
- **Landscape palette** on the left: click to arm a bench (horizontal/vertical), path (horizontal/vertical), or tree, then click the canvas to place. Placement is rejected if the footprint overlaps any room.
- **Save to Library** writes the plan into `plan_library.json`. **Export JSON** saves the raw data. **Export PNG** writes a PostScript file (`canvas.postscript`) that you can convert to PNG via ImageMagick.

---

## File structure

```
main.py               – entry point; instantiates AppShell
app.py                – AppShell: top step bar + stage switcher + toolbar
theme.py              – centralised colors + tk helper widgets
config.py             – canvas size, margins, pad, bed-length anchor for units
units.py              – pixel <-> feet conversion (bed = 6.5 ft => ~15.4 px/ft)
geometry_utils.py     – snap/rect helpers + polygon SAT / bbox / rotate / pt-in-poly
canvas_renderer.py    – RoomCanvasRenderer (Stage 1) + PlanCanvasRenderer (Stage 2/3)
presets.py            – hand-drawn preset bedroom/tea/library renderers (8 rooms)
packing.py            – dart-throw packer; random_pack, zone_pack, pack_bushes
llm_bridge.py         – (kept) text-prompt → generation-settings helper

model/
  __init__.py
  room_template.py    – RoomTemplate (polygon, furniture, roomtype, colors)
  furniture_lib.py    – built-in furniture catalog with Python draw functions
  custom_furniture.py – user-authored primitives + persisted store
  room_library.py     – persistent RoomLibrary; auto-seeds the 8 presets
  plan.py             – Plan + RoomInstance + PlanLibrary

stages/
  __init__.py
  stage_author.py     – Stage 1 UI (authoring)
  stage_generate.py   – Stage 2 UI: Random / Zoning / LLM sub-modes
  stage_finalize.py   – Stage 3 UI: drag/snap-back, landscape, export

Legacy (kept only so the old test suite still imports):
  hotel.py, rooms.py
```

---

## Metrics

All area readouts are in **square feet (ft²)**. The scale is anchored by a default bed length of **6.5 ft ≈ 100 px**, giving **PX_PER_FT ≈ 15.38**. See `units.py`.

---

## Keyboard shortcuts

| Stage | Key | Action |
|-------|-----|--------|
| any   | `Ctrl+1 / 2 / 3` | Jump to stage |
| Author | `Delete` | Remove selected furniture |
| Finalize | `R` | Rotate selected room 90° |
| Finalize | `Delete` | Remove selected room |

---

## Persistence

- `room_library.json` – RoomTemplates (authored and seeded presets).
- `custom_furniture.json` – User-authored custom furniture.
- `plan_library.json` – Saved plans from Stage 3.

These files are created next to `main.py` on first launch.

---

## Out of scope (for now)

- LLM backend wiring (prompts are captured but not executed).
- Arcs in custom furniture (rect/square/circle/triangle/line only).
- Multi-floor / stair circulation.
