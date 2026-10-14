import io
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.models import User
from apps.chat.models import Message
from apps.chat.services import reply as chat_reply
from apps.chat.services import start_conversation
from apps.core.models import Setting
from apps.listings.models import Listing
from apps.quotes import codeweavers, services
from apps.quotes.models import Quote

# The shape of Codeweavers' calculation answer, with made-up figures.
ANSWER = {"Calculation": [{
    "RegularPayment": {"Value": "250.50"}, "FinalPayment": {"Value": "251.50"},
    "RepresentativeApr": {"Value": 10.9}, "AmountOfCredit": {"Value": "10,000.00"},
    "TotalChargeForCredit": {"Value": "2,025.00"}, "TotalAmountPayable": {"Value": "14,025.00"},
    "Fees": [{"DisplayText": "Included in the final payment shown is an option to purchase fee of &#163;1.00"}],
    "ProductFamily": "Hire Purchase", "QuoteReference": "ref-123", "HasError": False,
    "Status": {"IsFailedCalculation": False}, "Errors": [],
}]}
PDF = b"%PDF-1.4 a made-up quote document"
FIELDS = {**codeweavers.parse_calculation(ANSWER), "pdf": PDF, "annual_mileage_applied": False,
          "product_quoted": "(MotoNovo Finance) PCP", "note": ""}


def car(external_id, **fields):
    defaults = dict(platform="motorway", url=f"https://pro.motorway.co.uk/vehicles/{external_id}", make="BMW",
                    model="1 Series", title="BMW 1 Series 118i", registration="XX20 TST", mileage=30000,
                    details_status="complete", status="live", suggested_price_pence=1200000,
                    ends_at=timezone.now() + timedelta(hours=30))
    return Listing.objects.create(external_id=str(external_id), **{**defaults, **fields})


def fake_codeweavers(outcomes=None):
    """Stands in for the browser: answers every request with FIELDS, or with the outcome given for its reg."""
    seen = []

    def get_quotes(requests, on_result):
        for request in requests:
            seen.append(request)
            outcome = (outcomes or {}).get(request.registration, FIELDS)
            if isinstance(outcome, codeweavers.CodeweaversUnavailable):
                raise outcome
            on_result(request, None if isinstance(outcome, Exception) else dict(outcome),
                      outcome if isinstance(outcome, Exception) else None)
    return mock.patch.object(services, "fetch_quotes", side_effect=get_quotes), seen


class ParseTests(SimpleTestCase):
    def test_figures_are_read_exactly_as_codeweavers_gave_them(self):
        self.assertEqual((FIELDS["monthly_pence"], FIELDS["final_payment_pence"], FIELDS["apr"]),
                         (25050, 25150, Decimal("10.9")))
        self.assertEqual((FIELDS["amount_of_credit_pence"], FIELDS["charges_pence"], FIELDS["total_payable_pence"]),
                         (1000000, 202500, 1402500))
        self.assertEqual(FIELDS["fees_text"], "Included in the final payment shown is an option to purchase fee of £1.00")
        self.assertEqual((FIELDS["product_family"], FIELDS["quote_ref"]), ("Hire Purchase", "ref-123"))

    def test_a_refused_or_empty_calculation_is_an_error_not_a_guess(self):
        refused = {"Calculation": [{**ANSWER["Calculation"][0], "HasError": True,
                                    "Errors": ["Vehicle is too old for this product"]}]}
        with self.assertRaisesMessage(codeweavers.QuoteError, "too old"):
            codeweavers.parse_calculation(refused)
        with self.assertRaises(codeweavers.QuoteError):
            codeweavers.parse_calculation({"Calculation": []})
        with self.assertRaises(codeweavers.QuoteError):
            codeweavers.parse_calculation({"Calculation": [{"RegularPayment": {"Value": "0.00"}}]})

    def test_pcp_first_and_hire_purchase_only_when_no_pcp_can_be_quoted(self):
        offered = ["(MotoNovo Finance) HP", "(DSG Prestige) Hire Purchase", "(DSG Prestige) Personal Contract Purchase",
                   "(Finset Limited) Personal Contract Purchase"]
        order = codeweavers.products_to_try
        pcp, hp = "(MotoNovo Finance) PCP", "(MotoNovo Finance) HP"
        self.assertEqual(order([hp, pcp], pcp, hp), [pcp, hp])
        # every lender's PCP is tried before any Hire Purchase, and the named HP product leads the fallbacks
        self.assertEqual(order(offered, pcp, hp),
                         ["(DSG Prestige) Personal Contract Purchase", "(Finset Limited) Personal Contract Purchase",
                          "(MotoNovo Finance) HP", "(DSG Prestige) Hire Purchase"])
        self.assertEqual(order([hp, "(DSG Prestige) Hire Purchase"], pcp, hp), [hp, "(DSG Prestige) Hire Purchase"])
        # with no fallback set, a car with no PCP is simply not quoted
        self.assertEqual(order(offered, pcp), offered[2:])
        with self.assertRaisesMessage(codeweavers.QuoteError, "offers no PCP product for this car"):
            order([hp, "(DSG Prestige) Hire Purchase"], pcp)
        with self.assertRaisesMessage(codeweavers.QuoteError, "offers no PCP or HP product"):
            order(["(Hawkstone) Lease Purchase"], pcp, hp)
        self.assertEqual([codeweavers.family_of(name) for name in offered], ["HP", "HP", "PCP", "PCP"])

    def test_a_calculation_for_another_car_price_or_term_is_refused(self):
        request = codeweavers.QuoteRequest(registration="XX20 TST", mileage=30500, cash_price_pence=1200000,
                                           deposit_pence=200000, term_months=48, annual_mileage=8000,
                                           product="(MotoNovo Finance) PCP", credit_tier="Excellent")
        sent = {"RegistrationNumber": "XX20TST", "CurrentMileage": 30500}
        calc = {"Term": {"Value": 48}, "CashPrice": {"Value": "12,000.00"}, "TotalDeposit": {"Value": "2,000.00"}}
        codeweavers.check_answer(request, sent, calc)  # exactly what was asked: accepted
        wrong = [({**sent, "RegistrationNumber": "RV20 SFX"}, calc, "car RV20 SFX"),
                 ({**sent, "CurrentMileage": 73500}, calc, "mileage 73500"),
                 (sent, {**calc, "Term": {"Value": 40}}, "40 months"),
                 (sent, {**calc, "CashPrice": {"Value": "16,700.00"}}, "price 16,700.00"),
                 (sent, {**calc, "TotalDeposit": {"Value": "0.00"}}, "deposit 0.00")]
        for sent_now, calc_now, expected in wrong:
            with self.subTest(expected=expected), self.assertRaisesMessage(codeweavers.QuoteError, expected):
                codeweavers.check_answer(request, sent_now, calc_now)

    def test_lender_comes_from_the_product_name(self):
        self.assertEqual(codeweavers.lender_of("(MotoNovo Finance) HP"), "MotoNovo Finance")


class QuotePdfTests(SimpleTestCase):
    """The stored document: the right car and term, with the no-vehicle picture in place of the grey box."""

    def document(self, registration="XX20 TST", term=48, placeholder=True):
        import io

        from PIL import Image, ImageDraw
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas

        if placeholder:  # Codeweavers' flat grey "Image not available" box
            picture = Image.new("RGB", (354, 200), (238, 238, 238))
            ImageDraw.Draw(picture).rectangle((120, 60, 230, 140), fill=(221, 221, 221))
        else:  # a real photo: colour all over
            picture = Image.new("RGB", (354, 200), (180, 30, 30))
            ImageDraw.Draw(picture).rectangle((0, 100, 354, 200), fill=(40, 90, 160))
        out = io.BytesIO()
        sheet = canvas.Canvas(out, pagesize=(595.92, 841.92))
        sheet.drawImage(ImageReader(picture), 85.7, 666.2, 135, 76.5)
        sheet.drawString(260, 720, "BMW 1 Series")
        sheet.drawString(100, 500, f"Term of Agreement {term} months")
        sheet.drawString(100, 480, f"Registration number {registration}")
        sheet.save()
        return out.getvalue()

    def request(self):
        return codeweavers.QuoteRequest(registration="XX20TST", mileage=1, cash_price_pence=1, deposit_pence=0,
                                        term_months=48, annual_mileage=8000, product="p", credit_tier="c")

    def test_the_grey_box_is_replaced_and_nothing_else_changes(self):
        from pypdf import PdfReader

        from apps.quotes.pdf import placeholder_boxes, with_vehicle_image

        original = self.document()
        fixed = with_vehicle_image(original)
        self.assertNotEqual(fixed, original)
        before, after = PdfReader(io.BytesIO(original)).pages[0], PdfReader(io.BytesIO(fixed)).pages[0]
        self.assertEqual([tuple(round(v, 1) for v in box) for box in placeholder_boxes(before)], [(85.7, 666.2, 135.0, 76.5)])
        self.assertEqual(sorted(before.extract_text().split()), sorted(after.extract_text().split()))  # same words
        self.assertEqual(len(list(after.images)), len(list(before.images)) + 1)  # the new picture was added

    def test_a_real_photo_is_left_alone(self):
        from apps.quotes.pdf import with_vehicle_image

        photo = self.document(placeholder=False)
        self.assertEqual(with_vehicle_image(photo), photo)
        self.assertEqual(with_vehicle_image(b"not a pdf at all"), b"not a pdf at all")  # never breaks a quote

    def test_a_document_for_another_car_or_term_is_not_kept(self):
        self.assertTrue(codeweavers.pdf_matches(self.document("XX20 TST", 48), self.request()))
        self.assertFalse(codeweavers.pdf_matches(self.document("RV20 SFX", 48), self.request()))
        self.assertFalse(codeweavers.pdf_matches(self.document("XX20 TST", 40), self.request()))
        self.assertFalse(codeweavers.pdf_matches(b"junk", self.request()))


class QuoteRulesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sales@example.com", "a-long-password")
        self.patch, self.seen = fake_codeweavers()
        self.run = mock.patch.object(services, "start_run", side_effect=services.run_quotes)  # run inline
        self.patch.start(), self.run.start()
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.run.stop)

    def quote(self, *listings, deposit=200000):
        quotes = services.request_quotes(self.user, [listing.id for listing in listings], deposit)
        return [Quote.objects.get(pk=q.pk) for q in quotes]

    def test_term_is_always_48_and_500_miles_are_added(self):
        (quote,) = self.quote(car(1, mileage=30000))
        sent = self.seen[0]
        self.assertEqual((sent.term_months, sent.mileage, sent.registration), (48, 30500, "XX20 TST"))
        self.assertEqual((sent.cash_price_pence, sent.deposit_pence), (1200000, 200000))
        self.assertEqual((sent.product, sent.credit_tier), ("(MotoNovo Finance) PCP", "Excellent"))
        self.assertEqual((quote.status, quote.monthly_pence, quote.lender), ("done", 25050, "MotoNovo Finance"))

    def test_annual_mileage_is_always_8000(self):
        (quote,) = self.quote(car(1))
        self.assertEqual((self.seen[0].annual_mileage, quote.annual_mileage), (8000, 8000))
        # Hire Purchase has no Annual Mileage field, so a customer is not shown one
        self.assertFalse(quote.annual_mileage_applied)
        self.assertIsNone(services.quote_json(quote)["customer"]["annual_mileage"])
        self.assertEqual(services.quote_json(quote)["staff"]["annual_mileage"], 8000)

    def test_annual_mileage_shows_on_a_mileage_based_product(self):
        with mock.patch.dict(FIELDS, {"annual_mileage_applied": True}):
            (quote,) = self.quote(car(1))
        self.assertTrue(quote.annual_mileage_applied)
        self.assertEqual(services.quote_json(quote)["customer"]["annual_mileage"], 8000)

    def test_pcp_only_by_default(self):
        self.quote(car(1))
        self.assertEqual((self.seen[0].product, self.seen[0].fallback_product), ("(MotoNovo Finance) PCP", ""))

    def test_a_hire_purchase_fallback_is_recorded_and_explained_to_staff(self):
        Setting.objects.create(key="codeweavers_fallback_product", value="(MotoNovo Finance) HP")  # only if switched on
        why = "No 48-month PCP on this car (the longest PCP term is DSG Prestige PCP up to 40 months), so HP was quoted."
        with mock.patch.dict(FIELDS, {"product_quoted": "(MotoNovo Finance) HP", "note": why}):
            (quote,) = self.quote(car(1))
        self.assertEqual(self.seen[0].fallback_product, "(MotoNovo Finance) HP")
        self.assertEqual((quote.product, quote.product_quoted, quote.lender),
                         ("(MotoNovo Finance) PCP", "(MotoNovo Finance) HP", "MotoNovo Finance"))
        data = services.quote_json(quote)
        self.assertEqual((data["staff"]["product"], data["staff"]["note"]), ("(MotoNovo Finance) HP", why))
        self.assertNotIn("No 48-month", str(data["customer"]))  # the reason is for staff
        # the same request later that day re-uses this quote instead of asking Codeweavers again
        (again,) = self.quote(quote.listing)
        self.assertEqual((again.pk, len(self.seen)), (quote.pk, 1))

    def test_the_fallback_can_be_switched_off(self):
        Setting.objects.create(key="codeweavers_fallback_product", value="")
        self.quote(car(1))
        self.assertEqual(self.seen[0].fallback_product, "")

    def test_annual_mileage_comes_from_settings(self):
        Setting.objects.create(key="codeweavers_annual_mileage", value=10000)
        self.quote(car(1))
        self.assertEqual(self.seen[0].annual_mileage, 10000)

    def test_term_and_extra_mileage_come_from_settings(self):
        Setting.objects.create(key="codeweavers_term_months", value=36)
        Setting.objects.create(key="codeweavers_extra_mileage", value=0)
        self.quote(car(1, mileage=30000))
        self.assertEqual((self.seen[0].term_months, self.seen[0].mileage), (36, 30000))

    def test_the_same_quote_is_not_fetched_twice_in_a_day(self):
        listing = car(1)
        (first,) = self.quote(listing)
        (again,) = self.quote(listing)
        self.assertEqual((first.pk, len(self.seen)), (again.pk, 1))
        (changed,) = self.quote(listing, deposit=300000)  # a different deposit is a different quote
        self.assertNotEqual(changed.pk, first.pk)
        self.assertEqual(len(self.seen), 2)

    def test_another_persons_quote_is_not_reused(self):
        listing = car(1)
        (first,) = self.quote(listing)
        colleague = User.objects.create_user("colleague@example.com", "a-long-password")
        (theirs,) = services.request_quotes(colleague, [listing.id], 200000)
        self.assertNotEqual(theirs.pk, first.pk)  # each person can open only their own quote
        self.assertEqual((theirs.requested_by, len(self.seen)), (colleague, 2))

    def test_cars_that_cannot_be_quoted(self):
        with self.assertRaisesMessage(services.CannotQuote, "at least one"):
            services.request_quotes(self.user, [])
        with self.assertRaisesMessage(services.CannotQuote, "up to 5"):
            services.request_quotes(self.user, [car(n, registration=f"XX{n}").id for n in range(6)])
        with self.assertRaisesMessage(services.CannotQuote, "no longer available"):
            self.quote(car("ended", status="ended"))  # an expired car is never quoted
        (no_reg,) = self.quote(car("noreg", registration=""))
        self.assertEqual(no_reg.status, "failed")
        self.assertIn("no registration", no_reg.error)
        (all_deposit,) = self.quote(car("cash"), deposit=1200000)
        self.assertIn("nothing to finance", all_deposit.error)
        self.assertEqual(self.seen, [])  # none of these reached Codeweavers

    def test_one_failed_car_does_not_stop_the_others(self):
        self.patch.stop()
        self.patch, self.seen = fake_codeweavers({"BAD 1": codeweavers.QuoteError("Codeweavers could not find a vehicle")})
        self.patch.start()
        bad, good = self.quote(car(1, registration="BAD 1"), car(2, registration="GOOD 2"))
        self.assertEqual((bad.status, good.status), ("failed", "done"))
        self.assertIn("could not find", bad.error)
        self.assertIsNone(bad.monthly_pence)  # never a made-up figure

    def test_codeweavers_down_means_quote_to_follow(self):
        self.patch.stop()
        self.patch, _ = fake_codeweavers({"XX20 TST": codeweavers.CodeweaversUnavailable("Could not sign in")})
        self.patch.start()
        (quote,) = self.quote(car(1))
        self.assertEqual((quote.status, quote.error), ("failed", "Could not sign in"))
        data = services.quote_json(quote)
        self.assertEqual(data["customer"]["message"], "Finance quote to follow")
        self.assertIsNone(data["customer"]["monthly_pence"])

    def test_customer_part_never_carries_the_quote_reference(self):
        (quote,) = self.quote(car(1))
        data = services.quote_json(quote)
        self.assertNotIn("ref-123", str(data["customer"]))
        self.assertNotIn("XX20", str(data["customer"]))
        self.assertEqual(data["staff"]["quote_ref"], "ref-123")
        self.assertEqual(data["customer"]["example"],
                         "Hire Purchase with MotoNovo Finance. Cash price £12,000.00, deposit £2,000.00, amount of "
                         "credit £10,000.00. 47 monthly payments of £250.50 and a final payment of £251.50. "
                         "Total amount payable £14,025.00. Representative 10.9% APR.")
        self.assertEqual(data["customer"]["disclaimer"], "Finance is subject to status. Terms and conditions apply.")

    def test_stuck_quotes_are_closed(self):
        stuck = Quote.objects.create(listing=car(1), registration="XX20 TST", mileage=1, cash_price_pence=1,
                                     term_months=48, product="p", credit_tier="c", status="running",
                                     created_at=timezone.now() - timedelta(minutes=11))
        services.fail_stuck()
        stuck.refresh_from_db()
        self.assertEqual((stuck.status, stuck.error), ("failed", "The quote timed out. Please try again."))


class QuoteApiTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("sales@example.com", "a-long-password")
        self.api = APIClient()
        self.api.force_authenticate(self.user)
        self.listing = car(1)
        patch, self.seen = fake_codeweavers()
        run = mock.patch.object(services, "start_run", side_effect=services.run_quotes)
        patch.start(), run.start()
        self.addCleanup(patch.stop)
        self.addCleanup(run.stop)

    def test_needs_a_login(self):
        self.assertIn(APIClient().post("/api/quotes", {"listing_ids": [str(self.listing.id)]}, format="json").status_code,
                      (401, 403))

    def test_submit_from_a_chat_and_poll(self):
        conversation = start_conversation(self.user)
        response = self.api.post("/api/quotes", {"listing_ids": [str(self.listing.id)], "deposit": "£2,000",
                                                 "conversation": str(conversation.id)}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        data = response.json()
        self.assertEqual([m["kind"] for m in data["messages"]], ["text", "quotes"])
        self.assertEqual(data["messages"][1]["body"], "Codeweavers quotes for 1 car, over 48 months with £2,000 deposit:")
        quote_id = data["messages"][1]["payload"]["quote_ids"][0]
        self.assertEqual(Message.objects.filter(conversation=conversation, kind="quotes").count(), 1)

        polled = self.api.get(f"/api/quotes?ids={quote_id}").json()["quotes"][0]
        self.assertEqual((polled["status"], polled["customer"]["monthly_pence"], polled["customer"]["apr"]),
                         ("done", 25050, "10.9"))
        self.assertEqual(polled["customer"]["deposit_pence"], 200000)

    def chat_with_form_deposit(self, deposit="£3,000"):
        conversation = start_conversation(self.user)
        chat_reply(conversation, form={"make_model": "BMW 1 Series", "deposit": deposit, "monthly_budget": "£400"})
        conversation.refresh_from_db()
        return conversation

    def ask(self, conversation, **extra):
        response = self.api.post("/api/quotes", {"listing_ids": [str(self.listing.id)],
                                                 "conversation": str(conversation.id), **extra}, format="json")
        self.assertEqual(response.status_code, 201, response.content)
        return response.json()

    def test_deposit_comes_from_the_enquiry_form(self):
        conversation = self.chat_with_form_deposit("£3,000")
        data = self.ask(conversation)  # no deposit sent: the form's is used
        self.assertEqual(self.seen[-1].deposit_pence, 300000)
        self.assertEqual(data["quotes"][0]["customer"]["deposit_pence"], 300000)
        self.assertIn("with £3,000 deposit", data["messages"][1]["body"])
        self.ask(conversation, deposit="")  # a blank box is the same as not sending one
        self.assertEqual(Quote.objects.exclude(deposit_pence=300000).count(), 0)

    def test_the_form_deposit_follows_a_later_change(self):
        conversation = self.chat_with_form_deposit("£3,000")
        chat_reply(conversation, text="deposit £1,500")
        conversation.refresh_from_db()
        self.ask(conversation)
        self.assertEqual(self.seen[-1].deposit_pence, 150000)
        chat = self.api.get(f"/api/chat/conversations/{conversation.id}").json()
        self.assertEqual(chat["deposit_pence"], 150000)

    def test_staff_can_override_the_deposit_for_one_quote(self):
        conversation = self.chat_with_form_deposit("£3,000")
        self.ask(conversation, deposit="£500")
        self.assertEqual(self.seen[-1].deposit_pence, 50000)
        data = self.ask(conversation, deposit="0")  # typed nought means no deposit, not "use the form"
        self.assertEqual(self.seen[-1].deposit_pence, 0)
        self.assertIn("with £0 deposit", data["messages"][1]["body"])

    def test_no_deposit_in_the_form_means_none(self):
        conversation = start_conversation(self.user)
        chat_reply(conversation, form={"make_model": "BMW 1 Series"})
        conversation.refresh_from_db()
        self.ask(conversation)
        self.assertEqual(self.seen[-1].deposit_pence, 0)

    def test_staff_can_preview_the_codeweavers_pdf(self):
        quote = services.request_quotes(self.user, [self.listing.id], 200000)[0]
        data = self.api.get(f"/api/quotes?ids={quote.id}").json()["quotes"][0]
        self.assertEqual(data["pdf_url"], f"/api/quotes/{quote.id}/pdf")
        response = self.api.get(data["pdf_url"])
        self.assertEqual((response.status_code, response["Content-Type"]), (200, "application/pdf"))
        self.assertEqual(b"".join(response.streaming_content), PDF)
        self.assertEqual(response["Content-Disposition"], 'inline; filename="Quote XX20 TST.pdf"')
        self.assertEqual(response["X-Frame-Options"], "SAMEORIGIN")  # it is previewed inside the chat page
        self.assertIn("no-store", response["Cache-Control"])
        download = self.api.get(data["pdf_url"] + "?download=1")
        self.assertTrue(download["Content-Disposition"].startswith("attachment"))

    def test_the_pdf_is_only_for_whoever_asked_and_the_owner(self):
        quote = services.request_quotes(self.user, [self.listing.id], 200000)[0]
        other = APIClient()
        other.force_authenticate(User.objects.create_user("other@example.com", "a-long-password", role="sales"))
        self.assertEqual(other.get(f"/api/quotes/{quote.id}/pdf").status_code, 404)
        owner = APIClient()
        owner.force_authenticate(User.objects.create_user("james@example.com", "a-long-password", role="owner"))
        self.assertEqual(owner.get(f"/api/quotes/{quote.id}/pdf").status_code, 200)
        self.assertIn(APIClient().get(f"/api/quotes/{quote.id}/pdf").status_code, (401, 403))

    def test_a_quote_without_a_document_still_shows_its_figures(self):
        with mock.patch.dict(FIELDS, {"pdf": None}):
            quote = services.request_quotes(self.user, [car("nopdf", registration="NO PDF").id], 200000)[0]
        data = self.api.get(f"/api/quotes?ids={quote.id}").json()["quotes"][0]
        self.assertEqual((data["status"], data["pdf_url"], data["customer"]["monthly_pence"]), ("done", "", 25050))
        self.assertEqual(self.api.get(f"/api/quotes/{quote.id}/pdf").status_code, 404)

    def test_only_your_own_chats_and_quotes(self):
        other = User.objects.create_user("other@example.com", "a-long-password")
        theirs = start_conversation(other)
        response = self.api.post("/api/quotes", {"listing_ids": [str(self.listing.id)], "conversation": str(theirs.id)},
                                 format="json")
        self.assertEqual(response.status_code, 404)
        quote = services.request_quotes(other, [self.listing.id])[0]
        self.assertEqual(self.api.get(f"/api/quotes?ids={quote.id}").json()["quotes"], [])

    def test_bad_requests(self):
        self.assertEqual(self.api.post("/api/quotes", {"listing_ids": []}, format="json").status_code, 400)
        gone = car("gone", status="ended")
        response = self.api.post("/api/quotes", {"listing_ids": [str(gone.id)]}, format="json")
        self.assertEqual(response.status_code, 400)
        self.assertIn("no longer available", response.json()["detail"])
