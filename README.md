# Financial Reasoning Benchmark Portfolio

Multi-hop reasoning tasks built from SEC EDGAR filings and FRED data to evaluate how LLMs handle retrieval, multi-step calculation and entity resolution. The repo also holds the Python parsers I wrote to verify every answer key.

**Live portfolio:** https://pmadathiparampil.github.io/reasoning-benchmark/

## What each task includes

1. **Prompt:** an underspecified, multi-hop question set
2. **Reasoning chain:** the golden trajectory, step by step, with sources and accession numbers
3. **Reasoning graph:** retrieval and compute nodes with their edges
4. **Rubric:** 50 points on final answers and 50 spread across intermediate steps
5. **Model review:** where a frontier model went wrong, and why

## Tasks

|#|Task|Sources|
|-|-|-|
|01|BlackRock 13F-HR: 3M position, Q2 vs Q3 2025|13F-HR, FRED SP500|
|02|AMD derived Q4 2024 free cash flow|10-Q, 10-K, FRED DGS10|
|03|State Street / Chase Manhattan cross-holdings, 1999|Plain-text 13F-HR, filer records|
|04|Citadel Securities FOCUS report and Citadel Advisors 13F|X-17A-5, 13F-HR, 13G/A|
|05|JPMorgan Chase's earliest plain-text 13F-HR|Plain-text 13F-HR, FRED|
|06|Renaissance Technologies 13F rank walk into a 10-K|13F-HR, 10-K, 13G|
|07|Aftershock forecast switch-day backtest (in development)|Earthquake catalogs, Page et al. (2016)|

## Scripts

|Script|Format|What it does|
|-|-|-|
|`scripts/13f\_html/parse\_13f\_html.py`|Modern XML-rendered 13F|Row lookup, CUSIP and issuer aggregation, ranking, put/call and discretion breakdowns, cross-file comparison|
|`scripts/13f\_plaintext/parse\_13f\_text\_chase.py`|Pre-2013 fixed-width 13F|Parses first rows and continuation rows, flags unmatched data-like lines|
|`scripts/13f\_plaintext/analyze\_13f\_text\_chase.py`|Pre-2013 fixed-width 13F|Physical row indexing, smallest-row lookup, VALUE-unit detection that skips the header decoy|
|`scripts/13f\_plaintext/parse\_13f\_text\_statestreet.py`|State Street 1999 13F|Reads column positions from each page's header, sum-checks discretion and voting splits|
|`scripts/npx/npx\_pipeline.py`|Form N-PX|Labels split vote outcomes, aggregates by issuer, digit-walk through FRED DGS10|
|`scripts/npx/npx\_final.py`|Form N-PX|Locked-in counting convention (zero-outcome rows count as zero)|
|`scripts/npx/npx\_independent\_walk.py`|Form N-PX|Alternative interpretation, used to test prompt ambiguity|
|`scripts/utils/compare.py`|Any text|Token-level diff of two prompt versions, saved as an HTML report|

## Running

```bash
pip install -r requirements.txt

# Modern 13F (save the information table HTML from EDGAR first)
python scripts/13f\_html/parse\_13f\_html.py data/citadel\_2024q4.html --top 10

# 1999 plain-text 13F (save the .txt submission file from EDGAR)
python scripts/13f\_plaintext/analyze\_13f\_text\_chase.py data/earlier.txt data/later.txt --cusip 36960410
```

Source filings aren't committed. Download them from EDGAR using the accession numbers in each task's reasoning chain.

## Note

All data comes from public SEC EDGAR filings and FRED. These are original tasks built for this portfolio.

