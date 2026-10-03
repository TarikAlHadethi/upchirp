"""Token prices and per-answer cost, shared by the benchmark and the public demo's daily cap.

Prices are US dollars per million tokens (input, output) from Anthropic's price
list. Bedrock regional (eu.) profiles may cost slightly more; the daily cap uses
these as an estimate and the AWS budget alarm is the backstop.
"""

import re
from collections.abc import Iterable
from typing import Any

PRICES_PER_MTOK = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0)}


def base_model(model_id: str) -> str:
    """'eu.anthropic.claude-opus-5-5-v1:0' -> 'claude-opus-5-5'."""
    name = model_id.split("anthropic.", 1)[-1] if "anthropic." in model_id else model_id
    return re.sub(r"(-\d{8})?(-v\d+(:\d+)?)?$", "", name)


def is_paid(model_id: str) -> bool:
    """Hosted Claude models cost money per answer; local Ollama models do not."""
    return "claude" in model_id or "anthropic" in model_id


def tokens(messages: Iterable[Any]) -> tuple[int, int]:
    """Total (input, output) tokens over a conversation's AI messages."""
    inp = out = 0
    for m in messages:
        usage = getattr(m, "usage_metadata", None) or {}
        inp += int(usage.get("input_tokens", 0))
        out += int(usage.get("output_tokens", 0))
    return inp, out


def cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float:
    if not is_paid(model_id):
        return 0.0  # local model: no money per answer
    # an unknown paid model is charged at the highest known price, so the cap never fails open
    price = PRICES_PER_MTOK.get(base_model(model_id), max(PRICES_PER_MTOK.values()))
    return (input_tokens * price[0] + output_tokens * price[1]) / 1e6
