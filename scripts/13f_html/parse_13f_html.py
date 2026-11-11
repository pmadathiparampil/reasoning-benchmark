"""
Form 13F Information Table parser (HTML-rendered version) -- full toolkit.

Reads a locally saved 13F "INFORMATION TABLE" HTML file and provides:
  - full row parsing
  - lookup by row position (1-indexed, e.g. for digit-walk designs)
  - lookup by CUSIP or issuer name (returns all matching rows)
  - sum of VALUE, aggregated by CUSIP
  - sum of VALUE, aggregated by issuer name
  - largest holding (by aggregated CUSIP value)
  - total portfolio value (sum of all rows)
  - total row count / distinct issuer count / distinct CUSIP count
  - breakdown by PUT/CALL type (total value of Call rows, Put rows, plain rows)
  - breakdown by investment discretion (SOLE / DFND / OTR)

NOTE ON UNITS: the VALUE column in this rendered table is labeled
"(to the nearest dollar)" -- i.e. each row's value is in actual dollars,
NOT thousands. The Form 13F Summary Page's "Value Total ($000)" figure
IS in thousands. Divide a row-sum by 1,000 (or multiply the Summary
Page figure by 1,000) before comparing the two -- otherwise you'll be
off by a factor of 1,000.

Run: python parse_13f_html.py filing.html [--top N] [--cusip X] [--compare]
Requires: pip install beautifulsoup4 lxml
"""

from bs4 import BeautifulSoup
from collections import defaultdict
import statistics

import argparse
import os

HEADER_MAP = {
    "NAME OF ISSUER": "issuer",
    "TITLE OF CLASS": "title_of_class",
    "CUSIP": "cusip",
    "FIGI": "figi",
    "(TO THE NEAREST DOLLAR)": "value",
    "PRN AMT": "shares_or_principal",
    "PRN": "sh_or_prn",
    "CALL": "put_call",
    "DISCRETION": "investment_discretion",
    "MANAGER": "other_manager",
    "SOLE": "voting_sole",
    "SHARED": "voting_shared",
    "NONE": "voting_none",
}


def to_int(s):
    if s is None:
        return None
    s = s.strip().replace(",", "")
    if s == "":
        return None
    try:
        return int(s)
    except ValueError:
        return None


def parse_file(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        soup = BeautifulSoup(f, "lxml")

    # Scan every <tr> in the whole document, regardless of which <table> it
    # sits in. The real SEC-rendered 13F page has a decorative multi-row
    # header ("COLUMN 1" / "COLUMN 2" ... then sub-labels) BEFORE the actual
    # field-name row (the one that literally contains "NAME OF ISSUER"). We
    # ignore everything until we find that exact row, then treat every row
    # after it as data.
    all_rows = soup.find_all("tr")

    col_map = {}
    records = []
    header_found = False

    for tr in all_rows:
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue

        cell_texts = [c.get_text(strip=True).upper() for c in cells]

        if not header_found:
            if "NAME OF ISSUER" in cell_texts:
                for idx, text in enumerate(cell_texts):
                    if text in HEADER_MAP:
                        col_map[idx] = HEADER_MAP[text]
                header_found = True
            continue  # skip this row either way (it's a header or pre-header row)

        # From here on, every row is treated as a data row.
        raw = {}
        for idx, cell in enumerate(cells):
            if idx in col_map:
                raw[col_map[idx]] = cell.get_text(strip=True)

        if not raw.get("issuer"):
            continue  # skip stray blank/footer rows with no issuer name

        record = {
            "row_number": len(records) + 1,
            "issuer": raw.get("issuer", ""),
            "title_of_class": raw.get("title_of_class", ""),
            "cusip": raw.get("cusip", ""),
            "figi": raw.get("figi", ""),
            "value_dollars": to_int(raw.get("value")),
            "shares_or_principal": to_int(raw.get("shares_or_principal")),
            "sh_or_prn": raw.get("sh_or_prn", ""),
            "put_call": raw.get("put_call", ""),
            "investment_discretion": raw.get("investment_discretion", ""),
            "other_manager": raw.get("other_manager", ""),
            "voting_sole": to_int(raw.get("voting_sole")),
            "voting_shared": to_int(raw.get("voting_shared")),
            "voting_none": to_int(raw.get("voting_none")),
        }
        records.append(record)

    if not header_found:
        raise ValueError('Could not find the header row containing "NAME OF ISSUER" anywhere in the file.')

    return records


# ---------- Lookup ----------

def get_row(records, position):
    """1-indexed row lookup, e.g. get_row(records, 4217)."""
    if position < 1 or position > len(records):
        raise IndexError(f"Position {position} out of range (1-{len(records)})")
    return records[position - 1]


def find_by_cusip(records, cusip):
    return [r for r in records if r["cusip"] == cusip]


def find_by_issuer(records, issuer_substring):
    needle = issuer_substring.upper()
    return [r for r in records if needle in r["issuer"].upper()]


# ---------- Aggregation ----------

def sum_by_cusip(records):
    """Returns {cusip: {'issuer': ..., 'total_value': ..., 'row_count': ...}}"""
    agg = defaultdict(lambda: {"issuer": "", "total_value": 0, "row_count": 0})
    for r in records:
        c = r["cusip"]
        agg[c]["issuer"] = r["issuer"]
        if r["value_dollars"] is not None:
            agg[c]["total_value"] += r["value_dollars"]
        agg[c]["row_count"] += 1
    return dict(agg)


def sum_by_issuer(records):
    agg = defaultdict(lambda: {"total_value": 0, "row_count": 0, "cusips": set()})
    for r in records:
        i = r["issuer"]
        if r["value_dollars"] is not None:
            agg[i]["total_value"] += r["value_dollars"]
        agg[i]["row_count"] += 1
        agg[i]["cusips"].add(r["cusip"])
    return dict(agg)


def largest_holding(records):
    """Largest position by aggregated CUSIP value (not just single largest row)."""
    by_cusip = sum_by_cusip(records)
    return max(by_cusip.items(), key=lambda kv: kv[1]["total_value"])


def total_portfolio_value(records):
    return sum(r["value_dollars"] for r in records if r["value_dollars"] is not None)


def breakdown_by_put_call(records):
    """Total value split by Call / Put / plain (long) positions."""
    result = {"Call": 0, "Put": 0, "": 0}
    counts = {"Call": 0, "Put": 0, "": 0}
    for r in records:
        key = r["put_call"] if r["put_call"] in ("Call", "Put") else ""
        if r["value_dollars"] is not None:
            result[key] += r["value_dollars"]
        counts[key] += 1
    return result, counts


def breakdown_by_discretion(records):
    result = defaultdict(int)
    counts = defaultdict(int)
    for r in records:
        d = r["investment_discretion"]
        if r["value_dollars"] is not None:
            result[d] += r["value_dollars"]
        counts[d] += 1
    return dict(result), dict(counts)


# ---------- Ranking (top-N / bottom-N) ----------

def rank_by_cusip_value(records, ascending=False):
    """
    Full list of (cusip, info) tuples, sorted by aggregated CUSIP value.
    ascending=False (default) -> largest first, rank 1 = biggest holding.
    ascending=True -> smallest first, rank 1 = smallest holding.
    info is the same dict shape as sum_by_cusip(): {'issuer', 'total_value', 'row_count'}.
    """
    by_cusip = sum_by_cusip(records)
    return sorted(by_cusip.items(), key=lambda kv: kv[1]["total_value"], reverse=not ascending)


def top_n_cusips(records, n):
    """Top n holdings by aggregated CUSIP value, largest first. Returns list of (cusip, info)."""
    return rank_by_cusip_value(records, ascending=False)[:n]


def bottom_n_cusips(records, n):
    """Bottom n holdings by aggregated CUSIP value, smallest first. Returns list of (cusip, info)."""
    return rank_by_cusip_value(records, ascending=True)[:n]


def cusip_rank(records, cusip):
    """
    Returns the 1-indexed rank of a specific CUSIP by aggregated value
    (rank 1 = largest holding in the whole table), or None if not found.
    """
    ranked = rank_by_cusip_value(records, ascending=False)
    for i, (c, info) in enumerate(ranked, start=1):
        if c == cusip:
            return i
    return None


# ---------- Stats on a set of values ----------

def value_stats(values):
    """
    Given a list of numeric values, returns sum/mean/median/min/max/count.
    Empty list returns all None except count=0 and sum=0.
    """
    values = [v for v in values if v is not None]
    if not values:
        return {"sum": 0, "mean": None, "median": None, "min": None, "max": None, "count": 0}
    return {
        "sum": sum(values),
        "mean": statistics.mean(values),
        "median": statistics.median(values),
        "min": min(values),
        "max": max(values),
        "count": len(values),
    }


def top_n_stats(records, n):
    """Sum/mean/median/etc. of the top n holdings' aggregated CUSIP values."""
    top = top_n_cusips(records, n)
    return value_stats([info["total_value"] for cusip, info in top])


def bottom_n_stats(records, n):
    """Sum/mean/median/etc. of the bottom n holdings' aggregated CUSIP values."""
    bottom = bottom_n_cusips(records, n)
    return value_stats([info["total_value"] for cusip, info in bottom])


# ---------- Put/Call-specific helpers ----------

def calls_only(records):
    """All rows flagged 'Call'."""
    return [r for r in records if r["put_call"] == "Call"]


def puts_only(records):
    """All rows flagged 'Put'."""
    return [r for r in records if r["put_call"] == "Put"]


def plain_only(records):
    """All rows with neither 'Call' nor 'Put' flag (plain long positions)."""
    return [r for r in records if r["put_call"] not in ("Call", "Put")]


def top_n_calls(records, n):
    """Top n individual Call-flagged rows by row-level value, largest first."""
    calls = calls_only(records)
    return sorted(calls, key=lambda r: r["value_dollars"] or 0, reverse=True)[:n]


def top_n_puts(records, n):
    """Top n individual Put-flagged rows by row-level value, largest first."""
    puts = puts_only(records)
    return sorted(puts, key=lambda r: r["value_dollars"] or 0, reverse=True)[:n]


def call_stats(records):
    """Sum/mean/median/etc. across all Call-flagged rows' individual values."""
    return value_stats([r["value_dollars"] for r in calls_only(records)])


def put_stats(records):
    """Sum/mean/median/etc. across all Put-flagged rows' individual values."""
    return value_stats([r["value_dollars"] for r in puts_only(records)])


def print_summary(records, label):
    """Standard per-file summary (same as the old default main() output)."""
    print(f"=== {label} ===")
    print(f"Parsed {len(records)} holding rows.")

    total_value = total_portfolio_value(records)
    distinct_issuers = len({r["issuer"] for r in records})
    distinct_cusips = len({r["cusip"] for r in records})

    print(f"Total rows: {len(records)}")
    print(f"Distinct issuers: {distinct_issuers}")
    print(f"Distinct CUSIPs: {distinct_cusips}")
    print(f"Total portfolio value (dollars): ${total_value:,}")
    print(f"Total portfolio value (in $000, for Summary Page comparison): ${total_value/1000:,.0f}")

    cusip, info = largest_holding(records)
    print(f"\nLargest holding by aggregated CUSIP value:")
    print(f"  {info['issuer']} (CUSIP {cusip}): ${info['total_value']:,} across {info['row_count']} rows")

    pc_value, pc_count = breakdown_by_put_call(records)
    print(f"\nValue breakdown by Put/Call:")
    for k, v in pc_value.items():
        label2 = k if k else "Plain (long)"
        print(f"  {label2}: ${v:,} across {pc_count[k]} rows")

    disc_value, disc_count = breakdown_by_discretion(records)
    print(f"\nValue breakdown by Investment Discretion:")
    for k, v in disc_value.items():
        print(f"  {k}: ${v:,} across {disc_count[k]} rows")


def print_top_bottom(records, label, top_n=None, bottom_n=None):
    if top_n:
        print(f"\n--- {label}: Top {top_n} holdings ---")
        for cusip, info in top_n_cusips(records, top_n):
            print(f"  {info['issuer']} ({cusip}): ${info['total_value']:,} across {info['row_count']} rows")
        stats = top_n_stats(records, top_n)
        print(f"  Sum: ${stats['sum']:,}  Mean: ${stats['mean']:,.2f}  Median: ${stats['median']:,.2f}")

    if bottom_n:
        print(f"\n--- {label}: Bottom {bottom_n} holdings ---")
        for cusip, info in bottom_n_cusips(records, bottom_n):
            print(f"  {info['issuer']} ({cusip}): ${info['total_value']:,} across {info['row_count']} rows")
        stats = bottom_n_stats(records, bottom_n)
        print(f"  Sum: ${stats['sum']:,}  Mean: ${stats['mean']:,.2f}  Median: ${stats['median']:,.2f}")


def print_lookup(records, label, cusip=None, issuer=None, row=None):
    if cusip:
        print(f"\n--- {label}: Rows for CUSIP {cusip} ---")
        rows = find_by_cusip(records, cusip)
        if not rows:
            print("  No rows found for that CUSIP.")
        for r in rows:
            print(f"  Row {r['row_number']}: {r['issuer']} = ${r['value_dollars']:,} ({r['put_call'] or 'plain'})")
        total = sum(r["value_dollars"] for r in rows if r["value_dollars"] is not None)
        print(f"  Aggregate: ${total:,}")

    if issuer:
        print(f"\n--- {label}: Rows matching issuer '{issuer}' ---")
        rows = find_by_issuer(records, issuer)
        if not rows:
            print("  No rows found for that issuer.")
        for r in rows:
            print(f"  Row {r['row_number']}: {r['issuer']} ({r['cusip']}) = ${r['value_dollars']:,}")

    if row:
        print(f"\n--- {label}: Row {row} ---")
        try:
            r = get_row(records, row)
            print(f"  {r}")
        except IndexError as e:
            print(f"  {e}")


def print_comparison(all_records, labels):
    """Cross-file comparison, run when 2+ files are provided."""
    print(f"\n=== Comparison across {len(labels)} files ===")

    totals = [total_portfolio_value(recs) for recs in all_records]
    for label, total in zip(labels, totals):
        print(f"  {label}: total value ${total:,}")

    if len(all_records) == 2:
        diff = totals[1] - totals[0]
        pct = round(diff / totals[0] * 100, 2) if totals[0] else None
        print(f"\n  Difference ({labels[1]} - {labels[0]}): ${diff:,} ({pct}% change)")

    # CUSIP overlap
    cusip_sets = [set(r["cusip"] for r in recs) for recs in all_records]
    common = set.intersection(*cusip_sets)
    print(f"\n  Common CUSIPs held across all {len(labels)} files: {len(common)}")

    if len(all_records) == 2:
        only_in_0 = cusip_sets[0] - cusip_sets[1]
        only_in_1 = cusip_sets[1] - cusip_sets[0]
        print(f"  CUSIPs only in {labels[0]}: {len(only_in_0)}")
        print(f"  CUSIPs only in {labels[1]}: {len(only_in_1)}")

    # Largest holding per file, side by side
    print(f"\n  Largest holding per file:")
    for label, recs in zip(labels, all_records):
        cusip, info = largest_holding(recs)
        print(f"    {label}: {info['issuer']} ({cusip}) = ${info['total_value']:,}")


def main():
    parser = argparse.ArgumentParser(
        description="Parse and analyze one or more Form 13F Information Table HTML files."
    )
    parser.add_argument("files", nargs="+", help="One or more saved 13F Information Table HTML files.")
    parser.add_argument("--top", type=int, help="Show top N holdings by aggregated CUSIP value.")
    parser.add_argument("--bottom", type=int, help="Show bottom N holdings by aggregated CUSIP value.")
    parser.add_argument("--cusip", type=str, help="Look up all rows for a specific CUSIP.")
    parser.add_argument("--issuer", type=str, help="Look up all rows matching an issuer name substring.")
    parser.add_argument("--row", type=int, help="Look up a specific row by 1-indexed position.")
    parser.add_argument("--compare", action="store_true", help="Show a cross-file comparison (2+ files).")
    parser.add_argument("--no-summary", action="store_true", help="Skip the default per-file summary output.")

    args = parser.parse_args()

    all_records = []
    labels = []

    for path in args.files:
        if not os.path.exists(path):
            print(f"ERROR: file not found: {path}")
            continue
        label = os.path.basename(path)
        records = parse_file(path)
        all_records.append(records)
        labels.append(label)

        if not args.no_summary:
            print_summary(records, label)

        print_top_bottom(records, label, top_n=args.top, bottom_n=args.bottom)
        print_lookup(records, label, cusip=args.cusip, issuer=args.issuer, row=args.row)
        print()  # spacer between files

    if args.compare and len(all_records) >= 2:
        print_comparison(all_records, labels)
    elif args.compare:
        print("--compare was given but fewer than 2 valid files were parsed.")


if __name__ == "__main__":
    main()
