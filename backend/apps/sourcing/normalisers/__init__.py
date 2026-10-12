"""One normaliser per platform: the runner's raw record -> the fields of a Listing."""

from . import bca, carwow, manheim, motorway

NORMALISERS = {
    "carwow": carwow.normalise,
    "manheim": manheim.normalise,
    "bca": bca.normalise,
    "motorway": motorway.normalise,
}


def normalise(platform, record):
    return NORMALISERS[platform](record)
