"""
llm_bridge.py - Translates a natural-language prompt into packing weights.

API key lookup order (first match wins):
  1. Environment variable  ANTHROPIC_API_KEY
  2. A file called         .env  in the project folder  (KEY=value format)
  3. A file called         secrets.py  in the project folder

option 2: create file named  .env  containing:
    ANTHROPIC_API_KEY=sk-ant-...

option 3: create file named  secrets.py  containing:
    ANTHROPIC_API_KEY = "sk-ant-..."

Both .env and secrets.py are listed in .gitignore so they are never
committed to GitHub.
"""

from __future__ import annotations
import json
import logging
import os
import re
from typing import Dict

from config import DEFAULT_WEIGHTS

log = logging.getLogger(__name__)


_SYSTEM_PROMPT = """
You are a hotel floor-plan design assistant.

The user will describe what they want in a hotel floor plan in natural language.
Your job is to output ONLY a JSON object (no markdown, no extra text) with any
combination of the following keys:

"weights": object - relative frequencies for each room type (all default to 1.0)
  Keys: BedroomA, BedroomB, BedroomC, BedroomD (PRIVATE/bedroom rooms)
        TeaRoom1, TeaRoom2, Library, ReadingRoom  (PUBLIC/communal rooms)
  Use 0.0 to exclude a type, higher values (3-5) to make it more common.

"n_rooms": int - total number of rooms to place (default 10, range 2-24)
  Use fewer rooms for more open/spacious layouts.

"pad": int - padding in pixels between rooms (default 30, range 0-80)
  Higher values = more open space between rooms.

"n_bushes": int - number of bushes/greenery elements (default 30, range 0-80)
  Use higher values for more greenery, 0 for none.

"spatial": string - spatial arrangement of room types, one of:
  "mixed"           - no spatial constraint (default)
  "bedrooms_top"    - bedrooms placed in top half, public rooms in bottom half
  "bedrooms_bottom" - bedrooms placed in bottom half, public rooms in top half
  "bedrooms_left"   - bedrooms placed in left half, public rooms in right half
  "bedrooms_right"  - bedrooms placed in right half, public rooms in left half

Rules:
- Only include keys that are relevant to the user's request.
- Always include "weights".
- Only output raw JSON - no code fences, no prose.

Examples:

Input: "mostly bedrooms, no library"
Output: {"weights":{"BedroomA":3,"BedroomB":3,"BedroomC":2,"BedroomD":2,"TeaRoom1":1,"TeaRoom2":1,"Library":0,"ReadingRoom":1}}

Input: "public rooms only"
Output: {"weights":{"BedroomA":0,"BedroomB":0,"BedroomC":0,"BedroomD":0,"TeaRoom1":2,"TeaRoom2":2,"Library":2,"ReadingRoom":2}}

Input: "more greenery and open space"
Output: {"weights":{"BedroomA":1,"BedroomB":1,"BedroomC":1,"BedroomD":1,"TeaRoom1":1,"TeaRoom2":1,"Library":1,"ReadingRoom":1},"n_bushes":70,"pad":60}

Input: "place bedrooms on the bottom, public rooms on the top"
Output: {"weights":{"BedroomA":1,"BedroomB":1,"BedroomC":1,"BedroomD":1,"TeaRoom1":1,"TeaRoom2":1,"Library":1,"ReadingRoom":1},"spatial":"bedrooms_bottom"}

Input: "sparse layout with mostly public rooms and lots of greenery"
Output: {"weights":{"BedroomA":0.5,"BedroomB":0.5,"BedroomC":0.5,"BedroomD":0.5,"TeaRoom1":2,"TeaRoom2":2,"Library":2,"ReadingRoom":2},"n_rooms":6,"n_bushes":60,"pad":50}
""".strip()


def _find_api_key() -> str:
    """
    Look for the Anthropic API key in three places, in order:
      1. Environment variable
      2. .env file in the same directory as this file
      3. secrets.py in the same directory as this file
    Returns empty string if not found anywhere.
    """
    # 1. environment variable (set via export or .zshrc)
    key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if key:
        return key

    here = os.path.dirname(os.path.abspath(__file__))

    # 2. .env file  (lines like:  ANTHROPIC_API_KEY=sk-ant-...)
    env_path = os.path.join(here, ".env")
    if os.path.isfile(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY"):
                    match = re.split(r"\s*=\s*", line, maxsplit=1)
                    if len(match) == 2:
                        key = match[1].strip().strip('"').strip("'")
                        if key:
                            return key

    # 3. secrets.py  (line like:  ANTHROPIC_API_KEY = "sk-ant-...")
    secrets_path = os.path.join(here, "secrets.py")
    if os.path.isfile(secrets_path):
        with open(secrets_path) as f:
            for line in f:
                line = line.strip()
                if line.startswith("ANTHROPIC_API_KEY"):
                    match = re.split(r"\s*=\s*", line, maxsplit=1)
                    if len(match) == 2:
                        key = match[1].strip().strip('"').strip("'")
                        if key:
                            return key

    return ""


_VALID_SPATIAL = {
    "mixed", "bedrooms_top", "bedrooms_bottom", "bedrooms_left", "bedrooms_right"
}


def prompt_to_settings(user_prompt: str) -> dict:
    """
    Call the Anthropic API and parse the response into a settings dict:
      {
        "weights":  {room: float, ...},
        "n_bushes": int   (optional),
        "pad":      int   (optional),
        "n_rooms":  int   (optional),
        "spatial":  str   (optional),
      }
    Raises RuntimeError on auth failure. Returns defaults on other errors.
    """
    api_key = _find_api_key()

    if not api_key:
        raise RuntimeError(
            "No API key found.\n\n"
            "Create a file called  .env  in your project folder containing:\n"
            "  ANTHROPIC_API_KEY=sk-ant-YOUR-KEY-HERE\n\n"
            "Get your key at: console.anthropic.com"
        )

    try:
        import anthropic
    except ImportError:
        raise RuntimeError(
            "The 'anthropic' package is not installed.\n"
            "Run:  pip install anthropic"
        )

    try:
        client  = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=512,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = message.content[0].text.strip()
        raw = re.sub(r"```[a-z]*", "", raw).strip()
        raw = raw.strip("`").strip()
        print(f"[llm_bridge] raw response: {raw}")
        data = json.loads(raw)

        # --- weights ---
        raw_weights = data.get("weights", {})
        # handle flat format (old style) where keys are room names at top level
        if not raw_weights and any(k in data for k in DEFAULT_WEIGHTS):
            raw_weights = data
        cleaned_weights: Dict[str, float] = {}
        for key in DEFAULT_WEIGHTS:
            val = raw_weights.get(key, DEFAULT_WEIGHTS[key])
            cleaned_weights[key] = max(0.0, float(val))

        settings: dict = {"weights": cleaned_weights}

        # --- optional fields ---
        if "n_bushes" in data:
            settings["n_bushes"] = max(0, min(80, int(data["n_bushes"])))
        if "pad" in data:
            settings["pad"] = max(0, min(80, int(data["pad"])))
        if "n_rooms" in data:
            settings["n_rooms"] = max(2, min(24, int(data["n_rooms"])))
        if "spatial" in data and data["spatial"] in _VALID_SPATIAL:
            settings["spatial"] = data["spatial"]

        return settings

    except anthropic.AuthenticationError:
        raise RuntimeError(
            "API key was rejected (401 authentication error).\n\n"
            "Your key may be invalid or expired.\n"
            "Check it at: console.anthropic.com/api-keys"
        )
    except Exception as exc:
        log.error("LLM call failed: %s", exc)
        return {"weights": DEFAULT_WEIGHTS.copy()}
