"""
Regenerates backend/data/category_usage.json - the measured table the
occasion model scores against.

    python -m backend.build_occasion_model

Reads dataset/kaggle_fashion/styles.csv (the Myntra catalogue already
in this project: 44,446 items, each labelled with a garment type and a
"usage" - Casual, Formal, Ethnic, Sports, Party, Smart Casual,
Travel) and writes, per garment type, the share of items carrying each
usage.

Why a generated file rather than reading the CSV at request time: the
CSV is 44k rows and lives in dataset/, which is gitignored and absent
on a fresh clone. The generated table is ~2KB, is committed, and keeps
recommendations working on a machine that has never downloaded the
dataset.

MINIMUM_ROWS exists because a share computed from four examples is
noise, not a measurement - Lehenga Choli has exactly 4 rows here, and
letting that through would put a made-up number on the same footing as
Jeans' 609. Types below the threshold are omitted, and
occasion_model.EXPLICIT_PROFILES covers the few that matter.
"""

import collections
import csv
import json
import os
import sys


MINIMUM_ROWS = 5

ARTICLE_TYPES_OF_INTEREST = [
    "Tshirts", "Shirts", "Tops", "Jeans", "Trousers", "Leggings",
    "Track Pants", "Shorts", "Skirts", "Kurtas", "Kurtis", "Sarees",
    "Dresses", "Jackets", "Blazers", "Sweaters", "Sweatshirts",
    "Churidar", "Salwar", "Patiala", "Tunics", "Capris", "Waistcoat",
    "Dupatta", "Lehenga Choli", "Formal Shoes", "Casual Shoes",
    "Heels", "Sports Shoes", "Flats", "Sandals",
]


def build(styles_path, output_path):

    with open(styles_path, encoding="utf-8", errors="replace") as handle:
        rows = list(csv.DictReader(handle))

    print(f"Read {len(rows)} catalogue rows from {styles_path}")

    table = {}
    skipped = []

    for article_type in ARTICLE_TYPES_OF_INTEREST:

        matching = [row for row in rows if row.get("articleType") == article_type]

        if len(matching) < MINIMUM_ROWS:
            skipped.append((article_type, len(matching)))
            continue

        usage_counts = collections.Counter(
            row["usage"] for row in matching
            if row.get("usage") not in ("", "NA", None)
        )

        total = sum(usage_counts.values())

        if not total:
            skipped.append((article_type, 0))
            continue

        table[article_type] = {
            usage: round(count / total, 3)
            for usage, count in usage_counts.most_common()
        }

        summary = "  ".join(
            f"{usage} {count / total:.0%}"
            for usage, count in usage_counts.most_common(3)
        )
        print(f"  {article_type:15s} n={len(matching):5d}  {summary}")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(table, handle, indent=1)

    print(f"\nWrote {len(table)} garment profiles to {output_path}")

    if skipped:
        print("\nToo few examples to measure (left to EXPLICIT_PROFILES):")
        for article_type, count in skipped:
            print(f"  {article_type}: {count} row(s)")

    return table


def main():

    here = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(here)

    styles_path = os.path.join(
        project_root, "dataset", "kaggle_fashion", "styles.csv"
    )

    if not os.path.isfile(styles_path):
        print(
            f"Could not find {styles_path}.\n"
            "The dataset folder is gitignored, so a fresh clone will not "
            "have it. The committed backend/data/category_usage.json is "
            "already usable - this script is only needed to regenerate it."
        )
        return 1

    build(styles_path, os.path.join(here, "data", "category_usage.json"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
