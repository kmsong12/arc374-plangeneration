# ============================================================
# ARC374 Session 09 - Procedural Plan Generation (Simple OOP)
# Tabs / files in this sketch:
#   - config.py           (parameters)
#   - rooms.py            (Room + BedroomTypeI)
#   - hotel.py            (Hotel = composition of rooms)
#   - site_and_grid.py    (site + grid drawing)
#   - geometry_utils.py   (snap + overlap tests)
#   - packing.py          (packing algorithm)
#   - metrics.py          (Metrics = stats + display)
#
# Keys:
#   R / click  - regenerate new layout
#   S          - save frame
#   M          - toggle metrics panel (layout stays the same)
# ============================================================

from config import *
from site_and_grid import *
from packing import *
from landscape import *

show_metrics = False
metrics      = None
current_seed = 0

def setup():
    size(W, H)
    smooth()
    noLoop()
    generate()

def generate():
    global metrics, current_seed
    current_seed = int(random(10**9))
    redraw()

def draw():
    global metrics
    randomSeed(current_seed)
    background(BG)

    site = site_rect()
    draw_site(site)
    draw_grid(site)

    hotel = pack_rooms_into_hotel(site)

    bushes = pack_bushes(site, hotel)
    draw_bushes(bushes)

    hotel.draw_rooms()

    metrics = hotel.get_metrics(site)

    if show_metrics:
        metrics.draw()

def mousePressed():
    generate()

def keyPressed():
    global show_metrics
    if key in ('r', 'R'):
        generate()
    if key in ('s', 'S'):
        saveFrame("session9-pack-####.png")
    if key in ('m', 'M'):
        show_metrics = not show_metrics
        redraw()