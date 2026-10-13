"""Normalised matching keys. Platforms word the same thing differently ('Mercedes', 'MERCEDES-BENZ',
'Manual Transmission'), so filters compare these keys, never the raw text."""

import re

MAKE_ALIASES = {
    "mercedes": "mercedesbenz", "merc": "mercedesbenz", "mercedesamg": "mercedesbenz",
    "vw": "volkswagen", "volkswagon": "volkswagen",
    "rangerover": "landrover", "landy": "landrover",
    "beemer": "bmw", "bimmer": "bmw",
    "vauxhal": "vauxhall", "citreon": "citroen", "ds": "dsautomobiles",
    "alfa": "alfaromeo", "aston": "astonmartin", "rolls": "rollsroyce",
}
COLOURS = ("black", "white", "grey", "silver", "blue", "red", "green", "yellow", "orange", "brown", "beige",
           "gold", "purple", "bronze", "pink")
NUMBER_WORDS = {"one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6", "seven": "7",
                "eight": "8"}
AUTO_WORDS = ("auto", "dsg", "cvt", "tronic", "semi", "steptronic", "powershift")


def tokens(text):
    return re.findall(r"[a-z0-9]+", str(text or "").lower())


def make_key(make):
    key = "".join(tokens(make))
    return MAKE_ALIASES.get(key, key)


def gearbox_kind(gearbox):
    """'Manual Transmission' -> 'manual'; 'Auto/Manual Mode', 'Semi-automatic', 'DSG' -> 'auto'."""
    text = str(gearbox or "").lower()
    if any(word in text for word in AUTO_WORDS):
        return "auto"
    return "manual" if "manual" in text else ""


def colour_key(colour):
    """'Metallic GREY' -> 'grey'; unknown -> ''."""
    words = tokens(str(colour or "").lower().replace("gray", "grey"))
    return next((c for c in COLOURS if c in words), "")


def model_matches(wanted, model, trim=""):
    """Does a listing's model (and trim) fit the model a customer asked for?

    'A Class' fits 'A-Class'; 'CLA' fits 'CLA 220 AMG'; 'A1' does not fit 'A180'.
    """
    want, have = [NUMBER_WORDS.get(word, word) for word in tokens(wanted)], tokens(f"{model} {trim}")
    if not want:
        return True
    if have[:len(want)] == want:
        return True
    joined = "".join(want)
    return len(joined) >= 4 and "".join(have).startswith(joined)
