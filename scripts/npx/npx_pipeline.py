"""
Bridgewater Form N-PX pipeline (local HTML version)

Reads the two saved N-PX proxy-voting-record HTML files (the rendered
table view, one <table class="infoTable"> per file) and:
  - labels every row and every FOR/AGAINST sub-outcome within a row
  - aggregates: distinct issuers, total records (both definitions —
    per-<tr> and per-vote-outcome), against-management count/pct
  - finds the issuer with the most records (+ runner-up)
  - compares that issuer's earlier-filing count
  - walks forward through FRED DGS10 using the ones digit of the total
  - computes the final signed basis-point change

Run: python npx_pipeline.py
Requires: pip install beautifulsoup4 lxml requests
"""

from bs4 import BeautifulSoup
from collections import defaultdict
import csv
import io
import requests
from datetime import datetime

HEADERS = {"User-Agent": "Research research@example.com"}

FILES = {
    "earlier": {"path": "npx2024.html", "filed": "2024-08-30"},
    "later": {"path": "npx2025.html", "filed": "2025-08-28"},
}

COLUMN_MAP = {
    "infoCol1": "issuer",
    "infoCol2": "cusip",
    "infoCol5": "meeting_date",
    "infoCol6": "vote_description",
    "infoCol7": "vote_category",
    "infoCol10": "shares_voted_total",
    "infoCol12a": "how_voted",
    "infoCol12b": "shares_voted_detail",
    "infoCol12c": "for_against_mgmt",
}


def parse_file(path):
    """
    Returns a list of labeled records. Each <tr> gets a row label like
    'R1'; if that row contains multiple FOR/AGAINST sub-outcomes
    (stacked with <br> inside the same cell), each sub-outcome gets a
    label like 'R1-a', 'R1-b' and shares the same issuer/CUSIP/meeting.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        soup = BeautifulSoup(f, "lxml")

    table = soup.find("table", class_="infoTable")
    rows = table.find_all("tr")

    records = []
    row_num = 0
    for tr in rows:
        cells = tr.find_all(["td"])
        if not cells:
            continue  # header row
        row_num += 1
        row_label = f"R{row_num}"

        data = {}
        for td in cells:
            classes = td.get("class", [])
            for cls in classes:
                if cls in COLUMN_MAP:
                    parts = [
                        s.strip()
                        for s in td.decode_contents().split("<br/>")
                        if s.strip()
                    ]
                    if not parts:
                        parts = [td.get_text(strip=True)]
                    data[COLUMN_MAP[cls]] = parts

        n_sub = max(
            (len(data.get(k, [])) for k in ["how_voted", "shares_voted_detail", "for_against_mgmt"]),
            default=1,
        )
        n_sub = max(n_sub, 1)

        for i in range(n_sub):
            suffix = chr(ord("a") + i)
            label = row_label if n_sub == 1 else f"{row_label}-{suffix}"

            def pick(key):
                vals = data.get(key, [])
                return vals[i] if i < len(vals) else (vals[0] if vals else "")

            records.append({
                "label": label,
                "row": row_num,
                "issuer": data.get("issuer", [""])[0] if data.get("issuer") else "",
                "cusip": data.get("cusip", [""])[0] if data.get("cusip") else "",
                "meeting_date": data.get("meeting_date", [""])[0] if data.get("meeting_date") else "",
                "how_voted": pick("how_voted"),
                "shares_voted_detail": pick("shares_voted_detail"),
                "for_against_mgmt": pick("for_against_mgmt"),
                "is_split_row": n_sub > 1,
            })

    return records


def aggregate(records):
    issuer_row_counts = defaultdict(set)
    issuer_record_counts = defaultdict(int)
    against_mgmt = 0

    for r in records:
        issuer_row_counts[r["issuer"]].add(r["row"])
        issuer_record_counts[r["issuer"]] += 1
        if r["for_against_mgmt"].upper() == "AGAINST":
            against_mgmt += 1

    total_rows = len({r["row"] for r in records})
    total_records = len(records)
    distinct_issuers = len(issuer_row_counts)

    against_pct_by_record = round(100 * against_mgmt / total_records, 4) if total_records else 0.0

    ranked = sorted(issuer_record_counts.items(), key=lambda kv: kv[1], reverse=True)
    winner, winner_count = ranked[0] if ranked else (None, 0)
    runner_up, runner_up_count = ranked[1] if len(ranked) > 1 else (None, 0)

    return {
        "total_rows": total_rows,
        "total_records": total_records,
        "distinct_issuers": distinct_issuers,
        "against_mgmt": against_mgmt,
        "against_pct_by_record": against_pct_by_record,
        "winner": winner,
        "winner_count": winner_count,
        "runner_up": runner_up,
        "runner_up_count": runner_up_count,
        "issuer_record_counts": issuer_record_counts,
    }


def fetch_dgs10(start_date, end_date):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10&cosd={start_date}&coed={end_date}"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    reader = csv.reader(io.StringIO(resp.text))
    next(reader)
    return [
        (row[0], float(row[1]))
        for row in reader
        if len(row) == 2 and row[1].strip() not in ("", ".")
    ]


def main():
    print(f"Parsing {FILES['earlier']['path']} ...")
    earlier_records = parse_file(FILES["earlier"]["path"])
    print(f"  -> {len(earlier_records)} labeled records "
          f"({len({r['row'] for r in earlier_records})} table rows)")

    print(f"Parsing {FILES['later']['path']} ...")
    later_records = parse_file(FILES["later"]["path"])
    print(f"  -> {len(later_records)} labeled records "
          f"({len({r['row'] for r in later_records})} table rows)")

    split_examples = [r for r in later_records if r["is_split_row"]][:6]
    if split_examples:
        print("\nExample split-row labels (one <tr>, multiple vote outcomes):")
        for r in split_examples:
            print(f"  {r['label']}: {r['issuer']} | {r['how_voted']} | {r['shares_voted_detail']} | {r['for_against_mgmt']}")

    later_agg = aggregate(later_records)
    earlier_agg = aggregate(earlier_records)

    print("\n--- Later filing aggregate (2025-08-28) ---")
    print(f"Table rows (<tr>): {later_agg['total_rows']}")
    print(f"Labeled records (rows split by FOR/AGAINST sub-outcome): {later_agg['total_records']}")
    print(f"Distinct issuers: {later_agg['distinct_issuers']}")
    print(f"Against management: {later_agg['against_mgmt']} ({later_agg['against_pct_by_record']}% of records)")
    print(f"Winner: {later_agg['winner']} ({later_agg['winner_count']} records)")
    print(f"Runner-up: {later_agg['runner_up']} ({later_agg['runner_up_count']} records)")

    winner = later_agg["winner"]
    winner_earlier_count = earlier_agg["issuer_record_counts"].get(winner, 0)
    if winner_earlier_count:
        pct_change = round(100 * (later_agg["winner_count"] - winner_earlier_count) / winner_earlier_count, 2)
    else:
        pct_change = None
    print(f"\n{winner} — earlier filing record count: {winner_earlier_count}, % change: {pct_change}")

    ones_digit = later_agg["total_records"] % 10
    print(f"\nOnes digit of total records: {ones_digit}")

    later_filed = FILES["later"]["filed"]
    obs = fetch_dgs10(later_filed, "2025-12-31")
    future_obs = [(d, v) for d, v in obs if datetime.strptime(d, "%Y-%m-%d").date() > datetime.strptime(later_filed, "%Y-%m-%d").date()]

    if ones_digit == 0:
        print("Ones digit is 0 — decide your fallback rule before proceeding.")
    elif len(future_obs) < ones_digit:
        print("Not enough FRED observations fetched — widen the coed date.")
    else:
        walked = future_obs[:ones_digit]
        print(f"Dates counted: {walked}")
        closing_date, closing_val = walked[-1]

        filing_date_obs = [(d, v) for d, v in obs if d <= later_filed]
        base_date, base_val = filing_date_obs[-1] if filing_date_obs else (None, None)
        used_fallback = base_date != later_filed if base_date else True

        if base_val is not None:
            bp_change = round((closing_val - base_val) * 100, 1)
            sign = "+" if bp_change >= 0 else ""
            print(f"\nBase date used: {base_date} (fallback used: {used_fallback})")
            print(f"Closing date: {closing_date} -> DGS10 = {closing_val}")
            print(f"Change: {sign}{bp_change} bp")
        else:
            print("Could not find a filing-date-or-earlier DGS10 observation.")


if __name__ == "__main__":
    main()
