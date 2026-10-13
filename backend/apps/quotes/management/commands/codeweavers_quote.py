from django.core.management.base import BaseCommand, CommandError

from apps.core.services import get_setting
from apps.quotes import codeweavers
from apps.quotes.pdf import with_vehicle_image


class Command(BaseCommand):
    help = "Get one Codeweavers quote from the command line, to check the connection works."

    def add_arguments(self, parser):
        parser.add_argument("registration")
        parser.add_argument("--mileage", type=int, required=True)
        parser.add_argument("--price", type=float, required=True, help="cash price in pounds")
        parser.add_argument("--deposit", type=float, default=0, help="deposit in pounds")
        parser.add_argument("--product", help="quote this product instead of the codeweavers_product setting")
        parser.add_argument("--save-pdf", help="write Codeweavers' quote PDF to this file")

    def handle(self, *args, registration, mileage, price, deposit, save_pdf, product, **options):
        request = codeweavers.QuoteRequest(
            registration=registration.upper(), mileage=mileage, cash_price_pence=int(price * 100),
            deposit_pence=int(deposit * 100), term_months=int(get_setting("codeweavers_term_months")),
            annual_mileage=int(get_setting("codeweavers_annual_mileage")),
            fallback_product=get_setting("codeweavers_fallback_product") or "",
            product=product or get_setting("codeweavers_product"), credit_tier=get_setting("codeweavers_credit_tier"))
        results = []
        try:
            codeweavers.get_quotes([request], lambda r, fields, error: results.append((fields, error)))
        except codeweavers.CodeweaversUnavailable as e:
            raise CommandError(str(e))
        fields, error = results[0]
        if error:
            raise CommandError(str(error))
        if save_pdf and fields.get("pdf"):
            with open(save_pdf, "wb") as f:
                f.write(with_vehicle_image(fields["pdf"]))
        self.stdout.write(f"Annual mileage: {request.annual_mileage:,} selected" if fields["annual_mileage_applied"]
                          else "Annual mileage: this product has no Annual Mileage field")
        self.stdout.write(f"PDF: {len(fields['pdf']):,} bytes" if fields.get("pdf") else "PDF: not returned")
        self.stdout.write(f"{registration}: £{fields['monthly_pence'] / 100:,.2f} a month over {fields['raw']['Term']['Value']} "
                          f"months, {fields['apr']}% APR, total payable £{fields['total_payable_pence'] / 100:,.2f} "
                          f"({fields['product_quoted']})")
        if fields["note"]:
            self.stdout.write(f"Note: {fields['note']}")
