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
  python3 draft.py --callups       # fill divisions that lost their champion

Mid-season, a belt changing hands leaves that division a contender short: the
new champion steps out of the field, and the champion he dethroned is OFF the
division (he was never drafted into the contender pool — champions are locked,
not drafted). update.py forces you to fill each empty slot: re-sign the deposed
champion, or call up someone the draft passed over. Call-ups are not draft
picks — they live in their own file and never appear on the draft board.

Writes:
  wrestling/drafts/<year>.csv           one row per (division, org, slot)
  wrestling/drafts/<year>-callups.csv   mid-season call-ups (off the board)
  wrestling/org/draft.html              between <!-- DRAFT_RECORDS_START/END -->
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
    """Return (ratings, ranks, site_date). ratings maps wrestler NAME -> current
    Elo for EVERYONE who has wrestled a singles match (not just the >= MIN_BOUTS
    wrestlers the P4P ranking publishes), so the draft board isn't mostly blank.
    ranks are the published P4P global ranks (rated wrestlers only)."""
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
    db.process_vacancies()      # reprocess wipes and rebuilds the reigns, so the
                                # vacancies have to be re-applied on top of it
    ratings, _bouts = elo.current_ratings(db)          # everyone who wrestled
    ranks = {}
    months, snaps = elo.build_snapshots(db)
    if months:
        last = snaps[months[-1]]
        for gender in ('men', 'women'):
            for r in last[gender]:
                ranks[r['name']] = r['rank']
    sd = elo._parse_date(format_site_date(site_date)) if site_date else None
    return ratings, ranks, sd


_RANK_CTX = None


def load_ranking_context(force=False):
    """For the org divisional rankings: current Elo (everyone), the archived
    month keys, per-month name->rating (for Movement), name->record from the
    latest month (for the Record column) — so the tables mirror the P4P tables —
    plus the LIVE champion of every division and every champion DEPOSED since
    the season's draft.

    Memoised: update.py resolves short divisions, books contenders and renders
    the rankings in one process, and all three need the same live picture. Pass
    force=True to re-read after the source HTML has changed."""
    global _RANK_CTX
    if _RANK_CTX is not None and not force:
        return _RANK_CTX
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
    db.process_vacancies()      # reprocess wipes and rebuilds the reigns; without
                                # this a vacated belt still reads as held, so the
                                # division shows a champion who has given it up
    ratings, _bouts = elo.current_ratings(db)
    months, snaps = elo.build_snapshots(db)
    rating_by_month = {}
    for key in months:
        rm = {}
        for g in ('men', 'women'):
            for r in snaps[key][g]:
                rm[r['name']] = r['rating']
        rating_by_month[key] = rm
    # Full W-L-D for everyone who has wrestled a singles match (not just the
    # >= MIN_BOUTS names the P4P snapshot publishes), so the Record column fills.
    wins, losses, draws = defaultdict(int), defaultdict(int), defaultdict(int)
    for _when, m in elo.singles_matches(db):
        a, b = m['fighter1'], m['fighter2']
        if m.get('is_draw'):
            draws[a] += 1
            draws[b] += 1
        elif m['winner'] == a:
            wins[a] += 1
            losses[b] += 1
        else:
            wins[b] += 1
            losses[a] += 1
    record_by_name = {n: f"{wins[n]}-{losses[n]}-{draws[n]}"
                      for n in set(wins) | set(losses) | set(draws)}
    # LIVE champions straight from the reprocessed DB — the rankings refresh on
    # every update, so the champ pinned atop each division must come from the
    # current reigns, NOT from rosters.csv (whose champion_* fields are only
    # rebuilt yearly at draft time and go stale the moment a title changes).
    live_champ_of = {}          # (org, division) -> {'name','slug','country'}
    all_champ_names = set()     # every current belt holder, any org/weight
    for org in db.championships:
        for weight in WEIGHT_ORDER:
            cur = db._current_champion(org, weight)
            if not cur:
                continue
            all_champ_names.add(cur[0])
            if org in ORG_PAGES:
                live_champ_of[(org, weight)] = {
                    'name': cur[0], 'slug': slugify(cur[0]), 'country': cur[1]}
    year, _rows = latest_draft_rows()
    deposed = _deposed_champions(db, draft_date(year) if year else None,
                                 all_champ_names)
    _RANK_CTX = (ratings, months, rating_by_month, record_by_name,
                 live_champ_of, all_champ_names, deposed, _last_active(db))
    return _RANK_CTX


def _last_active(db):
    """name -> date of their most recent appearance, singles OR multi-man. Live
    from the parsed cards, not rosters.csv's last_active (which is only rebuilt
    when roster.py runs and goes stale between drafts). Drives the "spread the
    opportunities" pick: the longest-idle wrestler in a bucket gets the shot."""
    seen = {}

    def mark(name, when):
        if name and when and (name not in seen or when > seen[name]):
            seen[name] = when

    for event in db.events:
        when = elo._parse_date(event.get('date'))
        for m in event.get('matches', []):
            mark(m.get('fighter1'), when)
            mark(m.get('fighter2'), when)
        for mm in event.get('multi_man_matches', []):
            for side in ('winners', 'losers', 'participants'):
                for f in mm.get(side) or []:
                    mark(f.get('name'), when)
    return seen


def _deposed_champions(db, season_start, all_champ_names):
    """(org, division) -> [{name, country, lost_on, lost_to}] for every champion
    who LOST that belt since the season's draft and holds no belt anywhere now.

    A dethroned champion is off the division, full stop. They were never drafted
    into the contender pool (champions are locked, not drafted), so silently
    sliding them back in at the top of the rankings invents a contender the
    draft never allocated. resolve_short_divisions() makes the call instead.
    Only reigns that ended THIS season count — anyone who lost a belt in an
    earlier year and was drafted since is an ordinary contender."""
    out = defaultdict(list)
    for org in db.championships:
        if org not in ORG_PAGES:
            continue
        for weight in WEIGHT_ORDER:
            reigns = db.championships[org].get(weight) or []
            for i, reign in enumerate(reigns):
                nxt = reigns[i + 1] if i + 1 < len(reigns) else None
                if reign.get('vacancy_date'):
                    lost_on, lost_to = reign['vacancy_date'], None
                elif nxt:
                    lost_on, lost_to = nxt.get('date'), nxt.get('champion')
                else:
                    continue                       # still the reigning champion
                when = elo._parse_date(lost_on)
                if season_start and when and when < season_start:
                    continue
                if reign['champion'] in all_champ_names:
                    continue                       # still holds a belt elsewhere
                out[(org, weight)].append({'name': reign['champion'],
                                           'country': reign.get('country', 'un'),
                                           'lost_on': lost_on, 'lost_to': lost_to})
    return out


# ─── Mid-season call-ups (the forced mini-draft) ─────────────────────────────
#
# When a belt changes hands the division is a contender short: the new champion
# steps out of the field, and the deposed champion is OFF the division. The gap
# is filled by a call-up — re-sign the deposed champion, or promote someone the
# draft passed over. Call-ups are NOT draft picks: they live in their own file
# and never appear on the draft board.

CALLUP_FIELDS = ['org', 'division', 'slug', 'name', 'country', 'replaces', 'date']


def callups_path(year):
    return os.path.join(DRAFTS_DIR, f"{year}-callups.csv")


def load_callups(year):
    if not year:
        return []
    path = callups_path(year)
    if not os.path.exists(path):
        return []
    with open(path, encoding='utf-8') as f:
        return [r for r in csv.DictReader(f) if (r.get('name') or '').strip()]


def append_callup(year, row):
    os.makedirs(DRAFTS_DIR, exist_ok=True)
    path = callups_path(year)
    fresh = not os.path.exists(path)
    with open(path, 'a', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=CALLUP_FIELDS)
        if fresh:
            w.writeheader()
        w.writerow(row)


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


def _fmt_line(i, r, ratings, site_date):
    el = _rating(r, ratings)
    el = f"{el:4.0f}" if el is not None else "  — "
    days = inactivity_days(r, site_date)
    dd = 'never' if days >= 10 ** 6 else f"{days}d"
    return (f"     {i:3}. {r['name']:<22} {r['division'].capitalize():13} "
            f"Elo {el}  idle {dd}")


def _show(av, ratings, site_date, lo, hi):
    for i in range(lo, min(hi, len(av))):
        print(_fmt_line(i + 1, av[i], ratings, site_date))
    if hi < len(av):
        print(f"     … {len(av) - hi} more — 'more' to scroll, 'all' for the whole "
              f"board, 'div <weight>' to filter")


def _prompt_pick(org, rnd, pickno, av, counts, ratings, site_date, board_left):
    print(f"\n── Round {rnd}, pick {pickno} — {ORG_NAMES[org]} on the clock "
          f"({board_left} on the board, {len(av)} eligible) ──")
    fills = '  '.join(f"{d[:4].capitalize()} {counts[(org, d)]}/{SLOTS_PER_ORG}"
                      for d in WEIGHT_ORDER)
    print(f"   {ORG_NAMES[org]}: {fills}")
    shown = [10]                                   # how many rows currently listed
    _show(av, ratings, site_date, 0, shown[0])
    print("   enter # (from the FULL list), or a name; 'more'/'all' to scroll, "
          "'div <weight>' to filter, 'auto'/'autoall'/'quit'")
    while True:
        try:
            cmd = input("   > ").strip()
        except EOFError:
            return av[0], True
        low = cmd.lower()
        if not cmd:
            return av[0], False                    # Enter = take #1 (best)
        if low == 'quit':
            sys.exit("Aborted; nothing written.")
        if low == 'auto':
            return av[0], False
        if low == 'autoall':
            return av[0], True
        if low in ('more', 'm'):
            _show(av, ratings, site_date, shown[0], shown[0] + 20)
            shown[0] = min(shown[0] + 20, len(av))
            continue
        if low == 'all':
            _show(av, ratings, site_date, shown[0], len(av))
            shown[0] = len(av)
            continue
        if low.startswith('div '):
            w = low[4:].strip()
            sub = [r for r in av if r['division'].startswith(w)]
            if not sub:
                print(f"   ? no eligible wrestler in a division matching '{w}'")
                continue
            print(f"   — {len(sub)} eligible in {w} —")
            for r in sub:
                # index within the full list, so the shown number still picks it
                print(_fmt_line(av.index(r) + 1, r, ratings, site_date))
            continue
        if cmd.isdigit():
            k = int(cmd)
            if 1 <= k <= len(av):                  # pick by number from FULL list
                return av[k - 1], False
            print(f"   ? out of range (1–{len(av)})")
            continue
        hit = ([r for r in av if low in (r['name'].lower(), r['slug'])]
               or [r for r in av if low in r['name'].lower()])
        if len(hit) == 1:
            return hit[0], False
        if not hit:
            print("   ? not available (already drafted, retired, or that "
                  "division is full for this org)")
        else:
            print("   ? ambiguous:", ', '.join(r['name'] for r in hit[:8]))


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
    html = ['    <details class="draft-year">',
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


def _mv_html(kind, places):
    if kind == 'up':
        return f'<span class="mv mv-up"><span class="mv-arrow">&#9650;</span> {places}</span>'
    if kind == 'down':
        return f'<span class="mv mv-down"><span class="mv-arrow">&#9660;</span> {places}</span>'
    if kind == 'new':
        return '<span class="mv mv-new">NEW</span>'
    return '<span class="mv mv-same">&#8211;</span>'


def _field_movement(field, months, rating_by_month):
    """name -> (kind, places): movement WITHIN this division field only, versus
    the previous archived month. `field` is already in current (display) order.
    The season's field is fixed, so members simply reshuffle — no 'NEW'."""
    if len(months) < 2:
        return {m['name']: ('same', 0) for m in field}
    prev = rating_by_month[months[-2]]
    cur_rank = {m['name']: i for i, m in enumerate(field, 1)}
    prev_order = sorted(field, key=lambda m: (-(prev.get(m['name'], -1e9)), m['name']))
    prev_rank = {m['name']: i for i, m in enumerate(prev_order, 1)}
    out = {}
    for m in field:
        delta = prev_rank[m['name']] - cur_rank[m['name']]
        out[m['name']] = (('up', delta) if delta > 0
                          else ('down', -delta) if delta < 0 else ('same', 0))
    return out


def division_field(org, division, rows, callups):
    """THE contender field for one org+division — the single source of truth the
    rankings render and the contender eliminators are booked from, so the card
    can never disagree with the published table.

    Always ten deep. It is that org's draft picks, plus any mid-season call-ups,
    minus:
      - anyone who currently holds a belt ANYWHERE (a champion is never a mere
        contender, and above all is never booked to earn a shot at himself), and
      - anyone who lost the belt this season and has not been called back up —
        BEATEN OR VACATED. Vacating is losing the title to nobody, so it costs
        them their place in the division exactly the same way.

    A vacancy therefore leaves the ten contenders untouched (the champion was
    never one of them) and simply empties the C row. Nothing needs refilling
    until somebody WINS the vacant belt and steps out of the ten."""
    (ratings, _months, _rbm, _rec,
     champ_of, all_champ_names, deposed, _la) = load_ranking_context()
    called = [c for c in callups
              if c.get('org') == org and c.get('division') == division]
    called_names = {c['name'] for c in called}
    gone = {d['name'] for d in deposed.get((org, division), [])} - called_names
    pool = [r for r in rows
            if r['org'] == org and r['division'] == division
            and r.get('slot') != 'C' and r.get('is_champ') != 'TRUE']
    pool += [{'name': c['name'], 'slug': c['slug'],
              'country': c.get('country') or 'un', 'org': org,
              'division': division, 'slot': 'R', 'is_champ': 'FALSE'}
             for c in called]
    seen, field = set(), []
    for m in pool:
        if m['name'] in all_champ_names or m['name'] in gone or m['name'] in seen:
            continue
        seen.add(m['name'])
        field.append(m)
    field.sort(key=lambda m: (-(ratings.get(m['name']) or -1e9), m['name']))
    return field[:SLOTS_PER_ORG]


def render_org_rankings(org, rows, champ_of, ratings, months, rating_by_month,
                        record_by_name, backfill, all_champ_names,
                        callups, deposed):
    """Per-division ranking tables for one org, styled exactly like the P4P
    tables (Rank | Wrestler | Record | Rating | Movement) with the champion
    pinned atop in a gold C cell; the field below is ranked by live Elo.

    Contenders exclude every current champion, and if that leaves fewer than 10
    the field is topped back up to exactly 10 from `backfill` (that year's best
    undrafted reserves), so a division always shows champion/vacant + 10."""
    members = defaultdict(list)          # division -> [member row, ...]
    for r in rows:
        if r['org'] == org:
            members[r['division']].append(r)
    who = {r['name']: (r['slug'], r['country']) for r in rows}

    def rec(name):
        return record_by_name.get(name, '&#8211;')

    def rat(name):
        v = ratings.get(name)
        return f'{v:.0f}' if v is not None else '&#8211;'

    html = [RANK_START, f'    <h2>{ORG_NAMES[org]} Rankings</h2>']
    for division in WEIGHT_ORDER:
        pool = members.get(division)
        if not pool:
            continue
        champ_row = champ_of.get((org, division))
        champ_name = champ_row['name'] if champ_row else None
        real = division_field(org, division, rows, callups)
        reserves = (backfill.get((org, division), [])
                    if len(real) < SLOTS_PER_ORG else [])
        reserve_names = {m['name'] for m in reserves}
        field = real + reserves          # already ≤ 10 total
        mv = _field_movement(real, months, rating_by_month)
        html.append('    <details class="draft-year">')
        html.append(f'      <summary>{ORG_NAMES[org]} {division.capitalize()} rankings</summary>')
        html.append('      <table class="p4p-rank">')
        html.append('        <tr>'
                    '<th style="width: 10%;">Rank</th>'
                    '<th style="width: 40%;">Wrestler</th>'
                    '<th style="width: 16%;">Record</th>'
                    '<th style="width: 16%;">Rating</th>'
                    '<th style="width: 18%;">Movement</th></tr>')
        if champ_name:
            slug, country = who.get(champ_name,
                                    (champ_row['slug'], champ_row['country']))
            html.append(f'        <tr><td class="rank-champ">C</td>'
                        f'<td>{_wlink(champ_name, slug, country)}</td>'
                        f'<td>{rec(champ_name)}</td><td>{rat(champ_name)}</td>'
                        f'<td>{_mv_html("same", 0)}</td></tr>')
        else:
            html.append('        <tr><td class="rank-champ">C</td>'
                        '<td><span class="sub">vacant</span></td>'
                        '<td>&#8211;</td><td>&#8211;</td>'
                        f'<td>{_mv_html("same", 0)}</td></tr>')
        for i, m in enumerate(field, 1):
            if m['name'] in reserve_names:
                kind, places = 'new', 0        # mid-season reserve call-up
            else:
                kind, places = mv[m['name']]
            html.append(f'        <tr><th>{i}</th>'
                        f'<td>{_wlink(m["name"], m["slug"], m["country"])}</td>'
                        f'<td>{rec(m["name"])}</td><td>{rat(m["name"])}</td>'
                        f'<td>{_mv_html(kind, places)}</td></tr>')
        html.append('      </table>')
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
    roster = load_roster()
    (ratings, months, rating_by_month, record_by_name,
     champ_of, all_champ_names, deposed, _idle) = load_ranking_context()
    callups = load_callups(year)

    # champ_of, all_champ_names and deposed all come from the LIVE reprocessed DB
    # (see load_ranking_context): a title change swaps the new champion atop the
    # division on the very next update, every belt holder is kept out of the
    # contender fields (a champ is never a mere contender, even in another org),
    # and the champion they took the belt from is off the division until
    # resolve_short_divisions() is told what to do with him.

    # Reserve pools: that year's UNDRAFTED wrestlers per division (not retired,
    # not a champion), best Elo first. A safety net only — resolve_short_divisions
    # normally fills every gap by hand before this runs, so nothing is left short.
    drafted_names = {r['name'] for r in rows} | {c['name'] for c in callups}
    reserve_pool = defaultdict(list)
    for row in roster:
        div = (row.get('division') or '').strip().lower()
        if (div not in WEIGHT_ORDER or truthy(row.get('retired'))
                or row['name'] in drafted_names or row['name'] in all_champ_names):
            continue
        reserve_pool[div].append(row)
    for div, lst in reserve_pool.items():
        lst.sort(key=lambda r: (-(ratings.get(r['name']) or -1e9), r['name']))

    # Allocate reserves per (org, division) so no reserve backfills two orgs.
    ptr = defaultdict(int)
    backfill = {}
    for org in ORG_PAGES:
        for div in WEIGHT_ORDER:
            need = SLOTS_PER_ORG - len(division_field(org, div, rows, callups))
            if need > 0:
                take = reserve_pool[div][ptr[div]:ptr[div] + need]
                ptr[div] += len(take)
                backfill[(org, div)] = take

    for org, path in ORG_PAGES.items():
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as f:
            html = f.read()
        block = render_org_rankings(org, rows, champ_of, ratings, months,
                                    rating_by_month, record_by_name,
                                    backfill, all_champ_names, callups, deposed)
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


# ─── The forced mini-draft: refill a division that lost its champion ─────────

def _callup_candidates(division, rows, callups, all_champ_names, ratings, roster):
    """Undrafted, unretired, beltless wrestlers in this division — the pool a
    call-up is picked from — best live Elo first."""
    taken = {r['name'] for r in rows} | {c['name'] for c in callups}
    out = [r for r in roster
           if (r.get('division') or '').strip().lower() == division
           and not truthy(r.get('retired'))
           and r['name'] not in taken
           and r['name'] not in all_champ_names]
    out.sort(key=lambda r: (-(ratings.get(r['name']) or -1e9), r['name']))
    return out


def resolve_short_divisions(quiet=False):
    """FORCED mini-draft — runs from update.py before anything is booked.

    Ten contenders per division, always. A belt changing hands costs one: the
    new champion steps out of the field, and the man he beat leaves the division
    entirely. That slot is yours to fill, every time — re-sign the departed
    champion as a contender, or call up someone the draft passed over.

    A VACANCY does not fire this. The champion was never one of the ten, so
    vacating just empties the C row and leaves the field intact — the vacant
    belt is then contested by Elo (see book_vacant_titles). Only when somebody
    WINS it does the field drop to nine and the prompt come round, which is the
    right moment to decide whether the man who walked away gets back in.

    The pick is a call-up, not a draft pick: it is written to
    drafts/<year>-callups.csv and never shows on the draft board. Returns the
    number of slots filled."""
    year, rows = latest_draft_rows()
    if not rows:
        return 0
    (ratings, _months, _rbm, _rec,
     champ_of, all_champ_names, deposed, _idle) = load_ranking_context()
    callups = load_callups(year)
    roster = load_roster()

    short = []
    for org in ORGS:
        for div in WEIGHT_ORDER:
            if not any(r['org'] == org and r['division'] == div for r in rows):
                continue
            # Ten contenders, always. A belt changing hands costs one (the
            # new champion steps out, the man he beat leaves the division). A
            # VACANCY costs none — the champion was never one of the ten — so
            # nothing fires until the vacant belt is won.
            need = SLOTS_PER_ORG - len(division_field(org, div, rows, callups))
            if need > 0:
                short.append((org, div, need))
    if not short:
        if not quiet:
            print("  Every division is at full strength — no call-ups needed.")
        return 0

    if not sys.stdin.isatty():
        print("\n  !! CALL-UPS PENDING — these divisions are a contender short:")
        for org, div, need in short:
            print(f"       {ORG_NAMES[org]} {div.capitalize()}: {need} slot(s)")
        print("     Run `python3 wrestling/draft.py --callups` from a terminal "
              "to fill them.\n")
        return 0

    filled = 0
    print("\n" + "=" * 66)
    print("  MID-SEASON CALL-UPS — a division lost its champion, refill it")
    print("=" * 66)
    for org, div, need in short:
        for _ in range(need):
            gap = deposed.get((org, div), [])
            called_names = {c['name'] for c in callups}
            free = [d for d in gap if d['name'] not in called_names]
            held = len(division_field(org, div, rows, callups))
            print(f"\n  {ORG_NAMES[org]} {div.capitalize()} — {held} contenders "
                  f"under contract, {SLOTS_PER_ORG - held} slot(s) open.")
            for d in free:
                how = (f"vacated the belt on {d['lost_on']}" if not d['lost_to']
                       else f"lost the belt to {d['lost_to']} on {d['lost_on']}")
                print(f"    Off the division: {d['name']} — {how}")
            pool = _callup_candidates(div, rows, callups, all_champ_names,
                                      ratings, roster)
            menu = ([{'name': d['name'], 'slug': slugify(d['name']),
                      'country': d['country'],
                      'tag': 'vacated' if not d['lost_to'] else 'deposed champion'}
                     for d in free]
                    + [{'name': r['name'], 'slug': r.get('slug') or slugify(r['name']),
                        'country': r.get('country') or 'un', 'tag': 'undrafted'}
                       for r in pool[:12]])
            if not menu:
                print("    (nobody available — leaving the slot open)")
                break
            print()
            for i, m in enumerate(menu, 1):
                el = ratings.get(m['name'])
                el = f"{el:4.0f}" if el is not None else "  — "
                print(f"    {i:2}. {m['name']:<28} {el}   ({m['tag']})")
            # Blank line or EOF walks away from the prompt: the slot stays open
            # and everything downstream (the card booking above all) still runs.
            pick = None
            while pick is None:
                try:
                    raw = input("    Call up # (or a name, "
                                "blank to leave open): ").strip()
                except EOFError:
                    raw = ''
                    print()
                if not raw:
                    print("      (left open — "
                          "`python3 wrestling/draft.py --callups` to fill it)")
                    break
                if raw.isdigit() and 1 <= int(raw) <= len(menu):
                    pick = menu[int(raw) - 1]
                else:
                    hits = [m for m in menu if raw.lower() in m['name'].lower()]
                    if len(hits) == 1:
                        pick = hits[0]
                    elif len(hits) > 1:
                        print("      Ambiguous: "
                              + ", ".join(h['name'] for h in hits))
                    else:
                        print("      No match — pick a number from the list.")
            if pick is None:
                break
            replaced = free[0]['name'] if free else ''
            row = {'org': org, 'division': div, 'slug': pick['slug'],
                   'name': pick['name'], 'country': pick['country'],
                   'replaces': replaced,
                   'date': datetime.now().strftime('%Y-%m-%d')}
            append_callup(year, row)
            callups.append(row)
            filled += 1
            print(f"    → {pick['name']} joins the {ORG_NAMES[org]} "
                  f"{div.capitalize()} rankings.")
    print(f"\n  ✓ {filled} call-up(s) recorded in "
          f"{os.path.basename(callups_path(year))} (not a draft pick — "
          f"they never appear on the draft board).\n")
    return filled


# ─── Book the SINGLES contender slots of the newest WTS from the draft ────────
#
# Battle-royal contender rows are left as 'xx vs xx' on purpose: a battle royal
# has ~8 entrants and only its final two are ever written, by hand in-game. But
# the SINGLES contender eliminators are booked automatically as top-5 vs bottom-5
# of that org's division so the card stays properly matched up. The field comes
# from division_field() — the LIVE rankings, not the frozen draft sheet — so a
# wrestler who has since won the belt can never be booked to earn a shot at his
# own title. Runs during update.py, only once a draft for the season exists.

def book_singles_contenders(quiet=False):
    import re as _re
    year, rows = latest_draft_rows()
    if not rows:
        if not quiet:
            print("  No draft on disk — singles contenders left blank "
                  "(run a draft first).")
        return 0

    (ratings, _months, _rbm, _rec,
     _champ_of, all_champ_names, deposed, last_active) = load_ranking_context()
    callups = load_callups(year)

    # Seeds come from the LIVE field, in the exact order the org page ranks it —
    # so #1-#5 vs #6-#10 always matches what the site publishes, and nobody
    # holding a belt is anywhere near a contender slot.
    top5, bot5 = defaultdict(list), defaultdict(list)   # (org,div) -> [(country,name)]
    ranked = {}                                        # (org,div) -> Elo order
    for org in ORGS:
        for div in WEIGHT_ORDER:
            field = division_field(org, div, rows, callups)
            half = SLOTS_PER_ORG // 2
            ranked[(org, div)] = [(m['country'], m['name']) for m in field]
            top5[(org, div)] = [(m['country'], m['name']) for m in field[:half]]
            bot5[(org, div)] = [(m['country'], m['name']) for m in field[half:]]

    def idlest(bucket, used):
        """Whoever in this bucket has gone longest without a match — the shot is
        an OPPORTUNITY, so it goes to the man who hasn't had one, not to the
        highest rating in the bucket every single card. Never-wrestled first;
        name breaks ties so the same card always books the same way."""
        cands = [m for m in bucket if m[1] not in used]
        if not cands:
            return None
        return min(cands, key=lambda m: (last_active.get(m[1]) or datetime.min,
                                         m[1]))

    ppv = os.path.join(SCRIPT_DIR, 'ppv', 'list.html')
    with open(ppv, encoding='utf-8') as f:
        raw = f.read()

    # The trailing run of not-yet-wrestled events, not just the newest WTS: a
    # WrestleMania or a LibreMania is two <details> blocks for the one night's
    # slot, and both need filling. Walking back stops at the first event that
    # has already happened, so history is never rewritten.
    spans = []
    pos = 0
    while True:
        s = raw.find('<details', pos)
        if s < 0:
            break
        e = raw.index('</details>', s) + len('</details>')
        spans.append((s, e))
        pos = e
    tail = []
    for s, e in reversed(spans):
        seg = raw[s:e]
        if 'match-card' not in seg:
            continue
        methods = [_re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', r, _re.DOTALL)
                   for r in _re.findall(r'<tr>.*?</tr>', seg, _re.DOTALL)]
        cells = [c for c in methods if len(c) >= 9]
        if cells and all(_re.sub('<[^>]+>', '', c[6]).strip() for c in cells):
            break                                    # already wrestled: stop
        tail.append((s, e))
    if not tail:
        return 0
    tail.reverse()
    start, end = tail[0][0], tail[-1][1]
    block = raw[start:end]
    nums = [int(x) for x in _re.findall(r"World Title Series\s+(\d+)", block)]
    n = max(nums) if nums else None

    stats = [0, 0]                                   # [names booked, champs evicted]
    BLANK_TD = '<td><span class="fi fi-xx"></span> </td>'
    ROW = r'<tr>.*?</tr>'
    blank = _re.compile(r'<td><span class="fi fi-xx"></span>\s*</td>')
    fighter_td = _re.compile(r'<td><span class="fi fi-[a-z]{2}"></span>.*?</td>',
                             _re.DOTALL)

    def bookable(row):
        """(org, weight, kind) if this row is an UNWRESTLED singles match we may
        book, else None. kind is 'contender' (an eliminator — top-5 vs bottom-5,
        picked on inactivity) or 'vacant' (a vacant belt — contested straight by
        Elo). History is never rewritten."""
        cells = _re.findall(r'<t[dh][^>]*>(.*?)</t[dh]>', row, _re.DOTALL)
        if len(cells) < 9:
            return None
        if _re.sub('<[^>]+>', '', cells[1]).strip().lower() != 'singles':
            return None                              # battle royals stay blank
        note = _re.sub('<[^>]+>', '', cells[8]).strip().lower()
        # A defence with nobody opposite is the flagship case: WrestleMania and
        # LibreMania put every belt of the host promotion on the line, far more
        # than the rotation crowns contenders for, so most of those champions
        # have no earned challenger. Those go to the best in the division on
        # rating — same treatment as a vacant belt.
        title = any(k in note for k in ('championship', 'title'))
        kind = ('vacant' if 'vacant' in note else
                'contender' if 'contender' in note else
                'challenger' if title else None)
        if not kind:
            return None
        org = next((o for o in ORGS if o in note), None)
        weight = _re.sub('<[^>]+>', '', cells[2]).strip().lower()
        if not org or weight not in WEIGHT_ORDER:
            return None
        if (_re.sub('<[^>]+>', '', cells[4]).strip().lower().startswith('def')
                or _re.sub('<[^>]+>', '', cells[6]).strip() != ''):
            return None                              # already wrestled
        return org, weight, kind

    def names_in(row):
        out = set()
        for c in fighter_td.findall(row):
            who = _re.sub('<[^>]+>', '', c).strip()
            if who:
                out.add(who)
        return out

    # Pass 1 — evict anyone standing in a contender slot who has since won a
    # belt. A champion cannot wrestle to become the challenger to his own title.
    def evict_row(mm):
        row = mm.group(0)
        meta = bookable(row)
        if not meta or meta[2] != 'contender':
            return row                               # a vacant belt has no champ

        def evict(cell):
            who = _re.sub('<[^>]+>', '', cell.group(0)).strip()
            if who and who in all_champ_names:
                stats[1] += 1
                return BLANK_TD
            return cell.group(0)
        return fighter_td.sub(evict, row)

    block = _re.sub(ROW, evict_row, block, flags=_re.DOTALL)

    # Nobody wrestles twice on one card, so everyone already booked anywhere on
    # it — title matches included — is off the table for the slots still open.
    used = set()
    for rm in _re.finditer(ROW, block, _re.DOTALL):
        used |= names_in(rm.group(0))

    # Pass 2 — fill the empty slots.
    def fill_row(mm):
        row = mm.group(0)
        meta = bookable(row)
        if not meta or not blank.search(row):
            return row
        key = (meta[0], meta[1])
        here = names_in(row)
        slots = len(blank.findall(row))
        queue = []

        if meta[2] in ('vacant', 'challenger'):
            # Nobody holds it, so nobody has earned a defence: the vacant belt
            # goes to the best in the division. If a contender was already
            # crowned for it he keeps his place and faces the next best who
            # isn't him — which, when he IS the top rating, means the runner-up.
            # A flagship defence with no contender crowned resolves the same
            # way: the champion faces the No. 1 rating in the division who is
            # not already booked on the card.
            for cand in ranked.get(key, []):
                if len(queue) >= slots:
                    break
                if cand[1] in used or cand[1] in here:
                    continue
                queue.append(cand)
        else:
            tp, bt = top5.get(key, []), bot5.get(key, [])
            if not tp or not bt:
                return row
            # A part-filled row still comes out top-5 vs bottom-5: take from the
            # half that isn't represented yet. Last resort, anyone in the division.
            order = [bt, tp] if here & {x[1] for x in tp} else [tp, bt]
            for bucket in order + [tp + bt]:
                if len(queue) >= slots:
                    break
                pick = idlest(bucket, used | here | {q[1] for q in queue})
                if pick:
                    queue.append(pick)
        if not queue:
            return row
        used.update(q[1] for q in queue)
        i = [0]

        def repl(_match):
            if i[0] >= len(queue):
                return _match.group(0)
            country, name = queue[i[0]]
            i[0] += 1
            stats[0] += 1
            return f'<td><span class="fi fi-{country}"></span> {name} </td>'
        return blank.sub(repl, row)

    new_block = _re.sub(ROW, fill_row, block, flags=_re.DOTALL)
    where = f"WTS {n}" if n else "the next event"
    if stats[1] and not quiet:
        print(f"  ! Removed {stats[1]} champion(s) from contender slots in "
              f"{where} — they hold the belt they were booked to challenge for.")
    if stats[0] or stats[1]:
        raw = raw[:start] + new_block + raw[end:]
        with open(ppv, 'w', encoding='utf-8') as f:
            f.write(raw)
        if stats[0] and not quiet:
            print(f"  ✓ Booked {stats[0]} singles name(s) into {where} "
                  f"(battle royals left blank)")
    elif not quiet:
        print(f"  No blank singles slots to fill in {where}.")
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
  python3 draft.py --callups             refill divisions that lost their champion
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
    if '--callups' in args:
        if resolve_short_divisions():
            book_singles_contenders()
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
