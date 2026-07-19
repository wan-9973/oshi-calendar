"""Shared entity profiles for ambiguous oshi names.

Profiles are reusable across users.  They contain only public entity-identifying
terms and never store user data.
"""
from __future__ import annotations

import unicodedata


def _key(value: str) -> str:
    return unicodedata.normalize("NFKC", value or "").casefold().strip()


PROFILES = {
    "hana": {
        "canonical_name": "HANA",
        "aliases": [],
        "anchors": [
            "BMSG", "B-RAVE", "No No Girls", "ちゃんみな",
            "CHIKA", "NAOKO", "JISOO", "YURI", "MOMOKA", "KOHARU", "MAHINA",
            "ROSE", "Drop", "Blue Jeans", "Burning Flower", "Cold Night",
        ],
    },
    "米津": {
        "canonical_name": "米津玄師",
        "aliases": ["Kenshi Yonezu"],
        "anchors": ["米津玄師", "Kenshi Yonezu", "IRIS OUT", "JANE DOE"],
    },
}


def profile_for(name: str) -> dict | None:
    name_key = _key(name)
    profile = PROFILES.get(name_key)
    if profile is None:
        # Once an ambiguous search name has been resolved, the DB stores the
        # canonical name.  Keep the same public profile available on later
        # page views and crawls without rewriting existing rows.
        profile = next(
            (candidate for candidate in PROFILES.values()
             if _key(candidate.get("canonical_name", "")) == name_key),
            None,
        )
    return dict(profile) if profile else None
