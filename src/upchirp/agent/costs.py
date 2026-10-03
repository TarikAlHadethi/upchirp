"""Token prices and per-answer cost, shared by the benchmark and the public demo's daily cap.

Prices are US dollars per million tokens (input, output) from Anthropic's price
list. Bedrock regional (eu.) profiles may cost slightly more; the daily cap uses
these as an estimate and the AWS budget alarm is the backstop.
"""

from collections.abc import Iterable
from typing import Any

PRICES_PER_MTOK = {"claude-opus-5-5": (4.0, 20.0), "claude-sonnet-5-5": (2.0, 10.0)}


def base_model(model_id: str) -> str:
    """'eu.anthropic.claude-opus-5-5' -> 'claude-opus-5-5'."""
    return model_id.rsplit(".", 1)[-1] if "anthropic." in model_id else model_id


def tokens(messages: Iterable[Any]) -> tuple[int, int]:
    """Total (input, output) tokens over a conversation's AI messages."""
    inp = out = 0
    for m in messages:
        usage = getattr(m, "usage_metadata", None) or {}
        inp += int(usage.get("input_tokens", 0))
        out += int(usage.get("output_tokens", 0))
    return inp, out


def cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float:
    price = PRICES_PER_MTOK.get(base_model(model_id))
    if price is None:
        return 0.0  # local model: no money per answer
    return (input_tokens * price[0] + output_tokens * price[1]) / 1e6
