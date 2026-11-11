"""
Parser for pre-2013 fixed-width plain-text Form 13F-HR information tables
(the format used inside the .txt submission file, e.g. Chase Manhattan
Corp's 1999 filings).

Usage:
    python parse_13f_text_chase.py path/to/0000019617-99-000119.txt
"""

import re
import sys
from collections import defaultdict

# First row of a holding: optional leading "0", optional whitespace,
# then a NAME that must START with a letter (this is what distinguishes
# it from a continuation row, which starts with a digit), then 2+ spaces,
# an 6-9 character alnum CUSIP, then VALUE and SHARES.
FIRST_ROW = re.compile(
    r'^\s*0?\s*'
    r'(?P<name>[A-Z][A-Z0-9&.,\'\-/ ]{4,39}?)\s{2,}'
    r'(?P<cusip>[A-Z0-9]{6,9})\s+'
    r'(?P<value>[\d,]+)\s+'
    r'(?P<shares>[\d,]+)\s+'
)

# Continuation row: "0" then a big gap then VALUE and SHARES, no name/cusip.
CONT_ROW = re.compile(
    r'^0\s{10,}'
    r'(?P<value>[\d,]+)\s+'
    r'(?P<shares>[\d,]+)\s+'
)

PAGE_NOISE = re.compile(
    r'(RUN DATE/TIME|FORM 13F SUMMARY|S E C   USE   ONLY|'
    r'ITEM  1  &  2|NAME AND CLASS OF ISSUER|FOR QTR ENDING|'
    r'^\s*<PAGE>|^\s*<TABLE>|^\s*<C>)'
)


def parse_file(path):
    with open(path, "r", errors="ignore") as f:
        lines = f.readlines()

    holdings = defaultdict(lambda: {"name": None, "value": 0, "shares": 0, "rows": 0})
    current_cusip = None
    unmatched = []

    for i, line in enumerate(lines):
        if PAGE_NOISE.search(line):
            continue

        # block separator line, e.g. "- -" or "-"
        if line.strip().startswith('-') and len(line.strip()) < 5:
            current_cusip = None
            continue

        m = FIRST_ROW.match(line)
        if m:
            cusip = m.group("cusip")
            current_cusip = cusip
            holdings[cusip]["name"] = m.group("name").strip()
            holdings[cusip]["value"] += int(m.group("value").replace(",", ""))
            holdings[cusip]["shares"] += int(m.group("shares").replace(",", ""))
            holdings[cusip]["rows"] += 1
            continue

        m = CONT_ROW.match(line)
        if m and current_cusip:
            holdings[current_cusip]["value"] += int(m.group("value").replace(",", ""))
            holdings[current_cusip]["shares"] += int(m.group("shares").replace(",", ""))
            holdings[current_cusip]["rows"] += 1
            continue

        # line looks like it might be data (starts with 0 or has digits
        # in a value-like position) but matched nothing -- flag it
        stripped = line.strip()
        if stripped and (stripped[0] == '0' or re.match(r'^[A-Z0-9]', stripped)):
            if re.search(r'\d,\d{3}|\d\s+\d', stripped):
                unmatched.append((i + 1, line.rstrip("\n")))

    return holdings, unmatched


def main():
    if len(sys.argv) != 2:
        print("Usage: python parse_13f_text_chase.py path/to/filing.txt")
        sys.exit(1)

    holdings, unmatched = parse_file(sys.argv[1])
    if not holdings:
        print("No holdings parsed. Paste ~30 lines of raw text (one full "
              "issuer block) so the pattern can be adjusted.")
        return

    ranked = sorted(holdings.items(), key=lambda kv: kv[1]["value"], reverse=True)

    print(f"Parsed {len(holdings)} distinct CUSIPs, "
          f"{sum(h['rows'] for h in holdings.values())} total rows.\n")

    print("=== TOP 15 BY AGGREGATE VALUE (in thousands, per table header) ===")
    for cusip, h in ranked[:15]:
        print(f"  {h['name']:<35} {cusip}  VALUE={h['value']:>12,}  "
              f"SHARES={h['shares']:>12,}  rows={h['rows']}")

    smallest = min(holdings.items(), key=lambda kv: kv[1]["shares"])
    print("\n=== SMALLEST AGGREGATE BY SHARE COUNT ===")
    print(f"  {smallest[1]['name']} {smallest[0]} SHARES={smallest[1]['shares']:,}")

    if unmatched:
        print(f"\n=== WARNING: {len(unmatched)} lines looked like data but "
              f"didn't match either pattern (possible undercounts) ===")
        print("First 10 unmatched lines (line number: text):")
        for lineno, text in unmatched[:10]:
            print(f"  {lineno}: {text}")
        if len(unmatched) > 10:
            print(f"  ... and {len(unmatched) - 10} more")


if __name__ == "__main__":
    main()
