from apps.core.services import get_setting


def price_listing(listing):
    """Fill prep cost and suggested selling price (in place, not saved).

    suggested price = buy price + prep cost + target margin. A price a person has set is kept.
    """
    if listing.prep_cost_pence is None:
        listing.prep_cost_pence = get_setting("prep_cost_pence")
    if listing.price_overridden:
        return listing
    if listing.buy_price_pence is None:
        listing.suggested_price_pence = None
    else:
        listing.suggested_price_pence = (
            listing.buy_price_pence + listing.prep_cost_pence + get_setting("target_margin_pence")
        )
    return listing
