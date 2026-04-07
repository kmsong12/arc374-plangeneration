"""
config.py – All tuneable parameters in one place.
Mirrors the Processing config.py but adapted for Tkinter/Python.
"""

# ── Canvas & site ──────────────────────────────────────────────
CANVAS_W = 900          # pixels available for the floor-plan canvas
CANVAS_H = 640

SITE_MARGIN = 50        # inset from canvas edge to site boundary
GRID_SIZE   = 10        # snap grid spacing (px)
PAD         = 30        # minimum gap between rooms when packing

# ── Packing ────────────────────────────────────────────────────
N_ROOMS_DEFAULT = 10    # default number of rooms to attempt
TRY             = 200   # max placement attempts per room

# Room-type constraint:  "all" | "bedrooms" | "public"
ROOM_CONSTRAINT = "all"

# ── Room size palettes (w, h) ──────────────────────────────────
A_SIZES  = [(160, 220), (180, 240), (200, 260)]   # Bedroom A – vertical
B_SIZES  = [(240, 160), (260, 180), (280, 190)]   # Bedroom B – horizontal
C_SIZES  = [(125, 125), (150, 150), (130, 130)]   # Bedroom C – square
D_SIZES  = [(160, 300), (180, 320), (200, 340)]   # Bedroom D – tall
T1_SIZES = [(220, 220), (260, 260), (200, 200)]   # Tea Room 1
T2_SIZES = [(260, 200), (280, 230), (250, 210)]   # Tea Room 2
LIB_SIZES= [(360, 300), (400, 360), (300, 260)]   # Library
RR_SIZES = [(200, 200), (150, 150), (180, 180)]   # Reading Room

# ── Drawing weights (probability thresholds, must sum to 1.0) ─
# Keys match room type labels; values are relative weights.
DEFAULT_WEIGHTS = {
    "BedroomA":    1.0 / 8,
    "BedroomB":    1.0 / 8,
    "BedroomC":    1.0 / 8,
    "BedroomD":    1.0 / 8,
    "TeaRoom1":    1.0 / 8,
    "TeaRoom2":    1.0 / 8,
    "Library":     1.0 / 8,
    "ReadingRoom": 1.0 / 8,
}

# ── Colours (Tkinter hex) ──────────────────────────────────────
SITE_BG        = "#FFFFFF"
SITE_BORDER    = "#1a1a1a"
GRID_DOT       = "#00000030"   # semi-transparent; drawn as small ovals
CANVAS_BG      = "#F5F4EE"

ROOM_COLORS = {
    "BedroomA":    "#E6F1FB",
    "BedroomB":    "#E6F1FB",
    "BedroomC":    "#EAF3DE",
    "BedroomD":    "#EAF3DE",
    "TeaRoom1":    "#FAEEDA",
    "TeaRoom2":    "#FAEEDA",
    "Library":     "#FBEAF0",
    "ReadingRoom": "#EEEDFE",
}

ROOM_BORDERS = {
    "BedroomA":    "#378ADD",
    "BedroomB":    "#378ADD",
    "BedroomC":    "#639922",
    "BedroomD":    "#639922",
    "TeaRoom1":    "#BA7517",
    "TeaRoom2":    "#BA7517",
    "Library":     "#D4537E",
    "ReadingRoom": "#7F77DD",
}

BUSH_COLOR  = "#0F6E56"
LABEL_COLOR = "#333333"

# ── Bushes ─────────────────────────────────────────────────────
N_BUSHES       = 30
BUSH_TRY       = 200
BUSH_R_RANGE   = (8, 16)
BUSH_PAD       = 15

# ── Sidebar / panel widths ─────────────────────────────────────
SIDEBAR_LEFT_W  = 190
SIDEBAR_RIGHT_W = 210
TOOLBAR_H       = 36
METRICS_BAR_H   = 28
