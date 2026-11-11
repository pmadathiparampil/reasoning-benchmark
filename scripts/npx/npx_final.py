"""
Bridgewater N-PX pipeline — CORRECTED FINAL VERSION.

Entry-counting convention (locked in):
  - A single listed proposal split into more than one recorded outcome
    (e.g. part FOR / part AGAINST on the same proposal) counts as one
    separate entry per recorded outcome.
  - A row with NO recorded outcome at all (blank How Voted / Shares
    Voted / For-Against-Management fields — e.g. a zero-share holding
    listed with nothing actually voted) counts as ZERO entries, not one.
    This matters: Bridgewater's actual 2025 N-PX filing contains exactly
    one such row (Masimo Corporation), which changes the total from 892
    to 891 and shifts the digit-walk landing position.

Per filing: total entries (per convention above) -> ones digit (0 -> 10)
-> squared -> landed entry at that position (position 1 = first entry).

Q1: % change in shares, earlier-landed -> later-landed.
Q2: floor(abs(Q1)), 0 -> 1, walk that many MORE positions forward from
    the later-filing landed entry (within the later filing) -> new entry.
    Days elapsed between earlier-landed meeting date and this new
    entry's meeting date.
"""

from bs4 import BeautifulSoup
from datetime import datetime
import math

FILES = {
    "earlier": {"path": "npx2024.html"},
    "later": {"path": "npx2025.html"},
}

COLUMN_MAP = {
    "infoCol1": "issuer",
    "infoCol2": "cusip",
    "infoCol5": "meeting_date",
    "infoCol6": "vote_description",
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
                    data[COLUMN_MAP[cls]] = parts

        n_sub = max(
            (len(data.get(k, [])) for k in ["how_voted", "shares_voted_detail", "for_against_mgmt"]),
            default=0,
        )
        # NOTE: default=0 (not 1) -- a row with zero recorded outcomes
        # contributes zero entries, per the locked-in convention above.

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
            })

    return entries


def to_int(s):
    try:
        return int(s.replace(",", ""))
    except ValueError:
        return None


def main():
    earlier = parse_file(FILES["earlier"]["path"])
    later = parse_file(FILES["later"]["path"])

    results = {}
    for key, entries in [("earlier", earlier), ("later", later)]:
        total = len(entries)
        ones_digit = total % 10
        base = 10 if ones_digit == 0 else ones_digit
        squared = base ** 2
        position = squared

        print(f"--- {key.upper()} filing ---")
        print(f"Total entries: {total}, ones digit: {ones_digit} -> base {base} -> squared {squared}")

        if position > len(entries):
            print(f"  WARNING: squared value {squared} exceeds total entries {len(entries)} — out of range!")
            landed = None
        else:
            landed = entries[position - 1]
            print(f"Landed at position {position}: {landed['label']}")
            print(f"  Issuer: {landed['issuer']}")
            print(f"  Meeting date: {landed['meeting_date']}")
            print(f"  Shares voted: {landed['shares_voted']}  Outcome: {landed['outcome']}")

        results[key] = {"entries": entries, "total": total, "position": position, "landed": landed}
        print()

    earlier_landed = results["earlier"]["landed"]
    later_landed = results["later"]["landed"]

    if not earlier_landed or not later_landed:
        print("Cannot proceed — a walk landed out of range.")
        return

    earlier_shares = to_int(earlier_landed["shares_voted"])
    later_shares = to_int(later_landed["shares_voted"])

    print("=== Q1 ===")
    if earlier_shares and later_shares is not None:
        q1 = round(100 * (later_shares - earlier_shares) / earlier_shares, 2)
        print(f"Shares: {earlier_shares} -> {later_shares} = {q1}% change")
    else:
        print("Could not compute Q1 — missing/invalid share figures.")
        return

    print("\n=== Q2 ===")
    steps = math.floor(abs(q1))
    if steps == 0:
        steps = 1
    print(f"floor(abs({q1})) = {steps}")

    later_entries = results["later"]["entries"]
    later_landed_pos = results["later"]["position"]
    new_pos = later_landed_pos + steps

    print(f"Walking {steps} more positions forward from later-filing position {later_landed_pos} -> new position {new_pos}")

    if new_pos > len(later_entries):
        print(f"WARNING: new position {new_pos} exceeds total later-filing entries {len(later_entries)} — out of range!")
        return

    new_entry = later_entries[new_pos - 1]
    print(f"New entry: {new_entry['label']}")
    print(f"  Issuer: {new_entry['issuer']}")
    print(f"  Meeting date: {new_entry['meeting_date']}")
    print(f"  Shares voted: {new_entry['shares_voted']}  Outcome: {new_entry['outcome']}")

    d1 = datetime.strptime(earlier_landed["meeting_date"], "%m/%d/%Y")
    d2 = datetime.strptime(new_entry["meeting_date"], "%m/%d/%Y")
    days = (d2 - d1).days
    print(f"\nQ2 answer: days between {earlier_landed['meeting_date']} and {new_entry['meeting_date']} = {days} days")

    print("\n=== FINAL ANSWERS ===")
    print(f"Q1: {q1}%")
    print(f"Q2: {days} days")


if __name__ == "__main__":
    main()
