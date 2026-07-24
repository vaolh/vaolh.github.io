#!/usr/bin/env python3
"""
draft.py — Annual wrestling draft (champ + 10 per org, per division)
====================================================================
Reads wrestling/rosters.csv (built by roster.py) and live Elo ratings (from
elo.py), then for every division assigns 10 challengers to each of the three
orgs (WWF / WWO / IWB) around the reigning champion, who is locked in place.

  - Champions are NOT drafted. They sit atop their org's division table in a
    yellow "C" cell (boxing style); the 10 drafted challengers rank below.
  - Retired wrestlers (lost a career apuesta — see roster.py) are excluded.
  - Selection spreads across the Elo ladder (guarantees the top-5 and bottom-5
    are represented, not just the strongest) and prioritises wrestlers who have
    not competed in a while, to spread opportunities.
  - Locks for a year. Each year is its own record; draft.html keeps the history.

USAGE  (run from the wrestling/ folder; venv with bs4 active)
  python3 draft.py                 # interactive draft for the current year
  python3 draft.py --year 2020     # draft a specific year
  python3 draft.py --auto          # auto-fill every division, no prompts
  python3 draft.py --render        # only rebuild draft.html from drafts/*.csv

Writes:
  wrestling/drafts/<year>.csv      one row per (division, org, slot)
  wrestling/org/draft.html         between <!-- DRAFT_RECORDS_START/END -->
"""

import csv
import io
import os
import sys
from collections import defaultdict
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from update import WrestlingDatabase, resolve_site_date, format_site_date  # noqa: E402
import elo  # noqa: E402
from roster import (slugify, read_text_any, truthy, WEIGHT_ORDER,  # noqa: E402
                    WEIGHT_INDEX, WOMENS_WEIGHTS, ORGS, ROSTER_PATH)

ORG_NAMES = {'wwf': 'WWF', 'wwo': 'WWO', 'iwb': 'IWB'}
SLOTS_PER_ORG = 10
DRAFTS_DIR = os.path.join(SCRIPT_DIR, 'drafts')
DRAFT_HTML = os.path.join(SCRIPT_DIR, 'org', 'draft.html')
YEAR_FIELDS = ['round', 'pick', 'org', 'slot', 'division', 'slug', 'name',
               'country', 'rating', 'is_champ']


# ─── Data loading ────────────────────────────────────────────────────────────

def load_roster():
    text = read_text_any(ROSTER_PATH)
    return list(csv.DictReader(io.StringIO(text)))


def load_ratings_and_site_date():
    """Return (ratings, ranks, site_date). ratings/ranks map wrestler NAME ->
    current Elo / global rank, from the latest monthly snapshot elo.py builds."""
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
    months, snaps = elo.build_snapshots(db)
    ratings, ranks = {}, {}
    if months:
        last = snaps[months[-1]]
        for gender in ('men', 'women'):
            for r in last[gender]:
                ratings[r['name']] = r['rating']
                ranks[r['name']] = r['rank']
    sd = elo._parse_date(format_site_date(site_date)) if site_date else None
    return ratings, ranks, sd


def inactivity_days(row, site_date):
    """How long since this wrestler last competed. Never-competed / unknown =
    very large, so they sort as 'most in need of an opportunity'."""
    la = (row.get('last_active') or '').strip()
    if not la or not site_date:
        return 10 ** 6
    try:
        d = datetime.strptime(la, '%Y-%m-%d')
    except ValueError:
        return 10 ** 6
    return max(0, (site_date - d).days)


# ─── Draft algorithm ─────────────────────────────────────────────────────────

def division_entries(roster, division):
    """(champs, pool) for a division. champs = rows holding that weight's belt
    (mapped to the org(s) they hold); pool = draftable challengers."""
    champs = {}          # org -> row
    pool = []
    for row in roster:
        if (row.get('division') or '').strip().lower() != division:
            continue
        if truthy(row.get('retired')):
            continue
        belts = _belts_of(row)
        held_here = [org for org, w in belts if w == division]
        if held_here:
            for org in held_here:
                champs[org] = row
        else:
            pool.append(row)
    return champs, pool


def _belts_of(row):
    """[(org, weight), ...] every belt a row currently holds."""
    out = []
    if row.get('champion_org') and row.get('champion_weight'):
        out.append((row['champion_org'].strip().lower(),
                    row['champion_weight'].strip().lower()))
    for tok in (row.get('champion_all') or '').split(';'):
        tok = tok.strip()
        if ':' in tok:
            o, w = tok.split(':', 1)
            pair = (o.strip().lower(), w.strip().lower())
            if pair not in out:
                out.append(pair)
    return out


def _rating(row, ratings):
    return ratings.get(row['name'])


DRAFT_ORDER = ('wwf', 'wwo', 'iwb')   # round-1 order; snake reverses each round


def build_board(roster):
    """(champ_of, board). champ_of maps (org, division) -> the reigning champion
    row (locked, not drafted). board = every draftable wrestler (has a division,
    not retired, not a champion)."""
    champ_of, board = {}, []
    for row in roster:
        div = (row.get('division') or '').strip().lower()
        if div not in WEIGHT_ORDER or truthy(row.get('retired')):
            continue
        belts = [(o, w) for (o, w) in _belts_of(row) if w == div]
        if belts:
            for o, w in belts:
                champ_of[(o, div)] = row
        else:
            board.append(row)
    return champ_of, board


def _menu_sort(rows, ratings, site_date):
    """Highest Elo first; unrated after (least idle first so returning names
    surface); name as a stable tiebreak."""
    return sorted(rows, key=lambda r: (
        -(_rating(r, ratings) if _rating(r, ratings) is not None else -1e9),
        inactivity_days(r, site_date), r['name']))


def _prompt_pick(org, rnd, pickno, av, counts, ratings, site_date, board_left):
    print(f"\n── Round {rnd}, pick {pickno} — {ORG_NAMES[org]} on the clock "
          f"({board_left} on the board) ──")
    fills = '  '.join(f"{d[:4].capitalize()} {counts[(org, d)]}/{SLOTS_PER_ORG}"
                      for d in WEIGHT_ORDER)
    print(f"   {ORG_NAMES[org]}: {fills}")
    top = av[:10]                                  # top 10 by Elo on the board
    for i, r in enumerate(top, 1):
        el = _rating(r, ratings)
        el = f"{el:4.0f}" if el is not None else "  — "
        days = inactivity_days(r, site_date)
        dd = 'never' if days >= 10 ** 6 else f"{days}d"
        print(f"     {i:2}. {r['name']:<22} {r['division'].capitalize():13} "
              f"Elo {el}  idle {dd}")
    print("   enter #, or a name; 'auto'=take best, 'autoall'=finish rest, 'quit'")
    while True:
        try:
            cmd = input("   > ").strip()
        except EOFError:
            return av[0], True
        low = cmd.lower()
        if not cmd:
            return top[0], False                   # Enter = take #1
        if low == 'quit':
            sys.exit("Aborted; nothing written.")
        if low == 'auto':
            return av[0], False
        if low == 'autoall':
            return av[0], True
        if cmd.isdigit():
            k = int(cmd)
            if 1 <= k <= len(top):
                return top[k - 1], False
            print("   ? out of range")
            continue
        hit = ([r for r in av if low in (r['name'].lower(), r['slug'])]
               or [r for r in av if low in r['name'].lower()])
        if len(hit) == 1:
            return hit[0], False
        if not hit:
            print("   ? not available (already drafted, retired, or that "
                  "division is full for this org)")
        else:
            print("   ? ambiguous:", ', '.join(r['name'] for r in hit[:6]))


def snake_draft(roster, ratings, site_date, auto):
    """NBA-style snake draft across the WHOLE pool. Each round every org picks
    once (order reverses each round); an org may take any available wrestler
    whose division it has not yet filled (champ + 10 per division). Returns
    (champ_of, picks) where picks are dicts {round, pick, org, row}."""
    champ_of, board = build_board(roster)
    counts = defaultdict(int)          # (org, division) -> drafted so far
    drafted, picks = set(), []
    total = len(ORGS) * len(WEIGHT_ORDER) * SLOTS_PER_ORG
    autoall, rnd, pickno = auto, 0, 0

    def needs(org):
        return any(counts[(org, d)] < SLOTS_PER_ORG for d in WEIGHT_ORDER)

    def avail_for(org):
        return [r for r in board if r['slug'] not in drafted
                and counts[(org, r['division'])] < SLOTS_PER_ORG]

    while pickno < total and any(needs(o) for o in ORGS):
        rnd += 1
        seq = DRAFT_ORDER if rnd % 2 else tuple(reversed(DRAFT_ORDER))
        for org in seq:
            if not needs(org):
                continue
            av = _menu_sort(avail_for(org), ratings, site_date)
            if not av:
                continue
            if autoall or not sys.stdin.isatty():
                pick = av[0]
            else:
                pick, autoall = _prompt_pick(org, rnd, pickno + 1, av, counts,
                                             ratings, site_date,
                                             len(board) - len(drafted))
            drafted.add(pick['slug'])
            counts[(org, pick['division'])] += 1
            pickno += 1
            picks.append({'round': rnd, 'pick': pickno, 'org': org, 'row': pick})
            if not autoall and sys.stdin.isatty():
                print(f"      → {ORG_NAMES[org]} select "
                      f"{pick['name']} ({pick['division'].capitalize()})")
    return champ_of, picks


def assign_seeds(picks, ratings):
    """Within each (org, division), rank the drafted 10 by Elo → seed 1..10
    (feeds the org rankings and the top-5-vs-bottom-5 contender booking)."""
    groups = defaultdict(list)
    for p in picks:
        groups[(p['org'], p['row']['division'])].append(p)
    for ps in groups.values():
        ps.sort(key=lambda p: -(_rating(p['row'], ratings)
                                if _rating(p['row'], ratings) is not None else -1e9))
        for i, p in enumerate(ps, 1):
            p['slot'] = i

# ─── Persistence ─────────────────────────────────────────────────────────────

def write_year_csv(year, champ_of, picks, ratings):
    """One row per champion (locked) and per drafted pick. Keeps both the draft
    ORDER (round/pick, for the board grid) and the Elo SEED (slot 1..10 per
    org+division, for the rankings and contender booking)."""
    os.makedirs(DRAFTS_DIR, exist_ok=True)
    path = os.path.join(DRAFTS_DIR, f"{year}.csv")

    def rating_str(row):
        r = _rating(row, ratings)
        return f"{r:.0f}" if r is not None else ''

    with open(path, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=YEAR_FIELDS)
        w.writeheader()
        # Champions first (locked, no round).
        seen = set()
        for (org, div), row in champ_of.items():
            key = (org, div, row['slug'])
            if key in seen:
                continue
            seen.add(key)
            w.writerow({'round': '', 'pick': '', 'org': org, 'slot': 'C',
                        'division': div, 'slug': row['slug'], 'name': row['name'],
                        'country': row.get('country', 'un'),
                        'rating': rating_str(row), 'is_champ': 'TRUE'})
        for p in picks:
            row = p['row']
            w.writerow({'round': p['round'], 'pick': p['pick'], 'org': p['org'],
                        'slot': p.get('slot', ''), 'division': row['division'],
                        'slug': row['slug'], 'name': row['name'],
                        'country': row.get('country', 'un'),
                        'rating': rating_str(row), 'is_champ': 'FALSE'})
    return path


def read_year_csvs():
    """year(int) -> list of row dicts, for every drafts/<year>.csv on disk."""
    out = {}
    if not os.path.isdir(DRAFTS_DIR):
        return out
    for fn in os.listdir(DRAFTS_DIR):
        if not fn.endswith('.csv'):
            continue
        try:
            year = int(fn[:-4])
        except ValueError:
            continue
        with open(os.path.join(DRAFTS_DIR, fn), encoding='utf-8') as f:
            out[year] = list(csv.DictReader(f))
    return out


# ─── draft.html rendering ────────────────────────────────────────────────────

def _wlink(name, slug, country):
    return (f'<span class="fi fi-{country or "un"}"></span> '
            f'<a href="/wrestling/wrestlers/{slug}.html">{name}</a>')


def render_year(year, rows):
    """The draft BOARD: rows = rounds, columns = orgs, each cell the pick with
    its division stacked under the name (NBA-style)."""
    picks = [r for r in rows if r.get('is_champ') != 'TRUE' and r.get('round')]
    # (round, org) -> pick row
    cell = {}
    rounds = set()
    for r in picks:
        try:
            rn = int(r['round'])
        except (ValueError, TypeError):
            continue
        rounds.add(rn)
        cell[(rn, r['org'])] = r
    open_attr = ' open' if year == max_year_on_disk() else ''
    html = [f'    <details class="draft-year"{open_attr}>',
            f'      <summary>{year} Draft &mdash; '
            f'{draft_date(year).strftime("%B %-d, %Y")}</summary>',
            '      <p class="sub">Snake draft across the whole pool — the pick '
            'order reverses every round. Reigning champions are pre-locked and '
            'not drafted. Each org fills champ + 10 per weight division.</p>',
            '      <div style="overflow-x:auto;">',
            '        <table class="draft-board">',
            '          <tr><th>Round</th>'
            + ''.join(f'<th>{ORG_NAMES[o]}</th>' for o in ORGS) + '</tr>']
    for rn in sorted(rounds):
        tds = [f'<th>{rn}</th>']
        for o in ORGS:
            r = cell.get((rn, o))
            if r:
                tds.append(f'<td>{_wlink(r["name"], r["slug"], r["country"])}'
                           f'<br><span class="sub">{r["division"].capitalize()}</span></td>')
            else:
                tds.append('<td></td>')
        html.append('          <tr>' + ''.join(tds) + '</tr>')
    html += ['        </table>', '      </div>', '    </details>']
    return '\n'.join(html)


def max_year_on_disk():
    ys = list(read_year_csvs().keys())
    return max(ys) if ys else None


START, END = '<!-- DRAFT_RECORDS_START -->', '<!-- DRAFT_RECORDS_END -->'


def render_draft_html():
    years = read_year_csvs()
    if not years:
        # No draft run — strip any stale records so the page reads clean.
        if os.path.exists(DRAFT_HTML):
            with open(DRAFT_HTML, encoding='utf-8') as f:
                html = f.read()
            new = _strip_block(html, START, END)
            if new != html:
                with open(DRAFT_HTML, 'w', encoding='utf-8') as f:
                    f.write(new)
                print("  No drafts on disk — cleared stale draft records from draft.html.")
        else:
            print("  No drafts/*.csv yet — nothing to render.")
        return
    body = '\n'.join(render_year(y, years[y]) for y in sorted(years, reverse=True))
    block = (f'{START}\n'
             '    <h2>Draft results</h2>\n'
             f'{body}\n'
             f'    {END}')
    with open(DRAFT_HTML, encoding='utf-8') as f:
        html = f.read()
    if START in html and END in html:
        pre = html[:html.index(START)]
        post = html[html.index(END) + len(END):]
        html = pre + block + post
    else:
        html = html.replace('</body>', f'\n{block}\n</body>', 1)
    with open(DRAFT_HTML, 'w', encoding='utf-8') as f:
        f.write(html)
    print(f"  ✓ Rendered {len(years)} draft year(s) into {DRAFT_HTML}")


# ─── Org-page rankings (per division, above the champions list) ──────────────

ORG_PAGES = {'wwf': os.path.join(SCRIPT_DIR, 'org', 'wwf.html'),
             'wwo': os.path.join(SCRIPT_DIR, 'org', 'wwo.html'),
             'iwb': os.path.join(SCRIPT_DIR, 'org', 'iwb.html')}
RANK_START, RANK_END = '<!-- RANKINGS_START -->', '<!-- RANKINGS_END -->'


def draft_date(year):
    """The draft is held on the SECOND SATURDAY of January of its year (same
    calendar logic the yearly awards use)."""
    from datetime import timedelta
    jan1 = datetime(year, 1, 1)
    first_sat = jan1 + timedelta(days=(5 - jan1.weekday()) % 7)   # Sat = 5
    return first_sat + timedelta(days=7)


def latest_draft_rows():
    years = read_year_csvs()
    if not years:
        return None, None
    y = max(years)
    return y, years[y]


def render_org_rankings(org, year, rows):
    """The six per-division ranking tables for one org (champ + 10), each in a
    <details>, newest draft. Champion sits atop in a yellow 'C' cell."""
    by = defaultdict(dict)     # division -> {slot: row}
    for r in rows:
        if r['org'] == org:
            by[r['division']][r['slot']] = r
    html = [RANK_START,
            f'    <h2>{ORG_NAMES[org]} divisional rankings</h2>',
            f'    <p class="sub">Contenders drafted for {year} '
            f'(draft held {draft_date(year).strftime("%B %-d, %Y")}). The '
            'champion (C) defends against the field over the year.</p>']
    for division in WEIGHT_ORDER:
        cells = by.get(division)
        if not cells:
            continue
        open_attr = ' open' if division in ('heavyweight', 'lightweight') else ''
        html.append(f'    <details class="draft-year"{open_attr}>')
        html.append(f'      <summary>{ORG_NAMES[org]} {division.capitalize()} rankings</summary>')
        html.append('      <div class="draft-row">')
        html.append('        <table class="draft-table">')
        champ = cells.get('C')
        cch = (_wlink(champ['name'], champ['slug'], champ['country'])
               if champ else '<span class="sub">vacant</span>')
        html.append(f'          <tr><td class="rank-champ">C</td><td>{cch}</td></tr>')
        for i in range(1, SLOTS_PER_ORG + 1):
            r = cells.get(str(i))
            inner = _wlink(r['name'], r['slug'], r['country']) if r else ''
            html.append(f'          <tr><td>{i}</td><td>{inner}</td></tr>')
        html.append('        </table>')
        html.append('      </div>')
        html.append('    </details>')
    html.append(f'    {RANK_END}')
    return '\n'.join(html)


def _strip_block(html, start, end):
    if start in html and end in html:
        return (html[:html.index(start)].rstrip('\n')
                + '\n' + html[html.index(end) + len(end):].lstrip('\n'))
    return html


def inject_org_rankings():
    year, rows = latest_draft_rows()
    if not rows:
        # No draft has been run — make sure no stale rankings linger.
        for org, path in ORG_PAGES.items():
            if not os.path.exists(path):
                continue
            with open(path, encoding='utf-8') as f:
                html = f.read()
            new = _strip_block(html, RANK_START, RANK_END)
            if new != html:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(new)
        print("  No draft on disk — cleared any existing rankings from org pages.")
        return
    for org, path in ORG_PAGES.items():
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as f:
            html = f.read()
        block = render_org_rankings(org, year, rows)
        if RANK_START in html and RANK_END in html:
            pre = html[:html.index(RANK_START)]
            post = html[html.index(RANK_END) + len(RANK_END):]
            html = pre + block + post
        else:
            # Insert just above "List of <ORG> world champions".
            import re as _re
            m = _re.search(r'<h2>List of[^<]*world champions</h2>', html)
            if m:
                html = html[:m.start()] + block + '\n\n    ' + html[m.start():]
            else:
                html = html.replace('</body>', f'\n{block}\n</body>', 1)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(html)
        print(f"  ✓ Rankings injected into {os.path.basename(path)}")


# ─── Book the SINGLES contender slots of the newest WTS from the draft ────────
#
# Battle-royal contender rows are left as 'xx vs xx' on purpose: a battle royal
# has ~8 entrants and only its final two are ever written, by hand in-game. But
# the SINGLES contender eliminators are booked automatically as top-5 vs bottom-5
# of that org's division (per the draft) so the card stays properly matched up.
# Runs during update.py, only once a draft for the season exists.

def book_singles_contenders(quiet=False):
    import re as _re
    year, rows = latest_draft_rows()
    if not rows:
        if not quiet:
            print("  No draft on disk — singles contenders left blank "
                  "(run a draft first).")
        return 0

    top5, bot5 = defaultdict(list), defaultdict(list)   # (org,div) -> [(country,name)]
    for r in rows:
        if r['slot'] == 'C':
            continue
        seed = int(r['slot'])
        bucket = top5 if seed <= 5 else bot5
        bucket[(r['org'], r['division'])].append((r['country'], r['name']))

    ppv = os.path.join(SCRIPT_DIR, 'ppv', 'list.html')
    with open(ppv, encoding='utf-8') as f:
        raw = f.read()
    nums = [int(n) for n in _re.findall(r"World Title Series\s+(\d+)", raw)]
    if not nums:
        return 0
    n = max(nums)
    m = _re.search(rf"World Title Series {n}:", raw)
    if not m:
        return 0
    start = raw.rfind('<details', 0, m.start())
    end = raw.index('</details>', m.start()) + len('</details>')
    block = raw[start:end]

    ptr = defaultdict(int)
    stats = [0]
    blank = _re.compile(r'<td><span class="fi fi-xx"></span>\s*</td>')

    def fix_row(row):
        cells = _re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, _re.DOTALL)
        if len(cells) < 9:
            return row
        mtype = _re.sub('<[^>]+>', '', cells[1]).strip().lower()
        if mtype != 'singles':                       # skip battle royals etc.
            return row
        note = _re.sub('<[^>]+>', '', cells[8]).strip().lower()
        if 'contender' not in note:
            return row
        org = next((o for o in ORGS if o in note), None)
        weight = _re.sub('<[^>]+>', '', cells[2]).strip().lower()
        if not org or weight not in WEIGHT_ORDER:
            return row
        tp, bt = top5.get((org, weight), []), bot5.get((org, weight), [])
        if not tp or not bt:
            return row
        k = ptr[(org, weight)]
        ptr[(org, weight)] += 1
        pair = [tp[k % len(tp)], bt[k % len(bt)]]    # a top-5 vs a bottom-5 seed
        i = [0]

        def repl(_match):
            if i[0] >= 2:
                return _match.group(0)
            country, name = pair[i[0]]
            i[0] += 1
            stats[0] += 1
            return f'<td><span class="fi fi-{country}"></span> {name} </td>'
        return blank.sub(repl, row)

    new_block = _re.sub(r'<tr>.*?</tr>', lambda mm: fix_row(mm.group(0)),
                        block, flags=_re.DOTALL)
    if stats[0]:
        raw = raw[:start] + new_block + raw[end:]
        with open(ppv, 'w', encoding='utf-8') as f:
            f.write(raw)
        if not quiet:
            print(f"  ✓ Booked {stats[0]} singles-contender name(s) into WTS {n} "
                  f"(battle royals left blank)")
    elif not quiet:
        print("  No blank singles-contender slots to fill in the newest WTS.")
    return stats[0]


# ─── 3-month jobber sweep for undrafted, inactive wrestlers ───────────────────

def jobber_sweep(months=3, apply=False):
    """List every wrestler who is NOT in the latest draft and has not competed
    in `months` months — the pool jobber.py should service. With apply=True and
    jobber.py present, prints the ready-to-run command per wrestler (kept manual
    so booking stays deliberate)."""
    roster = load_roster()
    ratings, _, site_date = load_ratings_and_site_date()
    year, rows = latest_draft_rows()
    drafted = {r['slug'] for r in (rows or [])}
    cutoff_days = months * 30
    due = []
    for r in roster:
        if r['slug'] in drafted or truthy(r.get('retired')):
            continue
        if inactivity_days(r, site_date) >= cutoff_days:
            due.append(r)
    due.sort(key=lambda r: -inactivity_days(r, site_date))
    print(f"\n{len(due)} undrafted wrestler(s) inactive ≥ {months} months "
          f"(jobber.py candidates):")
    for r in due:
        d = inactivity_days(r, site_date)
        dtxt = 'never' if d >= 10 ** 6 else f'{d}d'
        print(f"  {r['name']:<24} {r['division'] or '?':13} inactive {dtxt}")
    if apply:
        print("\nRun jobber.py for each (kept manual): "
              "python3 wrestling/jobber.py  # then enter the name")
    return due


# ─── Main ────────────────────────────────────────────────────────────────────

def run_draft(year, auto, loaded=None):
    roster = load_roster()
    ratings, ranks, site_date = loaded or load_ratings_and_site_date()
    board_n = len(build_board(roster)[1])
    print(f"Drafting {year}  (site date {site_date.date() if site_date else '?'}, "
          f"{board_n} draftable on the board, {len(ratings)} Elo-rated)")
    if not auto and sys.stdin.isatty():
        print("Snake draft: each round every org picks once, order reverses each "
              "round. Enter a number/name at each pick, or 'autoall' to finish.")

    champ_of, picks = snake_draft(roster, ratings, site_date, auto)
    assign_seeds(picks, ratings)

    # Per-org, per-division fill summary.
    from collections import Counter
    fills = Counter((p['org'], p['row']['division']) for p in picks)
    print(f"\n✓ {len(picks)} picks over {max((p['round'] for p in picks), default=0)} rounds")
    for o in ORGS:
        line = '  '.join(f"{d[:4].capitalize()} {fills[(o, d)]}/{SLOTS_PER_ORG}"
                         for d in WEIGHT_ORDER)
        print(f"  {ORG_NAMES[o]}: {line}")

    path = write_year_csv(year, champ_of, picks, ratings)
    print(f"\n✓ Wrote {path}")
    render_draft_html()
    inject_org_rankings()
    print("\nNow run `python3 wrestling/update.py` to book the singles contenders "
          "(top-5 vs bottom-5) into the newest WTS. Battle royals stay 'xx vs xx'.")


USAGE = """draft.py — annual wrestling draft
  python3 draft.py [--year N] [--auto]   run the draft (interactive unless --auto)
  python3 draft.py --render              rebuild org/draft.html from drafts/*.csv
  python3 draft.py --rankings            inject divisional rankings into org pages
  python3 draft.py --jobber-sweep [N]    list undrafted wrestlers idle N months (default 3)
"""


def main():
    args = sys.argv[1:]
    if '--help' in args or '-h' in args:
        print(USAGE)
        return
    if '--render' in args:
        render_draft_html()
        return
    if '--rankings' in args:
        inject_org_rankings()
        return
    if '--jobber-sweep' in args:
        i = args.index('--jobber-sweep')
        m = 3
        if i + 1 < len(args) and args[i + 1].isdigit():
            m = int(args[i + 1])
        jobber_sweep(months=m)
        return
    auto = '--auto' in args
    year = None
    if '--year' in args:
        year = int(args[args.index('--year') + 1])
    loaded = load_ratings_and_site_date()
    if year is None:
        sd = loaded[2]
        year = sd.year if sd else datetime.now().year
    run_draft(year, auto, loaded)


if __name__ == '__main__':
    main()
