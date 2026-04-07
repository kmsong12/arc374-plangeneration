"""
config.py – All tuneable parameters in one place.
"""

# ── Canvas & site ──────────────────────────────────────────────
CANVAS_W = 900
CANVAS_H = 640

SITE_MARGIN = 50
GRID_SIZE   = 10
PAD         = 30

N_ROOMS_DEFAULT = 10
TRY             = 200

# 0 = all rooms, 1 = bedrooms only, 2 = public rooms only
ROOM_CONSTRAINT = 0

# ── Room size palettes ─────────────────────────────────────────
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

# ── Colours ────────────────────────────────────────────────────
SITE_BG      = "#FAFAF6"
SITE_BORDER  = "#1a1a1a"
CANVAS_BG    = "#E8E6DE"
BUSH_COLOR   = "#1A8A60"
LABEL_COLOR  = "#444444"

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

# ── Bushes ─────────────────────────────────────────────────────
N_BUSHES     = 30
BUSH_TRY     = 200
BUSH_R_RANGE = (8, 16)
BUSH_PAD     = 15

# ── Panel sizes ────────────────────────────────────────────────
SIDEBAR_LEFT_W  = 192
SIDEBAR_RIGHT_W = 215
TOOLBAR_H       = 40
METRICS_BAR_H   = 28