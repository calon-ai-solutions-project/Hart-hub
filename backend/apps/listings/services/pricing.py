from apps.core.services import get_setting


def price_listing(listing):
    """Fill prep cost and suggested selling price (in place, not saved).

    customer price = platform (buy) price + the markup setting. A price a person has set is kept.
    Prep cost is recorded for the margin shown to staff (margin = price - buy price - prep cost).
    """
    if listing.prep_cost_pence is None:
        listing.prep_cost_pence = get_setting("prep_cost_pence")
    if listing.price_overridden:
        return listing
    if listing.buy_price_pence is None:
        listing.suggested_price_pence = None
    else:
        listing.suggested_price_pence = listing.buy_price_pence + get_setting("markup_pence")
    return listing
