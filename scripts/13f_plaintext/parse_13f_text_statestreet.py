"""
Parser + comparator for State Street Corp's pre-2013 fixed-width plain-text
13F-HR information tables (CIK 0000093751 style formatting, one row per
issuer, with two independent three-way splits: Investment Discretion
[Sole / Shared as Defined / Shared Other] and Voting Authority
[Sole / Shared / None]).

KEY DESIGN DECISION: column positions are NOT hardcoded. Every page of
this filing repeats its own header row containing the literal labels
"Sole  Defined  Other  Sole  Shared  None" -- this parser reads THOSE
exact positions fresh from each page, rather than assuming one fixed
set of column boundaries for the whole 500+ page document. This matters
because a $1 holding and a $8+ billion holding format to very different
widths, and using one guessed global offset broke on the widest rows
(confirmed on a real BellSouth row where VALUE=$8.7B).

There's a small, consistent gap between where the short header LABEL
ends and where the actual (often much wider) numeric column ends --
calibrated at +1 to +2 characters from real data. A generous tolerance
window absorbs any remaining page-to-page jitter.

Every parsed row is sanity-checked: the Investment Discretion split and
the Voting Authority split should each independently sum to SHARES.
Rows that fail this check are flagged explicitly rather than silently
trusted -- sometimes that means a parsing miss, sometimes it means the
source filing itself doesn't reconcile (confirmed with real data: one
BellSouth row is off by 20,198 in the raw text itself, not a parsing
bug).

Usage:
    # Single file: top holdings + sum-check
    python parse_13f_text_statestreet.py filing.txt

    # Single file: full detail for one CUSIP
    python parse_13f_text_statestreet.py filing.txt --cusip 00790310

    # Two files at once (earlier vs later): top holdings in both
    python parse_13f_text_statestreet.py earlier.txt later.txt

    # Two files: full side-by-side detail + comparison for one CUSIP
    python parse_13f_text_statestreet.py earlier.txt later.txt --cusip 00790310
"""

import re
import sys
import argparse

NUM_RE = re.compile(r"[\d][\d,]*")
CUSIP_RE = re.compile(r"\b([A-Z0-9]{6,9})\b")

# Fallback boundaries (offset from where SHARES ends), used only if a
# row appears before any page header has been seen yet.
FALLBACK_OFFSETS = [11, 22, 32, 43, 55, 66]
LABEL_TO_DATA_GAP = 2   # calibrated from real data; small, consistent
TOLERANCE = 6

FIELD_NAMES = ["disc_sole", "disc_shared_defined", "disc_shared_other",
               "vote_sole", "vote_shared", "vote_none"]

HEADER_LINE_RE = re.compile(
    r"^\s*Issuer\s+Class\s+Number\s+Value\s+Prin\s+Amt\s+"
    r"Sole\s+Defined\s+Other\s+Sole\s+Shared\s+None\s*$"
)

PAGE_NOISE = re.compile(
    r"(PAGE NO\.|STATE STREET CORPORATION|ITEM \d:|Name of|"
    r"^\s*-+\s*$|<TABLE>|<CAPTION>|<S>|PAGE MARKET VALUE|^\s*<PAGE>)"
)


def parse_page_header(line):
    """If this line is the 'Issuer Class Number Value ... None' header,
    return the 6 target column boundaries (absolute char positions,
    with the label->data gap already applied). Else return None."""
    if not HEADER_LINE_RE.match(line):
        return None
    tokens = [m.end() for m in re.finditer(r"\S+", line)]
    label_ends = tokens[-6:]  # Sole, Defined, Other, Sole, Shared, None
    return [end + LABEL_TO_DATA_GAP for end in label_ends]


def parse_row(line, lineno, page_boundaries):
    if PAGE_NOISE.search(line) or not line.strip():
        return None

    cusip_match = None
    for m in CUSIP_RE.finditer(line):
        if m.start() >= 26:
            cusip_match = m
            break
    if not cusip_match:
        return None

    name_and_class = line[:cusip_match.start()].strip()
    parts = re.split(r"\s{2,}", name_and_class)
    name = parts[0].strip() if parts else name_and_class
    title_of_class = parts[1].strip() if len(parts) > 1 else None
    cusip = cusip_match.group(1)

    remainder_offset = cusip_match.end()
    numbers = [{"value": int(m.group().replace(",", "")),
                "end": m.end() + remainder_offset}
               for m in NUM_RE.finditer(line[cusip_match.end():])]

    if len(numbers) < 2:
        return None

    row = {"row": lineno, "name": name, "class": title_of_class, "cusip": cusip,
           "value": numbers[0]["value"], "shares": numbers[1]["value"]}
    for f in FIELD_NAMES:
        row[f] = None

    # Determine the split between Investment Discretion (first group)
    # and Voting Authority (second group). Each group can hold 0-3
    # numbers, so with N remaining numbers, count alone can already
    # force a UNIQUE split (e.g. N=6 means split MUST be 3/3 -- no
    # other option satisfies "each group <= 3"). Only when count leaves
    # more than one possibility do we need the sum-to-SHARES check to
    # pick between them. This matters: requiring both sums to match
    # before EVER accepting a split was wrong -- it threw away good
    # Investment Discretion data on rows where only Voting Authority
    # has a real reconciliation gap in the source filing (confirmed:
    # ALLSTATE CORP's own filing has discretion summing perfectly but
    # voting off by 16,882 -- a genuine source anomaly, not ours to fix).
    optional_nums = numbers[2:]
    n = len(optional_nums)
    count_valid = [s for s in range(0, min(3, n) + 1) if n - s <= 3]

    split = None
    if len(count_valid) == 1:
        split = count_valid[0]
    else:
        sum_matches = [s for s in count_valid
                       if sum(x["value"] for x in optional_nums[:s]) == row["shares"]
                       and sum(x["value"] for x in optional_nums[s:]) == row["shares"]]
        if len(sum_matches) == 1:
            split = sum_matches[0]
        elif len(sum_matches) > 1:
            split = sum_matches[0]  # ambiguous coincidence; take first
        else:
            # No split makes both sides sum correctly. Fall back to
            # whichever candidate makes the DISCRETION side sum
            # correctly (discretion has been more reliable in practice
            # than voting for rows with real anomalies) -- if that also
            # fails, refuse to guess.
            disc_matches = [s for s in count_valid
                             if sum(x["value"] for x in optional_nums[:s]) == row["shares"]]
            split = disc_matches[0] if disc_matches else None

    row["split_ambiguous"] = (split is None)
    if split is None:
        return row

    discretion_group = optional_nums[:split]
    voting_group = optional_nums[split:]

    # WITHIN each group, which of the up-to-3 slots each number occupies
    # still benefits from column-position matching when a group has
    # fewer than 3 populated cells (position is the only way to tell
    # "the single number present is Sole" vs "...is Shared Other").
    # This uses whatever page-calibrated boundaries are available; if
    # a group is fully populated (3 of 3), order alone is unambiguous
    # and position isn't even needed.
    def assign_group(group, slot_names, boundaries_subset):
        if len(group) == len(slot_names):
            for name, num in zip(slot_names, group):
                row[name] = num["value"]
            return
        # partial group -- use nearest boundary position as tiebreaker
        for num in group:
            best = min(range(len(slot_names)),
                       key=lambda i: abs(num["end"] - boundaries_subset[i]))
            if row[slot_names[best]] is None:
                row[slot_names[best]] = num["value"]

    if page_boundaries:
        boundaries = page_boundaries
    else:
        boundaries = [numbers[1]["end"] + off for off in FALLBACK_OFFSETS]

    assign_group(discretion_group,
                 ["disc_sole", "disc_shared_defined", "disc_shared_other"],
                 boundaries[:3])
    assign_group(voting_group,
                 ["vote_sole", "vote_shared", "vote_none"],
                 boundaries[3:])

    return row


def parse_file(path):
    rows = []
    page_boundaries = None
    with open(path, "r", errors="ignore") as f:
        for i, line in enumerate(f, start=1):
            hdr = parse_page_header(line)
            if hdr:
                page_boundaries = hdr
                continue
            r = parse_row(line, i, page_boundaries)
            if r:
                rows.append(r)
    return rows


def check_sums(r):
    if r.get("split_ambiguous"):
        return "SOURCE DATA ISSUE: could not find a valid discretion/voting split -- the raw numbers likely don't parse cleanly (e.g. a broken/corrupted figure in the source text). Check the raw line by hand."
    disc_sum = (r["disc_sole"] or 0) + (r["disc_shared_defined"] or 0) + (r["disc_shared_other"] or 0)
    vote_sum = (r["vote_sole"] or 0) + (r["vote_shared"] or 0) + (r["vote_none"] or 0)
    problems = []
    if disc_sum != r["shares"]:
        problems.append(f"discretion split sums to {disc_sum:,}, not SHARES={r['shares']:,}")
    if vote_sum != r["shares"]:
        problems.append(f"voting split sums to {vote_sum:,}, not SHARES={r['shares']:,}")
    return "; ".join(problems) if problems else None


def print_sum_check_summary(rows):
    failed = [(r, check_sums(r)) for r in rows]
    failed = [(r, w) for r, w in failed if w]
    print(f"Sum-check: {len(rows) - len(failed)}/{len(rows)} rows reconcile "
          f"(both splits sum to SHARES).")
    if failed:
        print(f"  {len(failed)} rows did NOT reconcile -- either a parsing "
              f"miss or a genuine inconsistency in the source filing:")
        for r, w in failed[:15]:
            print(f"    row {r['row']}: {r['name']} ({r['cusip']}) -- {w}")
        if len(failed) > 15:
            print(f"    ... and {len(failed) - 15} more")


def show_top(label, rows, n):
    print(f"\n=== {label} ===")
    print_sum_check_summary(rows)
    clean_rows = [r for r in rows if not check_sums(r)]
    ranked = sorted(clean_rows, key=lambda r: r["value"], reverse=True)
    print(f"TOP {n} BY VALUE (reconciled rows only -- {len(clean_rows)}/{len(rows)} "
          f"total rows pass the sum-check):")
    for r in ranked[:n]:
        print(f"  {r['name']:<30} {r['cusip']}  VALUE=${r['value']:>15,}  "
              f"SHARES={r['shares']:>12,}")


def show_cusip_detail(label, rows, cusip):
    matches = [r for r in rows if r["cusip"] == cusip]
    if not matches:
        print(f"\n=== {label}: CUSIP {cusip} NOT FOUND ===")
        return None
    if len(matches) > 1:
        print(f"\n=== {label}: WARNING -- {len(matches)} rows found for "
              f"CUSIP {cusip}, expected 1 ===")
    r = matches[0]
    print(f"\n=== {label}: {r['name']} ({r['class']}) CUSIP {r['cusip']}, row {r['row']} ===")
    print(f"  VALUE = ${r['value']:,}")
    print(f"  SHARES = {r['shares']:,}")
    print(f"  Investment Discretion -- Sole: {r['disc_sole']}, "
          f"Shared as Defined: {r['disc_shared_defined']}, "
          f"Shared Other: {r['disc_shared_other']}")
    print(f"  Voting Authority       -- Sole: {r['vote_sole']}, "
          f"Shared: {r['vote_shared']}, None: {r['vote_none']}")
    warning = check_sums(r)
    print(f"  Sum check: {'FAILED -- ' + warning if warning else 'passed'}")
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+", help="One file, or two (earlier later)")
    ap.add_argument("--cusip")
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()

    if len(args.files) not in (1, 2):
        print("Provide 1 file (single-file mode) or 2 files (earlier later).")
        sys.exit(1)

    all_rows = [parse_file(f) for f in args.files]
    for f, rows in zip(args.files, all_rows):
        print(f"{f}: {len(rows)} rows parsed.")

    labels = ["FILE"] if len(args.files) == 1 else ["EARLIER FILE", "LATER FILE"]

    if not args.cusip:
        for label, rows in zip(labels, all_rows):
            show_top(label, rows, args.top)
        if len(args.files) == 2:
            earlier_clean = {r["cusip"] for r in all_rows[0] if not check_sums(r)}
            later_rows_by_cusip = {r["cusip"]: r for r in all_rows[1]}
            both_clean = [later_rows_by_cusip[c] for c in earlier_clean
                          if c in later_rows_by_cusip and not check_sums(later_rows_by_cusip[c])]
            both_clean.sort(key=lambda r: r["value"], reverse=True)
            print(f"\n=== TOP {args.top} BY LATER-FILE VALUE, RECONCILED IN "
                  f"**BOTH** FILINGS ({len(both_clean)} such CUSIPs total) ===")
            for r in both_clean[:args.top]:
                print(f"  {r['name']:<30} {r['cusip']}  VALUE=${r['value']:>15,}  "
                      f"SHARES={r['shares']:>12,}")
            print("\nOnce you've identified an issuer, re-run with "
                  "--cusip <CUSIP> for the full breakdown.")
        return

    results = [show_cusip_detail(label, rows, args.cusip)
               for label, rows in zip(labels, all_rows)]

    if len(args.files) == 2 and all(results):
        e, l = results
        print(f"\n=== COMPARISON ===")
        print(f"VALUE:  earlier=${e['value']:,}  later=${l['value']:,}  "
              f"change={l['value'] - e['value']:,}")
        print(f"SHARES: earlier={e['shares']:,}  later={l['shares']:,}  "
              f"change={l['shares'] - e['shares']:,}")


if __name__ == "__main__":
    main()
