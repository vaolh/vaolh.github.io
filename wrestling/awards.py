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

import glob
import os
import re
import sys
from collections import defaultdict
from datetime import datetime

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


def slugify(name):
    return name.lower().replace(' ', '-').replace('.', '')


def _wlink(name, country='un'):
    return (f'<span class="fi fi-{country}"></span> '
            f'<a href="/wrestling/wrestlers/{slugify(name)}.html">{name}</a>')


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1:'st',2:'nd',3:'rd'}.get(n % 10, 'th')}"


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


# ─── The Ring page ───────────────────────────────────────────────────────────

GENDER_LABEL = {'men': "Men's", 'women': "Women's"}


def render_auto(year_end, woty):
    """year_end / woty are {'men': {...}, 'women': {...}}."""
    h = [AUTO_START, '    <h2>The Ring Awards</h2>']
    # Wrestler of the Year — separate men's and women's award.
    h.append('    <details open>')
    h.append('      <summary><i>The Ring</i> Wrestler of the Year</summary>')
    for gender in ('men', 'women'):
        wy = woty[gender]
        title = ('Wrestler of the Year' if gender == 'men'
                 else 'Woman of the Year')
        h.append(f'        <p class="sub"><b><i>The Ring</i> {title}</b></p>')
        h.append('        <table class="champ-history" style="width:75%;">')
        h.append('        <tr><th>Year</th><th>Wrestler</th><th>Year-end rating</th></tr>')
        for y in sorted(wy, reverse=True):
            r = wy[y]
            h.append(f'        <tr><th>{y}</th><td>{_wlink(r["name"], r["country"])}</td>'
                     f'<td>{r["rating"]:.0f}</td></tr>')
        if not wy:
            h.append('        <tr><td colspan="3">No qualifying year yet.</td></tr>')
        h.append('        </table>')
    h.append('    </details>')
    # Year-End Top 100 — separate men's and women's ranking.
    h.append('    <details>')
    h.append(f'      <summary><i>The Ring</i> Year-End Top {TOP_N}</summary>')
    for gender in ('men', 'women'):
        ye = year_end[gender]
        h.append(f'      <p class="sub"><b>{GENDER_LABEL[gender]} Top {TOP_N}</b></p>')
        for y in sorted(ye, reverse=True):
            h.append(f'      <details><summary>{y} — {GENDER_LABEL[gender]} Top {TOP_N}</summary>')
            h.append('        <table class="champ-history" style="width:90%;">')
            h.append('        <tr><th>Rank</th><th>Wrestler</th><th>Record</th><th>Rating</th></tr>')
            for r in ye[y]:
                h.append(f'        <tr><th>{r["rank"]}</th>'
                         f'<td>{_wlink(r["name"], r["country"])}</td>'
                         f'<td>{r["record"]}</td><td>{r["rating"]:.0f}</td></tr>')
            h.append('        </table>')
            h.append('      </details>')
    h.append('    </details>')
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
        '    <!-- Hand-authored awards. Edit freely; awards.py never rewrites '
        'anything between these two markers. -->',
        tbl('<i>The Ring</i> Match of the Year', ['Year', 'Match', 'Event']),
        tbl('<i>The Ring</i> Rookie of the Year', ['Year', 'Wrestler']),
        tbl('<i>The Ring</i> Lifetime Achievement Award', ['Year', 'Wrestler']),
        f'    {HAND_END}',
    ])


def _replace_between(text, start, end, block):
    if start in text and end in text:
        return text[:text.index(start)] + block + text[text.index(end) + len(end):]
    return None


def write_ring_awards(year_end, woty):
    with open(RING_HTML, encoding='utf-8') as f:
        html = f.read()
    auto = render_auto(year_end, woty)

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

def wrestler_accolades(year_end, woty):
    """slug -> list of accolade strings (newest first). year_end / woty are
    {'men': ..., 'women': ...}; each wrestler is ranked within their gender."""
    acc = defaultdict(list)
    for gender in ('men', 'women'):
        title = ('Wrestler of the Year' if gender == 'men' else 'Woman of the Year')
        gword = 'male' if gender == 'men' else 'female'
        woty_years = defaultdict(list)
        for y, r in woty[gender].items():
            woty_years[slugify(r['name'])].append(y)
        for slug, years in woty_years.items():
            for y in sorted(years, reverse=True):
                acc[slug].append(f'<i>The Ring</i> {title} ({y})')
        finishes = defaultdict(list)   # slug -> [(year, rank)]
        for y, ranking in year_end[gender].items():
            for r in ranking:
                finishes[slugify(r['name'])].append((y, r['rank']))
        for slug, fs in finishes.items():
            for y, rk in sorted(fs, reverse=True):
                acc[slug].append(
                    f'Ranked No. {rk} of the top {TOP_N} {gword} singles wrestlers '
                    f'in <i>The Ring</i> {TOP_N} in {y}')
    return acc


def render_wrestler_block(items):
    lis = '\n'.join(f'      <li>{it}</li>' for it in items)
    return (f'{WA_START}\n'
            f'    <h3>Awards and honors</h3>\n'
            f'    <ul class="awards-list">\n{lis}\n    </ul>\n'
            f'    {WA_END}')


def inject_wrestler_awards(year_end, woty):
    acc = wrestler_accolades(year_end, woty)
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
    write_ring_awards(year_end, woty)
    inject_wrestler_awards(year_end, woty)


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
    print(f"Site date: {format_site_date(site_date) or '(none)'}")
    run(db)
    print("✓ The Ring awards updated!")


if __name__ == '__main__':
    main()
