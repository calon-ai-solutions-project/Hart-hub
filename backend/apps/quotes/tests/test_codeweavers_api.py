"""The Codeweavers JSON Finance API route, with the API faked. Figures are from a real answer."""

from decimal import Decimal
from unittest import mock

from django.test import SimpleTestCase, override_settings

from apps.quotes import codeweavers_api
from apps.quotes.codeweavers import CodeweaversUnavailable, QuoteRequest


def request(**changes):
    values = dict(registration="XX23 TST", mileage=20500, cash_price_pence=2100000, deposit_pence=300000,
                  term_months=48, annual_mileage=8000, product="(MotoNovo Finance) PCP", credit_tier="Excellent",
                  fallback_product="(MotoNovo Finance) HP")
    return QuoteRequest(**{**values, **changes})


def quote(**changes):
    values = {"Term": 48, "CashPrice": 21000.0, "TotalDeposit": 3000.0, "AnnualMileage": 8000, "RegularPayment": 283.34,
              "FinalPayment": 9877.0, "Residual": 9876.0, "Apr": 9.9, "TotalAmountPayable": 26477.32,
              "AmountOfCredit": 18000.0, "TotalChargeForCredit": 5477.32, "QuoteReference": "c4d7a5b0",
              "Fees": [{"DisplayText": "Included in the final payment shown is an option to purchase fee of &#163;1.00"}]}
    return {**values, **changes}


def answer(*vehicles):
    return {"VehicleResults": [{"Id": str(i), **v} for i, v in enumerate(vehicles)]}


@override_settings(CODEWEAVERS_USERNAME="user", CODEWEAVERS_PASSWORD="secret", CODEWEAVERS_API_URL="https://cw.test")
class ApiRouteTests(SimpleTestCase):
    def run_route(self, api_answer, *requests):
        results = []
        with mock.patch.object(codeweavers_api, "_post", return_value=api_answer) as post, \
                mock.patch.object(codeweavers_api, "lender_from_terms", return_value="MotoNovo Finance"):
            codeweavers_api.get_quotes(list(requests), lambda r, fields, error: results.append((r, fields, error)))
        return results, post

    def test_pcp_figures_exactly_as_codeweavers_gave_them(self):
        results, post = self.run_route(answer({"FinanceProductResults": [
            {"Key": "PCP", "Quote": quote()}, {"Key": "HP", "Quote": quote(RegularPayment=451.95)}]}), request())
        (_, fields, error), = results
        self.assertIsNone(error)
        self.assertEqual((fields["monthly_pence"], fields["final_payment_pence"], fields["total_payable_pence"]),
                         (28334, 987700, 2647732))
        self.assertEqual((fields["apr"], fields["product_family"], fields["product_quoted"]),
                         (Decimal("9.9"), "Personal Contract Purchase", "(MotoNovo Finance) PCP"))
        self.assertEqual(fields["fees_text"], "Included in the final payment shown is an option to purchase fee of £1.00")
        sent = post.call_args.args[0]
        self.assertEqual(sent["Parameters"]["FinanceProductFamilyKeys"], ["PCP", "HP"])
        self.assertEqual((sent["Parameters"]["Term"], sent["Parameters"]["Deposit"], sent["Parameters"]["AnnualMileage"]),
                         (48, 3000.0, 8000))
        self.assertEqual(sent["VehicleRequests"][0]["Vehicle"]["RegistrationNumber"], "XX23TST")

    def test_hp_only_when_there_is_no_pcp(self):
        results, _ = self.run_route(answer({"FinanceProductResults": [
            {"Key": "PCP", "HasError": True, "Error": {"DealerMessage": "Vehicle too old for PCP"}},
            {"Key": "HP", "Quote": quote(RegularPayment=254.85, Residual=None)}]}), request())
        (_, fields, _), = results
        self.assertEqual((fields["monthly_pence"], fields["product_quoted"], fields["balloon_pence"]),
                         (25485, "(MotoNovo Finance) HP", None))

    def test_a_different_term_or_price_is_refused(self):
        results, _ = self.run_route(answer({"FinanceProductResults": [{"Key": "PCP", "Quote": quote(Term=47)}]}),
                                    request(fallback_product=""))
        (_, fields, error), = results
        self.assertIsNone(fields)
        self.assertIn("47 months", str(error))

    def test_one_car_refused_does_not_stop_the_others(self):
        results, post = self.run_route(answer(
            {"HasError": True, "Error": {"DealerMessage": "Please contact us directly for finance information."}},
            {"FinanceProductResults": [{"Key": "PCP", "Quote": quote()}]}),
            request(registration="XX20 AAA"), request())
        self.assertEqual(post.call_count, 1)  # both cars in one call
        self.assertIn("contact us directly", str(results[0][2]))
        self.assertIsNotNone(results[1][1])

    def test_login_refused_means_nothing_can_be_quoted(self):
        response = mock.Mock(status_code=401)
        with mock.patch.object(codeweavers_api.requests, "post", return_value=response):
            with self.assertRaises(CodeweaversUnavailable):
                codeweavers_api.get_quotes([request()], lambda *a: None)

    def test_lender_is_read_from_codeweavers_terms(self):
        terms = mock.Mock(ok=True)
        terms.json.return_value = {"TermsAndConditions": "Finance is provided by MotoNovo Finance Limited, Two Central "
                                                         "Square, Cardiff. This is not a commitment to lend."}
        with mock.patch.object(codeweavers_api.requests, "get", return_value=terms):
            self.assertEqual(codeweavers_api.lender_from_terms("ref"), "MotoNovo Finance")
        self.assertEqual(codeweavers_api.lender_from_terms(""), "")
