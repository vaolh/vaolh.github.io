#!/usr/bin/env python3
"""
open.py — Open Tournament automation for ppv/list.html

Two jobs, both aimed at killing the fiddly hand-editing of the 8-seed bracket:

  1. Generate a fresh template (two <details>: Day 1 "Qualifiers" + Day 2
     "Finals") appended just before <div id="bottom"> at the bottom of the file:

         python3 open.py 2021                 # placeholder dates
         python3 open.py 2021 2021-11-30      # Day 1 = that date, Day 2 = +1 day

     You then fill in the 8 women's seeds + 8 men's seeds in the two brackets and
     the match-card results (Quarterfinals on Day 1; Semifinals + Finals on Day 2).

  2. Populate the brackets from the match-card results you typed:

         python3 open.py populate             # every Open in the file
         python3 open.py populate 2021        # just that year

     For each bracket it fills the QF / SF / Final advancement slots, the win
     method into each `score` cell, and the country flags — reading them straight
     from the match cards. Women vs men are told apart purely by which 8 names are
     seeded in each bracket, so no gender tags are required. It only writes cells
     it can resolve, so it is safe to re-run as you enter more results.

Nothing in .old/ is ever touched; update.py is not modified.
"""

import re
import sys
import os
from datetime import datetime, timedelta

try:
    from bs4 import BeautifulSoup
except ImportError:
    sys.exit("This script needs beautifulsoup4 (pip install beautifulsoup4).")

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_LIST = os.path.join(HERE, "ppv", "list.html")

# ---------------------------------------------------------------------------
# Bracket geometry
#
# The 14 class="team" cells appear in this fixed document order (top -> bottom):
#
#   idx  role
#    0   seed 1        (QF pairing A, top)
#    1   seed 8        (QF pairing A, bottom)
#    2   SF entrant  <- winner of QF A (seed 1 v 8)
#    3   SF entrant  <- winner of QF B (seed 4 v 5)
#    4   seed 4        (QF pairing B, top)
#    5   seed 5        (QF pairing B, bottom)
#    6   Finalist    <- winner of SF top (idx2 v idx3)
#    7   Finalist    <- winner of SF bottom (idx10 v idx11)
#    8   seed 2        (QF pairing C, top)
#    9   seed 7        (QF pairing C, bottom)
#   10   SF entrant  <- winner of QF C (seed 2 v 7)
#   11   SF entrant  <- winner of QF D (seed 3 v 6)
#   12   seed 3        (QF pairing D, top)
#   13   seed 6        (QF pairing D, bottom)
#
# The 14 class="score" cells run in the same order. A score cell holds the method
# by which the wrestler in the neighbouring team cell won the NEXT round (so a
# seed's score = how they won their QF; an SF entrant's score = how they won the
# SF; a finalist's score = how they won the Final). Losers' score cells stay blank.
# ---------------------------------------------------------------------------

TEAMIDX_TO_SEED = {0: 1, 1: 8, 4: 4, 5: 5, 8: 2, 9: 7, 12: 3, 13: 6}
SEED_TO_TEAMIDX = {v: k for k, v in TEAMIDX_TO_SEED.items()}

# QF pairings: (seed_hi, seed_lo, sf_entrant_slot_idx)
QF_PAIRINGS = [
    (1, 8, 2),   # QF A -> SF top entrant (idx 2)
    (4, 5, 3),   # QF B -> SF top entrant (idx 3)
    (2, 7, 10),  # QF C -> SF bottom entrant (idx 10)
    (3, 6, 11),  # QF D -> SF bottom entrant (idx 11)
]
# SF matches: (entrant_slot_a, entrant_slot_b, finalist_slot_idx)
SF_PAIRINGS = [
    (2, 3, 6),    # SF top   -> Finalist top (idx 6)
    (10, 11, 7),  # SF bottom-> Finalist bottom (idx 7)
]
# Final: the two finalist slots
FINAL_SLOTS = (6, 7)


def norm(name):
    return re.sub(r"\s+", " ", (name or "")).strip()


# ---------------------------------------------------------------------------
# Reading match cards
# ---------------------------------------------------------------------------

def flag_of(td):
    span = td.find("span", class_="fi")
    if not span:
        return "xx"
    for c in span.get("class", []):
        if c.startswith("fi-"):
            return c[3:]
    return "xx"

def name_of(td):
    return norm(td.get_text())


def parse_match_card(table):
    """Return a list of singles match dicts from a match-card table."""
    out = []
    tbody = table.find("tbody") or table
    rows = tbody.find_all("tr", recursive=False)
    if not rows:
        rows = tbody.find_all("tr")
    for row in rows[1:]:  # skip header row
        tds = row.find_all("td", recursive=False)
        ths = row.find_all("th", recursive=False)
        # Match rows have a <th>No.</th> then 8 <td>. The trailing info row is
        # all <th>, so it has no/short td list -> skipped here.
        if len(tds) < 8:
            continue
        # tds: [type, weight, fighter1, sep, fighter2, method, falls, notes]
        f1, sep, f2, method = tds[2], tds[3], tds[4], tds[5]
        notes = tds[7].get_text().strip()
        if "open tournament" not in notes.lower():
            continue
        sep_txt = sep.get_text().strip().lower()
        winner_is_1 = sep_txt.startswith("def")
        out.append({
            "f1": name_of(f1), "f1_flag": flag_of(f1),
            "f2": name_of(f2), "f2_flag": flag_of(f2),
            "method": method.get_text().strip(),
            "notes": notes,
            "resolved": bool(name_of(f1) and name_of(f2)) and winner_is_1,
        })
    return out


def match_between(matches, a, b):
    """Find the resolved match whose two fighters are {a, b}. Returns
    (winner_name, winner_flag, method) or None."""
    a, b = norm(a), norm(b)
    if not a or not b:
        return None
    for m in matches:
        if not m["resolved"]:
            continue
        pair = {norm(m["f1"]), norm(m["f2"])}
        if pair == {a, b}:
            # winner is always f1 (left of "def.")
            return (m["f1"], m["f1_flag"], m["method"])
    return None


# ---------------------------------------------------------------------------
# Reading & rewriting a single bracket's raw HTML
# ---------------------------------------------------------------------------

TEAM_RE = re.compile(r'(<td\b[^>]*\bclass="team"[^>]*>)(.*?)(</td>)', re.DOTALL)
SCORE_RE = re.compile(r'(<td\b[^>]*\bclass="score"[^>]*>)(.*?)(</td>)', re.DOTALL)


def team_cells(bracket_html):
    return list(TEAM_RE.finditer(bracket_html))

def score_cells(bracket_html):
    return list(SCORE_RE.finditer(bracket_html))


def cell_flag_name(inner):
    """Split a team cell's inner HTML into (flag, name)."""
    m = re.search(r'fi-([a-z]{2,3})\b', inner)
    flag = m.group(1) if m else "xx"
    name = norm(re.sub(r"<[^>]+>", "", inner))
    return flag, name


def team_inner(flag, name):
    return f'<span class="fi fi-{flag}"></span> {name} '


def replace_by_index(html, regex, updates):
    """Rewrite the inner (group 2) of the regex matches whose index is a key in
    `updates`. `updates[i]` is the new inner string."""
    matches = list(regex.finditer(html))
    out = []
    last = 0
    for i, mt in enumerate(matches):
        if i in updates:
            out.append(html[last:mt.start()])
            out.append(mt.group(1) + updates[i] + mt.group(3))
            last = mt.end()
    out.append(html[last:])
    return "".join(out)


def populate_bracket(bracket_html, matches):
    """Fill SF/Final slots, score methods and flags in one bracket. Returns
    (new_html, filled_count)."""
    teams = team_cells(bracket_html)
    scores = score_cells(bracket_html)
    if len(teams) != 14 or len(scores) != 14:
        return bracket_html, -1  # not a standard 8-seed bracket; leave alone

    # Seed names by seed number.
    seed_name = {}
    for idx, seed_no in TEAMIDX_TO_SEED.items():
        _, nm = cell_flag_name(teams[idx].group(2))
        seed_name[seed_no] = nm

    team_updates = {}
    score_updates = {}
    # Track the actual occupant (name/flag) placed in each SF-entrant / finalist slot.
    slot_occupant = {}   # team-idx -> (name, flag)

    # --- Quarterfinals ---
    for hi, lo, sf_slot in QF_PAIRINGS:
        res = match_between(matches, seed_name.get(hi), seed_name.get(lo))
        if not res:
            continue
        wname, wflag, method = res
        team_updates[sf_slot] = team_inner(wflag, wname)
        slot_occupant[sf_slot] = (wname, wflag)
        # method goes on the winning seed's score cell
        win_seed = hi if norm(wname) == norm(seed_name.get(hi)) else lo
        score_updates[SEED_TO_TEAMIDX[win_seed]] = method

    # --- Semifinals ---
    for slot_a, slot_b, fin_slot in SF_PAIRINGS:
        na = slot_occupant.get(slot_a)
        nb = slot_occupant.get(slot_b)
        if not na or not nb:
            continue
        res = match_between(matches, na[0], nb[0])
        if not res:
            continue
        wname, wflag, method = res
        team_updates[fin_slot] = team_inner(wflag, wname)
        slot_occupant[fin_slot] = (wname, wflag)
        # method on the SF entrant slot the winner occupied
        win_slot = slot_a if norm(wname) == norm(na[0]) else slot_b
        score_updates[win_slot] = method

    # --- Final ---
    fa = slot_occupant.get(FINAL_SLOTS[0])
    fb = slot_occupant.get(FINAL_SLOTS[1])
    if fa and fb:
        res = match_between(matches, fa[0], fb[0])
        if res:
            wname, _, method = res
            win_slot = FINAL_SLOTS[0] if norm(wname) == norm(fa[0]) else FINAL_SLOTS[1]
            score_updates[win_slot] = method

    new_html = replace_by_index(bracket_html, TEAM_RE, team_updates)
    new_html = replace_by_index(new_html, SCORE_RE, score_updates)
    return new_html, len(team_updates) + len(score_updates)


# ---------------------------------------------------------------------------
# Locating brackets & Open editions in the raw file
# ---------------------------------------------------------------------------

SUMMARY_RE = re.compile(r"<summary>\s*(\d{4})\s+Open Tournament\b[^<]*</summary>", re.I)
BRACKET_OPEN = '<table cellpadding="0" class="bracket">'


def find_open_details(raw):
    """Yield (year, summary_start, bracket_start, bracket_end) for each Open
    <details> that contains a bracket table. Positions index into `raw`."""
    for sm in SUMMARY_RE.finditer(raw):
        year = int(sm.group(1))
        b_start = raw.find(BRACKET_OPEN, sm.end())
        if b_start == -1:
            continue
        # Stop before the next summary so we don't grab a later bracket.
        nxt = SUMMARY_RE.search(raw, sm.end())
        limit = nxt.start() if nxt else len(raw)
        if b_start > limit:
            continue
        b_end = raw.find("</table>", b_start)
        yield year, sm.start(), b_start, b_end + len("</table>")


def collect_matches_by_year(raw):
    """Parse every Open match card, grouped by year."""
    soup = BeautifulSoup(raw, "html.parser")
    by_year = {}
    for det in soup.find_all("details"):
        summary = det.find("summary")
        if not summary:
            continue
        m = re.match(r"\s*(\d{4})\s+Open Tournament", summary.get_text(), re.I)
        if not m:
            continue
        year = int(m.group(1))
        card = det.find("table", class_="match-card")
        if not card:
            continue
        by_year.setdefault(year, []).extend(parse_match_card(card))
    return by_year


def populate(path, only_year=None):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    matches_by_year = collect_matches_by_year(raw)
    if not matches_by_year:
        print("No Open Tournament match cards found.")
        return

    # Rebuild from the end so earlier offsets stay valid as we splice.
    brackets = list(find_open_details(raw))
    if only_year is not None:
        brackets = [b for b in brackets if b[0] == only_year]
        if not brackets:
            print(f"No Open bracket found for {only_year}.")
            return

    total = 0
    for year, _s, b_start, b_end in sorted(brackets, key=lambda x: x[2], reverse=True):
        bracket_html = raw[b_start:b_end]
        matches = matches_by_year.get(year, [])
        new_html, filled = populate_bracket(bracket_html, matches)
        if filled == -1:
            print(f"  {year}: bracket not a standard 8-seed layout — skipped.")
            continue
        if new_html != bracket_html:
            raw = raw[:b_start] + new_html + raw[b_end:]
            total += filled
        print(f"  {year}: filled {max(filled,0)} bracket cell(s).")

    if total:
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw)
        print(f"Wrote {path} ({total} cells updated).")
    else:
        print("Nothing to update (no new resolvable results).")


# ---------------------------------------------------------------------------
# Template generation
# ---------------------------------------------------------------------------

BLANK_BRACKET = '''        <table cellpadding="0" class="bracket">
        <tbody>
        <!-- Header Row -->
        <tr>
            <td></td>
            <td colspan="3" class="header">Quarterfinals</td>
            <td></td>
            <td></td>
            <td colspan="3" class="header">Semifinals</td>
            <td></td>
            <td></td>
            <td colspan="3" class="header">Finals</td>
            <td></td>
        </tr>
        <!-- Width Definition Row -->
        <tr>
            <td style="width:1px"></td>
            <td style="width:20px">&nbsp;</td>
            <td style="width:170px">&nbsp;</td>
            <td style="width:45px">&nbsp;</td>
            <td style="width:15px"></td>
            <td style="width:15px"></td>
            <td style="width:45px">&nbsp;</td>
            <td style="width:150px">&nbsp;</td>
            <td style="width:45px">&nbsp;</td>
            <td style="width:15px"></td>
            <td style="width:15px"></td>
            <td style="width:45px">&nbsp;</td>
            <td style="width:150px">&nbsp;</td>
            <td style="width:45px">&nbsp;</td>
            <td style="width:1px"></td>
        </tr>
        <!-- Seed 1 -->
        <tr>
            <td class="h7"></td>
            <td rowspan="2" class="seed">1</td>
            <td rowspan="2" class="team"><span class="fi fi-xx"></span>  </td>
            <td rowspan="2" class="score"></td>
            <td rowspan="2" class="conn" style="border-bottom-width:2px"></td>
            <td rowspan="3" colspan="5" class="conn"></td>
            <td rowspan="9" colspan="5" class="conn"></td>
        </tr>
        <tr>
            <td class="h7"></td>
        </tr>
        <!-- Seed 8 -->
        <tr>
            <td class="h7"></td>
            <td rowspan="2" class="seed">8</td>
            <td rowspan="2" class="team"><span class="fi fi-xx"></span>  </td>
            <td rowspan="2" class="score"></td>
            <td rowspan="2" class="conn" style="border-top-width:2px;border-right-width:2px"></td>
        </tr>
        <!-- QF 1 -->
        <tr>
            <td class="h7"></td>
            <td rowspan="2" class="conn" style="border-bottom-width:2px"></td>
            <td rowspan="2" colspan="2" class="team"><span class="fi fi-xx"></span>  </td>
            <td rowspan="2" class="score"></td>
            <td rowspan="2" class="conn" style="border-bottom-width:2px"></td>
        </tr>
        <tr>
            <td class="h7"></td>
            <td rowspan="2" colspan="3" style="text-align:center"></td>
            <td style="border-color:inherit;border-width:0 2px 0 0;border-style:solid"></td>
        </tr>
        <tr>
            <td class="h7"></td>
            <td style="border-color:inherit;border-width:0 2px 0 0;border-style:solid"></td>
            <td rowspan="2" class="conn" style="border-top-width:2px"></td>
            <td rowspan="2" colspan="2" class="team"><span class="fi fi-xx"></span> </td>
            <td rowspan="2" class="score"></td>
            <td rowspan="2" class="conn" style="border-top-width:2px;border-right-width:2px"></td>
        </tr>
        <!-- Seed 4 -->
        <tr>
            <td class="h7"></td>
            <td rowspan="2" class="seed">4</td>
            <td rowspan="2" class="team"><span class="fi fi-xx"></span>  </td>
            <td rowspan="2" class="score"></td>
            <td rowspan="2" class="conn" style="border-bottom-width:2px;border-right-width:2px"></td>
        </tr>
        <tr>
            <td class="h7"></td>
            <td rowspan="3" colspan="5" class="conn" style="border-right-width:2px"></td>
        </tr>
        <!-- Seed 5 -->
        <tr>
            <td class="h7"></td>
            <td rowspan="2" class="seed">5</td>
            <td rowspan="2" class="team"><span class="fi fi-xx"></span>  </td>
            <td rowspan="2" class="score"></td>
            <td rowspan="2" class="conn" style="border-top-width:2px"></td>
        </tr>
        <!-- FINALS -->
        <tr>
            <td class="h7"></td>
            <td rowspan="2" class="conn" style="border-bottom-width:2px"></td>
            <td rowspan="2" colspan="2" class="team"><span class="fi fi-xx"></span> </td>
            <td rowspan="2" class="score"></td>
            <td rowspan="2" class="conn"></td>
        </tr>
        <tr>
            <td class="h7"></td>
            <td rowspan="2" colspan="8" style="text-align:center"></td>
            <td style="border-color:inherit;border-width:0 2px 0 0;border-style:solid"></td>
        </tr>
        <tr>
            <td class="h7"></td>
            <td style="border-color:inherit;border-width:0 2px 0 0;border-style:solid"></td>
            <td rowspan="2" class="conn" style="border-top-width:2px"></td>
            <td rowspan="2" colspan="2" class="team"><span class="fi fi-xx"></span> </td>
            <td rowspan="2" class="score"></td>
            <td rowspan="2" class="conn"></td>
        </tr>
        <!-- Seed 2 -->
        <tr>
            <td class="h7"></td>
            <td rowspan="2" class="seed">2</td>
            <td rowspan="2" class="team"><span class="fi fi-xx"></span>  </td>
            <td rowspan="2" class="score"></td>
            <td rowspan="2" class="conn" style="border-bottom-width:2px"></td>
            <td rowspan="3" colspan="5" class="conn" style="border-right-width:2px"></td>
        </tr>
        <tr>
            <td class="h7"></td>
            <td rowspan="8" colspan="5" class="conn"></td>
        </tr>
        <!-- Seed 7 -->
        <tr>
            <td class="h7"></td>
            <td rowspan="2" class="seed">7</td>
            <td rowspan="2" class="team"><span class="fi fi-xx"></span>  </td>
            <td rowspan="2" class="score"></td>
            <td rowspan="2" class="conn" style="border-top-width:2px;border-right-width:2px"></td>
        </tr>
        <!-- QF 2 -->
        <tr>
            <td class="h7"></td>
            <td rowspan="2" class="conn" style="border-bottom-width:2px"></td>
            <td rowspan="2" colspan="2" class="team"><span class="fi fi-xx"></span> </td>
            <td rowspan="2" class="score"></td>
            <td rowspan="2" class="conn" style="border-bottom-width:2px;border-right-width:2px"></td>
        </tr>
        <tr>
            <td class="h7"></td>
            <td rowspan="2" colspan="3" style="text-align:center"></td>
            <td style="border-color:inherit;border-width:0 2px 0 0;border-style:solid"></td>
        </tr>
        <tr>
            <td class="h7"></td>
            <td style="border-color:inherit;border-width:0 2px 0 0;border-style:solid"></td>
            <td rowspan="2" class="conn" style="border-top-width:2px"></td>
            <td rowspan="2" colspan="2" class="team"><span class="fi fi-xx"></span> </td>
            <td rowspan="2" class="score"></td>
            <td rowspan="2" class="conn" style="border-top-width:2px"></td>
        </tr>
        <!-- Seed 3 -->
        <tr>
            <td class="h7"></td>
            <td rowspan="2" class="seed">3</td>
            <td rowspan="2" class="team"><span class="fi fi-xx"></span> </td>
            <td rowspan="2" class="score"></td>
            <td rowspan="2" class="conn" style="border-bottom-width:2px;border-right-width:2px"></td>
        </tr>
        <tr>
            <td class="h7"></td>
            <td rowspan="2" colspan="5" class="conn"></td>
        </tr>
        <!-- Seed 6 -->
        <tr>
            <td class="h7"></td>
            <td rowspan="2" class="seed">6</td>
            <td rowspan="2" class="team"><span class="fi fi-xx"></span> </td>
            <td rowspan="2" class="score"></td>
            <td class="conn" style="border-top-width:2px"></td>
        </tr>
        </tbody>
        </table>
'''

CARD_HEADER = '''        <table class="match-card">
            <tbody><tr>
                <th>No.</th>
                <th>Match Type</th>
                <th>Weight Class</th>
                <th></th>
                <th>vs.</th>
                <th></th>
                <th>Method</th>
                <th>Falls</th>
                <th>Notes</th>
            </tr>
'''


def card_row(no, notes):
    return f'''            <tr>
                <th>{no}</th>
                <td>Singles</td>
                <td>Openweight</td>
                <td><span class="fi fi-xx"></span> </td>
                <td>def.</td>
                <td><span class="fi fi-xx"></span> </td>
                <td></td>
                <td>[1-0]</td>
                <td>{notes}</td>
            </tr>
'''


def card_info_row(date_str):
    return f'''            <tr>
                <th> <a href="">PPV</a> </th>
                <th colspan="2"><span class="fi fi-xx"></span> City, Country </th>
                <th colspan="2">Venue</th>
                <th>Attendance: </th>
                <th>Network</th>
                <th> </th>
                <th>{date_str} </th>
            </tr>
        </tbody></table>
'''


def build_details(year, subtitle, bracket, rows_notes, date_str):
    rows = "".join(card_row(i + 1, note) for i, note in enumerate(rows_notes))
    return (
        f"<!-- {year} Open -->\n"
        "    <details>\n"
        f"        <summary>{year} Open Tournament - {subtitle}</summary>\n"
        f"{bracket}"
        f"{CARD_HEADER}{rows}{card_info_row(date_str)}"
        "    </details>\n"
    )


def generate_template(path, year, date_str=None):
    if date_str:
        try:
            d1 = datetime.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            sys.exit(f"Date must be YYYY-MM-DD (got {date_str!r}).")
        day1 = d1.strftime("%B %-d, %Y")
        day2 = (d1 + timedelta(days=1)).strftime("%B %-d, %Y")
    else:
        day1 = day2 = "MONTH DAY, YEAR"

    # Day 1: women's bracket + 8 quarterfinal rows (4 men + 4 women).
    day1_notes = ["Open Tournament Quarterfinals"] * 8
    # Day 2: men's bracket + 4 semifinal rows + 2 final rows.
    day2_notes = ["Open Tournament Semifinals"] * 4 + ["Open Tournament Finals"] * 2

    block = "\n" + build_details(year, "Qualifiers", BLANK_BRACKET, day1_notes, day1) \
            + "\n" + build_details(year, "Finals", BLANK_BRACKET, day2_notes, day2) + "\n"

    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    anchor = '<div id="bottom"></div>'
    if anchor in raw:
        raw = raw.replace(anchor, block + anchor, 1)
    else:
        raw = raw.rstrip() + "\n" + block
    with open(path, "w", encoding="utf-8") as f:
        f.write(raw)
    print(f"Appended {year} Open template (Qualifiers + Finals) to {path}.")
    print("Fill in the seeds and match results, then run: python3 open.py populate")


# ---------------------------------------------------------------------------

USAGE = """Usage:
  python3 open.py <year> [YYYY-MM-DD]   generate a blank Open template
  python3 open.py populate [year]      fill brackets from match-card results

Optional trailing argument: path to list.html (default ppv/list.html)."""


def main(argv):
    args = argv[1:]
    # optional explicit path as last arg
    path = DEFAULT_LIST
    if args and args[-1].endswith(".html"):
        path = args.pop()
    if not os.path.exists(path):
        sys.exit(f"File not found: {path}")

    if not args:
        print(USAGE)
        return

    if args[0].lower() == "populate":
        year = int(args[1]) if len(args) > 1 else None
        populate(path, year)
        return

    if re.fullmatch(r"\d{4}", args[0]):
        year = int(args[0])
        date_str = args[1] if len(args) > 1 else None
        generate_template(path, year, date_str)
        return

    print(USAGE)


if __name__ == "__main__":
    main(sys.argv)
