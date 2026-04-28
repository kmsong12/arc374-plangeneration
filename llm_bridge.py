"""
llm_bridge.py - Translates a natural-language prompt into packing weights.

Supports **Anthropic (Claude)** or **OpenAI (ChatGPT API)** via provider selection.

API key lookup (first match wins) for each provider:
  1. Environment variable  ANTHROPIC_API_KEY / OPENAI_API_KEY
  2. A file called         .env  in the project folder  (KEY=value format)
  3. A file called         secrets.py  in the project folder

Example .env:
    ANTHROPIC_API_KEY=sk-ant-...
    OPENAI_API_KEY=sk-...

Both .env and secrets.py are listed in .gitignore so they are never committed.

Security: Revoke exposed keys at the provider consoles; never commit keys.
"""

from __future__ import annotations
import json
import logging
import os
import re
from typing import Any, Dict, List, Literal, Optional, Tuple, Union

from config import DEFAULT_WEIGHTS, N_ROOMS_DEFAULT

log = logging.getLogger(__name__)


# region agent log
def _agent_log(
        hypothesis_id: str, location: str, message: str, data: Dict[str, Any]) -> None:
    try:
        log_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "debug-22c64f.log")
        payload = {
            "sessionId": "22c64f",
            "timestamp": int(__import__("time").time() * 1000),
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
        }
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        pass
# endregion


def _infer_roomtypes_from_prompt(text: str) -> Union[List[str], None]:
    """
    Detect phrases like \"bedrooms only\" / \"only public rooms\" map to enabled
    roomtype filters for packing (matches ``RoomTemplate.roomtype`` literals).
    """
    t = (text or "").strip()
    public_first = (
        re.search(r"(?i)\b(?:only\s+)?public\s+(?:rooms?|spaces?|areas?)\s+only\b", t)
        or re.search(r"(?i)\b(?:commons?|communal)\s+only\b", t)
        or re.search(r"(?i)\bonly\s+public\b", t))
    bedrooms_first = (
        re.search(r"(?i)\bbedrooms?\s+only\b", t)
        or re.search(r"(?i)\bonly\s+bedrooms?\b", t))
    if bedrooms_first or re.search(r"(?i)\bprivate\s+(?:rooms?\s*)?only\b", t):
        return ["bedroom"]
    if public_first:
        return ["public room"]
    if re.search(r"(?i)\b(?:no|without)\s+public\b", t) or re.search(
            r"(?i)\bcollaboratives?\s+only\b", t):
        return ["bedroom"]
    if re.search(r"(?i)\b(?:no|without)\s+bed(?:room)?s?\b", t):
        return ["public room"]
    return None


def _preset_label_roomcategory(label: str) -> str:
    if label in ("BedroomA", "BedroomB", "BedroomC", "BedroomD"):
        return "bedroom"
    return "public room"


KNOWN_LIBRARY_ROOMTYPES = frozenset({"bedroom", "public room"})


def _heuristic_fallback_settings(user_prompt: str) -> Dict[str, Any]:
    """
    When the remote LLM call fails (quota, network, parse), infer ``n_rooms``
    from phrases like \"5 rooms\" and use neutral weights (1.0 per label),
    not ``DEFAULT_WEIGHTS`` (0.125 each) which reads as a broken response.
    """
    text = (user_prompt or "").strip()
    n_val: Any = None
    m = re.search(r"\b(\d{1,2})\s*rooms?\b", text, re.I)
    if m:
        n_val = max(2, min(40, int(m.group(1))))
    weights = {k: 1.0 for k in DEFAULT_WEIGHTS}
    out: Dict[str, Any] = {"weights": weights}
    if n_val is not None:
        out["n_rooms"] = int(n_val)
    else:
        out["n_rooms"] = N_ROOMS_DEFAULT
    inferred = _infer_roomtypes_from_prompt(text)
    if inferred:
        out["enabled_roomtypes"] = inferred
        for lk in weights:
            if _preset_label_roomcategory(lk) not in inferred:
                weights[lk] = 0.0
    return out


def _env_demo_llm() -> bool:
    """Offline demo parser — set ``ARC374_DEMO_LLM=1`` in ``.env`` or env."""
    v = os.environ.get("ARC374_DEMO_LLM", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _demo_infer_corner_zone(tl: str) -> Union[Tuple[str, Dict[str, float]], None]:
    """Map phrases like \"southwest corner\" to normalized zone ``{x,y,w,h}``."""
    pairs = (
        ("sw", (
            r"\b(south\s*west|southwest)\s*(corner|quarter|zone|only|part)?\b",
            r"\b(lower|bottom)[-\s]+(left|west)\b",
            r"\bsw\b")),
        ("se", (
            r"\b(south\s*east|southeast)\s*(corner|quarter|zone|only|part)?\b",
            r"\b(lower|bottom)[-\s]+(right|east)\b",
            r"\bse\b")),
        ("nw", (
            r"\b(north\s*west|northwest)\s*(corner|quarter|zone|only|part)?\b",
            r"\b(upper|top)[-\s]+(left|west)\b",
            r"\bnw\b")),
        ("ne", (
            r"\b(north\s*east|northeast)\s*(corner|quarter|zone|only|part)?\b",
            r"\b(upper|top)[-\s]+(right|east)\b",
            r"\bne\b")),
    )
    rects = {
        "nw": {"x": 0.02, "y": 0.02, "w": 0.46, "h": 0.46},
        "ne": {"x": 0.52, "y": 0.02, "w": 0.46, "h": 0.46},
        "sw": {"x": 0.02, "y": 0.52, "w": 0.46, "h": 0.46},
        "se": {"x": 0.52, "y": 0.52, "w": 0.46, "h": 0.46},
    }
    for tag, patterns in pairs:
        for pat in patterns:
            if re.search(pat, tl, re.I):
                return tag, rects[tag]
    return None


def _demo_nl_to_settings(user_prompt: str) -> Dict[str, Any]:
    """
    Local NL → settings for demos when API quota is exhausted.
    Handles room count, greenery level, bedroom/public emphasis, and optional
    corner zoning (e.g. \"bedrooms only in the southwest corner\").
    """
    text = (user_prompt or "").strip()
    tl = text.lower()
    weights = {k: 1.0 for k in DEFAULT_WEIGHTS}

    n_rooms = N_ROOMS_DEFAULT
    m = re.search(r"\b(\d{1,2})\s*rooms?\b", tl, re.I)
    if m:
        n_rooms = max(2, min(40, int(m.group(1))))

    if re.search(
            r"\b(bedrooms?\s+only|only\s+bedrooms?|private\s+rooms?\s+only)\b",
            tl):
        for lk in weights:
            if _preset_label_roomcategory(lk) != "bedroom":
                weights[lk] = 0.0
    elif re.search(
            r"\b(only\s+)?(public|communal|shared)\s+(rooms?|spaces?)\b", tl):
        for lk in weights:
            if _preset_label_roomcategory(lk) != "public room":
                weights[lk] = 0.0

    n_bushes = 35
    if re.search(
            r"\b(greenery\s*heavy|heavy\s*greenery|lots?\s+of\s+(bushes|trees|green)|"
            r"lush|dense\s+(green|landscape)|forest)\b",
            tl):
        n_bushes = 88
    elif re.search(
            r"\b(light|sparse|minimal)\s+(greenery|bushes|trees|green)\b", tl,
    ) or re.search(r"\blow\s+greenery\b", tl):
        n_bushes = 16
    elif re.search(
            r"\b(greenery|bushes?|trees?|landscap|green\s+space)\b", tl):
        n_bushes = 58

    out: Dict[str, Any] = {
        "weights": weights,
        "n_rooms": n_rooms,
        "n_bushes": max(0, min(120, n_bushes)),
        "pad": 30,
        "spatial": "mixed",
    }

    inf = _infer_roomtypes_from_prompt(text)
    if inf:
        out["enabled_roomtypes"] = inf
        for lk in weights:
            if _preset_label_roomcategory(lk) not in inf:
                weights[lk] = 0.0

    cz = _demo_infer_corner_zone(tl)
    if cz is not None:
        _tag, zn = cz
        zb = {lk: max(0.0, float(weights[lk])) for lk in DEFAULT_WEIGHTS}
        if sum(zb.values()) <= 0:
            zb = {lk: 1.0 for lk in DEFAULT_WEIGHTS}
        out["zones_normalized"] = [zn]
        out["zones_specs"] = [{
            "max": max(n_rooms, 4),
            "weights": zb,
        }]
        out["rooms_per_zone"] = [n_rooms]
        out["spatial"] = "mixed"

    return out


def _clamp_int(v: Any, lo: int, hi: int, default: int) -> int:
    try:
        x = int(v)
        return max(lo, min(hi, x))
    except (TypeError, ValueError):
        return default


def _clamp_float01(v: Any) -> Union[float, None]:
    """Return clamped float in ``[0, 1]`` or None if absent/invalid."""
    if v is None:
        return None
    try:
        x = float(v)
        return max(0.0, min(1.0, x))
    except (TypeError, ValueError):
        return None


def _clamp_positive_float(v: Any, lo: float, hi: float) -> Union[float, None]:
    try:
        x = float(v)
        return max(lo, min(hi, x))
    except (TypeError, ValueError):
        return None


def _coerce_zones_normalized(raw: Any) -> List[Tuple[float, float, float, float]]:
    """Normalize ``zones_normalized`` lists of ``{x,y,w,h}`` in relative 0–1 coords."""
    if not isinstance(raw, list):
        return []
    out: List[Tuple[float, float, float, float]] = []
    for item in raw[:12]:
        if not isinstance(item, dict):
            continue
        try:
            fx = float(item.get("x", 0))
            fy = float(item.get("y", 0))
            fw = float(item.get("w", 1))
            fh = float(item.get("h", 1))
            fx = max(0.0, min(1.0, fx))
            fy = max(0.0, min(1.0, fy))
            fw = max(0.01, min(1.0 - fx, fw))
            fh = max(0.01, min(1.0 - fy, fh))
            out.append((fx, fy, fw, fh))
        except (TypeError, ValueError):
            continue
    return out


def _coerce_zones_specs(
        raw: Any,
        n: int,
        weight_keys_fallback: Dict[str, float],
        ) -> List[Dict[str, Any]]:
    """
    ``zones_specs`` entries: {\"max\": int, \"weights\": optional dict}.

    Returned list length is clamped to ``n`` via pad/truncate.
    """
    specs: List[Dict[str, Any]] = []
    if isinstance(raw, list):
        for i, row in enumerate(raw[:n]):
            if not isinstance(row, dict):
                specs.append({"max": 10, "weights": dict(weight_keys_fallback)})
                continue
            mx = _clamp_int(row.get("max"), 1, 80, 10)
            wraw = row.get("weights")
            if isinstance(wraw, dict) and wraw:
                wmap: Dict[str, float] = {}
                for k, val in wraw.items():
                    try:
                        wmap[str(k)] = max(0.0, float(val))
                    except (TypeError, ValueError):
                        pass
                if not wmap:
                    wmap = dict(weight_keys_fallback)
            else:
                wmap = dict(weight_keys_fallback)
            specs.append({"max": mx, "weights": wmap})
    while len(specs) < n:
        specs.append({"max": 10, "weights": dict(weight_keys_fallback)})
    return specs[:n]


def _coerce_roomtype_weights(raw: Any) -> Union[Dict[str, float], None]:
    """Optional {\"bedroom\": float, \"public room\": float} from API."""
    if not isinstance(raw, dict):
        return None
    out: Dict[str, float] = {}
    for rk in ("bedroom", "public room"):
        if rk in raw:
            try:
                out[rk] = max(0.0, float(raw[rk]))
            except (TypeError, ValueError):
                continue
    return out if out else None


def _coerce_enabled_roomtypes(raw: Any) -> Optional[List[str]]:
    """
    Normalize API ``enabled_roomtypes`` / ``roomtypes`` to library literals
    (``bedroom``, ``public room``). Unknown strings are skipped.
    """
    if not isinstance(raw, list) or not raw:
        return None
    out: List[str] = []
    for x in raw:
        s = str(x).strip().lower().replace("_", " ")
        if s in ("public", "commons", "communal"):
            s = "public room"
        if s in KNOWN_LIBRARY_ROOMTYPES:
            out.append(s)
    seen: set = set()
    deduped: List[str] = []
    for x in out:
        if x not in seen:
            seen.add(x)
            deduped.append(x)
    return deduped or None


def _downgrade_spatial_for_single_roomtype(settings: Dict[str, Any]) -> None:
    """Bedroom/public split presets need both types; collapse to mixed if one only."""
    er = settings.get("enabled_roomtypes")
    if not isinstance(er, list) or len(er) != 1:
        return
    sp = settings.get("spatial", "mixed")
    if isinstance(sp, str) and sp.startswith("bedrooms_"):
        settings["spatial"] = "mixed"


def _merge_prompt_roomtypes(
        user_prompt: str,
        raw_api: dict,
        settings: dict) -> dict:
    """
    When the API omits ``enabled_roomtypes``, infer from phrases like
    \"bedrooms only\" and mask preset weights. Also fix split ``spatial``
    presets when only one category is allowed.
    """
    _er = raw_api.get("enabled_roomtypes")
    _rt = raw_api.get("roomtypes")
    had_api_list = (
        (isinstance(_er, list) and len(_er) > 0)
        or (isinstance(_rt, list) and len(_rt) > 0))
    merged = dict(settings)
    if had_api_list:
        _downgrade_spatial_for_single_roomtype(merged)
        # #region agent log
        er = merged.get("enabled_roomtypes")
        _agent_log(
            "H4", "llm_bridge:_merge_prompt_roomtypes",
            "api_supplied_roomtypes",
            {"enabled_roomtypes": er, "spatial": merged.get("spatial")})
        # #endregion
        return merged

    inferred = _infer_roomtypes_from_prompt(user_prompt)
    if not inferred:
        return merged

    merged["enabled_roomtypes"] = inferred
    cw = dict(merged.get("weights") or {})
    for lk in DEFAULT_WEIGHTS:
        if _preset_label_roomcategory(lk) not in inferred:
            cw[lk] = 0.0
    merged["weights"] = cw
    _downgrade_spatial_for_single_roomtype(merged)
    # #region agent log
    _agent_log(
        "H4", "llm_bridge:_merge_prompt_roomtypes",
        "prompt_inferred_roomtypes",
        {
            "inferred": inferred,
            "spatial": merged.get("spatial"),
        })
    # #endregion
    return merged


def _coerce_rooms_per_zone(raw: Any, n_zone: int) -> Union[List[int], None]:
    """List of ints, len ``n_zone``; distributes sum aligned with totals."""
    if not isinstance(raw, list) or n_zone <= 0:
        return None
    acc: List[int] = []
    for x in raw[:n_zone]:
        try:
            acc.append(max(0, int(x)))
        except (TypeError, ValueError):
            acc.append(0)
    while len(acc) < n_zone:
        acc.append(0)
    if sum(acc) <= 0:
        return None
    return acc[:n_zone]


def _normalize_llm_orientation(raw: Any) -> str:
    if raw is None:
        return "mixed"
    g = str(raw).strip().lower().replace("-", "_")
    if g in ("inward_collaborative", "inward", "collaborative"):
        return "inward_collaborative"
    if g in ("outward_private", "outward", "private"):
        return "outward_private"
    return "mixed"


def _normalize_api_key_value(raw: str) -> str:
    """Strip quotes and all whitespace (avoids accidental line breaks in .env)."""
    s = raw.strip().strip('"').strip("'")
    return "".join(s.split())


_SYSTEM_PROMPT = """
You are a hotel floor-plan design assistant.

The user describes a hotel floor plan in natural language. Output ONLY valid JSON
(no markdown, no prose, no code fences).

Core keys (always set "weights"):
- "weights": object with keys BedroomA..BedroomD, TeaRoom1, TeaRoom2, Library,
  ReadingRoom — relative frequencies (0 = exclude). Defaults 1.0.

Counts and spacing:
- "n_rooms": int — rooms to place, range 2–40 (default ~10).
- "pad": int — pixels between rooms, 0–120 (default 30).
- "n_bushes": int — landscape bushes 0–120 (default ~30).

Room-type mixing (mirrors slider “bedroom vs public” bias):
- "bedroom_bias": float 0–1 — higher favors bedroom templates vs public spaces.
- "roomtype_weights": optional object {\"bedroom\":float,\"public room\":float}
  — multiply-like emphasis on categories (non-negative).
- "enabled_roomtypes": optional array of \"bedroom\", \"public room\" (or synonym
  \"roomtypes\") — exclude all templates outside those categories when set.

Layout feel (mapped to packing):
- "layout_style": one of \"clustered\", \"scattered\", \"corridor\", \"mixed\".
  clustered = tighter groups; scattered = wider spacing; corridor = spine layout.
- "clustering": float 0–1 — pulls placement toward zone/site center when high.

Advanced spacing / packing control:
- "min_center_distance": float 0–200 — extra minimum gap feel (adds to pad).
- "entropy": float 0.3–3.0 — higher = more placement attempts (more random retries).

Spatial presets for "spatial" (bedroom vs public roomtypes in regions):
  mixed, bedrooms_top, bedrooms_bottom, bedrooms_left, bedrooms_right,
  bedrooms_west_third, bedrooms_east_third, bedrooms_north_third, bedrooms_south_third,
  bedrooms_north_middle_south_three, bedrooms_west_middle_east_three,
  bedrooms_nw_quarter, bedrooms_ne_quarter, bedrooms_sw_quarter, bedrooms_se_quarter

Custom zoning (overrides "spatial" when both set): use together
- "zones_normalized": [ {"x":0-1,"y":0-1,"w":0-1,"h":0-1}, ... ] — up to 12 rects
  in SITE-RELATIVE coordinates (origin top-left).
- "zones_specs": [ {"max": int, "weights": { template label or "#bedroom":float } }, ... ]
  — one entry per zone (same order as zones_normalized).
- "rooms_per_zone": [int, ...] — room counts per zone (optional; must match zone count).

Landscape:
- "bush_pad": int 0–120 — clearing around bushes.

Orientation (post-placement rotation spike):
- "orientation_goal": "mixed" | "inward_collaborative" | "outward_private"
  — loosely aligns door directions toward site center vs away.

Rules: Only include keys relevant to the request; always include "weights".
Output raw JSON only.

Example: {"weights":{"BedroomA":2,"BedroomB":1,"BedroomC":1,"BedroomD":1,
"TeaRoom1":1,"TeaRoom2":1,"Library":1,"ReadingRoom":1},"n_rooms":14,
"pad":40,"bedroom_bias":0.7,"layout_style":"clustered","clustering":0.65,
"spatial":"bedrooms_north_third","n_bushes":40}
""".strip()


def _lookup_env_key(var_name: str) -> str:
    """
    Read ``var_name`` (e.g. ANTHROPIC_API_KEY, OPENAI_API_KEY) from:
    1. os.environ
    2. .env in this package directory
    3. secrets.py in this package directory
    """
    key = _normalize_api_key_value(os.environ.get(var_name, ""))
    if key:
        return key

    here = os.path.dirname(os.path.abspath(__file__))
    for fname in (".env", "secrets.py"):
        path = os.path.join(here, fname)
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8-sig") as f:
                for line in f:
                    line_stripped = line.strip()
                    if line_stripped.startswith(var_name):
                        match = re.split(r"\s*=\s*", line_stripped, maxsplit=1)
                        if len(match) == 2:
                            key = _normalize_api_key_value(match[1])
                            if key:
                                return key
        except OSError:
            pass

    return ""


def _find_api_key() -> str:
    """Anthropic API key (backward-compatible name for tests)."""
    return _lookup_env_key("ANTHROPIC_API_KEY")


def _find_openai_api_key() -> str:
    """OpenAI API key."""
    return _lookup_env_key("OPENAI_API_KEY")


_VALID_SPATIAL = {
    "mixed",
    "bedrooms_top", "bedrooms_bottom", "bedrooms_left", "bedrooms_right",
    "bedrooms_west_third", "bedrooms_east_third",
    "bedrooms_north_third", "bedrooms_south_third",
    "bedrooms_north_middle_south_three",
    "bedrooms_west_middle_east_three",
    "bedrooms_nw_quarter", "bedrooms_ne_quarter",
    "bedrooms_sw_quarter", "bedrooms_se_quarter",
}


def _coerce_settings(data: dict) -> dict:
    """Normalize API JSON into the settings dict consumed by ``pack_from_llm_settings``."""
    raw_weights = data.get("weights", {})
    if not raw_weights and any(k in data for k in DEFAULT_WEIGHTS):
        raw_weights = data
    _agent_log(
        "H2", "llm_bridge:_coerce_settings:entry", "incoming_json",
        {
            "top_level_keys": sorted(data.keys()),
            "has_weights_key": "weights" in data,
            "weights_type": type(data.get("weights")).__name__,
            "weights_key_count": len(raw_weights)
            if isinstance(raw_weights, dict) else None,
            "n_rooms_raw": data.get("n_rooms"),
        })

    cleaned_weights: Dict[str, float] = {}
    for key in DEFAULT_WEIGHTS:
        val = raw_weights.get(key, DEFAULT_WEIGHTS[key])
        cleaned_weights[key] = max(0.0, float(val))

    settings: dict = {"weights": cleaned_weights}

    if "n_rooms" in data:
        settings["n_rooms"] = _clamp_int(data.get("n_rooms"), 2, 40, 10)

    if "n_bushes" in data:
        settings["n_bushes"] = max(0, min(120, int(data["n_bushes"])))
    if "pad" in data:
        settings["pad"] = max(0, min(120, int(data["pad"])))

    sp = data.get("spatial", "mixed")
    if isinstance(sp, str) and sp in _VALID_SPATIAL:
        settings["spatial"] = sp
    else:
        settings["spatial"] = "mixed"

    bb = _clamp_float01(data.get("bedroom_bias"))
    if bb is not None:
        settings["bedroom_bias"] = bb

    rtw = _coerce_roomtype_weights(data.get("roomtype_weights"))
    if rtw:
        settings["roomtype_weights"] = rtw

    er = _coerce_enabled_roomtypes(
        data.get("enabled_roomtypes") or data.get("roomtypes"))
    if er:
        settings["enabled_roomtypes"] = er
        for lk in cleaned_weights:
            if _preset_label_roomcategory(lk) not in er:
                cleaned_weights[lk] = 0.0

    cl = _clamp_float01(data.get("clustering"))
    if cl is not None:
        settings["clustering"] = cl

    ls = data.get("layout_style")
    if isinstance(ls, str):
        lsl = ls.strip().lower()
        if lsl in ("clustered", "scattered", "corridor", "mixed"):
            settings["layout_style"] = lsl

    md = _clamp_positive_float(data.get("min_center_distance"), 0.0, 200.0)
    if md is not None:
        settings["min_center_distance"] = md

    ent = _clamp_positive_float(data.get("entropy"), 0.3, 4.0)
    if ent is not None:
        settings["entropy"] = ent

    if "bush_pad" in data:
        settings["bush_pad"] = max(0, min(120, int(data["bush_pad"])))

    zm = _coerce_zones_normalized(data.get("zones_normalized"))
    if zm:
        settings["zones_normalized"] = zm
        zb = {k: cleaned_weights[k] for k in cleaned_weights}
        ns = len(zm)
        settings["zones_specs"] = _coerce_zones_specs(
            data.get("zones_specs"), ns, zb)
        rpz = _coerce_rooms_per_zone(data.get("rooms_per_zone"), ns)
        if rpz:
            settings["rooms_per_zone"] = rpz

    oo = _normalize_llm_orientation(data.get("orientation_goal"))
    if oo != "mixed":
        settings["orientation_goal"] = oo

    _downgrade_spatial_for_single_roomtype(settings)

    wvals = list(cleaned_weights.values())
    _agent_log(
        "H3", "llm_bridge:_coerce_settings:exit", "after_coercion",
        {
            "settings_keys": sorted(settings.keys()),
            "enabled_roomtypes": settings.get("enabled_roomtypes"),
            "n_rooms_coerced": settings.get("n_rooms"),
            "weights_min_max": [
                float(min(wvals)) if wvals else None,
                float(max(wvals)) if wvals else None,
            ],
            "all_weights_equal": (
                len(set(round(v, 6) for v in wvals)) <= 1 if wvals else None),
        })

    return settings


_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"

LLMProvider = Literal["anthropic", "openai"]


def _strip_response_fences(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"```[a-z]*", "", s).strip()
    s = s.strip("`").strip()
    return s


def _anthropic_messages_to_settings(user_prompt: str, api_key: str) -> dict:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2048,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )
    raw = message.content[0].text.strip()
    raw = _strip_response_fences(raw)
    log.debug("[llm_bridge] anthropic raw response: %s", raw[:500])
    data = json.loads(raw)
    wg = data.get("weights") if isinstance(data.get("weights"), dict) else {}
    _agent_log(
        "H2", "llm_bridge:_anthropic_messages:after_parse", "parsed_json_attrs",
        {
            "json_keys": sorted(data.keys()),
            "n_rooms_in_json": data.get("n_rooms"),
            "weights_keys_count": len(wg),
        })

    return _merge_prompt_roomtypes(user_prompt, data, _coerce_settings(data))


def _openai_chat_to_settings(user_prompt: str, api_key: str) -> dict:
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    completion = client.chat.completions.create(
        model=_OPENAI_DEFAULT_MODEL,
        max_tokens=2048,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        response_format={"type": "json_object"},
    )
    choice = completion.choices[0].message.content
    raw = (choice or "").strip()
    raw = _strip_response_fences(raw)
    log.debug("[llm_bridge] openai raw response: %s", raw[:500])
    data = json.loads(raw)
    wg = data.get("weights") if isinstance(data.get("weights"), dict) else {}
    _agent_log(
        "H2", "llm_bridge:_openai_chat:after_parse", "parsed_json_attrs",
        {
            "json_keys": sorted(data.keys()),
            "n_rooms_in_json": data.get("n_rooms"),
            "weights_keys_count": len(wg),
        })

    return _merge_prompt_roomtypes(user_prompt, data, _coerce_settings(data))


def prompt_to_settings(
        user_prompt: str,
        provider: Union[str, LLMProvider, None] = "anthropic",
        demo: Union[bool, None] = None,
        ) -> dict:
    """
    Call the chosen LLM API and parse the response into a settings dict:
      {
        "weights":  {room: float, ...},
        "n_bushes": int   (optional),
        "pad":      int   (optional),
        "n_rooms":  int   (optional),
        "spatial":  str   (optional),
      }

    ``provider``: ``\"anthropic\"`` (default, Claude) or ``\"openai\"`` (ChatGPT API).

    ``demo``: if True, skip the API and use the local :func:`_demo_nl_to_settings`
    parser (for demos / no quota). If None, use demo when the environment
    variable ``ARC374_DEMO_LLM`` is set to 1/true/yes/on.

    Raises RuntimeError on missing package, missing key, or auth failure.
    Returns default weights on other API/parse failures (same as before).
    """
    use_demo = demo is True or (demo is not False and _env_demo_llm())
    if use_demo:
        raw = _demo_nl_to_settings(user_prompt)
        return _merge_prompt_roomtypes(
            user_prompt, raw, _coerce_settings(raw))

    prov = (provider or "anthropic").lower().strip()
    if prov not in ("anthropic", "openai"):
        prov = "anthropic"

    if prov == "openai":
        return _prompt_to_settings_openai(user_prompt)
    return _prompt_to_settings_anthropic(user_prompt)


def _prompt_to_settings_anthropic(user_prompt: str) -> dict:
    api_key = _find_api_key()
    if not api_key:
        raise RuntimeError(
            "No Anthropic API key found.\n\n"
            "Create a file called  .env  in your project folder containing:\n"
            "  ANTHROPIC_API_KEY=sk-ant-YOUR-KEY-HERE\n\n"
            "Get your key at: https://console.anthropic.com"
        )

    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "The 'anthropic' package is not installed.\n"
            "Run:  pip install anthropic"
        )

    try:
        return _anthropic_messages_to_settings(user_prompt, api_key)
    except anthropic.AuthenticationError:
        raise RuntimeError(
            "Anthropic API key was rejected (401 authentication error).\n\n"
            "Try:\n"
            "  • Revoke the key and create a new one at:\n"
            "    https://console.anthropic.com/api-keys\n"
            "  • One line in .env: ANTHROPIC_API_KEY=sk-ant-... (no spaces around =)\n"
            "  • Only one ANTHROPIC_API_KEY line; save as UTF-8.\n"
            "  • If Windows has ANTHROPIC_API_KEY set, it overrides .env — clear or fix it.\n"
            "  • Restart the app after changing .env.\n"
        )
    except Exception as exc:
        log.error("Anthropic LLM call failed: %s", exc)
        _agent_log(
            "H1", "llm_bridge:_prompt_to_settings_anthropic", "exception_fallback",
            {
                "exc_type": type(exc).__name__,
                "exc_snip": str(exc)[:280],
                "using_heuristic_fallback": True,
            })

        _fb = _heuristic_fallback_settings(user_prompt)
        return _merge_prompt_roomtypes(user_prompt, _fb, _coerce_settings(_fb))


def _prompt_to_settings_openai(user_prompt: str) -> dict:
    api_key = _find_openai_api_key()
    if not api_key:
        raise RuntimeError(
            "No OpenAI API key found.\n\n"
            "Add to your .env in the project folder:\n"
            "  OPENAI_API_KEY=sk-YOUR-KEY-HERE\n\n"
            "Get a key at: https://platform.openai.com/api-keys"
        )

    try:
        return _openai_chat_to_settings(user_prompt, api_key)
    except ImportError as exc:
        # Missing package: ``from openai import OpenAI`` inside _openai_chat_to_settings
        if getattr(exc, "name", None) == "openai":
            raise RuntimeError(
                "The 'openai' package is not installed.\n"
                "Run:  pip install openai"
            ) from exc
        raise
    except Exception as exc:
        try:
            import openai

            auth_err = openai.AuthenticationError
        except (ImportError, AttributeError):
            auth_err = ()
        if auth_err and isinstance(exc, auth_err):
            raise RuntimeError(
                "OpenAI API key was rejected (authentication error).\n\n"
                "Try:\n"
                "  • Create a new key at: https://platform.openai.com/api-keys\n"
                "  • One line in .env: OPENAI_API_KEY=sk-... (no spaces around =)\n"
                "  • Restart the app after changing .env.\n"
            ) from exc
        log.error("OpenAI LLM call failed: %s", exc)
        _agent_log(
            "H1", "llm_bridge:_prompt_to_settings_openai", "exception_fallback",
            {
                "exc_type": type(exc).__name__,
                "exc_snip": str(exc)[:280],
                "using_heuristic_fallback": True,
            })

        _fb = _heuristic_fallback_settings(user_prompt)
        return _merge_prompt_roomtypes(user_prompt, _fb, _coerce_settings(_fb))
