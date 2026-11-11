"""
Analyzes two consecutive 13F-HR plain-text filings for the specific
figures a benchmark question asks for:

  - top issuers by AGGREGATE value in each file (to identify "the issuer")
  - for a chosen CUSIP: every individual row, in order, with its
    PHYSICAL ROW INDEX (position counting from the first data row of
    the whole table) -- so you can find the smallest row and cite
    exactly where it sits
  - the smallest-row comparison and implied $/share calculations the
    prompt asks for

Usage:
    # Step 1: see the top holdings in each file, to identify "the issuer"
    # (the one with largest AGGREGATE value in the LATER filing)
    python analyze_13f_text_chase.py earlier.txt later.txt

    # Step 2: once you know the CUSIP, get the full row-level breakdown
    python analyze_13f_text_chase.py earlier.txt later.txt --cusip 36960410
"""

import re
import sys
import argparse
from collections import defaultdict

FIRST_ROW = re.compile(
    r'^\s*0?\s*'
    r'(?P<name>[A-Z][A-Z0-9&.,\'\-/ ]{4,39}?)\s{2,}'
    r'(?P<cusip>[A-Z0-9]{6,9})\s+'
    r'(?P<value>[\d,]+)\s+'
    r'(?P<shares>[\d,]+)\s+'
)
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
VALUE_HEADER = re.compile(r'FAIR MKT\s*\n?\s*VALUE\s*\n?\s*\(([^)]+)\)', re.MULTILINE)


def find_value_unit(raw_text):
    """Find the VALUE column's unit label from the header block.

    The header has TWO parenthesized tokens close together -- e.g.
    "AUTHORITY   (SHARES)" (an unrelated column header) and, on the
    NEXT line, "(000'S)       AMOUNT" (the real VALUE unit). Only
    match a parenthesized token that sits on the SAME LINE as, and
    immediately before, the word AMOUNT -- that's what distinguishes
    the real unit from the decoy.
    """
    m = re.search(r"\(([^)]{1,15})\)[ \t]+AMOUNT", raw_text)
    if m:
        return m.group(1).strip()
    return None


def parse_file(path):
    """Returns (rows, header_unit) where rows is a list of dicts:
    {global_row_index, cusip, name, value, shares}
    global_row_index counts every data row (first + continuation) in
    the order they appear, starting at 1 for the first data row.
    """
    with open(path, "r", errors="ignore") as f:
        raw = f.read()
    header_unit = find_value_unit(raw)

    lines = raw.splitlines(keepends=True)
    rows = []
    current_cusip = None
    current_name = None
    row_idx = 0

    for line in lines:
        if PAGE_NOISE.search(line):
            continue
        if line.strip().startswith('-') and len(line.strip()) < 5:
            current_cusip = None
            current_name = None
            continue

        m = FIRST_ROW.match(line)
        if m:
            row_idx += 1
            current_cusip = m.group("cusip")
            current_name = m.group("name").strip()
            rows.append({
                "row": row_idx,
                "cusip": current_cusip,
                "name": current_name,
                "value": int(m.group("value").replace(",", "")),
                "shares": int(m.group("shares").replace(",", "")),
            })
            continue

        m = CONT_ROW.match(line)
        if m and current_cusip:
            row_idx += 1
            rows.append({
                "row": row_idx,
                "cusip": current_cusip,
                "name": current_name,
                "value": int(m.group("value").replace(",", "")),
                "shares": int(m.group("shares").replace(",", "")),
            })

    return rows, header_unit


def aggregate(rows):
    agg = defaultdict(lambda: {"name": None, "value": 0, "shares": 0, "rows": 0})
    for r in rows:
        a = agg[r["cusip"]]
        a["name"] = r["name"]
        a["value"] += r["value"]
        a["shares"] += r["shares"]
        a["rows"] += 1
    return agg


def show_top(label, rows, n=15):
    agg = aggregate(rows)
    ranked = sorted(agg.items(), key=lambda kv: kv[1]["value"], reverse=True)
    print(f"\n=== {label}: TOP {n} BY AGGREGATE VALUE ===")
    for cusip, h in ranked[:n]:
        print(f"  {h['name']:<35} {cusip}  VALUE={h['value']:>12,}  "
              f"SHARES={h['shares']:>12,}  rows={h['rows']}")


def analyze_cusip(label, rows, header_unit, cusip):
    matches = [r for r in rows if r["cusip"] == cusip]
    if not matches:
        print(f"\n=== {label}: CUSIP {cusip} not found ===")
        return None

    total_value = sum(r["value"] for r in matches)
    total_shares = sum(r["shares"] for r in matches)
    smallest = min(matches, key=lambda r: r["shares"])

    print(f"\n=== {label}: {matches[0]['name']} ({cusip}) ===")
    print(f"  VALUE-column unit (from header): {header_unit}")
    print(f"  Aggregate VALUE   = {total_value:,}")
    print(f"  Aggregate SHARES  = {total_shares:,}")
    print(f"  Number of rows    = {len(matches)}")
    print(f"  All rows (physical row index, VALUE, SHARES):")
    for r in matches:
        marker = "  <-- SMALLEST BY SHARES" if r is smallest else ""
        print(f"    row {r['row']:>6}: VALUE={r['value']:>10,}  SHARES={r['shares']:>10,}{marker}")

    return {
        "total_value": total_value,
        "total_shares": total_shares,
        "num_rows": len(matches),
        "smallest_row": smallest,
        "header_unit": header_unit,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("earlier")
    ap.add_argument("later")
    ap.add_argument("--cusip", help="CUSIP to analyze in detail")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    earlier_rows, earlier_unit = parse_file(args.earlier)
    later_rows, later_unit = parse_file(args.later)

    print(f"Earlier file ({args.earlier}): {len(earlier_rows)} data rows parsed. "
          f"VALUE unit detected: {earlier_unit!r}")
    print(f"Later file   ({args.later}): {len(later_rows)} data rows parsed. "
          f"VALUE unit detected: {later_unit!r}")

    if not args.cusip:
        show_top("EARLIER FILE", earlier_rows, args.top)
        show_top("LATER FILE", later_rows, args.top)
        print("\nOnce you've identified the issuer from the LATER file's #1 "
              "row above, re-run with --cusip <that CUSIP> for the full "
              "row-level breakdown needed to answer the questions.")
        return

    e = analyze_cusip("EARLIER FILE", earlier_rows, earlier_unit, args.cusip)
    l = analyze_cusip("LATER FILE", later_rows, later_unit, args.cusip)

    if not e or not l:
        return

    print("\n=== DERIVED ANSWERS ===")
    pct = (e["smallest_row"]["shares"] / l["smallest_row"]["shares"]) * 100
    print(f"Earlier smallest-row shares as % of later smallest-row shares: "
          f"{e['smallest_row']['shares']:,} / {l['smallest_row']['shares']:,} "
          f"x 100 = {pct:.2f}%")

    smallest_row_per_share = l["smallest_row"]["value"] / l["smallest_row"]["shares"]
    print(f"\nImplied $/share from LATER filing's smallest row: "
          f"{l['smallest_row']['value']:,} / {l['smallest_row']['shares']:,} "
          f"= {smallest_row_per_share:.2f} (in units: {l['header_unit']})")

    agg_per_share = l["total_value"] / l["total_shares"]
    print(f"\nImplied $/share from LATER filing's AGGREGATE: "
          f"{l['total_value']:,} / {l['total_shares']:,} "
          f"= {agg_per_share:.2f} (in units: {l['header_unit']})")

    diff = agg_per_share - smallest_row_per_share
    print(f"\nDifference (aggregate implied $/share - smallest-row implied "
          f"$/share): {agg_per_share:.2f} - {smallest_row_per_share:.2f} "
          f"= {diff:.2f}")


if __name__ == "__main__":
    main()
