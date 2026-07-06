"""CLI: 推し名 → 統合結果JSON（Phase 1完了条件の確認用）。

usage: python -m src.cli search "推し名" [--alias 別名 ...] [--save]
"""
from __future__ import annotations

import argparse
import json
import sys

from .search_service import find_or_create_oshi, save_results, search_all


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("search")
    sp.add_argument("name")
    sp.add_argument("--alias", action="append", default=[])
    sp.add_argument("--save", action="store_true")
    args = p.parse_args()

    def progress(msg, i, total):
        print(f"[{i}/{total}] {msg}", file=sys.stderr)

    result = search_all(args.name, args.alias, progress=progress)
    if args.save:
        oshi_id, _ = find_or_create_oshi(args.name, args.alias)
        n = save_results(oshi_id, result["records"])
        print(f"saved: oshi_id={oshi_id} new_items={n}", file=sys.stderr)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
