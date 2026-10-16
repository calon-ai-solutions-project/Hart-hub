"""The messages the Hub builds by code: the option messages, quotes, thanks and hand-overs, and the scripted
chatbot questions. AI never writes these or any finance figure (the conversational chatbot's own replies are
checked by conversation.guard).

Customer messages are built ONLY from the customer card and the quote's customer figures.
"""

from apps.quotes.services import money

NUMBERS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣"]


def pounds(pence):
    return f"£{pence / 100:,.0f}"


GREETING = "Hi, thanks for messaging The Hart Group 👋 I can help you find your next car and get finance quotes."

QUESTIONS = {
    "make_model": "What car are you looking for? A make and model is perfect (e.g. *BMW 1 Series*), or just "
                  "say *any*.",
    "monthly_budget": "What monthly budget would you like to stay under? (e.g. *£300*)",
    "deposit": "How much deposit could you put down? Reply *0* if none.",
    "gearbox": "Automatic or manual? (or *either*)",
    "part_exchange": "Do you have a car to part-exchange? If so, what is it? (or *no*)",
}


PURPOSE = "Are you looking to buy a car? 🚗"


def purpose(first=True):
    """Sent when someone only said hello: what are they messaging about?"""
    return f"{GREETING}\n\n{PURPOSE}" if first else PURPOSE


def noted(answers):
    """What the customer just told us, said back to them in a line: 'BMW M4 · up to £400/month'."""
    parts = []
    if answers.get("make_model") and answers["make_model"] != "any":
        parts.append(f"*{answers['make_model']}*")
    if answers.get("monthly_budget"):
        parts.append(f"up to {answers['monthly_budget']}/month")
    if answers.get("deposit"):
        parts.append("no deposit" if answers["deposit"] == "£0" else f"{answers['deposit']} deposit")
    if answers.get("gearbox") in ("Auto", "Manual"):
        parts.append("automatic" if answers["gearbox"] == "Auto" else "manual")
    if answers.get("part_exchange") and answers["part_exchange"] != "none":
        parts.append("with a part-exchange")
    return " · ".join(parts)


def chat_reply(question, new_answers, first=False, buying=False):
    """The bot's next message: a hello the first time, what it understood, then one question."""
    lines = [GREETING] if first else []
    said = noted(new_answers)
    if said:
        lines.append(f"Got it 👍 {said}")
    elif buying:  # they've just said yes, they want a car
        lines.append("Great, we can help with that 👍")
    lines.append(QUESTIONS[question])
    return "\n\n".join(lines)


def no_cars(answers):
    """No car could be found or quoted: say what was searched for and invite another car or budget."""
    searched = noted({name: answers.get(name) for name in ("make_model", "monthly_budget", "gearbox")})
    what = f"a match for {searched}" if searched else "a car that matches"
    return (f"Sorry, we couldn't find {what} that we can offer on finance right now 😕\n\n"
            "Would you like to try a different car, or a different monthly budget or deposit? Just tell me what "
            "you'd like and I'll search again.")


def person_will_reply():
    return "Thanks for your message 👍 One of our team will reply to you here shortly."


def form_link(url, first=True):
    opening = "Hi, thanks for getting in touch! 😊" if first else "Great, we can help with that 👍"
    return (f"{opening} So we can find exactly the right car for you, please fill in this quick form (it takes "
            f"about 1 minute):\n{url}")


def no_cars_form(searched, url):
    """No car could be quoted for the form's answers: a new form link to try another car or budget."""
    what = f"a match for {searched}" if searched else "a car that matches"
    return (f"Sorry, we couldn't find {what} that we can offer on finance right now 😕\n\n"
            "Would you like to try a different car, or a different monthly budget or deposit? Fill in the form "
            f"again with what you'd like and I'll search again:\n{url}")


def thanks(answers=None):
    said = noted(answers or {})
    return (f"Thank you, we've got your details ✅{chr(10) + said if said else ''}\n\nGive us a little while and "
            "we'll be back with your options and finance quotes.")


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
