#!/usr/bin/env python3
"""
awards.py — The Ring yearly awards + year-end Top 100
=====================================================
Runs after elo.py (it reuses elo's Elo snapshots). Produces:

  THE RING (org/ring.html, between <!-- RINGAWARDS_AUTO_START/END -->):
    - Wrestler of the Year   (math: highest year-end Elo among wrestlers who
                              were active that year; tie broken by rating gain)
    - Year-End Top 100       (one collapsible ranking per year — the old top-10
                              table, now tracking 100)

  BY-HAND awards (between <!-- RINGAWARDS_HAND_START/END -->) are written ONCE
  as empty templates and then never touched again, so your hand edits survive:
    - Match of the Year, Rookie of the Year, Lifetime Achievement Award

  WRESTLER PAGES (wrestling/wrestlers/*.html, between <!-- WAWARDS_START/END -->,
  inserted just after "Titles in Wrestling"): each wrestler's Ring accolades —
  Wrestler of the Year wins and year-end top-100 finishes — in the same style.

Run automatically at the end of `python3 update.py`, or standalone:
    python3 wrestling/awards.py
"""

import csv
import glob
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

import elo  # noqa: E402
from update import WrestlingDatabase, resolve_site_date, format_site_date  # noqa: E402

RING_HTML = os.path.join(SCRIPT_DIR, 'org', 'ring.html')
WRESTLERS_DIR = os.path.join(SCRIPT_DIR, 'wrestlers')
TOP_N = 100
MIN_YEAR_BOUTS = 3         # minimum bouts in a year to qualify for WOTY

AUTO_START, AUTO_END = '<!-- RINGAWARDS_AUTO_START -->', '<!-- RINGAWARDS_AUTO_END -->'
HAND_START, HAND_END = '<!-- RINGAWARDS_HAND_START -->', '<!-- RINGAWARDS_HAND_END -->'
WA_START, WA_END = '<!-- WAWARDS_START -->', '<!-- WAWARDS_END -->'
WREC_START, WREC_END = '<!-- WRECORDS_START -->', '<!-- WRECORDS_END -->'
RECORDS_HTML = os.path.join(SCRIPT_DIR, 'records.html')


def slugify(name):
    return name.lower().replace(' ', '-').replace('.', '')


def _wlink(name, country='un'):
    return (f'<span class="fi fi-{country}"></span> '
            f'<a href="/wrestling/wrestlers/{slugify(name)}.html">{name}</a>')


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1:'st',2:'nd',3:'rd'}.get(n % 10, 'th')}"


def awards_date(year):
    """The Ring awards ceremony is held on the LAST SUNDAY of December (same
    calendar style as the draft's second-Saturday-of-January date)."""
    dec31 = datetime(year, 12, 31)
    return dec31 - timedelta(days=(dec31.weekday() - 6) % 7)   # Sun = 6


def best_draft_picks():
    """slug -> (pick, year, org) of a wrestler's highest (lowest-numbered) draft
    pick across every year on record. Reads wrestling/drafts/*.csv."""
    best = {}
    for path in glob.glob(os.path.join(SCRIPT_DIR, 'drafts', '*.csv')):
        year = os.path.basename(path)[:-4]
        if not year.isdigit():
            continue
        year = int(year)
        with open(path, encoding='utf-8') as f:
            for r in csv.DictReader(f):
                pick = (r.get('pick') or '').strip()
                if not pick.isdigit():         # champ rows have no pick
                    continue
                pick = int(pick)
                slug = r['slug']
                if slug not in best or pick < best[slug][0]:
                    best[slug] = (pick, year, (r.get('org') or '').upper())
    return best


# ─── Compute ─────────────────────────────────────────────────────────────────

def gendered_year_end(snaps, months):
    """{'men': {year: [ranked...]}, 'women': {year: [ranked...]}} — men and
    women ranked SEPARATELY (never mixed), each its own year-end Top 100 taken
    from the last archived month of that year.

    Only COMPLETE years get an award — a year still in progress (e.g. it is only
    January) has no meaningful year-end, so it is excluded. A year counts as
    complete once the data has moved past it, or once its December is on record.
    """
    if not months:
        return {'men': {}, 'women': {}}
    latest = months[-1]
    latest_year, latest_month = int(latest[:4]), int(latest[5:7])

    def complete(y):
        return y < latest_year or (y == latest_year and latest_month == 12)

    by_year_last = {}
    for key in months:
        by_year_last[int(key[:4])] = key   # months chronological → last wins
    out = {'men': {}, 'women': {}}
    for y, key in by_year_last.items():
        if not complete(y):
            continue
        for gender in ('men', 'women'):
            ranked = sorted(snaps[key][gender],
                            key=lambda r: (-r['rating'], r['name']))[:TOP_N]
            rows = []
            for i, r in enumerate(ranked, 1):
                r = dict(r)
                r['rank'] = i
                rows.append(r)
            if rows:
                out[gender][y] = rows
    return out


def yearly_activity(db):
    """year -> {name: bouts} from every singles match with a result."""
    act = defaultdict(lambda: defaultdict(int))
    for when, m in elo.singles_matches(db):
        y = when.year
        act[y][m['fighter1']] += 1
        act[y][m['fighter2']] += 1
    return act


def wrestler_of_the_year(year_end, activity):
    """year -> winner dict. Highest year-end Elo among wrestlers active >= 3
    times that year; ties broken by rating gain since the previous year-end."""
    prev_rating = {}
    woty = {}
    for y in sorted(year_end):
        ranking = year_end[y]
        rate_now = {r['name']: r['rating'] for r in ranking}
        eligible = [r for r in ranking
                    if activity.get(y, {}).get(r['name'], 0) >= MIN_YEAR_BOUTS]
        if eligible:
            def gain(r):
                return r['rating'] - prev_rating.get(r['name'], elo.BASE_RATING)
            # Year-end rating is the primary signal; gain breaks near-ties.
            best = max(eligible, key=lambda r: (r['rating'], gain(r)))
            woty[y] = best
        prev_rating = rate_now
    return woty


def most_improved(year_end, activity):
    """year -> winner dict with 'gain'. Biggest year-over-year jump in year-end
    Elo among wrestlers who were active >= 3 times that year AND appeared in the
    previous year's year-end ranking (so the jump is real, not a debut)."""
    prev_rating = {}
    out = {}
    for y in sorted(year_end):
        ranking = year_end[y]
        rate_now = {r['name']: r['rating'] for r in ranking}
        eligible = [r for r in ranking
                    if activity.get(y, {}).get(r['name'], 0) >= MIN_YEAR_BOUTS
                    and r['name'] in prev_rating]
        if eligible:
            best = max(eligible, key=lambda r: r['rating'] - prev_rating[r['name']])
            w = dict(best)
            w['gain'] = best['rating'] - prev_rating[best['name']]
            out[y] = w
        prev_rating = rate_now
    return out


# ─── The Ring page ───────────────────────────────────────────────────────────

GENDER_LABEL = {'men': "Men's", 'women': "Women's"}


TOP_SHOWN = 10             # only the top 10 are shown on the page; 11-100 live
                           # on the individual wrestler pages.


def _year_award_table(wy, cols, cell):
    """A newest-first Year|Wrestler|<value> table for a per-year award."""
    h = ['        <table class="champ-history" style="width:75%;">',
         '        <tr>' + ''.join(f'<th>{c}</th>' for c in cols) + '</tr>']
    for y in sorted(wy, reverse=True):
        r = wy[y]
        h.append(f'        <tr><th>{y}</th><td>{_wlink(r["name"], r["country"])}</td>'
                 f'<td>{cell(r)}</td></tr>')
    if not wy:
        h.append(f'        <tr><td colspan="{len(cols)}">No qualifying year yet.</td></tr>')
    h.append('        </table>')
    return h


def _all_time_top(ye):
    """All-time top-10 names for a gender: each wrestler's best year-end rating
    across every year, highest first (equal to the latest year while only one
    year is on record, then it diverges)."""
    best = {}
    for rows in ye.values():
        for r in rows:
            if r['name'] not in best or r['rating'] > best[r['name']][0]:
                best[r['name']] = (r['rating'], r['country'])
    ranked = sorted(best.items(), key=lambda kv: (-kv[1][0], kv[0]))[:TOP_SHOWN]
    return [{'name': n, 'country': c} for n, (rat, c) in ranked]


def _ten_column_table(ye):
    """The ten-column grid for one gender (imitates the classic P4P-by-year
    table): ranks 1-10 across the top, an all-time 'All' row, then one row per
    year (newest first). Identical names in the same rank column across adjacent
    years are merged vertically with rowspan, exactly like the reference table."""
    h = ['        <div style="overflow-x:auto;">',
         '        <table class="p4p-grid">',
         '        <tr><th>Year</th>'
         + ''.join(f'<th>{i}</th>' for i in range(1, TOP_SHOWN + 1)) + '</tr>']
    if not ye:
        h.append(f'        <tr><td colspan="{TOP_SHOWN + 1}">No qualifying year yet.</td></tr>')
        h += ['        </table>', '        </div>']
        return h

    def cell(e):
        # No flags in this grid — names only, to match the reference table.
        return (f'<a href="/wrestling/wrestlers/{slugify(e["name"])}.html">'
                f'{e["name"]}</a>') if e else ''

    # All-time row (never merged with the year rows below it).
    allrow = _all_time_top(ye)
    h.append('        <tr><th>All</th>'
             + ''.join(f'<td>{cell(allrow[i] if i < len(allrow) else None)}</td>'
                       for i in range(TOP_SHOWN)) + '</tr>')

    years = sorted(ye, reverse=True)
    grid = [ye[y][:TOP_SHOWN] for y in years]        # grid[row][col] -> entry
    n = len(years)

    def name_at(r, c):
        return grid[r][c]['name'] if c < len(grid[r]) else None

    # Vertical merge: a run of identical names down a rank column becomes one
    # rowspan cell emitted at the top of the run.
    skip = [[False] * TOP_SHOWN for _ in range(n)]
    span = [[1] * TOP_SHOWN for _ in range(n)]
    for c in range(TOP_SHOWN):
        r = 0
        while r < n:
            nm = name_at(r, c)
            if nm is None:
                r += 1
                continue
            k = r + 1
            while k < n and name_at(k, c) == nm:
                k += 1
            span[r][c] = k - r
            for rr in range(r + 1, k):
                skip[rr][c] = True
            r = k

    for r in range(n):
        cells = [f'<th>{years[r]}</th>']
        for c in range(TOP_SHOWN):
            if skip[r][c]:
                continue
            e = grid[r][c] if c < len(grid[r]) else None
            rs = f' rowspan="{span[r][c]}"' if span[r][c] > 1 else ''
            cells.append(f'<td{rs}>{cell(e)}</td>')
        h.append('        <tr>' + ''.join(cells) + '</tr>')
    h += ['        </table>', '        </div>']
    return h


def _grid_details(year_end, gender):
    gl = GENDER_LABEL[gender]
    h = ['    <details>', f'      <summary><i>The Ring</i> {gl} {TOP_N}</summary>']
    h += _ten_column_table(year_end[gender])
    h.append('    </details>')
    return h


def _woty_details(woty):
    h = ['    <details>',
         '      <summary><i>The Ring</i> Wrestler of the Year</summary>']
    for gender in ('men', 'women'):
        title = 'Wrestler of the Year' if gender == 'men' else 'Woman of the Year'
        h.append(f'        <p class="sub"><b><i>The Ring</i> {title}</b></p>')
        h.append('        <table class="champ-history" style="width:33%;">')
        h.append('        <tr><th>Year</th><th>Wrestler</th></tr>')
        wy = woty[gender]
        for y in sorted(wy, reverse=True):
            r = wy[y]
            h.append(f'        <tr><th>{y}</th><td>{_wlink(r["name"], r["country"])}</td></tr>')
        if not wy:
            h.append('        <tr><td colspan="2">No qualifying year yet.</td></tr>')
        h.append('        </table>')
    h.append('    </details>')
    return h


def _improved_details(improved):
    h = ['    <details>',
         '      <summary><i>The Ring</i> Most Improved Wrestler</summary>']
    for gender in ('men', 'women'):
        label = 'Most Improved Wrestler' if gender == 'men' else 'Most Improved Woman'
        h.append(f'        <p class="sub"><b><i>The Ring</i> {label}</b></p>')
        h += _year_award_table(improved[gender], ['Year', 'Wrestler', 'Elo gain'],
                               lambda r: f'+{r["gain"]:.0f}')
    h.append('    </details>')
    return h


def _hand_details(summary, rows, cols, width):
    """Render a parsed hand award (rows from _parse_hand_award) as a details
    table, reusing each row's raw cell HTML so it renders identically."""
    h = ['    <details>', f'      <summary>{summary}</summary>',
         f'        <table class="champ-history" style="width:{width};">',
         '        <tr>' + ''.join(f'<th>{c}</th>' for c in cols) + '</tr>']
    for r in sorted(rows, key=lambda r: -r['year']):
        tds = ''.join(f'<td>{c.strip()}</td>' for c in r['cells'][1:])
        h.append(f'        <tr><th>{r["year"]}</th>{tds}</tr>')
    if not rows:
        h.append(f'        <tr><td colspan="{len(cols)}">No qualifying year yet.</td></tr>')
    h += ['        </table>', '    </details>']
    return h


def _rookie_details(hand):
    """Rookie of the Year — men's and women's, two sub-tables like WOTY."""
    h = ['    <details>',
         '      <summary><i>The Ring</i> Rookie of the Year</summary>']
    for label, rows in (('Rookie of the Year', hand['rookie']),
                        ('Woman Rookie of the Year', hand['rookie_w'])):
        h.append(f'        <p class="sub"><b><i>The Ring</i> {label}</b></p>')
        h.append('        <table class="champ-history" style="width:33%;">')
        h.append('        <tr><th>Year</th><th>Wrestler</th></tr>')
        for r in sorted(rows, key=lambda r: -r['year']):
            h.append(f'        <tr><th>{r["year"]}</th><td>{r["cells"][1].strip()}</td></tr>')
        if not rows:
            h.append('        <tr><td colspan="2">No qualifying year yet.</td></tr>')
        h.append('        </table>')
    h.append('    </details>')
    return h


def render_auto(year_end, woty, improved, hand):
    """Full awards section, in order. `hand` is parse_hand_awards() output. Order:
    Men's 100, Women's 100, Wrestler of the Year, Match of the Year, Rookie of
    the Year, Comeback of the Year, Most Improved, Lifetime Achievement."""
    h = [AUTO_START, '    <h2>The Ring Awards</h2>']
    latest = max((y for g in ('men', 'women') for y in year_end[g]), default=None)
    if latest is not None:
        h.append('    <p class="sub">Presented at the year-end ceremony, held the '
                 f'last Sunday of December ({awards_date(latest).strftime("%B %-d, %Y")}).</p>')
    h += _grid_details(year_end, 'men')
    h += _grid_details(year_end, 'women')
    h += _woty_details(woty)
    h += _hand_details('<i>The Ring</i> Match of the Year', hand['match'],
                       ['Year', 'Match', 'Event', 'Date'], '75%')
    h += _rookie_details(hand)
    h += _hand_details('<i>The Ring</i> Comeback of the Year', hand['comeback'],
                       ['Year', 'Wrestler'], '33%')
    h += _improved_details(improved)
    h += _hand_details('<i>The Ring</i> Lifetime Achievement Award', hand['lifetime'],
                       ['Year', 'Wrestler'], '33%')
    h.append(f'    {AUTO_END}')
    return '\n'.join(h)


def render_hand_template():
    """Empty by-hand award tables — written only once, then never overwritten."""
    def tbl(title, cols):
        head = ''.join(f'<th>{c}</th>' for c in cols)
        blanks = ''.join(f'<td>{"&nbsp;" if i else "YEAR"}</td>'
                         for i in range(len(cols)))
        return (f'    <details>\n'
                f'      <summary>{title}</summary>\n'
                f'        <table class="champ-history" style="width:75%;">\n'
                f'        <tr>{head}</tr>\n'
                f'        <!-- add rows by hand below; this section is never overwritten -->\n'
                f'        <tr>{blanks}</tr>\n'
                f'        </table>\n'
                f'    </details>')
    return '\n'.join([
        HAND_START,
        '    <!-- Hand-authored award DATA. Edit the rows freely; awards.py parses '
        'these tables and renders them (in order) into the awards section above, '
        'so this block is hidden. awards.py never rewrites anything here. -->',
        '    <div style="display:none" aria-hidden="true">',
        tbl('<i>The Ring</i> Match of the Year', ['Year', 'Match', 'Event', 'Date']),
        tbl('<i>The Ring</i> Comeback of the Year', ['Year', 'Wrestler']),
        # Rookie of the Year: one details, two tables (men's, then women's).
        ('    <details>\n'
         '      <summary><i>The Ring</i> Rookie of the Year</summary>\n'
         '        <!-- first table = men\'s Rookie of the Year, second = Woman Rookie of the Year -->\n'
         '        <table class="champ-history" style="width:75%;">\n'
         '        <tr><th>Year</th><th>Wrestler</th></tr>\n'
         '        <tr><td>YEAR</td><td>&nbsp;</td></tr>\n'
         '        </table>\n'
         '        <table class="champ-history" style="width:75%;">\n'
         '        <tr><th>Year</th><th>Wrestler</th></tr>\n'
         '        <tr><td>YEAR</td><td>&nbsp;</td></tr>\n'
         '        </table>\n'
         '    </details>'),
        tbl('<i>The Ring</i> Lifetime Achievement Award', ['Year', 'Wrestler']),
        '    </div>',
        f'    {HAND_END}',
    ])


def _replace_between(text, start, end, block):
    if start in text and end in text:
        return text[:text.index(start)] + block + text[text.index(end) + len(end):]
    return None


def write_ring_awards(year_end, woty, improved, hand):
    with open(RING_HTML, encoding='utf-8') as f:
        html = f.read()
    auto = render_auto(year_end, woty, improved, hand)

    # 1) Auto section — always refreshed.
    updated = _replace_between(html, AUTO_START, AUTO_END, auto)
    if updated is None:
        # First time: insert both sections just after the P4P rankings block,
        # above "List of The Ring world champions".
        anchor = re.search(r'<h2>List of[^<]*world champions</h2>', html)
        hand = render_hand_template()
        inject = f'{auto}\n\n{hand}\n\n    '
        if anchor:
            html = html[:anchor.start()] + inject + html[anchor.start():]
        else:
            html = html.replace('</body>', f'\n{inject}\n</body>', 1)
    else:
        html = updated
        # Ensure the hand template exists exactly once (created, never rewritten).
        if HAND_START not in html:
            html = html.replace(AUTO_END, AUTO_END + '\n\n' + render_hand_template(), 1)

    with open(RING_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    nw = len(woty['men']) + len(woty['women'])
    nl = len(year_end['men']) + len(year_end['women'])
    print(f"  ✓ The Ring awards written ({nw} WOTY, {nl} year-end top-{TOP_N} lists)")


# ─── Per-wrestler accolades ──────────────────────────────────────────────────

def _years_str(years):
    return ', '.join(str(y) for y in sorted(years, reverse=True))


def _parse_rows(table_html):
    """Rows of one table: {'year', 'cells', 'wrestlers'}; placeholders skipped."""
    rows = []
    for tr in re.findall(r'<tr>(.*?)</tr>', table_html, re.S):
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
        if not tds or not tds[0].strip().isdigit():
            continue
        links = re.findall(r'/wrestlers/([a-z0-9-]+)\.html">([^<]+)</a>', tr)
        countries = re.findall(r'fi fi-([a-z]{2})', tr)
        wrestlers = [(s, n, countries[i] if i < len(countries) else 'un')
                     for i, (s, n) in enumerate(links)]
        rows.append({'year': int(tds[0].strip()), 'cells': tds, 'wrestlers': wrestlers})
    return rows


def _award_tables(html, summary):
    """All <table> HTML blocks inside the award identified by its <summary>."""
    m = re.search(re.escape(summary) + r'</summary>(.*?)</details>', html, re.S)
    return re.findall(r'<table.*?</table>', m.group(1), re.S) if m else []


def _parse_hand_award(html, summary):
    """Parse a single-table hand award (identified by its <summary>) into rows."""
    tables = _award_tables(html, summary)
    return _parse_rows(tables[0]) if tables else []


def parse_hand_awards():
    """All four hand-authored awards, parsed from ring.html (the hidden data
    block). Every award gets a parser so it can render into the section and be
    injected onto the wrestlers' pages."""
    with open(RING_HTML, encoding='utf-8') as f:
        html = f.read()
    # Restrict to the hidden hand DATA block — the auto section above now
    # contains the same summaries (its rendered copies), which must be ignored.
    if HAND_START in html and HAND_END in html:
        html = html[html.index(HAND_START):html.index(HAND_END)]
    # Rookie is one award with two tables (men's, then women's), like WOTY.
    rk = _award_tables(html, '<i>The Ring</i> Rookie of the Year')
    return {
        'match':    _parse_hand_award(html, '<i>The Ring</i> Match of the Year'),
        'rookie':   _parse_rows(rk[0]) if len(rk) > 0 else [],
        'rookie_w': _parse_rows(rk[1]) if len(rk) > 1 else [],
        'comeback': _parse_hand_award(html, '<i>The Ring</i> Comeback of the Year'),
        'lifetime': _parse_hand_award(html, '<i>The Ring</i> Lifetime Achievement Award'),
    }


def _pretty_date(raw):
    raw = re.sub(r'<[^>]+>', '', raw).strip()
    for fmt in ('%b %d, %Y', '%B %d, %Y'):
        try:
            return datetime.strptime(raw, fmt).strftime('%B %-d')
        except ValueError:
            continue
    return raw


def wrestler_accolades(year_end, woty, improved, picks, hand):
    """slug -> list of accolade strings. year_end / woty / improved are
    {'men': ..., 'women': ...}; picks is best_draft_picks(); hand is
    parse_hand_awards() (every hand award is injected onto wrestler pages)."""
    acc = defaultdict(list)
    # Match of the Year — a SHARED award: every participant won it. One line per
    # match: the award (with year), then a smaller (same-colour) "vs." tail. No
    # flags, no line breaks; repeats simply add another line.
    moty_by_slug = defaultdict(list)      # slug -> [(year, line)]
    for match in hand['match']:
        parts = match['wrestlers']
        event = re.split(r'<', match['cells'][2], 1)[0].strip()
        date = _pretty_date(match['cells'][3])
        for i, (slug, name, country) in enumerate(parts):
            opp = ', '.join(n for j, (_s, n, _c) in enumerate(parts) if j != i)
            tail = f'vs. {opp} at {event} on {date}' if opp else f'at {event} on {date}'
            line = (f'Match of the Year Award ({match["year"]}) '
                    f'<span style="font-size:0.85em">{tail}</span>')
            moty_by_slug[slug].append((match['year'], line))
    for slug, entries in moty_by_slug.items():
        for _y, line in sorted(entries, reverse=True):
            acc[slug].append(line)
    # Rookie / Woman Rookie / Comeback / Lifetime — one per wrestler, years grouped.
    for key, label in (('rookie', 'Rookie of the Year'),
                       ('rookie_w', 'Woman Rookie of the Year'),
                       ('comeback', 'Comeback of the Year'),
                       ('lifetime', 'Lifetime Achievement Award')):
        years_by_slug = defaultdict(list)
        for row in hand[key]:
            for slug, _name, _c in row['wrestlers']:
                years_by_slug[slug].append(row['year'])
        for slug, years in years_by_slug.items():
            acc[slug].append(f'{label} ({_years_str(years)})')
    for gender in ('men', 'women'):
        title = ('Wrestler of the Year' if gender == 'men' else 'Woman of the Year')
        imp = ('Most Improved Wrestler' if gender == 'men' else 'Most Improved Woman')
        gword = 'male' if gender == 'men' else 'female'
        woty_years = defaultdict(list)
        for y, r in woty[gender].items():
            woty_years[slugify(r['name'])].append(y)
        for slug, years in woty_years.items():
            for y in sorted(years, reverse=True):
                acc[slug].append(f'{title} ({y})')
        imp_years = defaultdict(list)
        for y, r in improved[gender].items():
            imp_years[slugify(r['name'])].append(y)
        for slug, years in imp_years.items():
            for y in sorted(years, reverse=True):
                acc[slug].append(f'{imp} ({y})')
        # Only the BEST rank ever achieved, with every year it happened.
        best_rank = {}                 # slug -> (rank, [years])
        for y, ranking in year_end[gender].items():
            for r in ranking:
                slug = slugify(r['name'])
                cur = best_rank.get(slug)
                if cur is None or r['rank'] < cur[0]:
                    best_rank[slug] = (r['rank'], [y])
                elif r['rank'] == cur[0]:
                    cur[1].append(y)
        for slug, (rk, years) in best_rank.items():
            acc[slug].append(
                f'Ranked No. {rk} of the top {TOP_N} {gword} singles wrestlers '
                f'in <a href="/wrestling/org/ring.html"><i>The Ring</i> {TOP_N}</a> '
                f'({_years_str(years)})')
    # Highest draft pick ever (lowest overall pick number).
    for slug, (pick, year, org) in picks.items():
        acc[slug].append(
            f'Drafted No. {pick} overall by {org} in <a href="/wrestling/org/'
            f'draft.html">The Draft</a> ({year})')
    return acc


def render_wrestler_block(items):
    # Pyramid order: shortest visible line on top, longest at the bottom.
    def visible_len(s):
        return len(re.sub(r'<[^>]+>', '', s))
    items = sorted(items, key=visible_len)
    lines = ' <br>\n'.join(items)
    return (f'{WA_START}\n'
            f'    <h3>Awards and honors</h3>\n'
            f'    <p>{lines}</p>\n'
            f'    {WA_END}')


def inject_wrestler_awards(year_end, woty, improved, picks, hand):
    acc = wrestler_accolades(year_end, woty, improved, picks, hand)
    if not os.path.isdir(WRESTLERS_DIR):
        print("  ⚠ wrestlers/ not found, skipping accolades")
        return
    touched = 0
    for path in glob.glob(os.path.join(WRESTLERS_DIR, '*.html')):
        slug = os.path.basename(path)[:-5]
        items = acc.get(slug)
        with open(path, encoding='utf-8') as f:
            html = f.read()
        # Remove any stale block first (update.py may re-emit the page fresh).
        if WA_START in html and WA_END in html:
            html = (html[:html.index(WA_START)]
                    + html[html.index(WA_END) + len(WA_END):]).rstrip('\n') + '\n'
        if not items:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html)
            continue
        block = render_wrestler_block(items)
        # Insert just after the "Titles in Wrestling" section if present, else
        # right before the match record; else before MATCHES_END / </body>.
        anchor = re.search(r'<h3>\s*Professional wrestling record\s*</h3>', html)
        if anchor:
            html = html[:anchor.start()] + block + '\n\n' + html[anchor.start():]
        elif '<!-- MATCHES_END -->' in html:
            html = html.replace('<!-- MATCHES_END -->', block + '\n<!-- MATCHES_END -->', 1)
        else:
            html = html.replace('</body>', block + '\n</body>', 1)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        touched += 1
    print(f"  ✓ Injected accolades into {touched} wrestler page(s)")


# ─── Per-wrestler records ("No. 1 in …") ─────────────────────────────────────

def collect_record_leaders():
    """slug -> [(caption, value)] for every All-Time Records table where the
    wrestler sits at No. 1. records.html is fully rendered by the time this runs
    (update.py fills the stat tables, elo.py fills the rating ones). Two-wrestler
    matchup tables (Biggest Upsets / Highest Matches by Rating) have no single
    record-holder and are skipped."""
    if not os.path.exists(RECORDS_HTML):
        return {}
    html = open(RECORDS_HTML, encoding='utf-8').read()
    leaders = defaultdict(list)
    for tbl in re.findall(
            r'<table class="p4p-rank record-table">.*?</table>', html, re.S):
        cap = re.search(r'<caption>(.*?)</caption>', tbl, re.S)
        row = re.search(
            r'<th>1</th>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>', tbl, re.S)
        if not (cap and row):
            continue
        caption, cell, value = cap.group(1).strip(), row.group(1), row.group(2).strip()
        links = re.findall(r'/wrestling/wrestlers/([a-z0-9\-]+)\.html', cell)
        if len(links) != 1 or not value:      # skip matchup tables + empty tables
            continue
        leaders[links[0]].append((caption, value))
    return leaders


def render_records_block(items):
    """A pyramid-ordered Records section (shortest visible line on top), each
    line 'Record name – value'."""
    def line(cap, val):
        return f'{cap} &ndash; {val}'

    def visible_len(s):
        return len(re.sub(r'<[^>]+>', '', s))

    lines = sorted((line(c, v) for c, v in items), key=visible_len)
    body = ' <br>\n    '.join(lines)
    return (f'{WREC_START}\n'
            f'    <h3>Records</h3>\n'
            f'    <p>{body}</p>\n'
            f'    {WREC_END}')


def inject_wrestler_records():
    """Add a Records section (directly under Awards and honors) to every wrestler
    who leads at least one All-Time Records table."""
    leaders = collect_record_leaders()
    if not os.path.isdir(WRESTLERS_DIR):
        print("  ⚠ wrestlers/ not found, skipping records")
        return
    touched = 0
    for path in glob.glob(os.path.join(WRESTLERS_DIR, '*.html')):
        slug = os.path.basename(path)[:-5]
        with open(path, encoding='utf-8') as f:
            html = f.read()
        # Drop any stale block first so re-runs stay idempotent.
        if WREC_START in html and WREC_END in html:
            html = (html[:html.index(WREC_START)]
                    + html[html.index(WREC_END) + len(WREC_END):])
            html = re.sub(r'\n{3,}', '\n\n', html)
        items = leaders.get(slug)
        if not items:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(html)
            continue
        block = render_records_block(items)
        if WA_END in html:                     # right after Awards and honors
            html = html.replace(WA_END, f'{WA_END}\n\n{block}', 1)
        else:                                  # no awards: sit above the record
            anchor = re.search(r'<h3>\s*Professional wrestling record\s*</h3>', html)
            if anchor:
                html = html[:anchor.start()] + block + '\n\n' + html[anchor.start():]
            else:
                html = html.replace('</body>', block + '\n</body>', 1)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        touched += 1
    print(f"  ✓ Injected records into {touched} wrestler page(s)")


# ─── Entry points ────────────────────────────────────────────────────────────

def run(db):
    """Called from update.py (db already parsed) or from main()."""
    months, snaps = elo.build_snapshots(db)
    if not months:
        print("  (No Elo snapshots; awards skipped.)")
        return
    year_end = gendered_year_end(snaps, months)
    activity = yearly_activity(db)
    woty = {g: wrestler_of_the_year(year_end[g], activity) for g in ('men', 'women')}
    improved = {g: most_improved(year_end[g], activity) for g in ('men', 'women')}
    picks = best_draft_picks()
    hand = parse_hand_awards()   # parse the hand data block before it renders
    write_ring_awards(year_end, woty, improved, hand)
    inject_wrestler_awards(year_end, woty, improved, picks, hand)
    # After awards land, tag each record-leading wrestler with a Records section
    # (records.html is already fully rendered by update.py + elo.py at this point).
    inject_wrestler_records()


def main():
    os.chdir(os.path.dirname(SCRIPT_DIR))
    ppv, weekly = 'wrestling/ppv/list.html', 'wrestling/weekly/list.html'
    db = WrestlingDatabase()
    site_date, _ = resolve_site_date(ppv, weekly)
    db.cutoff = site_date
    db.parse_events(ppv, is_weekly=False)
    if os.path.exists(weekly):
        db.parse_events(weekly, is_weekly=True)
    db.events.sort(key=lambda e: elo._parse_date(e.get('date')) or datetime.min)
    db.reprocess_championships_chronologically()
    db.process_vacancies()      # reprocess rebuilds the reigns from scratch, so
                                # the vacancies must be re-applied on top of it
    print(f"Site date: {format_site_date(site_date) or '(none)'}")
    run(db)
    print("✓ The Ring awards updated!")


if __name__ == '__main__':
    main()
