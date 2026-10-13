"""Pick the best five from the shortlist and give each a one-line reason (staff only)."""

import re

from apps.ai.client import AiUnavailable, ai_enabled, complete_json

from .budget import price_ceiling_pence
from .search import DIFFERENT_COLOUR, DIFFERENT_MODEL, OVER_BUDGET

PROMPT_VERSION = "rerank-v1"
OPTIONS = 5
FORBIDDEN = re.compile(r"£|\bapr\b|per month|a month|monthly|finance|payment|deposit|\bavailable\b|\bends?\b", re.I)

SYSTEM = """You help a UK car dealer's salesperson choose which cars to offer a customer.
You get the customer's request and a numbered shortlist that already passed the hard checks.
Return JSON only: {"picks": [{"n": <shortlist number>, "reason": "<one short line>"}]}
- The shortlist is already in our best-first order. Keep that order unless a car lower down clearly fits
  what was asked for better (body style, fuel, trim, use).
- Pick the best 5 (or all of them if there are fewer), best first.
- Prefer cars with no warnings; among those, the closest fit to the request, then newer and lower mileage.
- The reason is at most 12 words on why it fits (model, colour, gearbox, age, mileage, body).
- Never mention prices, budgets, finance, payments or when the car is available."""


def rule_reason(candidate, requirement):
    car = candidate.listing
    parts = []
    if requirement.colours:
        parts.append(f"{car.colour.title()} as asked" if DIFFERENT_COLOUR not in candidate.flags
                     else f"{car.colour.title() or 'Colour unknown'} (not the colour asked for)")
    elif car.colour:
        parts.append(car.colour.title())
    if car.gearbox_kind:
        parts.append("automatic" if car.gearbox_kind == "auto" else "manual")
    if car.year:
        parts.append(str(car.year))
    if car.mileage is not None:
        parts.append(f"{car.mileage:,} miles")
    ceiling = price_ceiling_pence(requirement)
    if OVER_BUDGET in candidate.flags:
        parts.append(f"£{(car.suggested_price_pence - ceiling) / 100:,.0f} over budget")
    elif ceiling:
        parts.append("within budget")
    if DIFFERENT_MODEL in candidate.flags:
        parts.append("different model")
    return ", ".join(parts)


def describe(number, candidate):
    car = candidate.listing
    warnings = f" | warnings: {', '.join(candidate.flags)}" if candidate.flags else ""
    return (f"{number}. {car.make} {car.model} {car.trim} | {car.year or '?'} | "
            f"{car.mileage if car.mileage is not None else '?'} miles | {car.colour or '?'} | "
            f"{car.gearbox or '?'} | {car.fuel or '?'} | {car.body or '?'}{warnings}")


def ai_picks(requirement, candidates):
    request = (f"Request: {requirement.make} {requirement.model}".strip()
               + f" | colours: {', '.join(requirement.colours) or 'any'}"
               + f" | gearbox: {requirement.get_gearbox_display()}"
               + (f" | needed by: {requirement.needed_by}" if requirement.needed_by else "")
               + (f"\nIn the salesperson's words: {requirement.notes[:400]}" if requirement.notes else ""))
    shortlist = "\n".join(describe(n, c) for n, c in enumerate(candidates, 1))
    data = complete_json("rerank", PROMPT_VERSION, SYSTEM, f"{request}\n\nShortlist:\n{shortlist}")
    picks, seen = [], set()
    for pick in (data.get("picks") if isinstance(data, dict) else None) or []:
        number = pick.get("n") if isinstance(pick, dict) else None
        if not isinstance(number, int) or not 1 <= number <= len(candidates) or number in seen:
            continue  # the AI may only choose from the shortlist it was given
        seen.add(number)
        reason = str(pick.get("reason") or "").strip()[:255]
        if not reason or FORBIDDEN.search(reason):
            reason = ""  # a reason that talks money or availability is replaced by ours
        picks.append((candidates[number - 1], reason))
    if not picks:
        raise AiUnavailable("AI returned no usable picks.")
    return picks[:OPTIONS]


def choose(requirement, candidates):
    """([(candidate, reason)], used_ai): the options to show, best first."""
    if not candidates:
        return [], False
    used_ai = False
    picks = [(c, "") for c in candidates[:OPTIONS]]
    if ai_enabled() and len(candidates) > 1 and not requirement.sort:
        try:
            picks, used_ai = ai_picks(requirement, candidates), True
            chosen = [c for c, _ in picks]
            picks += [(c, "") for c in candidates if c not in chosen][:OPTIONS - len(picks)]
        except AiUnavailable:
            pass
    return [(c, reason or rule_reason(c, requirement)) for c, reason in picks], used_ai
