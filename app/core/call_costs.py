"""Explicit user-supplied linear prices; unknown usage is never free."""
from app.core.routing_utility import nonnegative


def summarize_costs(audit, prices):
    if not isinstance(prices, dict):
        raise ValueError("Prices must map model IDs to per-million token rates")
    for price in prices.values():
        if set(price) != {"input_per_million", "output_per_million", "currency"} or not all(
                nonnegative(price[k]) for k in ("input_per_million", "output_per_million")) or not price["currency"]:
            raise ValueError("Invalid token price")
    currencies = {p["currency"] for p in prices.values()}
    if len(currencies) > 1:
        raise ValueError("Use one currency per experiment")
    calls = []
    for row in audit:
        price, usage = prices.get(row["model"]), row.get("usage")
        cost = None
        if price is not None and usage is not None:
            cost = (usage["prompt_tokens"] * price["input_per_million"] + usage["completion_tokens"] * price["output_per_million"]) / 1_000_000
        calls.append({"model": row["model"], "status": row["status"], "cost": cost,
                      "latency_seconds": row.get("latency_seconds"), "usage": usage})
    known = [r["cost"] for r in calls if r["cost"] is not None]
    return {"calls": calls, "known_cost": sum(known), "total_cost": sum(known) if len(known) == len(calls) else None,
            "unpriced_calls": len(calls) - len(known), "failed_calls": sum(r["status"] == "error" for r in calls),
            "currency": next(iter(currencies), None), "pricing_model": "user_declared_linear_tokens"}
