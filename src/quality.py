"""Reclassify every medium without changing visibility or deleting items."""
from __future__ import annotations

from . import config, db
from .dedupe import relevance_score
from .entity_profiles import profile_for


def reclassify(apply: bool = False, oshi_id: int | None = None) -> dict:
    changed = unverified = 0
    examples = []
    with db.session() as s:
        owners = s.query(db.Oshi)
        if oshi_id is not None:
            owners = owners.filter(db.Oshi.id == oshi_id)
        for owner in owners.all():
            profile = profile_for(owner.name) or {}
            aliases = list(dict.fromkeys([*owner.aliases, *profile.get("aliases", [])]))
            for item in s.query(db.Item).filter(db.Item.oshi_id == owner.id).all():
                score = relevance_score({"title": item.title, "author_or_artist": item.author_or_artist,
                                         "caption": item.caption or ""},
                                        owner.name, aliases, profile.get("anchors", []))
                uncertain = score < config.SCORE_TITLE_MATCH
                if uncertain:
                    unverified += 1
                if score != item.relevance:
                    changed += 1
                    if len(examples) < 20:
                        examples.append({"oshi": owner.name, "item_code": item.item_code,
                                         "title": item.title, "unverified": uncertain})
                    item.relevance = score
        if apply:
            s.commit()
    return {"changed": changed, "excluded": 0, "unverified": unverified,
            "applied": apply, "examples": examples}


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(json.dumps(reclassify(parser.parse_args().apply)))
