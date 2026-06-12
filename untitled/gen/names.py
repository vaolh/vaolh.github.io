#################################################
################ NAME GENERATOR #################
#################################################

import re

### REPLICATION FILE: names.py
### PYTHON VERSION:   3.13+
### LAST EDIT:        2026-06-11 by vao2116

"""Seeded fantasy name generation for the world and its nations.

Names are assembled from weighted syllable banks so that a fixed seed always
produces the same set of pronounceable, vaguely Tolkienesque names. The slug
form derived from each name is the identifier that links a country polygon on
the map to its wiki article.
"""

### Syllable banks combined into nation and world names.
onsets = ["", "br", "th", "kr", "v", "n", "s", "m", "d", "g", "l", "r",
          "z", "f", "k", "t", "h", "ph", "dr", "tr", "sk", "vh", " qh".strip()]
nuclei = ["a", "e", "i", "o", "u", "ae", "ei", "ou", "ya", "yo", "ia", "au"]
codas = ["", "n", "r", "s", "l", "th", "rn", "sk", "ld", "rth", "ndor",
         "mar", "gard", "wyn", "dor", "heim", "var", "ros", "thal"]

### Suffixes appended to a minority of names to vary their cadence.
realm_suffixes = ["ia", "land", "mark", "reach", "wold", "moor", "vale"]


def _slugify(name):
    """Return a url-safe lowercase slug for a generated name."""
    slug = name.lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def _make_word(rng, min_syllables, max_syllables):
    """Assemble one capitalised word from the syllable banks."""
    syllable_count = rng.integers(min_syllables, max_syllables + 1)
    word = ""
    for index in range(syllable_count):
        onset = rng.choice(onsets) if index > 0 or rng.random() < 0.7 else ""
        nucleus = rng.choice(nuclei)
        coda = rng.choice(codas) if index == syllable_count - 1 else ""
        word += onset + nucleus + coda
    if rng.random() < 0.3:
        word += rng.choice(realm_suffixes)
    return word.capitalize()


def generate_names(count, rng):
    """Return ``count`` unique (name, slug) pairs drawn from a seeded stream."""
    names = []
    seen = set()
    while len(names) < count:
        word = _make_word(rng, 2, 3)
        slug = _slugify(word)
        if len(slug) < 3 or slug in seen:
            continue
        seen.add(slug)
        names.append((word, slug))
    return names


def generate_world_name(rng):
    """Return a single proper name for the world itself."""
    return _make_word(rng, 2, 3)
