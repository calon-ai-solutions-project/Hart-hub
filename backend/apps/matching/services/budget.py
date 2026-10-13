from apps.core.services import get_setting


def price_ceiling_pence(requirement):
    """The dearest car worth showing for this budget, or None when no budget was given.

    A cash budget is used as it is. A monthly budget is turned into a price with the APR and term in
    settings. This is a rough guide for FILTERING ONLY: it is never a finance quote and is never
    shown to a customer. Real figures come from Codeweavers.
    """
    if requirement.max_price_pence:
        return requirement.max_price_pence
    if not requirement.monthly_budget_pence:
        return None
    months = int(get_setting("finance_estimate_term_months"))
    monthly_rate = float(get_setting("finance_estimate_apr_percent")) / 100 / 12
    if monthly_rate <= 0:
        borrowed = requirement.monthly_budget_pence * months
    else:
        borrowed = requirement.monthly_budget_pence * (1 - (1 + monthly_rate) ** -months) / monthly_rate
    return int(borrowed) + (requirement.deposit_pence or 0)


def ceiling_note(requirement):
    """One line for staff explaining the ceiling."""
    ceiling = price_ceiling_pence(requirement)
    if ceiling is None:
        return "No budget given, so price was not used."
    if requirement.max_price_pence:
        return f"Budget: up to £{ceiling / 100:,.0f}."
    deposit = f" + £{requirement.deposit_pence / 100:,.0f} deposit" if requirement.deposit_pence else ""
    return (f"Budget: £{requirement.monthly_budget_pence / 100:,.0f} a month{deposit}, so cars up to about "
            f"£{ceiling / 100:,.0f}. That is a rough guide ({get_setting('finance_estimate_apr_percent')}% APR over "
            f"{get_setting('finance_estimate_term_months')} months), not a quote.")
