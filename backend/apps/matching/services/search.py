"""Find the cars that fit a requirement. Hard rules here; AI only ever ranks inside what this returns."""

from dataclasses import dataclass, field

from django.db.models import Q
from django.utils import timezone

from apps.core.services import get_setting
from apps.listings.models import Listing
from apps.listings.services.embedding import embed_query, similarities
from apps.listings.services.keys import make_key, model_matches

from .budget import price_ceiling_pence

OVER_BUDGET = "over_budget"
DIFFERENT_MODEL = "different_model"
DIFFERENT_COLOUR = "different_colour"
SHORTLIST = 20


SIMILARITY_WEIGHT = 45  # the closest car in the set gets this many points; colour is 30, age and mileage 20 each
DESCRIBED_WELL = 0.30  # a request with no make or budget is searched only if some car is at least this similar


@dataclass
class Candidate:
    listing: Listing
    score: float
    flags: list = field(default_factory=list)
    similarity: float | None = None  # None when vector search was not used for this car


def available_stock(now=None):
    """Cars that may be offered: still live, fully captured, priced and not past their end time."""
    now = now or timezone.now()
    return Listing.objects.filter(
        Q(ends_at__isnull=True) | Q(ends_at__gt=now),
        status__in=Listing.LIVE_STATUSES,
        details_status=Listing.DetailsStatus.COMPLETE,
        suggested_price_pence__isnull=False,
    )


def score(listing, requirement, now):
    """Higher is better, among cars that already passed the hard filters."""
    points = 0.0
    if requirement.colours and listing.colour_key in requirement.colours:
        points += 30
    if listing.year:
        points += max(0, min(20, (listing.year - (now.year - 12)) * 2))
    if listing.mileage is not None:
        points += max(0.0, 20 - listing.mileage / 5000)
    if listing.photo_count:
        points += 5
    return round(points, 2)


# How cars are ordered inside a tier. Exact matches always come before widened ones.
ORDERS = {
    "": lambda c: -c.score,
    "price": lambda c: c.listing.suggested_price_pence,
    "year": lambda c: -(c.listing.year or 0),
    "mileage": lambda c: c.listing.mileage if c.listing.mileage is not None else 10 ** 9,
}


def relative(similar):
    """Raw similarities sit in a narrow band, so spread them 0..1 across this set of cars."""
    if not similar:
        return {}
    low, high = min(similar.values()), max(similar.values())
    if high - low < 0.02:  # nothing to tell the cars apart
        return {key: 0.5 for key in similar}
    return {key: (value - low) / (high - low) for key, value in similar.items()}


def described(candidates):
    """Did a request with no make or budget ('a diesel van for work') describe a car we have?"""
    return any(c.similarity is not None and c.similarity >= DESCRIBED_WELL for c in candidates)


def once_per_car(candidates):
    """A platform can list the same car twice (relisted under a new number): keep its best-placed listing."""
    seen, unique = set(), []
    for candidate in candidates:
        plate = "".join(candidate.listing.registration.split()).upper()
        if plate and plate in seen:
            continue
        seen.add(plate)
        unique.append(candidate)
    return unique


def find(requirement, now=None):
    """(candidates, notes): up to 20 cars, best first, and plain-language notes on anything relaxed.

    Never relaxed: live status, the end time, and auto/manual. If nothing fits exactly it widens in
    this order, flagging each car: a little over budget, then other models of the same make.
    """
    now = now or timezone.now()
    stock = available_stock(now)
    if requirement.gearbox:
        stock = stock.filter(gearbox_kind=requirement.gearbox)
    if requirement.make:
        stock = stock.filter(make_key=make_key(requirement.make))
    cars = list(stock)
    other_colours = 0
    if requirement.colour_only and requirement.colours:  # "only grey": other colours are not shown at all
        wanted_colour = [c for c in cars if c.colour_key in requirement.colours]
        other_colours, cars = len(cars) - len(wanted_colour), wanted_colour
    right_model = [c for c in cars if model_matches(requirement.model, c.model, c.trim)]
    other_model = [c for c in cars if c not in right_model] if requirement.make else []

    ceiling = price_ceiling_pence(requirement)
    stretch = ceiling * (100 + get_setting("chat_over_budget_percent")) / 100 if ceiling else None

    def within(listing, limit):
        return limit is None or listing.suggested_price_pence <= limit

    tiers = [
        ([c for c in right_model if within(c, ceiling)], []),
        ([c for c in right_model if not within(c, ceiling) and within(c, stretch)], [OVER_BUDGET]),
        ([c for c in other_model if within(c, ceiling)], [DIFFERENT_MODEL]),
    ]
    # Vectors rank INSIDE each tier only: every car below has already passed the hard filters.
    survivors = [c.id for listings, _ in tiers for c in listings]
    similar = similarities(survivors, embed_query(requirement.search_text)) if survivors else {}
    closeness = relative(similar)

    candidates = []
    for listings, flags in tiers:
        tier = []
        for listing in listings:
            car_flags = list(flags)
            if requirement.colours and listing.colour_key not in requirement.colours:
                car_flags.append(DIFFERENT_COLOUR)
            similarity = similar.get(listing.id)
            points = score(listing, requirement, now) + closeness.get(listing.id, 0) * SIMILARITY_WEIGHT
            tier.append(Candidate(listing, round(points, 2), car_flags, similarity))
        candidates += sorted(tier, key=ORDERS.get(requirement.sort, ORDERS[""]))
    candidates = once_per_car(candidates)[:SHORTLIST]

    notes = []
    wanted = f"{requirement.make} {requirement.model}".strip() or "that budget"
    colour = "/".join(requirement.colours)
    if not candidates and other_colours:
        notes.append(f"There are no {colour} ones, but {other_colours} in other colours. Tap “Any colour” to see them.")
    elif not candidates:
        notes.append(why_nothing(requirement, now, ceiling))
    elif not tiers[0][0]:
        if tiers[1][0]:
            notes.append(f"Nothing for {wanted} inside the budget, so these are a little over it.")
        else:
            notes.append(f"No {wanted} available right now, so these are other {requirement.make} models.")
    if candidates and other_colours:
        notes.append(f"Showing {colour} only. {other_colours} more in other colours are hidden.")
    return candidates, notes


def why_nothing(requirement, now, ceiling):
    """Which rule removed everything, so the salesperson knows what to change."""
    stock = available_stock(now)
    if not stock.exists():
        return "There are no live, priced cars in the database right now. Run a scrape or sync first."
    if requirement.make:
        stock = stock.filter(make_key=make_key(requirement.make))
        if not stock.exists():
            return f"There are no live {requirement.make} cars at the moment."
    if requirement.gearbox:
        stock = stock.filter(gearbox_kind=requirement.gearbox)
        if not stock.exists():
            label = "automatic" if requirement.gearbox == "auto" else "manual"
            return f"There are no live {label} {requirement.make or 'cars'} at the moment.".replace("  ", " ")
    if ceiling:
        cheapest = min(stock.values_list("suggested_price_pence", flat=True))
        return (f"Nothing fits the budget (about £{ceiling / 100:,.0f}). "
                f"The cheapest car that otherwise fits is £{cheapest / 100:,.0f}.")
    return "Nothing matches that request at the moment."
