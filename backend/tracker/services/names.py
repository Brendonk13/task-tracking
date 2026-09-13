"""Adjective-animal session name generator, e.g. ``cool-willow``."""

from random import Random

ADJECTIVES = [
    "amber", "bold", "brave", "bright", "calm", "clever", "cool", "crisp",
    "eager", "fair", "gentle", "glad", "golden", "happy", "jolly", "keen",
    "kind", "lively", "lucky", "merry", "mild", "neat", "noble", "proud",
    "quick", "quiet", "rapid", "shy", "silver", "sleek", "smart", "snug",
    "soft", "sunny", "swift", "tidy", "vivid", "warm", "wild", "wise",
]

ANIMALS = [
    "badger", "bear", "beaver", "bison", "crane", "deer", "dolphin", "eagle",
    "falcon", "ferret", "finch", "fox", "gecko", "hare", "heron", "ibis",
    "jaguar", "koala", "lemur", "lynx", "marten", "moose", "newt", "otter",
    "owl", "panda", "parrot", "puffin", "quail", "raven", "robin", "seal",
    "sparrow", "stoat", "swan", "tiger", "toad", "walrus", "willow", "wren",
]

rng = Random()


def generate_name(rng: Random | None = None) -> str:
    rng = rng if rng is not None else globals()["rng"]
    return f"{rng.choice(ADJECTIVES)}-{rng.choice(ANIMALS)}"
