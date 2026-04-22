"""
canvas_renderer.py  -  Draws the hotel plan on a Tkinter Canvas.

Arc conversion rule:
  Processing: arc(cx, cy, w, h, start, stop)
  Tkinter: create_arc(x0,y0,x1,y1, start=, extent=)

  Conversion:
    x0 = cx - w/2,  y0 = cy - h/2
    x1 = cx + w/2,  y1 = cy + h/2
    tk_start  = -proc_start_deg (flip CW to CCW)
    tk_extent = -(proc_stop - proc_start) in degrees

"""

from __future__ import annotations
import math
import tkinter as tk
from typing import List, Tuple, Optional

from config import (
    GRID_SIZE, SITE_BORDER,
    ROOM_COLORS, ROOM_BORDERS, LABEL_COLOR,
)
from hotel import Hotel
from rooms import Room

WALL  = 6
INNER = 3
LIN   = 1
BG    = "#ffffff"
BLK   = "#000000"

def _rect(c, x, y, w, h, fill="", outline=BLK, width=1):
    if w <= 0 or h <= 0:
        return
    c.create_rectangle(x, y, x+w, y+h, fill=fill, outline=outline, width=width)

def _line(c, x1, y1, x2, y2, fill=BLK, width=1):
    c.create_line(x1, y1, x2, y2, fill=fill, width=width)

def _oval_center(c, cx, cy, rw, rh, fill="", outline=BLK, width=1):
    # Ellipse specified by center + radius.
    c.create_oval(cx-rw, cy-rh, cx+rw, cy+rh,
                  fill=fill, outline=outline, width=width)

def _proc_arc(c, cx, cy, w, h, start_rad, stop_rad,
              outline=BLK, width=1):
    # bounding box
    x0 = cx - w/2;  y0 = cy - h/2
    x1 = cx + w/2;  y1 = cy + h/2
    # convert radians→degrees, flip direction
    start_deg = math.degrees(start_rad)
    stop_deg  = math.degrees(stop_rad)
    tk_start  = -start_deg
    tk_extent = -(stop_deg - start_deg)
    c.create_arc(x0, y0, x1, y1,
                 start=tk_start, extent=tk_extent,
                 style=tk.ARC, outline=outline, width=width)

# Processing angle constants
_HALF_PI  = math.pi / 2
_PI       = math.pi
_TWO_PI   = math.pi * 2

# helper functions
def _wall_ring(c, x, y, w, h, t):
    _rect(c, x, y, w, h, fill=BLK, outline="")
    _rect(c, x+t, y+t, w-2*t, h-2*t, fill=BG, outline="")

def _inner_wall(c, x1, y1, x2, y2, t):
    if x1 == x2:  # vertical
        _rect(c, x1-t/2, min(y1,y2), t, abs(y2-y1), fill=BLK, outline="")
    else:          # horizontal
        _rect(c, min(x1,x2), y1-t/2, abs(x2-x1), t, fill=BLK, outline="")

def _cut_h(c, xl, yc, w, wt):
    _rect(c, xl, yc-wt/2, w, wt, fill=BG, outline="")

def _cut_v(c, xc, yt, h, wt):
    _rect(c, xc-wt/2, yt, wt, h, fill=BG, outline="")

# door arcs (exact port of Processing helpers) 
def _door_arc_right(c, hx, hy, r):
    _proc_arc(c, hx, hy, 2*r, 2*r, 0, _HALF_PI)
    _line(c, hx, hy, hx+r, hy)

def _door_arc_up_right(c, hx, hy, r):
    _proc_arc(c, hx, hy, 2*r, 2*r, _PI+_HALF_PI, _TWO_PI)
    _line(c, hx, hy, hx+r, hy)

def _shower(c, x, y, w, h):
    _rect(c, x, y, w, h)
    _line(c, x, y, x+w, y+h)
    _line(c, x, y+h, x+w, y)

def _sink(c, x, y, w, h):
    _rect(c, x, y, w, h)
    _oval_center(c, x+w/2, y+h/2, min(w,h)*0.28, min(w,h)*0.28)

def _toilet(c, cx, cy, rw=16, rh=11):
    _oval_center(c, cx, cy, rw, rh)

def _couch(c, x, y, w, h):
    _rect(c, x, y, w, h)
    _line(c, x+w/3, y, x+w/3, y+h)
    _line(c, x+2*w/3, y, x+2*w/3, y+h)

def _table(c, x, y, w, h):
    _rect(c, x, y, w, h)

def _chair_sq(c, cx, cy, s=12):
    _rect(c, cx-s/2, cy-s/2, s, s)


#  Room drawing functions - port of room_utils.py

def _draw_bedroom_A(c, x, y, rw, rh):
    A_BASE = 400.0
    sc = rw / A_BASE
    wall = WALL; inn = INNER
    edoor = int(90*sc); bdoor = int(80*sc)

    _wall_ring(c, x, y, rw, rh, wall)

    # window top centred
    win_w = int(rw*0.46); wx = x+(rw-win_w)/2.0; wy = y
    _rect(c, wx, wy, win_w, wall, fill=BG, outline="")
    ext = wall*1.25
    _line(c, wx-ext, wy,           wx+win_w+ext, wy)
    _line(c, wx,     wy+wall/3,    wx+win_w,     wy+wall/3)
    _line(c, wx,     wy+wall*2/3,  wx+win_w,     wy+wall*2/3)
    _line(c, wx-ext, wy+wall,      wx+win_w+ext, wy+wall)

    # entry door bottom-left
    door_x = x+wall
    _cut_h(c, door_x, y+rh-wall/2, edoor, wall)
    _door_arc_up_right(c, door_x, y+rh-wall, edoor)

    # bathroom bottom-right
    bath_right_x = x+rw-wall
    bath_top_y   = y+rh-wall-rh*0.32
    bath_bot_y   = y+rh-wall
    door_right   = door_x+edoor
    bath_wall_x  = door_right+inn/2

    _inner_wall(c, bath_wall_x, bath_top_y+inn/2, bath_wall_x, bath_bot_y, inn)
    _inner_wall(c, bath_wall_x, bath_top_y, bath_right_x, bath_top_y, inn)
    _rect(c, x+wall, bath_top_y-inn-1,
          bath_wall_x-(x+wall)-inn/2, inn*2+4, fill=BG, outline="")

    bath_door_y = bath_top_y+inn/2
    _cut_v(c, bath_wall_x, bath_door_y, bdoor, inn)
    _door_arc_right(c, bath_wall_x, bath_door_y, bdoor)

    bx  = bath_wall_x+inn/2+int(4*sc)
    bww = bath_right_x-door_right-inn
    bhh = rh*0.32-inn
    sh_w = bww*0.45; sh_x = x+rw-wall-sh_w
    _shower(c, sh_x, bath_top_y, sh_w, rh*0.32)
    gap_w = sh_x-bx; sk_w = gap_w*0.42; sk_h = bhh*0.22
    _sink(c, sh_x-sk_w-int(6*sc), bath_top_y, sk_w, sk_h)
    tlt_w=int(38*sc); tlt_h=int(28*sc)
    tank_w=int(42*sc); tank_h=int(16*sc)
    tlt_cx=bx+tank_w*0.5+int(4*sc); tank_y=bath_bot_y-tank_h
    _toilet(c, tlt_cx, tank_y-tlt_h*0.5, tlt_w/2, tlt_h/2)
    _rect(c, tlt_cx-tank_w/2, tank_y, tank_w, tank_h)

    bed_w=rw*0.44; bed_h=rh*0.36
    bed_x=x+rw-wall-bed_w; bed_y=y+wall+int(rh*0.10)
    _rect(c, bed_x, bed_y, bed_w, bed_h)
    pw=bed_w*0.08; ph=bed_h*0.28
    off=int(6*sc)
    _rect(c, bed_x+bed_w-pw-off, bed_y+bed_h*0.10, pw, ph)
    _rect(c, bed_x+bed_w-pw-off, bed_y+bed_h*0.62, pw, ph)
    ns_w=int(bed_w*0.18); ns_h=int(bed_h*0.10); ns_x=x+rw-wall-ns_w
    _rect(c, ns_x, bed_y-ns_h, ns_w, ns_h)
    _rect(c, ns_x, bed_y+bed_h, ns_w, ns_h)
    tbl_w=rw*0.12; tbl_h=rh*0.28
    _table(c, x+wall, bed_y+(bed_h-tbl_h)/2, tbl_w, tbl_h)


def _draw_bedroom_B(c, x, y, rw, rh):
    B_BASE = 500.0
    sc=rw/B_BASE; wall=WALL; inn=INNER
    edoor=int(90*sc); bdoor=int(80*sc)

    _wall_ring(c, x, y, rw, rh, wall)

    ety = y+rh-wall-edoor
    _cut_v(c, x+wall/2, ety, edoor, wall)
    _door_arc_up_right(c, x+wall, ety+edoor, edoor)

    bath_bot_y=y+rh*0.55; part_x=x+rw*0.38
    _inner_wall(c, part_x, y+wall, part_x, bath_bot_y+inn/2, inn)
    _inner_wall(c, x+wall, bath_bot_y, part_x, bath_bot_y, inn)
    _cut_h(c, x+wall, bath_bot_y, bdoor, inn)
    _rect(c, x+wall, bath_bot_y-inn, bdoor, inn*2+2, fill=BG, outline="")
    _door_arc_up_right(c, x+wall, bath_bot_y, bdoor)

    bx2=x+wall; by2=y+wall; bw2=part_x-x-wall; bh2=bath_bot_y-y-wall
    _shower(c, bx2, by2, bw2, bh2*0.48)
    sk_w2=bw2*0.38; sk_h2=bh2*0.24
    _sink(c, bx2+bw2-sk_w2, bath_bot_y-inn/2-sk_h2, sk_w2, sk_h2)
    tlt_w2=int(32*sc); tlt_h2=int(22*sc)
    tank_w2=int(16*sc); tank_h2=int(36*sc)
    tlt_cx2=part_x-inn/2-tlt_w2/2-tank_w2
    sh_bot=by2+bh2*0.48
    tlt_cy2=sh_bot+(bath_bot_y-inn/2-sk_h2-sh_bot)*0.5
    _toilet(c, tlt_cx2, tlt_cy2, tlt_w2/2, tlt_h2/2)
    _rect(c, part_x-inn/2-tank_w2, tlt_cy2-tank_h2/2, tank_w2, tank_h2)

    bzone_w=rw-rw*0.38-wall*2
    bed_w2=bzone_w*0.70; bed_h2=rh*0.38
    bed_x2=x+rw-wall-bed_w2; bed_y2=y+wall+int(rh*0.08)
    div_y2=bed_y2+int(rh*0.38)+int(rh*0.04)
    wend_x=part_x+int(rw*0.18)
    _inner_wall(c, wend_x, div_y2, x+rw-wall, div_y2, inn)
    win_x2=x+rw-wall+1
    _rect(c, win_x2, div_y2, wall-2, y+rh-wall-div_y2, fill=BG, outline="")
    for frac in (0,1/3,2/3,1):
        _line(c, win_x2+(wall-2)*frac, div_y2, win_x2+(wall-2)*frac, y+rh-wall)
    _rect(c, bed_x2, bed_y2, bed_w2, bed_h2)
    pw2=bed_w2*0.08; ph2=bed_h2*0.28; off2=int(6*sc)
    _rect(c, bed_x2+bed_w2-pw2-off2, bed_y2+bed_h2*0.10, pw2, ph2)
    _rect(c, bed_x2+bed_w2-pw2-off2, bed_y2+bed_h2*0.62, pw2, ph2)
    ns_w2=int(bed_w2*0.18); ns_h2=int(bed_h2*0.10); ns_x2=x+rw-wall-ns_w2
    _rect(c, ns_x2, bed_y2-ns_h2, ns_w2, ns_h2)
    _rect(c, ns_x2, bed_y2+bed_h2, ns_w2, ns_h2)
    couch_w=bzone_w*0.55; couch_h=rh*0.12
    couch_x=x+rw-wall-couch_w; couch_y=div_y2+inn/2
    _couch(c, couch_x, couch_y, couch_w, couch_h)
    ctbl_w=couch_w*0.70; ctbl_h=rh*0.08
    _table(c, couch_x+(couch_w-ctbl_w)/2, y+rh-wall-ctbl_h, ctbl_w, ctbl_h)
    _table(c, part_x+inn, y+rh-wall-rh*0.10, rw*0.22, rh*0.10)


def _draw_bedroom_C(c, x, y, rs, _=None):
    wall=rs*0.5/9
    _rect(c, x, y, rs, rs, fill=BLK, outline="")
    _rect(c, x+wall, y+wall, rs*8/9, rs*8/9, fill=BG, outline="")
    # bathroom block top-right
    _rect(c, x+wall+rs*4/9, y+wall, rs*4/9, rs*4/9, fill=BLK, outline="")
    _rect(c, x+wall*2+rs*4/9, y+wall, rs*4/9-wall, rs*4/9-wall, fill=BG, outline="")

    # main door: arc(x+margin*2, y+margin, 2r,2r, 0, HALF_PI)
    margin=wall; r_d=rs*1.5/9
    _proc_arc(c, x+margin*2, y+margin, 2*r_d, 2*r_d, 0, _HALF_PI)
    _line(c, x+margin*2, y+margin, x+margin*2, y+margin+r_d)
    _rect(c, x+margin*2, y, r_d, margin, fill=BG, outline="")

    # bathroom door: arc(x+margin_b, y+margin_b-wall-radius, 2r,2r, HALF_PI, PI)
    inner_rs=rs*8/9; margin_b=wall+inner_rs/2
    _proc_arc(c, x+margin_b, y+margin_b-wall-r_d, 2*r_d, 2*r_d, _HALF_PI, _PI)
    _line(c, x+margin_b, y+margin_b-wall-r_d, x+margin_b-r_d, y+margin_b-wall-r_d)
    _rect(c, x+margin_b, y+margin_b-wall-r_d, wall, r_d, fill=BG, outline="")

    # bathroom fixtures
    bx3=x+rs*4/9+wall*2; by3=y+wall
    _rect(c, bx3+rs*0.5/9, by3, rs/9, rs*0.5/9)
    _oval_center(c, bx3+rs/9, by3+rs/9, rs*0.375/9, rs*0.5/9)
    # shower arc: arc(bx+inner/2-wall, by, rs*3/9, rs*3/9, HALF_PI, PI)
    _proc_arc(c, bx3+rs*4/9-wall, by3, rs*3/9, rs*3/9, _HALF_PI, _PI)
    sk_w3=rs*2/9; sk_h3=rs/9
    sk_x3=bx3+rs*4/9-wall-sk_w3; sk_y3=by3+rs*4/9-wall-sk_h3
    _rect(c, sk_x3, sk_y3, sk_w3, sk_h3)
    _oval_center(c, sk_x3+sk_w3/2, sk_y3+sk_h3/2, sk_w3/4, sk_h3/4)

    # L-desk
    ds=rs*1.5/9
    _line(c, x+wall, y+wall+rs*4/9, x+ds, y+wall+rs*4/9)
    _line(c, x+ds, y+wall+rs*4/9, x+ds, y+wall+rs*8/9-ds)
    _line(c, x+ds, y+wall+rs*8/9-ds, x+ds*2, y+wall+rs*8/9-ds)
    _line(c, x+ds*2, y+wall+rs*8/9-ds, x+ds*2, y+wall+rs*8/9)
    r_ch=rs/9
    _oval_center(c, x+ds*1.5, y+wall+rs*8/9-ds*1.5, r_ch/2, r_ch/2)
    _rect(c, x+wall, y+wall+rs*8/9-ds/2-rs*1.9/9, rs*0.4/9, rs*1.9/9)

    # bed
    bw4=rs*3/9; bh4=rs*4/9
    _rect(c, x+rs-wall-bw4, y+rs-wall-bh4, bw4, bh4)
    _rect(c, x+rs-wall-rs*2/9, y+rs-wall-rs*0.75/9, rs/9, rs*0.5/9)

    # window
    _rect(c, x+rs*1.5/9, y+rs*8.5/9, rs*3/9, wall, fill=BG, outline="")
    _rect(c, x+rs*1.5/9, y+rs*8.6/9, rs*3/9, wall*0.8, fill=BG, outline="")


def _draw_bedroom_D(c, x, y, rw, rh):
    ww=rw*0.5/11; wh=rh*0.5/16
    _rect(c, x, y, rw, rh, fill=BLK, outline="")
    _rect(c, x+ww, y+wh, rw*10/11, rh*15/16, fill=BG, outline="")
    _rect(c, x+rw*4.5/11, y+rh*8/16, rw*6/11, rh*4/16, fill=BLK, outline="")
    _rect(c, x+rw*4.5/11+ww, y+rh*8/16+wh, rw*5.5/11, rh*3/16, fill=BG, outline="")

    rwd=rw*1.5/11; rhd=rh*1.5/16
    # main door: arc(x+wall, y+rh*10/16, 2rwd,2rhd, 0, HALF_PI)
    _proc_arc(c, x+ww, y+rh*10/16, 2*rwd, 2*rhd, 0, _HALF_PI)
    _line(c, x+ww, y+rh*10/16, x+ww+rwd, y+rh*10/16)
    _rect(c, x, y+rh*10/16, ww, rhd, fill=BG, outline="")

    # bathroom door: arc(bx+wall, by+rh*3.5/16, 2rwd,2rhd, PI+HALF_PI, 2*PI)
    bx5=x+rw*4.5/11; by5=y+rh*8/16
    _proc_arc(c, bx5+ww, by5+rh*3.5/16, 2*rwd, 2*rhd, _PI+_HALF_PI, _TWO_PI)
    _rect(c, bx5, by5+rh*2/16, ww, rhd, fill=BG, outline="")

    # bathroom fixtures
    _rect(c, bx5+ww, by5+wh, rw*2/11, rh/16)
    _rect(c, bx5+ww+rw*0.4/11, by5+wh+rh*0.5/16, rw/11, rh*0.25/16)
    _rect(c, bx5+ww+rw*2/11+rw*0.5/11, by5+wh, rw/11, rh*0.5/16)
    _oval_center(c, bx5+ww+rw*3/11, by5+wh+rh/16, rw*0.375/11, rh*0.5/16)
    sh5x=bx5+ww+rw*4/11; sh5y=by5+wh
    _rect(c, sh5x, sh5y, rw*1.5/11, rh*3/16)
    _line(c, sh5x, sh5y, sh5x+rw*1.5/11, sh5y+rh*3/16)
    _line(c, sh5x, sh5y+rh*3/16, sh5x+rw*1.5/11, sh5y)

    # two beds
    bw6=rw*5/11; bh6=rh*2.75/16; bx6=x+rw*5.5/11
    for by6 in (y+rh*1.5/16, y+rh*5.25/16):
        _rect(c, bx6, by6, bw6, bh6)
    _rect(c, x+rw*9.5/11, y+rh*1.875/16, rw*0.5/11, rh*2/16)
    _rect(c, x+rw*9.5/11, y+rh*5.625/16, rw*0.5/11, rh*2/16)
    _rect(c, x+rw*9/11, y+rh*4.25/16, rw*1.5/11, rh/16)
    # cabinet
    _rect(c, x+ww, y+wh, rw*1.5/11, rh*6.125/16)
    _line(c, x+ww, y+wh+rh*3.0625/16, x+ww+rw*1.5/11, y+wh+rh*3.0625/16)
    # table + chairs
    _rect(c, x+rw*1.75/11, y+rh*13.25/16, rw*1.5/11, rh*2.25/16)
    for fy in (y+rh*13.5/16+rh*0.04, y+rh*13.5/16+rh*0.09):
        for fx in (x+rw*1.75/11-rw*0.055, x+rw*3.25/11+rw*0.055):
            _oval_center(c, fx, fy, rw*0.035, rh*0.022)
    # couch
    _rect(c, x+rw*5/11, y+rh*14/16, rw*5/11, rh*1.5/16)
    _rect(c, x+rw*5.5/11, y+rh*14/16, rw*4/11, rh/16)
    for lx in (x+rw*6.5/11, x+rw*7.5/11, x+rw*8.5/11):
        _line(c, lx, y+rh*14/16, lx, y+rh*15/16)
    # TV
    _rect(c, x+rw*5.5/11, y+rh*12/16, rw*4/11, rh*0.5/16)
    _rect(c, x+rw*6/11, y+rh*12.1/16, rw*3/11, rh*0.25/16)
    # windows
    _rect(c, x+rw*10.5/11, y+rh*12.25/16, ww, rh*3/16, fill=BG, outline="")
    _rect(c, x+rw*2/11, y, rw*8.5/11, wh, fill=BG, outline="")


def _wall_box(c, x, y, w, h, t):
    _rect(c, x, y, w, h, fill=BLK, outline="")
    _rect(c, x+t, y+t, w-2*t, h-2*t, fill=BG, outline="")

def _top_window(c, x, y, w, t):
    win_w=int(w*0.46); wx=x+(w-win_w)/2.0
    _rect(c, wx, y, win_w, t, fill=BG, outline="")
    ext=t*1.25
    _line(c, wx-ext, y,           wx+win_w+ext, y)
    _line(c, wx,     y+t/3,       wx+win_w,     y+t/3)
    _line(c, wx,     y+t*2/3,     wx+win_w,     y+t*2/3)
    _line(c, wx-ext, y+t,         wx+win_w+ext, y+t)

def _left_door(c, x, y, w, h, t):
    # arc(x+t, oy+door_h, 2r,2r, PI+HALF_PI, TWO_PI)
    door_h=int(min(100, h*0.18)); oy=y+h-t-door_h
    _rect(c, x, oy, t, door_h, fill=BG, outline="")
    hx=x+t; hy=oy+door_h; r=door_h
    _proc_arc(c, hx, hy, 2*r, 2*r, _PI+_HALF_PI, _TWO_PI)
    _line(c, hx, hy, hx+r, hy)

def _draw_tea_room_1(c, x, y, w, h):
    t=WALL
    _wall_box(c, x, y, w, h, t)
    _top_window(c, x, y, w, t)
    _left_door(c, x, y, w, h, t)
    tw=int(w*0.22); th=int(h*0.14); s=12
    for cxf,cyf in ((0.28,0.26),(0.72,0.26),(0.28,0.68),(0.72,0.68)):
        cx=x+w*cxf; cy=y+h*cyf
        c.create_oval(cx-tw/2, cy-th/2, cx+tw/2, cy+th/2,
                      fill="", outline=BLK, width=1)
        gap=s*1.1; oy2=th/2+gap; spread=tw*0.36; nudge=gap*0.55
        for dx,dy in ((-spread,-oy2+nudge),(0,-oy2),(spread,-oy2+nudge),
                       (-spread,oy2-nudge),(0,oy2),(spread,oy2-nudge)):
            _chair_sq(c, cx+dx, cy+dy, s)

def _draw_tea_room_2(c, x, y, w, h):
    t=WALL
    _wall_box(c, x, y, w, h, t)
    _top_window(c, x, y, w, t)
    _left_door(c, x, y, w, h, t)
    cw2=int(w*0.10); ch2=int(h*0.48)
    _rect(c, x+w-t-cw2, y+t, cw2, ch2)
    _rect(c, x+w-t-cw2+(cw2-cw2*0.55)/2, y+t+ch2*0.70, cw2*0.55, ch2*0.18)
    d=int(min(w,h)*0.18)
    for txf,tyf in ((0.30,0.32),(0.64,0.32),(0.38,0.70),(0.76,0.70)):
        tx=x+w*txf; ty=y+h*tyf
        c.create_oval(tx-d/2, ty-d/2, tx+d/2, ty+d/2,
                      fill="", outline=BLK, width=1)
        r_t=d/2+12*1.1
        for angle in (90,270,180,0):
            ax=tx+r_t*math.cos(math.radians(angle))
            ay=ty-r_t*math.sin(math.radians(angle))
            _chair_sq(c, ax, ay, 12)

def _draw_reading_room(c, x, y, rw, rh):
    ww=rw*0.5/12.5; wh=rh*0.5/12.5
    _rect(c, x, y, rw, rh, fill=BLK, outline="")
    _rect(c, x+ww, y+wh, rw*11.5/12.5, rh*11.5/12.5, fill=BG, outline="")

    r_d=rw*1.5/12.5; r_h=rh*1.5/12.5
    # door: arc(x+wall, y+wall+rh*8.5/12.5, 2rd,2rh, 0, HALF_PI)
    _proc_arc(c, x+ww, y+wh+rh*8.5/12.5, 2*r_d, 2*r_h, 0, _HALF_PI)
    _line(c, x+ww, y+wh+rh*8.5/12.5, x+ww+r_d, y+wh+rh*8.5/12.5)
    _rect(c, x, y+wh+rh*7/12.5, ww, r_h, fill=BG, outline="")

    for i in range(46):
        _rect(c, x+i*rw*0.25/12.5+ww, y+wh+rh*10.5/12.5, rw*0.25/12.5, rh/12.5)

    for txf,tyf in ((3/12.5,4.5/12.5),(7.5/12.5,7/12.5)):
        tx=x+rw*txf; ty=y+rh*tyf; tw2=rw*2.5/12.5; th2=rh*2.5/12.5
        _rect(c, tx, ty, tw2, th2)
        r_s=rw*0.5/12.5; r_h2=rh*0.5/12.5
        for cx2,cy2 in ((tx+tw2/2,ty-r_h2),(tx+tw2/2,ty+th2+r_h2),
                         (tx-r_s,ty+th2/2),(tx+tw2+r_s,ty+th2/2)):
            _oval_center(c, cx2, cy2, r_s, r_h2)

    for txf in (0.5/12.5,3/12.5,5.5/12.5):
        tx=x+rw*txf; ty=y+rh*0.5/12.5; tw2=rw*2.5/12.5; th2=rh*2/12.5
        _rect(c, tx, ty, tw2, th2)
        r_ch=rw*0.5/12.5
        # arc(tx+rw*1.25/12.5, ty+th2, 2r,2r, 0, PI)  (semicircle below desk)
        _proc_arc(c, tx+rw*1.25/12.5, ty+th2, 2*r_ch, 2*r_ch, 0, _PI)
        _rect(c, tx+rw*0.5/12.5, ty+rh*0.3/12.5, rw*1.5/12.5, rh*0.5/12.5)
        _rect(c, tx+rw*0.75/12.5, ty+rh*0.8/12.5, rw/12.5, rh*0.25/12.5)

    atx=x+rw*8/12.5; aty=y+rh*0.5/12.5
    r_a=rw*4/12.5; r_ha=rh*4/12.5
    _line(c, atx, aty, atx, aty+rh*2/12.5)
    _line(c, atx+rw*2/12.5, aty+rh*4/12.5, atx+rw*4/12.5, aty+rh*4/12.5)
    # arc(atx, aty+rh*4/12.5, ra,rha, -HALF_PI, 0)  → Processing 3*HALF_PI to TWO_PI
    _proc_arc(c, atx, aty+rh*4/12.5, r_a, r_ha, _PI+_HALF_PI, _TWO_PI)

    _rect(c, x+rw*12/12.5, y+rh*4.5/12.5, ww, rh*6.5/12.5, fill=BG, outline="")


def _draw_library(c, x, y, rw, rh):
    ww=rw*0.5/26; wh=rh*0.5/17
    _rect(c, x, y, rw, rh, fill=BLK, outline="")
    _rect(c, x+ww, y+wh, rw*25/26, rh*16/17, fill=BG, outline="")

    r_dw=rw*1.5/26; r_dh=rh*1.5/17
    dx=x+rw*9/26; dy=y+rh*16.5/17
    _rect(c, dx, dy, r_dw*2, wh, fill=BG, outline="")
    # door arcs: arc(dx, dy, 2r,2r, -HALF_PI, 0) and arc(dx+3/26rw, dy, ...)
    _proc_arc(c, dx,           dy, 2*r_dw, 2*r_dh, _PI+_HALF_PI, _TWO_PI)
    _proc_arc(c, dx+rw*3/26,   dy, 2*r_dw, 2*r_dh, _PI,          _PI+_HALF_PI)
    _line(c, dx, dy-r_dh, dx, dy)
    _line(c, dx+rw*3/26, dy-r_dh, dx+rw*3/26, dy)

    for row_yf in (2.875/17,5.375/17,6.375/17,8.875/17):
        bx7=x+rw*2.5/26; by7=y+rh*row_yf
        for i in range(32):
            _rect(c, bx7+i*rw*0.25/26, by7, rw*0.25/26, rh/17)

    # L-table
    lx=x+rw*0.5/26; ly=y+rh*0.5/17
    _line(c, lx, ly+rh*0.75/17, lx+rw*12.25/26, ly+rh*0.75/17)
    _line(c, lx+rw*12.25/26, ly+rh*0.75/17, lx+rw*12.25/26, ly+rh*5.75/17)
    r_s=rw*0.5/26
    for xf in (1.5/26,4.5/26,7.5/26,10.5/26):
        cxc=x+rw*xf; cyc=y+rh*0.75/17+rh*0.5/17
        # arc(cxc, cyc, 2r,2r, 0, PI)  chair semicircle above line
        _proc_arc(c, cxc, cyc, 2*r_s, 2*r_s, 0, _PI)
    for yf in (2.25/17,4.75/17):
        cxc=x+rw*12.25/26; cyc=y+rh*0.5/17+rh*yf
        # arc(cxc, cyc, 2r,2r, HALF_PI, PI+HALF_PI)
        _proc_arc(c, cxc, cyc, 2*r_s, 2*r_s, _HALF_PI, _PI+_HALF_PI)

    _draw_reading_room(c, x+rw*13.5/26, y, rw*12.5/26, rh*12.5/17)

    # bathroom
    bx9=x; by9=y+rh*12/17
    _rect(c, bx9, by9, rw*5.5/26, rh*5/17, fill=BLK, outline="")
    _rect(c, bx9+ww, by9+wh, rw*4.5/26, rh*4/17, fill=BG, outline="")
    _rect(c, bx9+rw*3/26, by9+wh, rw*2/26, rh/17)
    _oval_center(c, bx9+rw*4/26, by9+wh+rh*0.5/34, rw*0.75/26, rh*0.25/17)
    _rect(c, bx9+rw*1.5/26, by9+wh, rw/26, rh*0.5/17)
    _oval_center(c, bx9+rw*2/26, by9+rh*1.75/17, rw*0.5/26, rh*0.75/17)
    r_d9=rw*1.5/26; r_h9=rh*1.5/17
    # arc(bx9+rw*5/26, by9+rh*4.5/17, 2r,2r, PI, PI+HALF_PI)
    _proc_arc(c, bx9+rw*5/26, by9+rh*4.5/17, 2*r_d9, 2*r_h9, _PI, _PI+_HALF_PI)
    _rect(c, bx9+rw*5/26, by9+rh*3/17, ww, r_h9, fill=BG, outline="")


# ------------------------------------------------------------------------
#  Landscape elements
# ------------------------------------------------------------------------

def _draw_bench(c, x, y, w, h, orient="h"):
    seat="#9C8462"; leg="#6B5740"; back="#7A6248"
    if orient=="h":
        _rect(c, x,       y+h*0.1, w*0.10, h*0.9, fill=leg,  outline="")
        _rect(c, x+w*0.90,y+h*0.1, w*0.10, h*0.9, fill=leg,  outline="")
        _rect(c, x+w*0.05,y+h*0.35,w*0.90, h*0.45,fill=seat, outline=leg, width=1)
        _rect(c, x+w*0.05,y,        w*0.90, h*0.30,fill=back, outline=leg, width=1)
        for i in range(1,4):
            _line(c, x+w*0.05+w*0.90*i/4, y+2,
                     x+w*0.05+w*0.90*i/4, y+h*0.30-2, fill=leg)
    else:
        _rect(c, x+w*0.1, y,        w*0.8, h*0.10, fill=leg,  outline="")
        _rect(c, x+w*0.1, y+h*0.90, w*0.8, h*0.10, fill=leg,  outline="")
        _rect(c, x+w*0.35,y+h*0.05, w*0.45,h*0.90, fill=seat, outline=leg, width=1)
        _rect(c, x,       y+h*0.05, w*0.30,h*0.90, fill=back, outline=leg, width=1)
        for i in range(1,4):
            _line(c, x+2,      y+h*0.05+h*0.90*i/4,
                     x+w*0.30-2,y+h*0.05+h*0.90*i/4, fill=leg)

def _draw_furniture_item(c, item, selected=False):
    """Draw a single furniture item on the canvas."""
    from config import FURNITURE_COLORS, FURNITURE_BORDERS
    t = item["type"]
    x, y, w, h = item["x"], item["y"], item["w"], item["h"]
    fill   = FURNITURE_COLORS.get(t,  "#D4C5A9")
    border = FURNITURE_BORDERS.get(t, "#8B7355")

    if t == "Plant":
        cx2, cy2 = x + w // 2, y + h // 2
        r = min(w, h) // 2
        c.create_oval(cx2 - r, cy2 - r, cx2 + r, cy2 + r,
                      fill="#7BC67E", outline="#388E3C", width=1.5)
        r2 = int(r * 0.6)
        c.create_oval(cx2 - r2, cy2 - r, cx2 + r2, cy2,
                      fill="#4CAF50", outline="#388E3C", width=1)
    elif t == "Table":
        _rect(c, x, y, w, h, fill=fill, outline=border, width=1.5)
        leg = 5
        for lx2, ly2 in ((x, y), (x + w - leg, y),
                          (x, y + h - leg), (x + w - leg, y + h - leg)):
            _rect(c, lx2, ly2, leg, leg, fill=border, outline="")
    elif t == "Chair":
        _rect(c, x, y, w, h, fill=fill, outline=border, width=1.5)
        back_h = max(6, h // 4)
        _rect(c, x, y, w, back_h, fill=border, outline="")
    elif t == "Sofa":
        _rect(c, x, y, w, h, fill=fill, outline=border, width=1.5)
        arm = max(6, w // 7)
        _rect(c, x,         y, arm, h, fill=border, outline="")
        _rect(c, x + w - arm, y, arm, h, fill=border, outline="")
        back_h = max(6, h // 4)
        _rect(c, x, y, w, back_h, fill=border, outline="")
    elif t == "Bed":
        _rect(c, x, y, w, h, fill=fill, outline=border, width=1.5)
        head_h = max(8, h // 6)
        _rect(c, x, y, w, head_h, fill=border, outline="")
        pw = w // 2
        ph = max(10, h // 6)
        _rect(c, x + (w - pw) // 2, y + head_h + 4, pw, ph,
              fill="#FFFFFF", outline=border, width=1)
    elif t == "Wardrobe":
        _rect(c, x, y, w, h, fill=fill, outline=border, width=1.5)
        _line(c, x + w // 2, y + 4, x + w // 2, y + h - 4,
              fill=border, width=1)
        hy2 = y + h // 2
        _oval_center(c, x + w // 4,     hy2, 3, 3, fill=border, outline="")
        _oval_center(c, x + 3 * w // 4, hy2, 3, 3, fill=border, outline="")
    else:
        _rect(c, x, y, w, h, fill=fill, outline=border, width=1.5)

    if selected:
        pad = 3
        c.create_rectangle(x - pad, y - pad, x + w + pad, y + h + pad,
                            outline="#E85D24", width=2, fill="", dash=(4, 3))
    # type label below
    c.create_text(x + w // 2, y + h + 8, text=t,
                  font=("Helvetica", 6), fill="#888880")


def _draw_path(c, x, y, w, h):
    _rect(c, x, y, w, h, fill="#D4CCBA", outline="#B0A898", width=1)
    if w>=h:
        step=max(24,w//6)
        for px in range(int(x+step),int(x+w),step):
            _line(c, px,y+2,px,y+h-2, fill="#C0B8A4")
        _line(c, x+2,y+h/2,x+w-2,y+h/2, fill="#C0B8A4")
    else:
        step=max(24,h//6)
        for py in range(int(y+step),int(y+h),step):
            _line(c, x+2,py,x+w-2,py, fill="#C0B8A4")
        _line(c, x+w/2,y+2,x+w/2,y+h-2, fill="#C0B8A4")


#  CanvasRenderer

class CanvasRenderer:
    def __init__(self, canvas: tk.Canvas):
        self.canvas = canvas

    def draw(self, site, hotel, bushes,
             landscape_items=None,
             show_grid=True, show_labels=False,
             selected_room=None, zone_rects=None,
             sel_furn=None):
        """
        sel_furn: (room_ref, idx) tuple identifying the selected furniture item,
                  or None if no furniture is selected.
        """
        c=self.canvas; c.delete("all")
        sx,sy,sw,sh=site
        cw=c.winfo_width() or 2000; ch=c.winfo_height() or 2000

        c.create_rectangle(0,0,cw,ch, fill="#E8E6DE", outline="")

        if show_grid:
            self._draw_grid(site)

        c.create_rectangle(sx,sy,sx+sw,sy+sh, fill="#FAFAF6",
                           outline="#1a1a1a", width=2)

        if zone_rects:
            for zx,zy,zw,zh in zone_rects:
                c.create_rectangle(zx,zy,zx+zw,zy+zh,
                                   fill="#FFF3CD",outline="#BA7517",
                                   width=1,dash=(4,3),stipple="gray25")

        if landscape_items:
            for item in landscape_items:
                if item["type"]=="path":
                    _draw_path(c,item["x"],item["y"],item["w"],item["h"])

        self._draw_bushes(bushes)

        if landscape_items:
            for item in landscape_items:
                if item["type"]=="bench":
                    _draw_bench(c,item["x"],item["y"],
                                item["w"],item["h"],item.get("orient","h"))

        for room in hotel.rooms:
            self._draw_room(room, selected=(room is selected_room),
                            show_label=show_labels,
                            sel_furn=sel_furn)

    def draw_preview(self, label: str, base_w: int, base_h: int):
        """Draw a single room centred on the canvas with no other elements."""
        from rooms import ROOM_CLASSES
        c = self.canvas
        c.delete("all")
        cw = c.winfo_width() or 900
        ch = c.winfo_height() or 640
        c.create_rectangle(0, 0, cw, ch, fill="#F0EDE5", outline="")

        pad = 80
        scale = min((cw - 2 * pad) / base_w, (ch - 2 * pad) / base_h)
        rw = int(base_w * scale)
        rh = int(base_h * scale)
        x = (cw - rw) // 2
        y = (ch - rh) // 2

        room = ROOM_CLASSES[label](x, y, rw, rh)
        self._draw_room(room, selected=False, show_label=False)

        c.create_text(cw // 2, 24, text=label,
                      font=("Helvetica", 13, "bold"), fill="#2C2C2A")
        c.create_text(cw // 2, ch - 18,
                      text="Click canvas to return",
                      font=("Helvetica", 9), fill="#888880")

    def hit_test(self, px, py, hotel):
        return hotel.room_at(px, py)

    def _draw_grid(self, site):
        sx,sy,sw,sh=site; c=self.canvas
        for gy in range(sy, sy+sh+1, GRID_SIZE):
            for gx in range(sx, sx+sw+1, GRID_SIZE):
                c.create_oval(gx-1,gy-1,gx+1,gy+1, fill="#C4C2BA", outline="")

    def _draw_bushes(self, bushes):
        c=self.canvas
        for bx,by,br in bushes:
            for ox,oy in [(0,-br*.75),(br*.75,0),(0,br*.75),(-br*.75,0),
                          (-br*.5,-br*.5),(br*.5,-br*.5),(br*.5,br*.5),
                          (-br*.5,br*.5),(0,0)]:
                r=br/2
                c.create_oval(bx+ox-r,by+oy-r,bx+ox+r,by+oy+r,
                              fill="#1A8A60",outline="#0A5C40",width=0.5)

    def _draw_room(self, room, selected, show_label, sel_furn=None):
        c=self.canvas; lbl=room.label
        fill_col=ROOM_COLORS.get(lbl,"#F0EEE8")
        line_col=ROOM_BORDERS.get(lbl,"#888")
        border_w = 2.5 if getattr(room, "pinned", False) else 1.5
        c.create_rectangle(room.x,room.y,room.x+room.w,room.y+room.h,
                           fill=fill_col,outline=line_col,width=border_w)
        try:
            self._draw_interior(room)
        except Exception:
            pass
        # Per-room furniture (drawn on top of interior, room-relative → absolute)
        for i, fitem in enumerate(getattr(room, "furniture", [])):
            abs_item = dict(fitem, x=room.x + fitem["x"], y=room.y + fitem["y"])
            is_sel = (sel_furn is not None and
                      sel_furn[0] is room and sel_furn[1] == i)
            _draw_furniture_item(c, abs_item, selected=is_sel)
        # Pin indicator: small filled circle in top-right corner
        if getattr(room, "pinned", False):
            px = room.x + room.w - 8
            py = room.y + 8
            c.create_oval(px - 6, py - 6, px + 6, py + 6,
                          fill="#E85D24", outline="white", width=1.5)
        if selected:
            pad=4
            c.create_rectangle(room.x-pad,room.y-pad,
                               room.x+room.w+pad,room.y+room.h+pad,
                               outline="#E85D24",width=2,fill="",dash=(5,3))
        if show_label:
            c.create_text(room.cx, room.y+room.h-10,
                         text=lbl, font=("Helvetica",7), fill=LABEL_COLOR)

    def _draw_interior(self, room):
        c=self.canvas; lbl=room.label
        x,y,w,h=room.x,room.y,room.w,room.h
        fn={
            "BedroomA":    _draw_bedroom_A,
            "BedroomB":    _draw_bedroom_B,
            "BedroomC":    _draw_bedroom_C,
            "BedroomD":    _draw_bedroom_D,
            "TeaRoom1":    _draw_tea_room_1,
            "TeaRoom2":    _draw_tea_room_2,
            "Library":     _draw_library,
            "ReadingRoom": _draw_reading_room,
        }.get(lbl)
        if fn:
            fn(c, x, y, w, h)