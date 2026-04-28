"""
config.py - Global configuration.

The detailed per-room sizes and color palettes that used to live here
now live inside the seeded `RoomLibrary` (see `model/room_library.py`)
and the `furniture_lib` catalog. What remains in this file is the
top-level canvas geometry, grid / padding defaults, and the bed-length
anchor used by `units.py`.

A handful of legacy constants (`DEFAULT_WEIGHTS`, `ROOM_COLORS`,
`ROOM_BORDERS`, `FURNITURE_ITEMS`, ...) are kept so the old `test_suite`
and `rooms.py` module keep importing without a hard break.
"""

# --- Canvas / site --------------------------------------------------------
CANVAS_W = 900
CANVAS_H = 640

SITE_MARGIN = 50
GRID_SIZE   = 10
PAD         = 30

N_ROOMS_DEFAULT = 10
TRY             = 200

# 0 = all rooms, 1 = bedrooms only, 2 = public rooms only  (legacy)
ROOM_CONSTRAINT = 0

# --- Bed-length anchor for units.py (do not remove) -----------------------
BED_LENGTH_FT = 6.5
BED_LENGTH_PX = 100

# --- UI panels ------------------------------------------------------------
SIDEBAR_LEFT_W  = 220
SIDEBAR_RIGHT_W = 240
TOOLBAR_H       = 44
STEPBAR_H       = 42
METRICS_BAR_H   = 28

# --- Room author (Stage 1) -------------------------------------------------
# Wall / door / window slab depth in **template world units** (feet-style
# numbers; same as Door default ``h`` in ``furniture_lib``). Exterior
# outline stroke uses ``room_polygon_outline_screen_px``. Interior ``Wall``
# thickness is stored in the same units so snapping lines up at every zoom.
AUTHOR_WALL_DEPTH_WORLD = 0.3

# Legacy name: nominal stroke at scale 1 (used by imports / tests).
ROOM_POLYGON_OUTLINE_PX = max(1.0, AUTHOR_WALL_DEPTH_WORLD * 1.0)


def room_polygon_outline_screen_px(scale: float) -> float:
    """Canvas stroke width in pixels matching ``AUTHOR_WALL_DEPTH_WORLD``."""
    return max(1.0, AUTHOR_WALL_DEPTH_WORLD * max(float(scale), 1e-6))


def room_outline_thickness_template(scale: float) -> float:
    """Interior wall slab thickness (template units), equal to Door depth."""
    _ = scale  # fixed in world units; callers pass zoom for API compat
    return AUTHOR_WALL_DEPTH_WORLD

# --- Bushes ---------------------------------------------------------------
N_BUSHES     = 30
BUSH_TRY     = 200
BUSH_R_RANGE = (8, 16)
BUSH_PAD     = 15

# --- Colours (minimal, most now come from theme.py / library) -------------
SITE_BG      = "#FAFAF6"
SITE_BORDER  = "#1a1a1a"
CANVAS_BG    = "#E8E6DE"
BUSH_COLOR   = "#1A8A60"
LABEL_COLOR  = "#444444"

# ======================================================================
# Legacy (kept only to satisfy `rooms.py` and the old test suite).  New
# code must prefer `model.room_library` and `model.furniture_lib`.
# ======================================================================

A_SIZES  = [(160, 220), (180, 240), (200, 260)]
B_SIZES  = [(240, 160), (260, 180), (280, 190)]
C_SIZES  = [(125, 125), (150, 150), (130, 130)]
D_SIZES  = [(160, 300), (180, 320), (200, 340)]
T1_SIZES = [(220, 220), (260, 260), (200, 200)]
T2_SIZES = [(260, 200), (280, 230), (250, 210)]
LIB_SIZES= [(360, 300), (400, 360), (300, 260)]
RR_SIZES = [(200, 200), (150, 150), (180, 180)]

DEFAULT_WEIGHTS = {
    "BedroomA":    1/8, "BedroomB": 1/8,
    "BedroomC":    1/8, "BedroomD": 1/8,
    "TeaRoom1":    1/8, "TeaRoom2": 1/8,
    "Library":     1/8, "ReadingRoom": 1/8,
}

ROOM_COLORS = {
    "BedroomA":    "#EBF3FB",
    "BedroomB":    "#EBF3FB",
    "BedroomC":    "#EDF5E2",
    "BedroomD":    "#EDF5E2",
    "TeaRoom1":    "#FDF3E2",
    "TeaRoom2":    "#FDF3E2",
    "Library":     "#FCF0F5",
    "ReadingRoom": "#F1F0FD",
}

ROOM_BORDERS = {
    "BedroomA":    "#378ADD",
    "BedroomB":    "#378ADD",
    "BedroomC":    "#639922",
    "BedroomD":    "#639922",
    "TeaRoom1":    "#C27A18",
    "TeaRoom2":    "#C27A18",
    "Library":     "#C8447A",
    "ReadingRoom": "#7B72D8",
}

# legacy furniture constants (unused by new stages; tests may import)
FURNITURE_ITEMS = {
    "Table":    {"w": 60,  "h": 80},
    "Chair":    {"w": 32,  "h": 32},
    "Sofa":     {"w": 90,  "h": 45},
    "Bed":      {"w": 80,  "h": 100},
    "Wardrobe": {"w": 55,  "h": 80},
    "Plant":    {"w": 28,  "h": 28},
}
FURNITURE_COLORS = {
    "Table":    "#D4C5A9",
    "Chair":    "#C4B5A0",
    "Sofa":     "#B8A898",
    "Bed":      "#E8E0D8",
    "Wardrobe": "#C8B898",
    "Plant":    "#7BC67E",
}
FURNITURE_BORDERS = {
    "Table":    "#8B7355",
    "Chair":    "#7A6248",
    "Sofa":     "#7A6248",
    "Bed":      "#888888",
    "Wardrobe": "#8B7355",
    "Plant":    "#388E3C",
}
