"""Every message the Hub sends a customer, built by code. AI never writes customer wording or finance figures.

Customer messages are built ONLY from the customer card and the quote's customer figures.
"""

from apps.quotes.services import money

NUMBERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]


def pounds(pence):
    return f"£{pence / 100:,.0f}"


def form_link(url):
    return ("Hi, thanks for getting in touch! 😊 So we can find exactly the right car for you, please fill in this "
            f"quick form (it takes about 1 minute):\n{url}")


def thanks():
    return ("Thank you, we've got your details ✅ Give us a little while and we'll be back with your options and "
            "finance quotes.")


def still_working():
    return "We're still putting your options together and will message you shortly. 👍"


def form_reminder(url):
    return f"Once you've filled in the quick form we'll get straight to work:\n{url}"


def intro(count):
    cars = "1 car" if count == 1 else f"{count} cars"
    return (f"Great news! We've found *{cars}* that match what you're looking for. Each one is below with its "
            "finance quote. Just reply with the number of the one you like 👇")


def product_name(quote_customer):
    family = (quote_customer.get("product_family") or "").lower()
    return "PCP" if "contract" in family or "pcp" in family else "Hire purchase" if "hire" in family else "Finance"


def car(number, card, quote, page_url):
    """One car: the key details, the monthly payment from Codeweavers, when the deal ends and the photos link."""
    details = " · ".join(str(part) for part in (
        card.get("year"), f"{card['mileage']:,} miles" if card.get("mileage") is not None else None,
        card.get("fuel"), card.get("gearbox"), card.get("colour")) if part)
    # Decided 14 Oct 2026 (Mehedi): no price line and no representative example in the car message.
    # FCA advertising rules (CONC 3.5) normally need a representative example beside a monthly payment,
    # so this needs Alom's / Hart's sign-off before real customers receive it.
    lines = [f"{NUMBERS[number - 1]} *{card['title']}*", details]
    if quote:
        lines.append(f"📉 {product_name(quote)} {quote['term_months']} months: *{money(quote['monthly_pence'])}/month* "
                     f"with {pounds(quote['deposit_pence'])} deposit")
    lines.append(f"⏳ {card['available_until']}")
    lines.append(f"📸 More photos: {page_url}")
    return "\n".join(line for line in lines if line)


def closing():
    # Decided 14 Oct 2026 (Mehedi): no finance disclaimer and no bonus line here. "Subject to status" wording is
    # normally expected with finance figures (FCA CONC 3.5), so this is part of the same sign-off as texts.car.
    return ("Like one of these? Reply with its number (e.g. *2*) and one of our team will be in touch to sort "
            "everything out.")


def handed_over(title, person):
    who = person or "one of our team"
    return f"Great choice! 🙌 I've passed the {title} to {who}, who'll message you shortly."
