"""Codeweavers JSON Finance API: the same quotes as the Showroom, for many cars in about a second.

POST {CODEWEAVERS_API_URL}/public/v3/jsonfinance/calculate, signed in with Hart's Codeweavers login
(HTTP basic auth). Checked against the Showroom on real cars: identical monthly, final payment, APR
and total payable. Every answer is still checked against what was asked before it is kept.

What the API does not give: the customer quote document (PDF). Quotes made here have no PDF.
"""

import html
import logging
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation

import requests
from django.conf import settings

from .codeweavers import CodeweaversUnavailable, QuoteError, family_of, pence, plate

logger = logging.getLogger(__name__)

CALCULATE = "/public/v3/jsonfinance/calculate"
TERMS = "/api/finance/quote/{reference}/termsandconditions"
FAMILY_NAMES = {"PCP": "Personal Contract Purchase", "HP": "Hire Purchase"}
TIMEOUT = 60


def configured():
    return bool(settings.CODEWEAVERS_USERNAME and settings.CODEWEAVERS_PASSWORD)


def _post(body):
    try:
        response = requests.post(settings.CODEWEAVERS_API_URL + CALCULATE, json=body, timeout=TIMEOUT,
                                 auth=(settings.CODEWEAVERS_USERNAME, settings.CODEWEAVERS_PASSWORD))
    except requests.RequestException as e:
        raise CodeweaversUnavailable(f"Could not reach the Codeweavers API ({type(e).__name__}).") from e
    if response.status_code in (401, 403):
        raise CodeweaversUnavailable("Codeweavers refused the Hub's login for its API.")
    if response.status_code >= 400:
        message = ""
        try:
            message = (response.json().get("Error") or {}).get("UserMessage") or ""
        except ValueError:
            pass
        raise CodeweaversUnavailable(f"The Codeweavers API answered {response.status_code}. {message}".strip())
    return response.json()


def lender_from_terms(reference):
    """'Finance is provided by MotoNovo Finance Limited, ...' -> 'MotoNovo Finance'. Empty if unknown."""
    if not reference:
        return ""
    try:
        response = requests.get(settings.CODEWEAVERS_API_URL + TERMS.format(reference=reference), timeout=TIMEOUT,
                                auth=(settings.CODEWEAVERS_USERNAME, settings.CODEWEAVERS_PASSWORD))
        text = response.json().get("TermsAndConditions") or "" if response.ok else ""
    except (requests.RequestException, ValueError):
        return ""
    found = re.search(r"provided by (.+?)(?: Limited| Ltd| plc|,)", text)
    return found.group(1).strip() if found else ""


def _money(value):
    return pence(value)


def check(request, quote):
    """Refuse an answer that is not for exactly the deal asked for."""
    problems = []
    if quote.get("Term") != request.term_months:
        problems.append(f"{quote.get('Term')} months")
    if _money(quote.get("CashPrice")) != request.cash_price_pence:
        problems.append(f"price {quote.get('CashPrice')}")
    if _money(quote.get("TotalDeposit", quote.get("Deposit"))) != request.deposit_pence:
        problems.append(f"deposit {quote.get('TotalDeposit')}")
    if quote.get("AnnualMileage") not in (None, request.annual_mileage):
        problems.append(f"{quote.get('AnnualMileage')} miles a year")
    if problems:
        raise QuoteError("Codeweavers calculated something different from what was asked ("
                         + ", ".join(problems) + "), so the quote was not used.")


def to_fields(request, family, quote):
    """One API quote -> the fields of a Quote, in the same shape as the Showroom route."""
    check(request, quote)
    monthly = _money(quote.get("RegularPayment"))
    if not monthly:
        raise QuoteError("Codeweavers returned no monthly payment.")
    try:
        apr = Decimal(str(quote.get("Apr")))
    except InvalidOperation:
        apr = None
    fees = "; ".join(html.unescape(str(fee.get("DisplayText") or "")) for fee in quote.get("Fees") or [])
    reference = str(quote.get("QuoteReference") or "")
    lender = lender_from_terms(reference)
    asked_kind = family_of(request.product)
    product = request.product if family == asked_kind else (request.fallback_product or family)
    if lender and family_of(product) == family:
        product = f"({lender}) {family}"
    return {
        "monthly_pence": monthly,
        "final_payment_pence": _money(quote.get("FinalPayment")),
        "balloon_pence": (_money(quote.get("Residual")) or None) if family == "PCP" else None,
        "apr": apr,
        "amount_of_credit_pence": _money(quote.get("AmountOfCredit")),
        "charges_pence": _money(quote.get("TotalChargeForCredit")),
        "total_payable_pence": _money(quote.get("TotalAmountPayable")),
        "fees_text": fees[:255],
        "product_family": FAMILY_NAMES[family],
        "quote_ref": reference[:64],
        "annual_mileage_applied": quote.get("AnnualMileage") == request.annual_mileage,
        "product_quoted": product,
        "raw": {"source": "api"} | {key: quote.get(key) for key in (
            "RegularPayment", "FinalPayment", "Apr", "RateOfInterest", "TotalAmountPayable", "TotalChargeForCredit",
            "AmountOfCredit", "CashPrice", "TotalDeposit", "Term", "AnnualMileage", "Residual", "Fees", "Payments",
            "NumberOfRegularPayments", "ExcessMileageRate", "QuoteReference", "ValidTo")},
    }


def pick(request, results):
    """(family, quote) to use: the asked-for kind (PCP) if it quoted, else the fallback kind (HP)."""
    by_family = {str(r.get("Key") or "").upper(): r for r in results}
    order = [family_of(request.product)] + ([family_of(request.fallback_product)] if request.fallback_product else [])
    reasons = []
    for family in [f for f in order if f]:
        result = by_family.get(family)
        if result and not result.get("HasError") and result.get("Quote"):
            return family, result["Quote"]
        reasons.append(((result or {}).get("Error") or {}).get("DealerMessage") or f"no {family} product")
    raise QuoteError(re.sub(r"<[^>]+>", "", "; ".join(dict.fromkeys(reasons)) or "Codeweavers could not quote this car.")[:250])


def get_quotes(quote_requests, on_result):
    """Quote every request, calling on_result(request, fields, error) for each, like the Showroom route.

    Requests with the same deal (term, deposit, mileage, credit tier) go in one API call.
    """
    if not configured():
        raise CodeweaversUnavailable("Codeweavers login is not set (CODEWEAVERS_USERNAME and _PASSWORD).")
    groups = defaultdict(list)
    for request in quote_requests:
        families = tuple(f for f in (family_of(request.product), family_of(request.fallback_product)) if f)
        groups[(request.term_months, request.deposit_pence, request.annual_mileage, request.credit_tier,
                families)].append(request)
    for (term, deposit, annual, tier, families), group in groups.items():
        body = {
            "Parameters": {"Term": term, "Deposit": deposit / 100, "DepositType": "Amount", "AnnualMileage": annual,
                           "CustomerSelectedCreditTier": tier or "Excellent",
                           "FinanceProductFamilyKeys": list(families) or ["PCP", "HP"], "ReturnErrors": True},
            "VehicleRequests": [{"Id": str(i), "Vehicle": {
                "CashPrice": r.cash_price_pence / 100, "RegistrationNumber": plate(r.registration),
                "CurrentMileage": r.mileage, "CurrentMileageUnit": "Miles",
                "Type": "LCV" if r.vehicle_type == "LCV" else "Car", "VehicleStatus": "PreOwned"}}
                for i, r in enumerate(group)],
        }
        answer = _post(body)
        answered = {str(v.get("Id")): v for v in answer.get("VehicleResults") or []}
        for i, request in enumerate(group):
            vehicle = answered.get(str(i))
            try:
                if vehicle is None:
                    raise QuoteError("Codeweavers returned nothing for this car.")
                if vehicle.get("HasError"):
                    message = (vehicle.get("Error") or {}).get("DealerMessage") or "Codeweavers could not quote this car."
                    raise QuoteError(re.sub(r"<[^>]+>", "", message)[:250])
                family, quote = pick(request, vehicle.get("FinanceProductResults") or [])
                fields = to_fields(request, family, quote)
            except QuoteError as error:
                on_result(request, None, error)
                continue
            on_result(request, fields, None)
