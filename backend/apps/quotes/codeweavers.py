"""Codeweavers Showroom connector: gets finance quotes by driving the Showroom screens in a browser.

There is no API access yet, so this signs in as a Showroom user, opens the quick-quote screen, looks
the car up by registration, enters mileage, price, deposit and term, presses calculate and reads the
figures from Codeweavers' own answer. It never opens the Application tab and never saves or submits
anything: quotes only.

Codeweavers allows one session per login. Signing in here signs out anyone else using the same
login, so the Hub should have its own Showroom user.
"""

import logging
import queue
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import connection

from apps.core.models import Setting

logger = logging.getLogger(__name__)

SESSION_DIR = settings.BASE_DIR / ".codeweavers"
SESSION_FILE = SESSION_DIR / "session.json"
PROPOSAL_SETTING = "codeweavers_proposal_url"  # the one proposal the Hub re-uses for every quote
FRAME = "legacy-app-compatibility-iframe"
ONE_AT_A_TIME = threading.Lock()  # one login, one browser
LOCK_KEY = 7106202601  # any fixed number: the database lock every server process shares


@contextmanager
def one_session():
    """One Codeweavers session at a time, across every server process (web workers and the job worker).

    Codeweavers allows one session per login, so two quote runs at once would sign each other out.
    A second run waits here until the first has finished.
    """
    with ONE_AT_A_TIME:
        if connection.vendor != "postgresql":
            yield
            return
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_lock(%s)", [LOCK_KEY])
        try:
            yield
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SELECT pg_advisory_unlock(%s)", [LOCK_KEY])


class QuoteError(Exception):
    """This car could not be quoted. The message is safe to show to staff."""


class CodeweaversUnavailable(Exception):
    """Codeweavers could not be reached or signed in to: nothing can be quoted right now."""


@dataclass
class QuoteRequest:
    registration: str
    mileage: int
    cash_price_pence: int
    deposit_pence: int
    term_months: int
    annual_mileage: int
    product: str
    credit_tier: str
    fallback_product: str = ""  # quoted when no product of the first kind is available at the term
    vehicle_type: str = "Car"


def pence(value):
    """'17,367.24' or 17367.24 -> 1736724; nothing -> None."""
    if value in (None, ""):
        return None
    try:
        return int((Decimal(str(value).replace(",", "").replace("£", "").strip()) * 100).to_integral_value())
    except InvalidOperation:
        return None


def parse_calculation(body):
    """Codeweavers' calculation answer -> the fields of a Quote. Raises QuoteError if it refused."""
    calculations = (body or {}).get("Calculation") or []
    if not calculations:
        raise QuoteError("Codeweavers returned no calculation.")
    calc = calculations[0]
    failed = (calc.get("Status") or {}).get("IsFailedCalculation")
    if calc.get("HasError") or failed:
        errors = calc.get("Errors") or []
        message = calc.get("DealerMessage") or (errors[0] if errors else "") or "Codeweavers could not quote this car."
        raise QuoteError(re.sub(r"<[^>]+>", "", str(message))[:250])

    def value(name):
        return (calc.get(name) or {}).get("Value")

    monthly = pence(value("RegularPayment"))
    if not monthly:
        raise QuoteError("Codeweavers returned no monthly payment.")
    fees = "; ".join(re.sub(r"&#163;", "£", str(fee.get("DisplayText") or "")) for fee in calc.get("Fees") or [])
    try:
        apr = Decimal(str(value("RepresentativeApr")))
    except InvalidOperation:
        apr = None
    raw_annual = (calc.get("AnnualMileage") or {}).get("Value")
    return {
        "monthly_pence": monthly,
        "final_payment_pence": pence(value("FinalPayment")),
        "balloon_pence": pence(value("Rv")) or None,
        "apr": apr,
        "amount_of_credit_pence": pence(value("AmountOfCredit")),
        "charges_pence": pence(value("TotalChargeForCredit")),
        "total_payable_pence": pence(value("TotalAmountPayable")),
        "fees_text": fees[:255],
        "product_family": str(calc.get("ProductFamily") or "")[:60],
        "quote_ref": str(calc.get("QuoteReference") or "")[:64],
        "raw": {key: calc.get(key) for key in ("RegularPayment", "FinalPayment", "RepresentativeApr", "RateOfInterest",
                                               "TotalAmountPayable", "TotalChargeForCredit", "AmountOfCredit",
                                               "CashPrice", "TotalDeposit", "Term", "Fees", "Payments",
                                               "NumberOfRegularPayments", "ProductFamily", "ProductKey",
                                               "ExcessMileageCharge", "Rv",
                                               "QuoteReference", "QuoteCreated", "CommissionString")}
        | {"AnnualMileage": int(raw_annual) if str(raw_annual or "").isdigit() else None},
    }


def lender_of(product):
    """'(MotoNovo Finance) HP' -> 'MotoNovo Finance'."""
    found = re.match(r"\((.+?)\)", product or "")
    return found.group(1) if found else ""


def configured():
    return bool(settings.CODEWEAVERS_LOGIN_URL and settings.CODEWEAVERS_USERNAME and settings.CODEWEAVERS_PASSWORD)


# ---------------------------------------------------------------- browser

def _settle(page, ms=2500):
    try:
        page.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    page.wait_for_timeout(ms)


def _sign_in(page):
    """Sign in to the Showroom. Takes over the login if someone else is using it."""
    page.goto(settings.CODEWEAVERS_LOGIN_URL, wait_until="networkidle", timeout=60000)
    page.fill("#username", settings.CODEWEAVERS_USERNAME)
    page.fill("#password", settings.CODEWEAVERS_PASSWORD)
    page.click("button[type=submit]:has-text('Log in')")
    page.wait_for_timeout(5000)
    text = page.inner_text("body")
    if "already logged in elsewhere" in text:
        logger.warning("Codeweavers: this login was in use elsewhere; that session has been signed out.")
        page.click("#submit")
        page.wait_for_timeout(4000)
    _settle(page)
    if "select-workspace" in page.url:
        page.locator("xpath=//*[normalize-space(text())='Codeweavers']/following::*[normalize-space(text())='Login'][1]").click()
        _settle(page, 5000)
    if "/showroom/" not in page.url or "identity.codeweavers.app" in page.url:
        raise CodeweaversUnavailable("Could not sign in to Codeweavers. Check the login details.")


def _open_quote_screen(page, proposal_url):
    """Open the Hub's quick-quote screen, signing in and creating its proposal only when needed.

    Returns the proposal URL to use (and to remember).
    """
    if proposal_url:
        page.goto(proposal_url, wait_until="domcontentloaded", timeout=60000)
        _settle(page, 5000)
        if "identity.codeweavers.app" in page.url:
            _sign_in(page)
            page.goto(proposal_url, wait_until="domcontentloaded", timeout=60000)
            _settle(page, 5000)
        if "/quick-quote" in page.url and page.frame(name=FRAME):
            return proposal_url
    if "/showroom/" not in page.url or "identity.codeweavers.app" in page.url:
        _sign_in(page)
    # one proposal is created once and re-used, so the Hub does not fill Hart's proposal list
    page.locator("a:has-text('Create Quote')").first.click()
    page.wait_for_url("**/quick-quote", timeout=60000)
    _settle(page, 5000)
    if not page.frame(name=FRAME):
        raise CodeweaversUnavailable("The Codeweavers quote screen did not load.")
    return page.url


SIGNED_OUT = ("Someone else signed in to Codeweavers with the Hub's login, which signed the Hub out part-way "
              "through. Please try again; a separate Showroom user for the Hub stops this happening.")


def _quote_form(page, wait_seconds=40):
    """The quote form (it lives in a frame that the screen rebuilds after a vehicle is chosen)."""
    for _ in range(wait_seconds * 2):
        if "identity.codeweavers.app" in page.url:
            raise CodeweaversUnavailable(SIGNED_OUT)
        form = page.frame(name=FRAME)
        try:
            if form is not None and form.locator("#ProductKey").count():
                return form
        except Exception:
            pass  # the frame was replaced while we looked
        page.wait_for_timeout(500)
    if "identity.codeweavers.app" in page.url or not page.frame(name=FRAME):
        raise CodeweaversUnavailable(SIGNED_OUT)
    raise QuoteError("The Codeweavers quote form did not load for this car.")


def _type_money(box, pence_value):
    box.click()
    box.press("Control+a")
    box.type(f"{pence_value / 100:.2f}", delay=40)
    box.press("Tab")


FAMILIES = {  # how each kind of product is worded in the Showroom's product list
    "PCP": ("pcp", "personal contract purchase"),
    "HP": (" hp", "hire purchase"),
}


def family_of(product):
    """'(MotoNovo Finance) PCP' -> 'PCP'; an unknown wording -> ''."""
    name = f" {product}".lower()
    return next((family for family, words in FAMILIES.items() if any(word in name for word in words)), "")


def of_kind(options, wanted):
    """The product asked for, then other lenders' products of the same kind, in the Showroom's order."""
    family = family_of(wanted)
    same_kind = [option for option in options if option != wanted and family and family_of(option) == family]
    return ([wanted] if wanted in options else []) + same_kind


def products_to_try(options, wanted, fallback=""):
    """The products to try, in order.

    First every product of the wanted kind (PCP), starting with the one asked for. Only if none of
    those can be quoted does it move on to the fallback kind (Hire Purchase), starting with the
    fallback product named in settings. Lenders do not offer every product on every car.
    """
    first = of_kind(options, wanted)
    second = [option for option in of_kind(options, fallback) if option not in first] if fallback else []
    if not first and not second:
        kinds = " or ".join(kind for kind in (family_of(wanted), family_of(fallback)) if kind) or f"“{wanted}”"
        raise QuoteError(f"Codeweavers offers no {kinds} product for this car. "
                         f"It offers: {', '.join(options[:14]) or 'nothing'}.")
    return first + second


def _options(dropdown, page, expect=None):
    """A dropdown's choices, waiting a little for the screen to finish filling it in."""
    for _ in range(24):
        options = [text.strip() for text in dropdown.locator("option").all_inner_texts() if text.strip()]
        if options and (expect is None or expect in options):
            return options
        page.wait_for_timeout(500)
    return options


def _steady_options(dropdown, page):
    """A dropdown's choices once they have stopped changing (the screen re-fills it after a product change)."""
    before = _options(dropdown, page)
    for _ in range(10):
        page.wait_for_timeout(700)
        now = _options(dropdown, page)
        if now == before:
            return now
        before = now
    return before


def plate(registration):
    """'rv20 sfx' -> 'RV20SFX', for comparing registrations however they are spaced."""
    return re.sub(r"[^A-Z0-9]", "", str(registration or "").upper())


def check_answer(request, sent, calc):
    """Refuse a calculation that is not for exactly the car and deal we asked for.

    The Showroom screen keeps the last car, product and term, so this is the guard against a quote
    that looks right but belongs to something else.
    """
    def number(value):
        try:
            return float(str(value).replace(",", "").replace("£", ""))
        except (TypeError, ValueError):
            return None

    problems = []
    if plate(sent.get("RegistrationNumber") or sent.get("Identifier")) != plate(request.registration):
        problems.append(f"car {sent.get('RegistrationNumber') or sent.get('Identifier')}")
    if number(sent.get("CurrentMileage")) != float(request.mileage):
        problems.append(f"mileage {sent.get('CurrentMileage')}")
    if number((calc.get("Term") or {}).get("Value")) != float(request.term_months):
        problems.append(f"{(calc.get('Term') or {}).get('Value')} months")
    if number((calc.get("CashPrice") or {}).get("Value")) != request.cash_price_pence / 100:
        problems.append(f"price {(calc.get('CashPrice') or {}).get('Value')}")
    if number((calc.get("TotalDeposit") or {}).get("Value")) != request.deposit_pence / 100:
        problems.append(f"deposit {(calc.get('TotalDeposit') or {}).get('Value')}")
    if problems:
        raise QuoteError("Codeweavers calculated something different from what was asked ("
                         + ", ".join(problems) + "), so the quote was not used.")


def pdf_matches(pdf, request):
    """Does the quote document name this car and this term?"""
    try:
        import io

        from pypdf import PdfReader

        text = "".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)
    except Exception:
        return False
    squeezed = "".join(text.split()).upper()
    return plate(request.registration) in squeezed and f"TERMOFAGREEMENT{request.term_months}MONTHS" in squeezed


def _select(dropdown, label, what, page):
    options = _options(dropdown, page, expect=label)
    if label not in options:
        raise QuoteError(f"Codeweavers does not offer {what} “{label}” on this product. "
                         f"It offers: {', '.join(options[:1])} to {', '.join(options[-1:])}.")
    dropdown.select_option(label=label)


def _quote_pdf(context, page, request):
    """Save the quote on the Hub's proposal and fetch Codeweavers' own quote document (a PDF).

    Codeweavers only offers the document for a saved quote. Saving keeps it in that one proposal's
    quote history; nothing is submitted or sent to anyone.
    """
    share = page.locator("[data-spec='share-quote-btn']")
    page.locator("[data-spec='save-quote-btn']").click()
    description = page.locator("#quote-save-description")
    try:  # the description is only asked for the first time the proposal is saved
        description.wait_for(state="visible", timeout=6000)
    except Exception:
        pass
    else:
        description.fill("Hart Hub quotes")
        page.locator("button.cw-button-primary", has_text="Save").last.click()
    page.wait_for_function("document.querySelector(\"[data-spec='share-quote-btn']\")?.disabled === false",
                           timeout=30000)
    share.click()
    button = page.locator("button", has_text="Print Quote")
    button.wait_for(state="visible", timeout=15000)
    with context.expect_event(
            "response", lambda r: "/documents/quotes/" in r.url and "/transcript/" in r.url, timeout=60000) as document:
        with context.expect_page() as viewer:
            button.click()
    data = document.value.body()
    viewer.value.close()
    if not data.startswith(b"%PDF"):
        raise QuoteError("Codeweavers did not return a PDF for this quote.")
    return data


def _quote_one(context, page, proposal_url, request):
    page.goto(proposal_url, wait_until="domcontentloaded", timeout=60000)  # a fresh screen for every car
    _settle(page, 5000)
    form = _quote_form(page)

    # the car, by registration
    form.locator("a.asset-lookup-type-container__search-engine").click()
    page.wait_for_timeout(2500)
    page.locator("button.cw-tab-button", has_text="VRM").click()
    if request.vehicle_type != "Car":
        page.select_option("#vehicle-type-selector-options", label=request.vehicle_type)
    page.fill("#vrmLookup", request.registration)
    with page.expect_response(lambda r: "/vehicle" in r.url.lower() and r.request.method in ("GET", "POST"),
                              timeout=30000):
        page.locator("button", has_text="Lookup").click()
    mileage = page.locator("input[type=number].ui-text-input")
    try:
        # the panel can still be showing the previous car: wait until it shows the one we asked for
        page.wait_for_function(
            "reg => document.body.innerText.replace(/\\s/g, '').toUpperCase().includes(reg)", arg=plate(request.registration),
            timeout=25000)
        mileage.wait_for(state="visible", timeout=10000)
    except Exception as e:
        raise QuoteError(f"Codeweavers could not find a vehicle for registration {request.registration}.") from e
    page.wait_for_timeout(800)
    mileage.fill(str(request.mileage))
    page.locator("button", has_text="Confirm Vehicle").click()
    _settle(page, 5000)

    # the deal
    form = _quote_form(page)
    # the first product that offers the wanted term on this car: PCP products first, then the fallback kind
    wanted_kind = family_of(request.product)
    product, longest = None, []
    for candidate in products_to_try(_options(form.locator("#ProductKey"), page), request.product,
                                     request.fallback_product):
        form.locator("#ProductKey").select_option(label=candidate)
        _settle(page, 3000)  # the fields below change with the product
        terms = _steady_options(form.locator("#Term"), page)
        if str(request.term_months) in terms:
            product = candidate
            break
        longest.append(f"{lender_of(candidate) or candidate} {family_of(candidate)} up to {terms[-1] if terms else '?'} months")
    if product is None:
        raise QuoteError(f"No product offers {request.term_months} months on this car ({'; '.join(longest)}).")
    note = ""
    if wanted_kind and family_of(product) != wanted_kind:  # say why this is not the usual kind of quote
        tried = [line for line in longest if f" {wanted_kind} " in line]
        why = f"the longest {wanted_kind} term is {'; '.join(tried)}" if tried else f"no {wanted_kind} product is offered"
        note = f"No {request.term_months}-month {wanted_kind} on this car ({why}), so {family_of(product) or product} was quoted."
    tier = form.locator("#CreditScoreTier")  # not every product asks for a credit rating
    if tier.count() and tier.is_visible():
        _select(tier, request.credit_tier, "the credit rating", page)
    _select(form.locator("#Term"), str(request.term_months), "a term of", page)
    page.wait_for_timeout(600)
    # Annual Mileage is only on the screen for mileage-based products (PCP); Hire Purchase has no such field
    annual = form.locator("#AnnualMileage")
    asked_annual = annual.count() > 0 and annual.is_visible()
    if asked_annual:
        _select(annual, str(request.annual_mileage), "an annual mileage of", page)
    _type_money(form.locator("[data-e2e$='TotalPriceFieldInput']"), request.cash_price_pence)
    _type_money(form.locator("#CashDeposit"), request.deposit_pence)
    page.wait_for_timeout(800)

    # calculate, and read Codeweavers' own answer rather than the screen
    with page.expect_response(lambda r: "/plutus/calculations" in r.url and r.request.method == "POST",
                              timeout=60000) as answer:
        form.locator("#btn-calc-to-regularpayment").click()
    if answer.value.status != 200:
        raise QuoteError(f"Codeweavers answered {answer.value.status} to the calculation.")
    body = answer.value.json()
    fields = parse_calculation(body)
    check_answer(request, answer.value.request.post_data_json or {}, body["Calculation"][0])
    fields["annual_mileage_applied"] = asked_annual
    fields["product_quoted"] = product  # may be another lender's, or the fallback kind
    fields["note"] = note[:255]
    if asked_annual and fields["raw"].get("AnnualMileage") != request.annual_mileage:
        raise QuoteError(f"Codeweavers quoted {fields['raw'].get('AnnualMileage')} annual miles, not "
                         f"{request.annual_mileage:,}, so the quote was not used.")
    _settle(page, 2000)
    try:  # the figures stand even if the document cannot be fetched
        fields["pdf"] = _quote_pdf(context, page, request)
        if not pdf_matches(fields["pdf"], request):  # never keep a document for another car or term
            raise QuoteError("the document Codeweavers returned is for a different car or term")
    except Exception as e:
        logger.warning("Codeweavers quote PDF for %s was not fetched: %s", request.registration, str(e).splitlines()[0])
        try:
            page.screenshot(path=str(SESSION_DIR / "last-pdf-error.png"))
        except Exception:
            pass
        fields["pdf"] = None
    return fields


def _browse(requests, proposal_url, results):
    """The browser work, on its own thread. Everything it learns goes on the `results` queue.

    It must not touch the database: the browser library runs an event loop in this thread, and
    Django refuses database calls from a thread like that.
    """
    from playwright.sync_api import Error as BrowserError
    from playwright.sync_api import sync_playwright

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(viewport={"width": 1500, "height": 950}, locale="en-GB",
                                              accept_downloads=True,
                                              storage_state=str(SESSION_FILE) if SESSION_FILE.exists() else None)
                page = context.new_page()
                try:
                    proposal_url = _open_quote_screen(page, proposal_url)
                except BrowserError as e:
                    raise CodeweaversUnavailable(f"Codeweavers did not respond: {str(e).splitlines()[0][:150]}") from e
                results.put(("proposal", proposal_url))
                context.storage_state(path=str(SESSION_FILE))
                for request in requests:
                    try:
                        results.put(("result", request, _quote_one(context, page, proposal_url, request), None))
                    except QuoteError as e:
                        results.put(("result", request, None, e))
                    except CodeweaversUnavailable:
                        raise
                    except BrowserError as e:
                        try:
                            page.screenshot(path=str(SESSION_DIR / "last-error.png"))
                        except Exception:
                            pass
                        logger.warning("Codeweavers quote for %s failed: %s", request.registration, e)
                        results.put(("result", request, None,
                                     QuoteError("Codeweavers did not respond in time for this car.")))
                context.storage_state(path=str(SESSION_FILE))
            finally:
                browser.close()
    except CodeweaversUnavailable as e:
        results.put(("fatal", e))
    except Exception as e:  # never leave the caller waiting
        logger.exception("Codeweavers browser session failed")
        results.put(("fatal", CodeweaversUnavailable(f"Codeweavers session failed: {type(e).__name__}")))
    finally:
        results.put(("done",))


def get_quotes(requests, on_result):
    """Quote each request in turn in one browser session, calling on_result(request, fields, error).

    `fields` is a dict for the Quote on success; `error` is a QuoteError for that one car. Raises
    CodeweaversUnavailable when nothing more could be quoted at all.
    """
    if not configured():
        raise CodeweaversUnavailable("Codeweavers login is not set (CODEWEAVERS_* in the environment).")
    SESSION_DIR.mkdir(exist_ok=True)
    stored = Setting.objects.filter(key=PROPOSAL_SETTING).values_list("value", flat=True).first()
    with one_session():
        results = queue.Queue()
        threading.Thread(target=_browse, args=(list(requests), stored, results), daemon=True).start()
        fatal = None
        while True:
            item = results.get()
            if item[0] == "done":
                break
            if item[0] == "proposal" and item[1] != stored:
                Setting.objects.update_or_create(key=PROPOSAL_SETTING, defaults={
                    "value": item[1], "description": "The Showroom proposal the Hub re-uses for every quote."})
            elif item[0] == "result":
                on_result(*item[1:])
            elif item[0] == "fatal":
                fatal = item[1]
    if fatal:
        raise fatal
