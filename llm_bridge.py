"""
llm_bridge.py – Translates a natural-language prompt into packing weights.

Uses the Anthropic API (claude-sonnet-4-20250514).
If the API key is not set, falls back to default weights silently.

Usage
-----
    from llm_bridge import prompt_to_weights
    weights = prompt_to_weights("More bedrooms in the north, tea room near entrance")
"""

from __future__ import annotations
import json
import os
import logging
from typing import Dict

from config import DEFAULT_WEIGHTS

log = logging.getLogger(__name__)


_SYSTEM_PROMPT = """
You are a hotel floor-plan design assistant.

The user will describe what they want in a hotel floor plan in natural language.
Your job is to output ONLY a JSON object (no markdown, no extra text) with the
following keys and float values that represent relative weights for the random
packing algorithm:

  BedroomA, BedroomB, BedroomC, BedroomD,
  TeaRoom1, TeaRoom2, Library, ReadingRoom

Rules:
- All values must be non-negative floats.
- They do not need to sum to 1 (the caller normalises them).
- Use 0.0 to exclude a room type completely.
- Use higher values (e.g. 3.0–5.0) to make a type much more common.
- Default weight for each type is 1.0.
- Only output raw JSON – no code fences, no prose.

Example input: "mostly bedrooms, no library"
Example output: {"BedroomA":3,"BedroomB":3,"BedroomC":2,"BedroomD":2,"TeaRoom1":1,"TeaRoom2":1,"Library":0,"ReadingRoom":1}
""".strip()


def prompt_to_weights(user_prompt: str) -> Dict[str, float]:
    """
    Call the Anthropic API and parse the response as a weights dict.
    Returns DEFAULT_WEIGHTS on any error.
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        log.warning("ANTHROPIC_API_KEY not set – using default weights.")
        return DEFAULT_WEIGHTS.copy()

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=256,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_prompt}],
        )
        raw = message.content[0].text.strip()
        weights = json.loads(raw)

        # Validate: all expected keys present, values are numbers
        cleaned: Dict[str, float] = {}
        for key in DEFAULT_WEIGHTS:
            val = weights.get(key, DEFAULT_WEIGHTS[key])
            cleaned[key] = max(0.0, float(val))

        return cleaned

    except Exception as exc:
        log.error("LLM call failed: %s – using default weights.", exc)
        return DEFAULT_WEIGHTS.copy()
