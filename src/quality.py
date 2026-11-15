"""Reversible reclassification of cached direct-source matches. No item deletion."""
from __future__ import annotations

from . import config, db
from .dedupe import relevance_score
from .entity_profiles import profile_for


def reclassify(apply: bool = False, oshi_id: int | None = None) -> dict:
    changed = excluded = 0
    examples = []
    with db.session() as s:
        owners = s.query(db.Oshi)
        if oshi_id is not None:
            owners = owners.filter(db.Oshi.id == oshi_id)
        for owner in owners.all():
            profile = profile_for(owner.name) or {}
            aliases = list(dict.fromkeys([*owner.aliases, *profile.get("aliases", [])]))
            for item in s.query(db.Item).filter(db.Item.oshi_id == owner.id).all():
                # Captions were not retained. Restrict repair to direct-source
                # results; broad-search records cannot be safely reconstructed.
                if item.source_api not in {"books_book", "books_cd", "books_dvd", "kobo"}:
                    continue
                score = relevance_score({"title": item.title, "author_or_artist": item.author_or_artist},
                                        owner.name, aliases, profile.get("anchors", []))
                hidden = int(score < config.SCORE_THRESHOLD)
                if hidden != item.quality_excluded or score != item.relevance:
                    changed += 1
                    excluded += hidden
                    if len(examples) < 20:
                        examples.append({"oshi": owner.name, "item_code": item.item_code,
                                         "title": item.title, "excluded": bool(hidden)})
                    item.quality_excluded = hidden
                    item.relevance = score
        if apply:
            s.commit()
    return {"changed": changed, "excluded": excluded, "applied": apply, "examples": examples}


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    print(json.dumps(reclassify(parser.parse_args().apply)))
