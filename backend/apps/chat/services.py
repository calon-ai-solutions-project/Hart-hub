from django.db import transaction

from apps.core.services import emit_event
from apps.matching.models import Match, Requirement
from apps.matching.services import parse, rerank, search
from apps.matching.services.budget import ceiling_note
from apps.matching.services.cards import customer_card, staff_card

from .models import Conversation, Message

GREETING = "Hi, what are you looking for? Let me know and I’ll send you some options ASAP!"
# Fixed wording, added by code. AI never writes or changes anything about finance.
BONUS = ("Bonus: With any car purchased through us, your first payment isn’t due until 30 days after signing "
         "the agreement—effectively making your first month free!")
FORM_FIELDS = [
    {"name": "make_model", "label": "Make & Model", "placeholder": "e.g. BMW 1 Series"},
    {"name": "colour", "label": "Preferred Colour", "placeholder": "e.g. Black"},
    {"name": "gearbox", "label": "Auto or Manual", "options": ["Auto", "Manual", "Either"]},
    {"name": "deposit", "label": "Deposit (if any)", "placeholder": "e.g. £2,000"},
    {"name": "monthly_budget", "label": "Max Monthly Budget", "placeholder": "e.g. £300"},
    {"name": "needed_by", "label": "When do you need it by?", "placeholder": "e.g. End of the month"},
]
NEED_MORE = ("I need a little more to search on. Tell me the make and model, or a budget "
             "(for example “BMW 1 Series, automatic, £300 a month”).")
CLEARED = "All filters cleared. What would you like to look for?"
SORT_LABELS = {"price": "Cheapest first", "year": "Newest first", "mileage": "Lowest mileage first"}

# The × on a filter chip: what it clears, and how that reads in the thread.
REMOVALS = {
    "make_model": ({"make": "", "model": ""}, "Any make"),
    "colours": ({"colours": [], "colour_only": False}, "Any colour"),
    "gearbox": ({"gearbox": ""}, "Auto or manual"),
    "budget": ({"monthly_budget_pence": None, "max_price_pence": None, "deposit_pence": None}, "No budget limit"),
    "sort": ({"sort": ""}, "Best match first"),
}


def start_conversation(user):
    with transaction.atomic():
        conversation = Conversation.objects.create(user=user)
        Message.objects.create(conversation=conversation, role=Message.Role.BOT, kind=Message.Kind.FORM,
                               body=GREETING, payload={"fields": FORM_FIELDS, "bonus": BONUS})
    return conversation


def pounds(pence):
    return f"£{pence / 100:,.0f}"


def colour_words(requirement):
    return "/".join(requirement.colours)


def describe(requirement):
    """The request back in a few words, so the salesperson can see what was understood."""
    parts = [f"{requirement.make} {requirement.model}".strip() or "any make"]
    if requirement.colours:
        parts.append(f"{colour_words(requirement)} only" if requirement.colour_only else colour_words(requirement))
    if requirement.gearbox:
        parts.append(requirement.get_gearbox_display().lower())
    return ", ".join(parts)


def active_filters(requirement):
    """What is currently narrowing the search, as chips the salesperson can remove one by one."""
    chips = []
    if requirement.make or requirement.model:
        chips.append({"key": "make_model", "label": f"{requirement.make} {requirement.model}".strip()})
    if requirement.colours:
        label = f"{colour_words(requirement)} only" if requirement.colour_only else f"prefers {colour_words(requirement)}"
        chips.append({"key": "colours", "label": label.capitalize()})
    if requirement.gearbox:
        chips.append({"key": "gearbox", "label": requirement.get_gearbox_display()})
    if requirement.max_price_pence:
        chips.append({"key": "budget", "label": f"Up to {pounds(requirement.max_price_pence)}"})
    elif requirement.monthly_budget_pence:
        deposit = f" + {pounds(requirement.deposit_pence)} deposit" if requirement.deposit_pence else ""
        chips.append({"key": "budget", "label": f"{pounds(requirement.monthly_budget_pence)} a month{deposit}"})
    if requirement.sort:
        chips.append({"key": "sort", "label": SORT_LABELS[requirement.sort]})
    return chips


def suggestions(requirement, candidates, options):
    """One-tap next steps, chosen from what was actually found. Each is sent back as an ordinary message."""
    ideas = []
    if requirement.colours and not requirement.colour_only and any(search.DIFFERENT_COLOUR in c.flags for c, _ in options):
        ideas.append(f"Only {requirement.colours[0]}")
    if requirement.colours and (requirement.colour_only or len(options) < rerank.OPTIONS):
        ideas.append("Any colour")
    if not requirement.colours:
        seen = [c.listing.colour_key for c in candidates if c.listing.colour_key]
        for colour in sorted(set(seen), key=seen.count, reverse=True)[:2]:
            if len(set(seen)) > 1:
                ideas.append(f"Only {colour}")
    if not requirement.gearbox and len({c.listing.gearbox_kind for c in candidates}) > 1:
        ideas += ["Automatic only", "Manual only"]
    if len(options) > 1:
        ideas += ["Best match first"] if requirement.sort else ["Cheapest first", "Lowest mileage"]
    if (requirement.make or requirement.model) and len(options) < rerank.OPTIONS:
        ideas.append("Any make")
    return ideas[:6]


def headline(requirement, candidates, options):
    wanted = describe(requirement)
    if not options:
        return f"Sorry, I couldn't find anything for {wanted} right now."
    if len(options) == 1:
        return f"I found 1 car for {wanted}."
    if len(candidates) > len(options):
        return f"Here are the best {len(options)} of {len(candidates)} cars for {wanted}."
    return f"I found {len(options)} cars for {wanted}."


def typed_summary(form):
    """How a submitted form reads in the thread."""
    return "\n".join(f"{field['label']}: {form[field['name']]}" for field in FORM_FIELDS
                     if str(form.get(field["name"]) or "").strip())


def reply(conversation, *, text="", form=None, remove=""):
    """Handle one message from the salesperson. Returns the new messages [user, bot]."""
    form = {k: v for k, v in (form or {}).items() if str(v or "").strip()}
    text = (text or "").strip()
    if remove:
        fields, parsed_by_ai, said = dict(REMOVALS[remove][0]), False, REMOVALS[remove][1]
    elif form:
        fields, parsed_by_ai, said = parse.from_form(form), False, typed_summary(form)
    else:
        (fields, parsed_by_ai), said = parse.parse_message(text), text

    with transaction.atomic():
        asked = Message.objects.create(conversation=conversation, role=Message.Role.USER, body=said)
        # every message carries the request forward: a follow-up only changes what it mentions
        previous = conversation.requirement
        requirement = Requirement(created_by=conversation.user)
        if previous:
            for name in (*Requirement.FIELDS, "notes"):
                setattr(requirement, name, getattr(previous, name))
        parse.apply_fields(requirement, fields)
        if remove == "make_model" or fields.get("make") == "":
            requirement.notes = ""  # the words that described the old car no longer apply
        elif not remove:
            words = form.get("make_model", "") if form else text
            requirement.notes = f"{requirement.notes} {words}".strip()[-500:]

        candidates, notes = search.find(requirement) if requirement.searchable or requirement.notes else ([], [])
        if not requirement.searchable and not search.described(candidates):
            conversation.requirement = None
            conversation.save()
            answer = Message.objects.create(conversation=conversation, role=Message.Role.BOT,
                                            body=CLEARED if remove else NEED_MORE, payload={"filters": []})
            return [asked, answer]

        requirement.save()
        emit_event("requirement.saved", {"requirement_id": str(requirement.id), "channel": "chatbot"},
                   actor=conversation.user)
        options, ranked_by_ai = rerank.choose(requirement, candidates)
        Match.objects.bulk_create([
            Match(requirement=requirement, listing=c.listing, rank=rank, score=c.score, reason=reason, flags=c.flags)
            for rank, (c, reason) in enumerate(options, 1)
        ])
        emit_event("matches.found", {"requirement_id": str(requirement.id), "options": len(options),
                                     "shortlist": len(candidates)}, actor=conversation.user)

        answer = Message.objects.create(
            conversation=conversation, role=Message.Role.BOT, kind=Message.Kind.OPTIONS,
            body=headline(requirement, candidates, options),
            payload={
                "notes": [*notes, ceiling_note(requirement)],
                "filters": active_filters(requirement),
                "suggestions": suggestions(requirement, candidates, options),
                "shortlisted": len(candidates),
                "deposit_pence": requirement.deposit_pence,
                "ai": {"parsed": parsed_by_ai, "ranked": ranked_by_ai},
                "vector_search": any(c.similarity is not None for c in candidates),
                # `customer` is the only part that may ever be sent on; `staff` never leaves the portal
                "cards": [{"customer": customer_card(c.listing),
                           "staff": staff_card(c.listing, reason, c.flags, c.score, c.similarity)}
                          for c, reason in options],
            },
        )
        conversation.requirement = requirement
        conversation.title = describe(requirement)[:120]  # the list always shows the current request
        conversation.save()
    return [asked, answer]
