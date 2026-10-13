"""Turn what a salesperson typed (the form, or a sentence) into requirement fields.

AI is used when it is configured; otherwise the rules below do the job. Either way money values are
only ever taken from what was typed, never guessed.
"""

import re

from apps.ai.client import AiUnavailable, ai_enabled, complete_json
from apps.listings.models import Listing
from apps.listings.services.keys import COLOURS, NUMBER_WORDS, make_key, tokens

from ..models import Requirement

PROMPT_VERSION = "requirement-parse-v1"

MAKES = (
    "Abarth", "Alfa Romeo", "Aston Martin", "Audi", "Bentley", "BMW", "BYD", "Citroen", "Cupra", "Dacia",
    "DS Automobiles", "Fiat", "Ford", "Honda", "Hyundai", "Jaguar", "Jeep", "Kia", "Land Rover", "Lexus",
    "Maserati", "Mazda", "Mercedes-Benz", "MG", "MINI", "Mitsubishi", "Nissan", "Peugeot", "Polestar", "Porsche",
    "Renault", "SEAT", "Skoda", "Smart", "Subaru", "Suzuki", "Tesla", "Toyota", "Vauxhall", "Volkswagen", "Volvo",
)
SPOKEN_MAKES = {"mercedes": "Mercedes-Benz", "merc": "Mercedes-Benz", "vw": "Volkswagen", "range rover": "Land Rover",
                "alfa": "Alfa Romeo", "aston": "Aston Martin"}
MONEY = r"£?\s*(\d[\d,]*(?:\.\d+)?)\s*(k\b)?"
MONTH_WORDS = r"(?:pm\b|p/m|pcm\b|per month|a month|/ ?month|monthly|each month)"
STOP_WORDS = {*COLOURS, "auto", "automatic", "manual", "with", "in", "under", "max", "up", "to", "for", "and",
              "budget", "around", "about", "please", "deposit", "or", "any", "colour", "color", "the", "an",
              "by", "asap", "need", "needed", "want", "looking", "below", "over", "petrol", "diesel", "electric",
              "hybrid", "car", "cars", "something", "ideally", "preferably", "month", "monthly"}
# "only grey", "must be black": the colour is a hard rule, not a preference
INSIST = r"\b(only|just|must|strictly|has to be|have to be|nothing but|no other)\b"
FILLER = {"in", "please", "colour", "color", "one", "ones", "a", "the", "car", "cars", "only", "just", "must", "be",
          "strictly", "show", "me", "want", "i", "it", "them", "that", "those", "is", "are", "ok", "or", "and"}
SORTS = (("cheap|lowest price|low price|price first", "price"), ("newest|latest|most recent|youngest", "year"),
         ("low mileage|lowest mileage|least miles|fewest miles", "mileage"),
         ("best match|default order|recommended", ""))
NOTHING = {"", "none", "no", "n/a", "na", "nil", "-", "any", "either", "not sure", "dont mind", "don't mind"}


def to_pence(value):
    """'£2,000', '2k', '300pm', 300 -> pence; 'none' or nothing typed -> None."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(round(value * 100)) if value > 0 else None
    found = re.search(MONEY, str(value), re.I)
    if not found:
        return None
    pounds = float(found.group(1).replace(",", "")) * (1000 if found.group(2) else 1)
    return int(round(pounds * 100)) if pounds > 0 else None


def known_makes():
    """{make key: display name} for every make we know, including whatever is in stock."""
    makes = {make_key(name): name for name in MAKES}
    for name in Listing.objects.exclude(make="").values_list("make", flat=True).distinct():
        makes.setdefault(make_key(name), name.title() if name.isupper() else name)
    return makes


def find_make(words, makes):
    """(index, length, display name) of the first make named in a list of words, or None."""
    for i in range(len(words)):
        for size in (2, 1):
            spoken = " ".join(words[i:i + size])
            if len(words[i:i + size]) < size:
                continue
            name = SPOKEN_MAKES.get(spoken) or makes.get(make_key(spoken))
            if name:
                return i, size, name
    return None


def split_make_model(text):
    """'BMW 1 Series' -> ('BMW', '1 Series'); 'Qashqai' -> ('Nissan', 'Qashqai') when it is in stock."""
    words = [NUMBER_WORDS.get(word, word) for word in tokens(text)]
    found = find_make(words, known_makes())
    if found:
        i, size, name = found
        model = []
        for word in words[i + size:i + size + 3]:
            if word in STOP_WORDS:
                break
            model.append(word)
        return name, " ".join(model[:2]).title() if model else ""
    for make, model in Listing.objects.exclude(model="").values_list("make", "model").distinct():
        first = (tokens(model) or [""])[0]
        if len(first) >= 3 and first in words:
            return (make.title() if make.isupper() else make), first.title()
    return "", ""


def gearbox_of(text):
    text = str(text or "").lower()
    if re.search(r"\bauto(matic)?\b", text) and not re.search(r"\b(or|either)\b.*\bmanual\b|\bmanual\b.*\bor\b", text):
        return "auto"
    if re.search(r"\bmanual\b", text) and not re.search(r"\bauto", text):
        return "manual"
    return ""


def colours_of(text):
    words = tokens(str(text or "").lower().replace("gray", "grey"))
    return [c for c in COLOURS if c in words]


def from_form(form):
    """The six form fields -> requirement fields. Blank answers are simply left out."""
    fields = {}
    make, model = split_make_model(form.get("make_model"))
    if not make and str(form.get("make_model") or "").strip().lower() not in NOTHING:
        model = str(form.get("make_model")).strip()[:80]  # keep what was typed even if we do not know the make
    if make or model:
        fields.update(make=make, model=model)
    if colours_of(form.get("colour")):
        fields["colours"] = colours_of(form.get("colour"))
        fields["colour_only"] = bool(re.search(INSIST, str(form.get("colour")).lower()))
    if gearbox_of(form.get("gearbox")):
        fields["gearbox"] = gearbox_of(form.get("gearbox"))
    for name, key in (("deposit", "deposit_pence"), ("monthly_budget", "monthly_budget_pence"),
                      ("max_price", "max_price_pence")):
        if to_pence(form.get(name)) is not None:
            fields[key] = to_pence(form.get(name))
    needed = str(form.get("needed_by") or "").strip()
    if needed.lower() not in NOTHING:
        fields["needed_by"] = needed[:120]
    return fields


LABELS = (("make_model", ("make", "model")), ("colour", ("colour", "color")),
          ("gearbox", ("auto", "manual", "gearbox", "transmission")), ("deposit", ("deposit",)),
          ("monthly_budget", ("monthly", "budget")), ("needed_by", ("when", "need")))


def labelled_form(text):
    """The form pasted back with answers ('Make & Model: BMW 1 Series ...') -> form dict, else None."""
    form = {}
    for line in text.splitlines():
        label, _, answer = line.partition(":")
        if not answer.strip():
            continue
        label = label.lower()
        for name, words in LABELS:
            if name not in form and any(word in label for word in words):
                form[name] = answer.strip()
                break
    return form if len(form) >= 2 else None


def from_text(text):
    """A plain sentence -> requirement fields, by rules (used when AI is off or fails)."""
    form = labelled_form(text)
    if form:
        return from_form(form)
    fields, rest = {}, text.lower()

    def take(pattern, key):
        nonlocal rest
        found = re.search(pattern, rest, re.I)
        if found:
            fields[key] = to_pence("".join(g or "" for g in found.groups()))
            rest = rest.replace(found.group(0), " ", 1)

    take(rf"deposit(?: of| is)?\s*{MONEY}", "deposit_pence")
    if "deposit_pence" not in fields:
        take(rf"{MONEY}\s*deposit", "deposit_pence")
    take(rf"{MONEY}\s*{MONTH_WORDS}", "monthly_budget_pence")
    if "monthly_budget_pence" not in fields:
        take(rf"monthly(?: budget)?(?: of| is)?\s*{MONEY}", "monthly_budget_pence")
    take(rf"(?:under|max(?:imum)?|up to|below|budget(?: of| is)?|less than)\s*{MONEY}", "max_price_pence")
    fields = {k: v for k, v in fields.items() if v is not None}

    if re.search(r"\bany colou?r\b", rest):
        fields.update(colours=[], colour_only=False)
    elif colours_of(rest):
        fields["colours"] = colours_of(rest)
        # a message that is nothing but a colour ("grey", "in black please") means that colour only
        nothing_else = not [w for w in tokens(rest.replace("gray", "grey")) if w not in COLOURS and w not in FILLER]
        fields["colour_only"] = bool(re.search(INSIST, rest)) or nothing_else
    for pattern, order in SORTS:
        if re.search(pattern, rest):
            fields["sort"] = order
            break
    if gearbox_of(rest):
        fields["gearbox"] = gearbox_of(rest)
    make, model = split_make_model(rest)
    if make or model:
        fields.update(make=make, model=model)
    elif re.search(r"\bany (make|car|model|brand)\b|\banything\b", rest):
        fields.update(make="", model="")  # "any make" drops the car asked for earlier
    return fields


SYSTEM = """You read what a car salesperson typed about what their customer wants and return JSON only:
{"make": str|null, "model": str|null, "colours": [str]|null, "gearbox": "auto"|"manual"|null,
 "deposit_gbp": number|null, "monthly_budget_gbp": number|null, "max_price_gbp": number|null,
 "needed_by": str|null}
Rules:
- Use null for anything not stated. Never guess or estimate a money value.
- make is the manufacturer in its usual spelling (e.g. "Mercedes-Benz", "Volkswagen"); model is the model only.
- colours are plain lower-case colour words. An explicit "any colour" is [].
- An explicit "any make" / "any car" is "make": "" and "model": "".
- max_price_gbp is a cash price limit; monthly_budget_gbp is a payment per month. Do not convert one to the other.
- This may be a follow-up that changes an earlier request: return only what this message states."""


def from_ai(text):
    data = complete_json("requirement-parse", PROMPT_VERSION, SYSTEM, text[:2000])
    if not isinstance(data, dict):
        raise AiUnavailable("AI returned something that is not an object.")
    fields = {}
    if data.get("make") or data.get("model"):
        fields.update(make=str(data.get("make") or "")[:60], model=str(data.get("model") or "")[:80])
    elif data.get("make") == "":
        fields.update(make="", model="")
    if isinstance(data.get("colours"), list):
        fields["colours"] = colours_of(" ".join(str(c) for c in data["colours"]))
    if data.get("gearbox") in ("auto", "manual"):
        fields["gearbox"] = data["gearbox"]
    for name, key in (("deposit_gbp", "deposit_pence"), ("monthly_budget_gbp", "monthly_budget_pence"),
                      ("max_price_gbp", "max_price_pence")):
        if isinstance(data.get(name), (int, float)) and to_pence(data[name]) is not None:
            fields[key] = to_pence(data[name])
    if data.get("needed_by"):
        fields["needed_by"] = str(data["needed_by"])[:120]
    return fields


def parse_message(text):
    """(fields, used_ai) for one chat message.

    Short refinements ("only grey", "cheapest first") are understood by the rules alone: instant, free and
    always the same. Longer sentences go to the AI, with the rules still deciding "only" and the sort order.
    """
    ruled = from_text(text)
    if not ai_enabled() or labelled_form(text) or (ruled and len(tokens(text)) <= 4):
        return ruled, False
    try:
        fields = from_ai(text)
    except AiUnavailable:
        return ruled, False
    for name in ("colour_only", "sort"):
        if name in ruled:
            fields[name] = ruled[name]
    if "colours" in ruled and "colours" not in fields:
        fields["colours"] = ruled["colours"]
    return fields, True


def apply_fields(requirement, fields):
    """Lay newly stated fields over a requirement (a follow-up only changes what it mentions)."""
    for name in Requirement.FIELDS:
        if name in fields:
            setattr(requirement, name, fields[name])
    if "make" in fields and "model" not in fields:
        requirement.model = ""
    if "colours" in fields and "colour_only" not in fields:
        requirement.colour_only = False  # a newly stated colour is a preference unless they insist
    if not requirement.colours:
        requirement.colour_only = False
    return requirement
