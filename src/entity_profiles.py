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
    profile = PROFILES.get(_key(name))
    return dict(profile) if profile else None
