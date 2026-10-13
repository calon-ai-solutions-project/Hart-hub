import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.core.files.base import ContentFile
from django.db import connection
from django.utils import timezone

from apps.core.services import emit_event, get_setting, uk_date
from apps.listings.models import Listing
from apps.matching.services.search import available_stock

from . import codeweavers
from .models import Quote
from .pdf import with_vehicle_image

logger = logging.getLogger(__name__)

MAX_CARS = 5
STUCK_AFTER = timedelta(minutes=10)


class CannotQuote(ValueError):
    """The request itself is wrong (no cars, too many, cars no longer available)."""


def money(pence):
    return f"£{pence / 100:,.2f}"


def apr_text(apr):
    """Decimal('9.90') -> '9.9', as Codeweavers shows it."""
    return None if apr is None else f"{apr.normalize():f}"


def inputs_for(listing, deposit_pence):
    """What is sent to Codeweavers for a car. Term, product and credit rating come from settings."""
    return {
        "registration": listing.registration.strip().upper(),
        "mileage": (listing.mileage or 0) + int(get_setting("codeweavers_extra_mileage")),
        "cash_price_pence": listing.suggested_price_pence,
        "deposit_pence": deposit_pence,
        "term_months": int(get_setting("codeweavers_term_months")),
        "annual_mileage": int(get_setting("codeweavers_annual_mileage")),
        "product": get_setting("codeweavers_product"),
        "credit_tier": get_setting("codeweavers_credit_tier"),
    }


def request_quotes(user, listing_ids, deposit_pence=0, conversation=None):
    """Ask Codeweavers for a quote on each chosen car. Returns the Quote rows straight away;
    the quotes themselves arrive in the background.

    A car quoted today with exactly the same inputs is not quoted again.
    """
    listing_ids = list(dict.fromkeys(listing_ids))
    if not listing_ids:
        raise CannotQuote("Choose at least one car.")
    if len(listing_ids) > MAX_CARS:
        raise CannotQuote(f"Choose up to {MAX_CARS} cars at a time.")
    listings = {listing.id: listing for listing in available_stock().filter(id__in=listing_ids)}
    if len(listings) != len(listing_ids):
        raise CannotQuote("One of those cars is no longer available, so it cannot be quoted.")
    deposit_pence = max(int(deposit_pence or 0), 0)

    quotes, to_run = [], []
    for listing_id in listing_ids:
        listing = listings[listing_id]
        inputs = inputs_for(listing, deposit_pence)
        if deposit_pence >= listing.suggested_price_pence:
            quotes.append(Quote.objects.create(
                listing=listing, requested_by=user, conversation=conversation, status=Quote.Status.FAILED,
                error="The deposit covers the whole price, so there is nothing to finance.",
                finished_at=timezone.now(), **inputs))
            continue
        if not inputs["registration"]:
            quotes.append(Quote.objects.create(
                listing=listing, requested_by=user, conversation=conversation, status=Quote.Status.FAILED,
                error="This car has no registration, so Codeweavers cannot look it up.",
                finished_at=timezone.now(), **inputs))
            continue
        same_today = [q for q in Quote.objects.filter(listing=listing, status=Quote.Status.DONE, **inputs)[:5]
                      if uk_date(q.created_at) == uk_date() and q.pdf]  # one without its document is fetched again
        if same_today:
            quotes.append(same_today[0])
            continue
        quote = Quote.objects.create(listing=listing, requested_by=user, conversation=conversation, **inputs)
        quotes.append(quote)
        to_run.append(quote.id)
    if to_run:
        start_run(to_run)
    return quotes


def start_run(quote_ids):
    """With a worker the job is queued; without one (local development) it runs on a thread."""
    if settings.CELERY_TASK_ALWAYS_EAGER:
        threading.Thread(target=_run_on_thread, args=(quote_ids,), daemon=True).start()
    else:
        from .tasks import run_quotes as task

        task.delay([str(quote_id) for quote_id in quote_ids])


def _run_on_thread(quote_ids):
    try:
        run_quotes(quote_ids)
    finally:
        connection.close()


def vehicle_type(listing):
    return "LCV" if "van" in f"{listing.body} {listing.model}".lower() else "Car"


def run_quotes(quote_ids):
    """Get the waiting quotes from Codeweavers, one browser session for all of them."""
    quotes = list(Quote.objects.filter(id__in=quote_ids, status=Quote.Status.PENDING).select_related("listing"))
    if not quotes:
        return
    Quote.objects.filter(id__in=[q.id for q in quotes]).update(status=Quote.Status.RUNNING)
    by_request = {}
    for quote in quotes:
        request = codeweavers.QuoteRequest(
            registration=quote.registration, mileage=quote.mileage, cash_price_pence=quote.cash_price_pence,
            deposit_pence=quote.deposit_pence, term_months=quote.term_months,
            annual_mileage=quote.annual_mileage, product=quote.product,
            fallback_product=get_setting("codeweavers_fallback_product") or "",
            credit_tier=quote.credit_tier, vehicle_type=vehicle_type(quote.listing))
        by_request[id(request)] = (request, quote)

    def on_result(request, fields, error):
        quote = by_request[id(request)][1]
        if error is None:
            pdf = fields.pop("pdf", None)
            for name, value in fields.items():
                setattr(quote, name, value)
            if pdf:
                quote.pdf.save("quote.pdf", ContentFile(with_vehicle_image(pdf)), save=False)
            quote.status = Quote.Status.DONE
            quote.lender = codeweavers.lender_of(quote.product_quoted or quote.product)
            emit_event("quote.received", {"quote_id": str(quote.id), "listing_id": str(quote.listing_id)})
        else:
            quote.status, quote.error = Quote.Status.FAILED, str(error)[:255]
        quote.finished_at = timezone.now()
        quote.save()

    reason = ""
    try:
        codeweavers.get_quotes([request for request, _ in by_request.values()], on_result)
    except codeweavers.CodeweaversUnavailable as e:
        reason = str(e)
        logger.warning("Codeweavers unavailable: %s", e)
    except Exception:
        reason = "Something went wrong getting the quote."
        logger.exception("Quote run failed")
    finally:
        Quote.objects.filter(id__in=[q.id for q in quotes], status=Quote.Status.RUNNING).update(
            status=Quote.Status.FAILED, error=(reason or "Codeweavers did not return a quote.")[:255],
            finished_at=timezone.now())


def fail_stuck():
    """A quote left waiting (for example the server restarted mid-run) is closed so the screen can move on."""
    Quote.objects.filter(status__in=[Quote.Status.PENDING, Quote.Status.RUNNING],
                         created_at__lt=timezone.now() - STUCK_AFTER).update(
        status=Quote.Status.FAILED, error="The quote timed out. Please try again.", finished_at=timezone.now())


def example(quote):
    """The quote as one sentence, built by code from Codeweavers' figures (AI never writes finance wording)."""
    if quote.status != Quote.Status.DONE:
        return ""
    regular = quote.term_months - 1 if quote.final_payment_pence not in (None, quote.monthly_pence) else quote.term_months
    payments = f"{regular} monthly payments of {money(quote.monthly_pence)}"
    if regular != quote.term_months:
        optional = "an optional final payment" if quote.balloon_pence else "a final payment"
        payments += f" and {optional} of {money(quote.final_payment_pence)}"
    product = f"{quote.product_family} with {quote.lender}" if quote.lender else quote.product_family or "Finance"
    return (f"{product}. Cash price {money(quote.cash_price_pence)}, deposit {money(quote.deposit_pence)}, amount of "
            f"credit {money(quote.amount_of_credit_pence)}. {payments}. Total amount payable "
            f"{money(quote.total_payable_pence)}. Representative {apr_text(quote.apr)}% APR.")


def quote_json(quote):
    """`customer` holds the only fields a customer may ever see; `staff` never leaves the portal."""
    listing = quote.listing
    done = quote.status == Quote.Status.DONE
    return {
        "id": str(quote.id),
        "listing_id": str(quote.listing_id),
        "status": quote.status,
        "pdf_url": f"/api/quotes/{quote.id}/pdf" if done and quote.pdf else "",
        "customer": {
            "title": listing.title or f"{listing.make} {listing.model}".strip(),
            "cash_price_pence": quote.cash_price_pence,
            "deposit_pence": quote.deposit_pence,
            "term_months": quote.term_months,
            "annual_mileage": quote.annual_mileage if done and quote.annual_mileage_applied else None,
            "monthly_pence": quote.monthly_pence if done else None,
            "final_payment_pence": quote.final_payment_pence if done else None,
            "optional_final_payment": bool(done and quote.balloon_pence),
            "apr": apr_text(quote.apr) if done else None,
            "amount_of_credit_pence": quote.amount_of_credit_pence if done else None,
            "total_payable_pence": quote.total_payable_pence if done else None,
            "lender": quote.lender if done else "",
            "product_family": quote.product_family if done else "",
            "fees": quote.fees_text if done else "",
            "example": example(quote),
            "disclaimer": get_setting("finance_disclaimer") if done else "",
            "message": "" if done else ("Finance quote to follow" if quote.finished else "Getting quote from Codeweavers…"),
        },
        "staff": {
            "registration": quote.registration,
            "mileage_sent": quote.mileage,
            "annual_mileage": quote.annual_mileage,
            "annual_mileage_applied": quote.annual_mileage_applied,
            "product": quote.product_quoted or quote.product,
            "note": quote.note,
            "credit_tier": quote.credit_tier,
            "quote_ref": quote.quote_ref,
            "error": quote.error,
        },
    }


__all__ = ["CannotQuote", "Listing", "request_quotes", "run_quotes", "fail_stuck", "quote_json"]
