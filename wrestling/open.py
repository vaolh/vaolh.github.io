#!/usr/bin/env python3
"""
open.py — Open Tournament + event automation for ppv/list.html

=============================================================================
CHEAT SHEET  (run from the wrestling/ folder)
=============================================================================

  BLANK OPEN TOURNAMENT  (two <details>: Day 1 "Qualifiers" + Day 2 "Finals",
  appended just before <div id="bottom"> at the bottom of the file)

      python3 open.py 2021                 # placeholder dates
      python3 open.py 2021 2021-11-30      # Day 1 = that date, Day 2 = +1 day
      python3 open.py open 2021 ...        # same thing, spelled out

  BLANK WORLD TITLE SERIES EVENT  (a normal 8-match card, auto-numbered to the
  next "World Title Series N" found in the file — e.g. after WTS 27 you get 28)

      python3 open.py wts                  # -> "World Title Series 28: TBD"
      python3 open.py wts 2020-01-15       # with a date

  POPULATE  (fill the brackets + next-stage matchups from the results you typed)

      python3 open.py populate             # every Open in the file
      python3 open.py populate 2021        # just that year
      # also runs automatically at the start of `python3 update.py`

  (Any command takes an optional trailing path to a list.html; default is
   ppv/list.html next to this script.)

=============================================================================
WHAT `open` EXPECTS  —  the men / women convention
=============================================================================

An Open edition = TWO <details> blocks in this order:

  Day 1  "<year> Open Tournament - Qualifiers"  -> the WOMEN'S bracket
  Day 2  "<year> Open Tournament - Finals"      -> the MEN'S   bracket

Each block has an 8-seed bracket + a match card. Fill them like this:

  * Seeds: type the 8 WOMEN into the Day-1 bracket and the 8 MEN into the
    Day-2 bracket, in seed order (the seed numbers 1,8,4,5,2,7,3,6 are fixed).
  * ORDER within the cards (fixed gender sequence, matching the 2019 edition):

        Day-1 QUARTERFINALS (8 rows):
          1 Men    2 Women  3 Women  4 Men
          5 Women  6 Men    7 Women  8 Men
        Day-2 SEMIFINALS (4 rows) then FINALS (2 rows):
          1 Men    2 Women  3 Men    4 Women
          5 Women's Final   6 Men's Final

  * Notes carry the gender + round, e.g. "Men's Open Tournament Semifinals".
    Generated templates already write these; keep the "Women's/Men's ...
    Quarterfinals/Semifinals/Finals" wording so update.py counts both winners
    and populate routes each matchup to the correctly-labelled row (the row
    ORDER above is just how the blank template is laid out — the gender word in
    the note is what actually decides where a matchup lands).
  * In each match row the WINNER goes on the left of "def." (use "vs." for a
    matchup not wrestled yet — populate fills those in for you).

How populate uses that:
  - It fills a bracket by matching the 8 seeded names against the cards, so the
    women/men split is really driven by *who is seeded in that bracket* — the
    gender in the notes only decides which SF/Final card ROW a matchup lands in
    (if a card row's note has no gender it just fills in row order, so gender
    the notes to get the men-first / women-final layout above).
  - It only writes cells/rows it can resolve and never overwrites a filled one,
    so it is safe to re-run as more results are entered.

Nothing in .old/ is ever touched.
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


def detect_bracket_gender(bracket_html, matches):
    """Return 'women'/'men' if a QF match involving this bracket's seeds carries a
    gendered note, else None (caller falls back to bracket order)."""
    teams = team_cells(bracket_html)
    if len(teams) != 14:
        return None
    seeds = {norm(re.sub(r"<[^>]+>", "", teams[i].group(2)))
             for i in TEAMIDX_TO_SEED}
    for m in matches:
        if norm(m["f1"]) in seeds and norm(m["f2"]) in seeds:
            low = m["notes"].lower()
            if "women" in low:
                return "women"
            if "men" in low:
                return "men"
    return None


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
    """Fill SF/Final slots, score methods and flags in one bracket.

    Returns (new_html, filled_count, matchups) where matchups describes the
    next-stage pairings that are now known, so the caller can also drop them into
    the match card:
        matchups = {'sf': [(a,fa,b,fb), ...], 'final': (a,fa,b,fb) | None}
    """
    empty = {'sf': [], 'final': None}
    teams = team_cells(bracket_html)
    scores = score_cells(bracket_html)
    if len(teams) != 14 or len(scores) != 14:
        return bracket_html, -1, empty  # not a standard 8-seed bracket; leave alone

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

    # --- Next-stage matchups for the match card ---
    matchups = {'sf': [], 'final': None}
    for slot_a, slot_b, _fin in SF_PAIRINGS:   # top, then bottom
        na = slot_occupant.get(slot_a)
        nb = slot_occupant.get(slot_b)
        if na and nb:
            matchups['sf'].append((na[0], na[1], nb[0], nb[1]))
    if fa and fb:
        matchups['final'] = (fa[0], fa[1], fb[0], fb[1])

    new_html = replace_by_index(bracket_html, TEAM_RE, team_updates)
    new_html = replace_by_index(new_html, SCORE_RE, score_updates)
    return new_html, len(team_updates) + len(score_updates), matchups


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


# --- Match-card region helpers -------------------------------------------

CARD_OPEN = '<table class="match-card">'
ROW_RE = re.compile(r'<tr>\s*<th>\d+</th>.*?</tr>', re.DOTALL)
TD_RE = re.compile(r'(<td\b[^>]*>)(.*?)(</td>)', re.DOTALL)


def find_open_cards(raw):
    """Yield (year, card_start, card_end) for every Open Tournament match card."""
    for sm in SUMMARY_RE.finditer(raw):
        year = int(sm.group(1))
        # the details ends at the next summary (or EOF)
        nxt = SUMMARY_RE.search(raw, sm.end())
        limit = nxt.start() if nxt else len(raw)
        pos = sm.end()
        while True:
            c_start = raw.find(CARD_OPEN, pos)
            if c_start == -1 or c_start > limit:
                break
            c_end = raw.find("</table>", c_start) + len("</table>")
            yield year, c_start, c_end
            pos = c_end


def row_fighters_and_notes(row_html):
    """Return (name1, name2, notes_lower) for a match row."""
    tds = TD_RE.findall(row_html)
    if len(tds) < 8:
        return None, None, ""
    n1 = norm(re.sub(r"<[^>]+>", "", tds[2][1]))
    n2 = norm(re.sub(r"<[^>]+>", "", tds[4][1]))
    notes = norm(re.sub(r"<[^>]+>", "", tds[7][1])).lower()
    return n1, n2, notes


def existing_pairs_in_card(card_html):
    pairs = set()
    for row in ROW_RE.findall(card_html):
        n1, n2, _ = row_fighters_and_notes(row)
        if n1 and n2:
            pairs.add(frozenset((n1, n2)))
    return pairs


def _row_gender(notes):
    if "women" in notes:
        return "women"
    if "men" in notes:  # note: checked after "women" since it is a substring
        return "men"
    return None


def _take(queue, row_gender):
    """Pop a matchup from queue suited to the row's gender. Tuples are
    (gender, a, fa, b, fb); gender may be None (unknown)."""
    for i, item in enumerate(queue):
        g = item[0]
        if row_gender is None or g is None or g == row_gender:
            return queue.pop(i)
    return None


def fill_card(card_html, sf_queue, final_queue):
    """Drop next-stage matchups into blank Semifinal / Final rows (names + 'vs.',
    no result). Consumes from the queues. Returns (new_html, filled_rows).
    Queue items are (gender, a, fa, b, fb)."""
    filled = 0

    def repl(m):
        nonlocal filled
        row = m.group(0)
        n1, n2, notes = row_fighters_and_notes(row)
        blank = (not n1) and (not n2)
        if not blank:
            return row
        is_sf = "semifinal" in notes
        is_final = ("final" in notes) and not is_sf
        rg = _row_gender(notes)
        item = _take(sf_queue, rg) if is_sf else (_take(final_queue, rg) if is_final else None)
        if not item:
            return row
        _g, a, fa, b, fb = item
        filled += 1
        # rewrite fighter1 (td idx 2) and fighter2 (td idx 4) inner cells
        idx = [0]
        def td_repl(t):
            i = idx[0]; idx[0] += 1
            if i == 2:
                return t.group(1) + team_inner(fa, a) + t.group(3)
            if i == 4:
                return t.group(1) + team_inner(fb, b) + t.group(3)
            return t.group(0)
        return TD_RE.sub(td_repl, row)

    return ROW_RE.sub(repl, card_html), filled


def populate(path, only_year=None):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    matches_by_year = collect_matches_by_year(raw)
    if not matches_by_year:
        print("No Open Tournament match cards found.")
        return

    brackets = list(find_open_details(raw))
    cards = list(find_open_cards(raw))
    if only_year is not None:
        brackets = [b for b in brackets if b[0] == only_year]
        cards = [c for c in cards if c[0] == only_year]
        if not brackets:
            print(f"No Open bracket found for {only_year}.")
            return

    # --- Pass 1: compute bracket edits + collect next-stage matchups per year ---
    # Brackets are yielded in document order, so the first bracket of a year is
    # Day 1 (women) and the second is Day 2 (men). Each matchup is tagged with a
    # gender (detected from the QF note, else by that bracket order) so it fills
    # the correctly-labelled card row.
    edits = []                    # (start, end, new_html)
    year_matchups = {}            # year -> {'sf': [...], 'final': [...]}
    year_bracket_count = {}
    for year, _s, b_start, b_end in brackets:
        matches = matches_by_year.get(year, [])
        bracket_html = raw[b_start:b_end]
        new_html, filled, mu = populate_bracket(bracket_html, matches)
        if filled == -1:
            print(f"  {year}: bracket not a standard 8-seed layout — skipped.")
            continue
        if new_html != bracket_html:
            edits.append((b_start, b_end, new_html))
        order = year_bracket_count.get(year, 0)
        year_bracket_count[year] = order + 1
        gender = detect_bracket_gender(bracket_html, matches) or ("women" if order == 0 else "men")
        ym = year_matchups.setdefault(year, {'sf': [], 'final': []})
        ym['sf'].extend((gender,) + m for m in mu['sf'])
        if mu['final']:
            ym['final'].append((gender,) + mu['final'])
        print(f"  {year}: filled {max(filled,0)} bracket cell(s).")

    # --- Pass 2: fill blank Semifinal / Final rows in the match cards ---
    # Drop matchups the user hasn't already entered, keeping bracket order.
    for year in {y for y, *_ in cards}:
        year_cards = [(s, e) for y, s, e in cards if y == year]
        already = set()
        for s, e in year_cards:
            already |= existing_pairs_in_card(raw[s:e])
        mu = year_matchups.get(year, {'sf': [], 'final': []})
        # tuples are (gender, a, fa, b, fb); dedup on the {a, b} name pair
        sf_q = [m for m in mu['sf'] if frozenset((m[1], m[3])) not in already]
        fin_q = [m for m in mu['final'] if frozenset((m[1], m[3])) not in already]
        for s, e in year_cards:
            card_html = raw[s:e]
            new_card, n = fill_card(card_html, sf_q, fin_q)
            if n:
                edits.append((s, e, new_card))
                print(f"  {year}: filled {n} match-card matchup row(s).")

    if not edits:
        print("Nothing to update (no new resolvable results).")
        return

    # Apply edits from the end so earlier offsets stay valid.
    for start, end, new_html in sorted(edits, key=lambda x: x[0], reverse=True):
        raw = raw[:start] + new_html + raw[end:]

    with open(path, "w", encoding="utf-8") as f:
        f.write(raw)
    print(f"Wrote {path}.")


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

    # Day 1: women's bracket + 8 quarterfinal rows. Fixed gender sequence
    # (matches the 2019 edition): Men, Women, Women, Men, Women, Men, Women, Men.
    _MQF = "Men's Open Tournament Quarterfinals"
    _WQF = "Women's Open Tournament Quarterfinals"
    day1_notes = [_MQF, _WQF, _WQF, _MQF, _WQF, _MQF, _WQF, _MQF]
    # Day 2: men's bracket + 4 semifinals (men top, women top, men bottom, women
    # bottom) + 2 finals (women's final first, then men's).
    day2_notes = ["Men's Open Tournament Semifinals",
                  "Women's Open Tournament Semifinals",
                  "Men's Open Tournament Semifinals",
                  "Women's Open Tournament Semifinals",
                  "Women's Open Tournament Finals",
                  "Men's Open Tournament Finals"]

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
# Blank World Title Series (regular event) template, auto-numbered
# ---------------------------------------------------------------------------

def wts_row(no):
    return f'''            <tr>
                <th>{no}</th>
                <td>Singles</td>
                <td>Weight</td>
                <td><span class="fi fi-xx"></span> </td>
                <td>def.</td>
                <td><span class="fi fi-xx"></span> </td>
                <td></td>
                <td>[1-0]</td>
                <td></td>
            </tr>
'''


def next_wts_number(raw):
    nums = [int(n) for n in re.findall(r"World Title Series\s+(\d+)", raw)]
    return (max(nums) + 1) if nums else 1


def generate_wts(path, date_str=None, rows=8):
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    number = next_wts_number(raw)
    if date_str:
        try:
            date_disp = datetime.strptime(date_str, "%Y-%m-%d").strftime("%B %-d, %Y")
        except ValueError:
            sys.exit(f"Date must be YYYY-MM-DD (got {date_str!r}).")
    else:
        date_disp = "MONTH DAY, YEAR"

    body = "".join(wts_row(i + 1) for i in range(rows))
    block = (
        f"\n<!-- WTS {number} -->\n"
        "    <details>\n"
        f"        <summary>World Title Series {number}: TBD</summary>\n"
        f"{CARD_HEADER}{body}{card_info_row(date_disp)}"
        "    </details>\n\n"
    )

    anchor = '<div id="bottom"></div>'
    if anchor in raw:
        raw = raw.replace(anchor, block + anchor, 1)
    else:
        raw = raw.rstrip() + "\n" + block
    with open(path, "w", encoding="utf-8") as f:
        f.write(raw)
    print(f"Appended blank World Title Series {number} to {path}.")


# ---------------------------------------------------------------------------

USAGE = """Usage:
  python3 open.py <year> [YYYY-MM-DD]   generate a blank Open Tournament template
  python3 open.py wts [YYYY-MM-DD]      generate a blank WTS event (auto-numbered)
  python3 open.py populate [year]       fill brackets + next-stage matchups

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

    cmd = args[0].lower()

    if cmd == "populate":
        year = int(args[1]) if len(args) > 1 else None
        populate(path, year)
        return

    if cmd == "wts":
        date_str = args[1] if len(args) > 1 else None
        generate_wts(path, date_str)
        return

    if cmd == "open" and len(args) > 1 and re.fullmatch(r"\d{4}", args[1]):
        generate_template(path, int(args[1]), args[2] if len(args) > 2 else None)
        return

    if re.fullmatch(r"\d{4}", args[0]):
        year = int(args[0])
        date_str = args[1] if len(args) > 1 else None
        generate_template(path, year, date_str)
        return

    print(USAGE)


if __name__ == "__main__":
    main(sys.argv)
