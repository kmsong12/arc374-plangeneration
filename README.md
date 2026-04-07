# ARC374 Final Project – Hotel Floor Plan Generator
**Team:** Chaemin Lim (cl5456) · Joshua Song (js8604) · Ahania Soni (as7918)

---

## Quick start

```bash
# 1. Clone / pull the repo
git clone <your-repo-url>
cd <repo-folder>

# 2. Install dependencies (Pillow for PNG export; tkinter ships with Python)
pip install pillow

# 3. (Optional) set your Anthropic API key for the LLM prompt mode
export ANTHROPIC_API_KEY=sk-ant-...     # macOS / Linux
set    ANTHROPIC_API_KEY=sk-ant-...     # Windows CMD

# 4. Run
python main.py
```

**Python 3.9+** required. Tested on macOS 14 and Windows 11.

---

## File structure

```
main.py            – entry point; launches the Tkinter window
app.py             – HotelApp: UI layout + interaction logic
config.py          – all tuneable parameters in one place
hotel.py           – Hotel data model (composition of rooms)
rooms.py           – Room dataclasses (inheritance hierarchy)
packing.py         – dart-throwing packing + bush placement
canvas_renderer.py – draws the plan onto a Tkinter Canvas
geometry_utils.py  – snap, overlap, hit-test helpers
llm_bridge.py      – translates a text prompt into packing weights
```

---

## Generation modes

| Mode | How to use |
|------|-----------|
| **Random / Procedural** | Click **↺ Regenerate** or press `R`. Drag placed rooms to reposition. |
| **Drag & Drop** | Switch to this mode; click a room in the library (left panel) and place it on canvas. |
| **Zoning** | Draw a zone rectangle on the canvas; future generations will respect region constraints. *(Stub – Week 3)* |
| **LLM Prompt** | Type a natural-language description and click **Generate with prompt ↗**. Requires `ANTHROPIC_API_KEY`. |

---

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `R` | Regenerate |
| `S` | Export PNG |
| `G` | Toggle grid |
| `L` | Toggle room labels |

*(Wire these up in `app.py` → `root.bind(...)` as needed.)*

---

## Development roadmap

- **Week 2 (current):** Basic UI, random packing, metrics bar, LLM weight stub.
- **Week 3:** Drag-and-drop room placement from library, zoning constraints.
- **Week 4:** Room editing (resize, delete), full zoning → packing integration.
- **Week 5:** Unit tests, user evaluation, portfolio, screen recording.
