"""
Bridgewater N-PX independent-walk pipeline (Interpretation B)

For EACH filing independently:
  1. Total all entries (split FOR/AGAINST sub-outcomes counted separately).
  2. Take ones digit (0 -> 10).
  3. Walk forward that many entries from the first entry in the filing's
     own as-filed (alphabetical) order -> land on one entry.

Then:
  Q1: % change in shares voted, earlier-landed-entry -> later-landed-entry
  Q2: calendar days between the two landed entries' meeting dates
"""

from bs4 import BeautifulSoup
from datetime import datetime

FILES = {
    "earlier": {"path": "npx2024.html", "filed": "2024-08-30"},
    "later": {"path": "npx2025.html", "filed": "2025-08-28"},
}

COLUMN_MAP = {
    "infoCol1": "issuer",
    "infoCol2": "cusip",
    "infoCol5": "meeting_date",
    "infoCol6": "vote_description",
    "infoCol10": "shares_voted_total",
    "infoCol12a": "how_voted",
    "infoCol12b": "shares_voted_detail",
    "infoCol12c": "for_against_mgmt",
}


def parse_file(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        soup = BeautifulSoup(f, "lxml")
    table = soup.find("table", class_="infoTable")
    rows = table.find_all("tr")

    entries = []
    row_num = 0
    for tr in rows:
        cells = tr.find_all(["td"])
        if not cells:
            continue
        row_num += 1
        row_label = f"R{row_num}"

        data = {}
        for td in cells:
            for cls in td.get("class", []):
                if cls in COLUMN_MAP:
                    parts = [s.strip() for s in td.decode_contents().split("<br/>") if s.strip()]
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

            entries.append({
                "label": label,
                "issuer": data.get("issuer", [""])[0] if data.get("issuer") else "",
                "cusip": data.get("cusip", [""])[0] if data.get("cusip") else "",
                "meeting_date": data.get("meeting_date", [""])[0] if data.get("meeting_date") else "",
                "vote_description": data.get("vote_description", [""])[0] if data.get("vote_description") else "",
                "shares_voted": pick("shares_voted_detail"),
                "outcome": pick("for_against_mgmt"),
                "how_voted": pick("how_voted"),
            })

    return entries


def walk(entries):
    total = len(entries)
    ones_digit = total % 10
    walk_n = 10 if ones_digit == 0 else ones_digit
    landed = entries[walk_n - 1]
    return total, ones_digit, walk_n, landed


def to_int(s):
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return None


def main():
    for key in ["earlier", "later"]:
        entries = parse_file(FILES[key]["path"])
        total, ones_digit, walk_n, landed = walk(entries)
        FILES[key]["entries"] = entries
        FILES[key]["total"] = total
        FILES[key]["ones_digit"] = ones_digit
        FILES[key]["walk_n"] = walk_n
        FILES[key]["landed"] = landed

        print(f"--- {key.upper()} filing ({FILES[key]['path']}) ---")
        print(f"Total entries: {total}")
        print(f"Ones digit: {ones_digit} -> walk {walk_n} entries")
        print(f"Landed entry: {landed['label']}")
        print(f"  Issuer: {landed['issuer']}")
        print(f"  CUSIP: {landed['cusip']}")
        print(f"  Meeting date: {landed['meeting_date']}")
        print(f"  Vote description: {landed['vote_description']}")
        print(f"  Shares voted: {landed['shares_voted']}")
        print(f"  Outcome: {landed['outcome']}")
        print()

    earlier_landed = FILES["earlier"]["landed"]
    later_landed = FILES["later"]["landed"]

    earlier_shares = to_int(earlier_landed["shares_voted"])
    later_shares = to_int(later_landed["shares_voted"])

    print("=== ANSWERS ===")
    if earlier_shares and later_shares is not None:
        pct_change = round(100 * (later_shares - earlier_shares) / earlier_shares, 2)
        print(f"Q1: Shares voted {earlier_shares} -> {later_shares} = {pct_change}% change")
    else:
        print("Q1: Could not compute — missing/invalid share figures.")

    try:
        d1 = datetime.strptime(earlier_landed["meeting_date"], "%m/%d/%Y")
        d2 = datetime.strptime(later_landed["meeting_date"], "%m/%d/%Y")
        days = (d2 - d1).days
        print(f"Q2: Meeting dates {earlier_landed['meeting_date']} -> {later_landed['meeting_date']} = {days} calendar days")
    except Exception as e:
        print(f"Q2: Could not compute — {e}")


if __name__ == "__main__":
    main()
