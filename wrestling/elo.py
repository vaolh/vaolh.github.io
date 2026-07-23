#!/usr/bin/env python3
"""
elo.py — Continuous Elo rating system + monthly P4P archive
===========================================================
Replaces p4p.py. Called at the end of update.py's main(), or standalone:

    cd /path/to/your/site
    python3 wrestling/elo.py

Every singles match is replayed in chronological order through a combat-sports
Elo model (see RATING MODEL below). The standings at the end of each month are
archived as a pound-for-pound ranking.

Writes:
  - wrestling/p4p/index.html      (list of archived months)
  - wrestling/p4p/YYYY-MM.html    (one ranking page per month)
  - wrestling/org/ring.html       (between <!-- P4Prankings_START/END -->)
  - wrestling/org/pwhof.html      (between <!-- HOFMEMBERS_START/END -->)
  - wrestling/wrestlers/*.html    (Career Record + Highest Ranking infobox rows)


RATING MODEL
------------
Standard Elo, with one modification for combat sports: the expected score is
shifted by the size gap between the two wrestlers' divisions.

    handicap = SIZE_STEP * (division_index(A) - division_index(B))
    E_A      = 1 / (1 + 10 ** ((R_B - R_A + handicap) / 400))
    R_A     += K * (S_A - E_A)

Divisions are indexed heaviest-first, so a *lighter* wrestler has the higher
index and a positive handicap, which lowers their expected score. Because the
update is driven by (actual - expected), that single term produces both halves
of what we want, with no special-casing:

  - a welterweight who beats a heavyweight gains far more than a normal win
  - a welterweight who loses to a heavyweight drops far less than a normal loss
  - a heavyweight who loses to a welterweight is punished hard

K is scaled by how much the bout was worth (title matches, tournament bouts)
and how decisively it ended (a countout moves the needle less than a pinfall).
"""

import os
import re
import sys
from collections import defaultdict
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from update import WrestlingDatabase, resolve_site_date, format_site_date

# =============================================================================
# CONSTANTS
# =============================================================================

# Divisions heaviest -> lightest. Index doubles as the size ladder: the first
# four are the men's divisions, the last two the women's.
WEIGHT_ORDER = ('heavyweight', 'bridgerweight', 'middleweight',
                'welterweight', 'lightweight', 'featherweight')
WEIGHT_INDEX = {w: i for i, w in enumerate(WEIGHT_ORDER)}
WOMENS_WEIGHTS = ('lightweight', 'featherweight')

ALL_ORGS   = ('wwf', 'wwo', 'iwb', 'ring')
MAJOR_ORGS = ('wwf', 'wwo', 'iwb')

BASE_RATING = 1500.0
K_BASE      = 32.0

# Elo points of handicap per division of size difference. Three divisions of
# gap (welterweight vs. heavyweight) is 120 points ~ a 2:1 expectation swing.
SIZE_STEP = 40.0

# Stake multipliers on K.
K_TITLE      = 1.50   # championship match
K_OPENWEIGHT = 1.25   # Open Tournament / openweight bout

# Decisiveness multipliers on K.
METHOD_WEIGHT = {
    'pinfall':    1.00,
    'submission': 1.00,
    'decision':   0.75,
    'inconclusive': 0.50,   # DQ, countout, no contest
}

# A wrestler must have this many bouts before appearing in a ranking.
MIN_BOUTS = 3
TOP_N     = 10

# Hall of Fame criteria (ported from p4p.py, scored on peak Elo).
HOF_MAX_PER_YEAR     = 3
HOF_MIN_WINS         = 15
HOF_MIN_WIN_PCT      = 0.68
HOF_MIN_PEAK_ELO     = 1600.0
HOF_RETIREMENT_YEARS = 5
HOF_REQUIRE_MAJOR    = True

P4P_DIR = 'wrestling/p4p'


# =============================================================================
# HELPERS
# =============================================================================

def _parse_date(s):
    if not s:
        return None
    for fmt in ("%B %d, %Y", "%B %Y", "%b %d, %Y", "%b %Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except (ValueError, AttributeError):
            pass
    return None


def _month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def _month_label(key):
    y, m = key.split('-')
    return f"{datetime(int(y), int(m), 1):%B} {y}"


def flag(country):
    return f'<span class="fi fi-{country}"></span>'


def _page_name(name):
    return name.lower().replace(' ', '-').replace('.', '')


def _wlink(name):
    return f'<a href="/wrestling/wrestlers/{_page_name(name)}.html">{name}</a>'


def _method_class(method):
    m = (method or '').lower()
    if 'pinfall' in m:
        return 'pinfall'
    if 'submission' in m:
        return 'submission'
    if any(t in m for t in ('dq', 'disqualification', 'count out', 'countout',
                            'no contest')):
        return 'inconclusive'
    return 'decision'


def _is_title_match(db, match):
    is_title, _orgs = db.is_title_match(match.get('notes', ''))
    return is_title


# =============================================================================
# RATING ENGINE
# =============================================================================

def expected_score(rating_a, rating_b, idx_a, idx_b):
    """Expected score for A, shifted by the size gap between divisions.

    idx_* are division indices (0 = heaviest). None means the wrestler has no
    established division yet, in which case no handicap is applied.
    """
    if idx_a is None or idx_b is None:
        handicap = 0.0
    else:
        handicap = SIZE_STEP * (idx_a - idx_b)
    return 1.0 / (1.0 + 10.0 ** ((rating_b - rating_a + handicap) / 400.0))


def k_factor(db, match):
    k = K_BASE * METHOD_WEIGHT[_method_class(match.get('method'))]
    if _is_title_match(db, match):
        k *= K_TITLE
    elif (match.get('weight_class') or '').lower() == 'openweight':
        k *= K_OPENWEIGHT
    return k


def singles_matches(db):
    """Every singles match with a result, in chronological order."""
    out = []
    for event in db.events:
        for m in event['matches']:
            if not (m.get('winner') or m.get('is_draw')):
                continue
            d = _parse_date(m.get('date'))
            if not d:
                continue
            out.append((d, m))
    out.sort(key=lambda t: (t[0], t[1].get('match_num', 0)))
    return out


def classify_genders(db):
    """women = fought at least one bout in a women's division (same rule the
    old p4p.py used); everyone else is men."""
    women = set()
    for event in db.events:
        for m in event['matches']:
            if (m.get('weight_class') or '').lower() in WOMENS_WEIGHTS:
                women.add(m['fighter1'])
                women.add(m['fighter2'])
    men = set(db.wrestlers) - women
    return men, women


def build_snapshots(db):
    """Replay every match, snapshotting the standings at each month end.

    Returns (months, snapshots) where months is the ordered list of month keys
    and snapshots maps month key -> {'men': [...], 'women': [...]}; each entry
    is a full ranking list (not just the top 10) of dicts.
    """
    men, women = classify_genders(db)
    matches = singles_matches(db)
    if not matches:
        return [], {}

    ratings = defaultdict(lambda: BASE_RATING)
    bouts   = defaultdict(int)
    wins    = defaultdict(int)
    losses  = defaultdict(int)
    draws   = defaultdict(int)
    # Divisions fought so far, so a wrestler's division reflects the date of
    # the snapshot rather than where they ended up years later.
    div_counts = defaultdict(lambda: defaultdict(int))

    def division_index(name):
        counts = div_counts.get(name)
        if not counts:
            return None
        # Most-fought division; ties break heavier (lower index).
        return WEIGHT_INDEX[min(counts, key=lambda w: (-counts[w], WEIGHT_INDEX[w]))]

    def rank_list(names):
        rows = []
        for name in sorted(names):
            if bouts[name] < MIN_BOUTS or name not in db.ppv_wrestlers:
                continue
            rows.append({
                'name':    name,
                'rating':  ratings[name],
                'record':  f"{wins[name]}-{losses[name]}-{draws[name]}",
                'country': db.wrestlers[name].get('country', 'un'),
            })
        # Rating desc, then name for a stable order between equal ratings.
        rows.sort(key=lambda r: (-r['rating'], r['name']))
        for i, r in enumerate(rows, 1):
            r['rank'] = i
        return rows

    months    = []
    snapshots = {}
    idx_m     = 0
    while idx_m < len(matches):
        key = _month_key(matches[idx_m][0])
        last_date = matches[idx_m][0]

        while idx_m < len(matches) and _month_key(matches[idx_m][0]) == key:
            when, m = matches[idx_m]
            last_date = when
            a, b = m['fighter1'], m['fighter2']

            wc = (m.get('weight_class') or '').lower()
            if wc in WEIGHT_INDEX:
                div_counts[a][wc] += 1
                div_counts[b][wc] += 1

            idx_a, idx_b = division_index(a), division_index(b)
            ra, rb = ratings[a], ratings[b]
            ea = expected_score(ra, rb, idx_a, idx_b)
            k  = k_factor(db, m)

            if m.get('is_draw'):
                sa = 0.5
                draws[a] += 1
                draws[b] += 1
            elif m['winner'] == a:
                sa = 1.0
                wins[a] += 1
                losses[b] += 1
            else:
                sa = 0.0
                wins[b] += 1
                losses[a] += 1

            ratings[a] = ra + k * (sa - ea)
            ratings[b] = rb + k * ((1.0 - sa) - (1.0 - ea))
            bouts[a] += 1
            bouts[b] += 1
            idx_m += 1

        months.append(key)
        snapshots[key] = {
            'men':   rank_list(men),
            'women': rank_list(women),
        }

    # Early months where nobody has cleared MIN_BOUTS yet produce empty tables.
    # Ratings still accumulated through them (the loop above ran regardless) —
    # they just aren't worth publishing, and dropping them here means movement
    # is measured against the previous *published* ranking.
    months = [k for k in months if snapshots[k]['men'] or snapshots[k]['women']]
    return months, snapshots


def movement(snapshots, months, key, gender, name):
    """(kind, places) of a wrestler's move since the previous archived month."""
    i = months.index(key)
    if i == 0:
        return ('new', 0)
    prev = {r['name']: r['rank'] for r in snapshots[months[i - 1]][gender]}
    if name not in prev:
        return ('new', 0)
    cur = next(r['rank'] for r in snapshots[key][gender] if r['name'] == name)
    delta = prev[name] - cur
    if delta > 0:
        return ('up', delta)
    if delta < 0:
        return ('down', -delta)
    return ('same', 0)


# =============================================================================
# HTML GENERATION
# =============================================================================

def movement_html(kind, places):
    # The triangles are wrapped so they can be scaled down independently of the
    # figure beside them — at full size they set the row height.
    if kind == 'up':
        return (f'<span class="mv mv-up">'
                f'<span class="mv-arrow">&#9650;</span> {places}</span>')
    if kind == 'down':
        return (f'<span class="mv mv-down">'
                f'<span class="mv-arrow">&#9660;</span> {places}</span>')
    if kind == 'new':
        return '<span class="mv mv-new">NEW</span>'
    return '<span class="mv mv-same">&#8211;</span>'


def ranking_table(db, snapshots, months, key, gender, label, top_n=TOP_N):
    rows = snapshots[key][gender][:top_n]
    out = [
        f'    <table class="p4p-rank">',
        f'    <caption>{label}</caption>',
        '        <tr>',
        '            <th style="width: 10%;">Rank</th>',
        '            <th style="width: 40%;">Wrestler</th>',
        '            <th style="width: 16%;">Record</th>',
        '            <th style="width: 16%;">Rating</th>',
        '            <th style="width: 18%;">Movement</th>',
        '        </tr>',
    ]
    if not rows:
        out.append('        <tr><td colspan="5">No ranked wrestlers.</td></tr>')
    for r in rows:
        kind, places = movement(snapshots, months, key, gender, r['name'])
        out += [
            '        <tr>',
            f'            <th>{r["rank"]}</th>',
            f'            <td>{flag(r["country"])} {_wlink(r["name"])}</td>',
            f'            <td>{r["record"]}</td>',
            f'            <td>{r["rating"]:.0f}</td>',
            f'            <td>{movement_html(kind, places)}</td>',
            '        </tr>',
        ]
    out.append('    </table>')
    return '\n'.join(out)


PAGE_HEAD = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script>(function(){var f=['iwb','wwf','wwo'][Math.floor(Math.random()*3)],b='/assets/img/icons/'+f+'/';[['apple-touch-icon','180x180','apple-touch-icon.png'],['icon','32x32','favicon-32x32.png'],['icon','16x16','favicon-16x16.png']].forEach(function(i){var l=document.createElement('link');l.rel=i[0];l.sizes=i[1];l.href=b+i[2];document.head.appendChild(l);});var m=document.createElement('link');m.rel='manifest';m.href=b+'site.webmanifest';document.head.appendChild(m);})();</script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/lipis/flag-icons@7.3.2/css/flag-icons.min.css">
    <title>__TITLE__</title>
    <link rel="stylesheet" href="/assets/css/wiki.css">
<script>(function(){var t=localStorage.getItem('theme')||(window.matchMedia('(prefers-color-scheme: dark)').matches?'dark':'light');document.documentElement.setAttribute('data-theme',t)})()</script>
<script defer src="/assets/js/theme.js"></script>
</head>
<body>
<ul class="wiki-nav">
</ul>
"""

PAGE_FOOT = """
</body>
</html>
"""


def write_month_page(db, snapshots, months, key):
    label = _month_label(key)
    i = months.index(key)
    prev_link = (f'<a href="/wrestling/p4p/{months[i-1]}.html">&#8592; '
                 f'{_month_label(months[i-1])}</a>') if i > 0 else ''
    next_link = (f'<a href="/wrestling/p4p/{months[i+1]}.html">'
                 f'{_month_label(months[i+1])} &#8594;</a>') if i < len(months) - 1 else ''

    body = [
        f'<h1>{label} Pound-for-Pound Rankings</h1>',
        '',
        # Written out in full; update.py's date pass abbreviates the month.
        f'<p>The top 10 wrestlers were ranked on 1 {label} as follows:</p>',
        '',
        ranking_table(db, snapshots, months, key, 'men', "Men's Pound-for-Pound"),
        '',
        ranking_table(db, snapshots, months, key, 'women', "Women's Pound-for-Pound"),
        '',
        f'<p class="p4p-nav">{prev_link} {next_link}</p>',
        '',
        '<p><a href="/wrestling/p4p/index.html">All rankings</a> &middot; '
        '<a href="/wrestling/org/ring.html">The Ring</a></p>',
    ]

    html = (PAGE_HEAD.replace('__TITLE__', f'{label} P4P Rankings')
            + '\n'.join(body) + PAGE_FOOT)
    path = f'{P4P_DIR}/{key}.html'
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html)


def write_index_page(db, snapshots, months):
    rows = []
    for key in reversed(months):
        men   = snapshots[key]['men']
        women = snapshots[key]['women']
        top_m = f'{flag(men[0]["country"])} {_wlink(men[0]["name"])}' if men else '&mdash;'
        top_w = f'{flag(women[0]["country"])} {_wlink(women[0]["name"])}' if women else '&mdash;'
        rows += [
            '        <tr>',
            f'            <td><a href="/wrestling/p4p/{key}.html">{_month_label(key)}</a></td>',
            f'            <td>{top_m}</td>',
            f'            <td>{top_w}</td>',
            '        </tr>',
        ]

    body = [
        '<h1>Pound-for-Pound Rankings</h1>',
        '',
        '<p><i>The Ring</i> publishes a pound-for-pound ranking at the close of every '
        'month in which wrestling took place. Ratings are Elo-based and updated after '
        'every bout; a win over a wrestler from a heavier division counts for more '
        'than a win inside your own. '
        '<a href="/wrestling/org/ring.html">The Ring</a></p>',
        '',
        '    <table class="p4p-months">',
        '    <caption>Archived rankings</caption>',
        '        <tr>',
        '            <th style="width: 34%;">Month</th>',
        '            <th style="width: 33%;">Men\'s No. 1</th>',
        '            <th style="width: 33%;">Women\'s No. 1</th>',
        '        </tr>',
    ] + rows + ['    </table>']

    html = (PAGE_HEAD.replace('__TITLE__', 'P4P Rankings Archive')
            + '\n'.join(body) + PAGE_FOOT)
    with open(f'{P4P_DIR}/index.html', 'w', encoding='utf-8') as f:
        f.write(html)


def generate_ring_html(db, snapshots, months):
    """The P4P section embedded in ring.html — current standings + archive link."""
    if not months:
        return '    <p>No rankings published yet.</p>\n'
    key = months[-1]
    label = _month_label(key)
    parts = [
        f'    <p>Current as of {label}. '
        f'<a href="/wrestling/p4p/index.html">Full archive of monthly rankings</a>.</p>',
        '',
        ranking_table(db, snapshots, months, key, 'men', "Men's Pound-for-Pound"),
        '',
        ranking_table(db, snapshots, months, key, 'women', "Women's Pound-for-Pound"),
        '',
    ]
    return '\n'.join(parts) + '\n'


# =============================================================================
# PEAK RANKING (wrestler infoboxes)
# =============================================================================

def peak_rankings(snapshots, months):
    """name -> 'No. X (Month YYYY)' — the best rank ever held, dated to the
    month it was first attained. `months` is in order, so the first month to
    set a given best is the earliest; later months matching it don't override.
    """
    best = {}
    for key in months:
        for gender in ('men', 'women'):
            for r in snapshots[key][gender][:TOP_N]:
                cur = best.get(r['name'])
                if cur is None or r['rank'] < cur[0]:
                    best[r['name']] = (r['rank'], key)
    return {
        name: f"No. {rank} ({_month_label(key)})"
        for name, (rank, key) in best.items()
    }


# =============================================================================
# HALL OF FAME
# =============================================================================

def peak_elo(db):
    """name -> highest rating ever reached (needs its own replay)."""
    peaks = defaultdict(lambda: BASE_RATING)
    ratings = defaultdict(lambda: BASE_RATING)
    div_counts = defaultdict(lambda: defaultdict(int))

    def division_index(name):
        counts = div_counts.get(name)
        if not counts:
            return None
        return WEIGHT_INDEX[min(counts, key=lambda w: (-counts[w], WEIGHT_INDEX[w]))]

    for when, m in singles_matches(db):
        a, b = m['fighter1'], m['fighter2']
        wc = (m.get('weight_class') or '').lower()
        if wc in WEIGHT_INDEX:
            div_counts[a][wc] += 1
            div_counts[b][wc] += 1
        ra, rb = ratings[a], ratings[b]
        ea = expected_score(ra, rb, division_index(a), division_index(b))
        k = k_factor(db, m)
        sa = 0.5 if m.get('is_draw') else (1.0 if m['winner'] == a else 0.0)
        ratings[a] = ra + k * (sa - ea)
        ratings[b] = rb + k * ((1.0 - sa) - (1.0 - ea))
        peaks[a] = max(peaks[a], ratings[a])
        peaks[b] = max(peaks[b], ratings[b])
    return peaks


def last_match_year(db, name):
    years = [_parse_date(m.get('date')).year
             for m in db.wrestlers[name]['matches']
             if _parse_date(m.get('date'))]
    return max(years) if years else 0


def first_match_year(db, name):
    years = [_parse_date(m.get('date')).year
             for m in db.wrestlers[name]['matches']
             if _parse_date(m.get('date'))]
    return min(years) if years else 0


def all_titles_str(db, name):
    parts = []
    for org in ALL_ORGS:
        for weight in WEIGHT_ORDER:
            for reign in db.championships[org][weight]:
                if reign['champion'] != name:
                    continue
                label = '<i>The Ring</i>' if org == 'ring' else org.upper()
                txt = f"{label} {weight.capitalize()}"
                if txt not in parts:
                    parts.append(txt)
    return ' <br> '.join(parts)


def read_infobox_height(name):
    path = f'wrestling/wrestlers/{_page_name(name)}.html'
    if not os.path.exists(path):
        return ''
    content = open(path, encoding='utf-8').read()
    m = re.search(r'<th>Billed height</th>\s*<td>(.*?)</td>', content, re.DOTALL)
    return m.group(1).strip() if m else ''


def compute_hof_classes(db, peaks):
    years = sorted({_parse_date(e['date']).year for e in db.events
                    if _parse_date(e.get('date'))})
    if not years:
        return {}
    classes = {}
    inducted = set()
    for year in range(min(years) + HOF_RETIREMENT_YEARS + 1, max(years) + 1):
        eligible = []
        for name in sorted(db.wrestlers):
            if name in inducted or name not in db.ppv_wrestlers:
                continue
            w = db.wrestlers[name]
            total = w['wins'] + w['losses'] + w['draws']
            if total == 0:
                continue
            if last_match_year(db, name) > year - HOF_RETIREMENT_YEARS:
                continue
            if w['wins'] < HOF_MIN_WINS:
                continue
            if w['wins'] / total < HOF_MIN_WIN_PCT:
                continue
            if HOF_REQUIRE_MAJOR and not any(
                    reign['champion'] == name
                    for org in MAJOR_ORGS
                    for weight in WEIGHT_ORDER
                    for reign in db.championships[org][weight]):
                continue
            if peaks[name] < HOF_MIN_PEAK_ELO:
                continue
            eligible.append((name, peaks[name]))
        eligible.sort(key=lambda x: (-x[1], x[0]))
        if eligible[:HOF_MAX_PER_YEAR]:
            classes[year] = [n for n, _ in eligible[:HOF_MAX_PER_YEAR]]
            inducted.update(classes[year])
    return classes


def generate_hof_html(db, peaks, peak_rank):
    classes = compute_hof_classes(db, peaks)
    lines = [
        '    <!-- List of PWHOF Members -->',
        '    <table class="hof-history">',
        '    <tr>',
        '        <th>No.</th><th>Class</th><th>Ring name</th>'
        '<th>Record</th><th>Height</th><th>Titles</th>'
        '<th>Highest Ranking</th><th>Activity</th>',
        '    </tr>',
    ]
    row = 1
    for year in sorted(classes):
        for name in classes[year]:
            w = db.wrestlers.get(name)
            if not w:
                continue
            record  = f"{w['wins']}-{w['losses']}-{w['draws']}"
            titles  = all_titles_str(db, name)
            ranking = peak_rank.get(name, '')
            height  = read_infobox_height(name)
            debut   = first_match_year(db, name)
            retired = last_match_year(db, name)
            lines += [
                '    <tr>',
                f'        <th>{row}</th>',
                f'        <td>Class of {year}</td>',
                f'        <td>{flag(w["country"])} {name}</td>',
                f'        <td>{record}</td>',
                f'        <td>{height}</td>' if height else '        <th></th>',
                f'        <td>{titles}</td>' if titles else '        <th></th>',
                f'        <td>{ranking}</td>' if ranking else '        <th></th>',
                f'        <td>Debut: {debut} <br> Retired: {retired}</td>',
                '    </tr>',
            ]
            row += 1
    lines += ['    </table>', '']
    return '\n'.join(lines) + '\n'


# =============================================================================
# FILE WRITERS
# =============================================================================

def giant_killers(db, top_n=10):
    """Biggest single upset per wrestler, judged at match time: how big an
    underdog the winner was, in rating points, including the division-size
    handicap. Replays the same Elo model as build_snapshots so the ratings a
    win is measured against are the ones in effect that night."""
    ratings = defaultdict(lambda: BASE_RATING)
    div_counts = defaultdict(lambda: defaultdict(int))

    def division_index(name):
        counts = div_counts.get(name)
        if not counts:
            return None
        return WEIGHT_INDEX[min(counts, key=lambda w: (-counts[w], WEIGHT_INDEX[w]))]

    best = {}
    for _when, m in singles_matches(db):
        a, b = m['fighter1'], m['fighter2']
        wc = (m.get('weight_class') or '').lower()
        if wc in WEIGHT_INDEX:
            div_counts[a][wc] += 1
            div_counts[b][wc] += 1
        idx_a, idx_b = division_index(a), division_index(b)
        ra, rb = ratings[a], ratings[b]

        # Record the upset from the ratings BEFORE this match updates them.
        if not m.get('is_draw') and m.get('winner'):
            if m['winner'] == a:
                win, lose, rw, rl, iw, il = a, b, ra, rb, idx_a, idx_b
            else:
                win, lose, rw, rl, iw, il = b, a, rb, ra, idx_b, idx_a
            hcap = SIZE_STEP * (iw - il) if (iw is not None and il is not None) else 0.0
            deficit = (rl - rw) + hcap        # > 0 → winner was the underdog
            cur = best.get(win)
            if deficit > 0 and (cur is None or deficit > cur['value']):
                best[win] = {'value': deficit, 'opponent': lose}

        ea = expected_score(ra, rb, idx_a, idx_b)
        k = k_factor(db, m)
        sa = 0.5 if m.get('is_draw') else (1.0 if m['winner'] == a else 0.0)
        ratings[a] = ra + k * (sa - ea)
        ratings[b] = rb + k * ((1.0 - sa) - (1.0 - ea))

    ranked = sorted(best.items(), key=lambda kv: -kv[1]['value'])[:top_n]
    return [{'name': n, 'country': db.wrestlers.get(n, {}).get('country', 'un'),
             'value': d['value'], 'opponent': d['opponent']} for n, d in ranked]


def generate_giant_killer_html(db):
    """Giant Killer record table in the same P4P style update.py uses."""
    rows = giant_killers(db)
    out = ['    <table class="p4p-rank record-table">',
           '    <caption>Giant Killer &mdash; Biggest Upsets</caption>',
           '        <tr>',
           '            <th style="width: 10%;">No.</th>',
           '            <th style="width: 66%;">Wrestler</th>',
           '            <th style="width: 24%; text-align: right;">Rating gap</th>',
           '        </tr>']
    if not rows:
        out.append('        <tr><td colspan="3">&mdash;</td></tr>')
    for i, r in enumerate(rows, 1):
        out += ['        <tr>',
                f'            <th>{i}</th>',
                f'            <td>{flag(r["country"])} {_wlink(r["name"])} '
                f'<span class="sub">def. {_wlink(r["opponent"])}</span></td>',
                f'            <td style="text-align: right;">+{r["value"]:.0f}</td>',
                '        </tr>']
    out.append('    </table>')
    return '\n'.join(out) + '\n'


def _replace_between(path, start, end, html, what):
    if not os.path.exists(path):
        print(f"  ⚠ {path} not found")
        return
    content = open(path, encoding='utf-8').read()
    if start not in content or end not in content:
        print(f"  ⚠ Markers not found in {path}")
        return
    content = (content.split(start)[0] + start + '\n' + html
               + end + content.split(end)[1])
    open(path, 'w', encoding='utf-8').write(content)
    print(f"✓ Updated {what} in {path}")


# Rankings this script writes are month-form ("No. 1 (Dec 2019)"); the
# hand-authored ones on pre-database legends are year-form ("No. 1 (1965)").
_GENERATED_RANKING_RE = re.compile(
    r'<th>Highest Ranking</th>\s*<td>\s*No\.\s*\d+\s*\([A-Z][a-z]{2,8}\s+\d{4}')


def _is_generated_ranking(content):
    return bool(_GENERATED_RANKING_RE.search(content))


def current_rankings(snapshots, months):
    """name -> 'No. X' in the most recently published ranking."""
    if not months:
        return {}
    out = {}
    for gender in ('men', 'women'):
        for r in snapshots[months[-1]][gender][:TOP_N]:
            out[r['name']] = f"No. {r['rank']}"
    return out


def update_infoboxes(db, peak_rank, current_rank):
    wrestlers_dir = 'wrestling/wrestlers'
    if not os.path.exists(wrestlers_dir):
        print("  ⚠ wrestling/wrestlers/ not found, skipping infobox update")
        return

    updated = 0
    for name in sorted(db.ppv_wrestlers):
        w = db.wrestlers.get(name)
        if not w:
            continue
        filepath = f'{wrestlers_dir}/{_page_name(name)}.html'
        if not os.path.exists(filepath):
            continue
        content = open(filepath, encoding='utf-8').read()
        original = content
        # Only pages that carry an actual infobox are touched. Note that a bare
        # '<th>Record</th>' is not enough — every page's match table has a
        # "Record" column header — so require it to be an infobox row (a <th>
        # immediately followed by its <td>).
        if not re.search(r'<th>(?:Career )?Record</th>\s*<td>', content):
            continue

        record  = f"{w['wins']}-{w['losses']}-{w['draws']}"
        highest = peak_rank.get(name, '')
        current = current_rank.get(name, '')

        content = re.sub(r'<th>Record</th>(\s*<td>)[^<]*(</td>)',
                         r'<th>Career Record</th>\g<1>' + record + r'\g<2>', content)
        content = re.sub(r'(<th>Career Record</th>\s*<td>)[^<]*(</td>)',
                         r'\g<1>' + record + r'\g<2>', content)
        content = content.replace('<th>Highest P4P Ranking</th>',
                                  '<th>Highest Ranking</th>')

        ranking_row = (
            '\n                <tr>\n'
            '                    <th>Highest Ranking</th>\n'
            f'                    <td>{highest}</td>\n'
            '                </tr>'
        )
        if '<th>Highest Ranking</th>' in content:
            if highest:
                content = re.sub(r'(<th>Highest Ranking</th>\s*<td>)[^<]*(</td>)',
                                 r'\g<1>' + highest + r'\g<2>', content)
            elif _is_generated_ranking(content):
                # Only clear rows this script wrote. Several pre-database
                # legends (El Santo, Lou Thesz, ...) carry hand-authored
                # year-form rankings from before the match data begins; if one
                # of them ever picks up a match they must not be wiped.
                content = re.sub(r'\s*<tr>\s*<th>Highest Ranking</th>.*?</tr>',
                                 '', content, flags=re.DOTALL)
        elif highest:
            content = re.sub(r'(<th>Career Record</th>\s*<td>[^<]*</td>\s*</tr>)',
                             r'\g<1>' + ranking_row, content)

        # Current ranking sits directly above Highest Ranking. '<th>Ranking</th>'
        # can't collide with '<th>Highest Ranking</th>' — the latter never
        # contains the former as a substring.
        current_row = (
            '\n                <tr>\n'
            '                    <th>Ranking</th>\n'
            f'                    <td>{current}</td>\n'
            '                </tr>'
        )
        if '<th>Ranking</th>' in content:
            if current:
                content = re.sub(r'(<th>Ranking</th>\s*<td>)[^<]*(</td>)',
                                 r'\g<1>' + current + r'\g<2>', content)
            else:
                content = re.sub(r'\s*<tr>\s*<th>Ranking</th>.*?</tr>',
                                 '', content, flags=re.DOTALL)
        elif current:
            if '<th>Highest Ranking</th>' in content:
                content = re.sub(r'(\s*<tr>\s*<th>Highest Ranking</th>)',
                                 current_row + r'\g<1>', content, count=1)
            else:
                content = re.sub(
                    r'(<th>Career Record</th>\s*<td>[^<]*</td>\s*</tr>)',
                    r'\g<1>' + current_row, content)

        if content != original:
            open(filepath, 'w', encoding='utf-8').write(content)
            updated += 1
    print(f"✓ Infoboxes updated: {updated} file(s) changed")


# =============================================================================
# ENTRY POINT
# =============================================================================

def run(db):
    """Compute ratings and regenerate every page that depends on them."""
    print("Computing Elo ratings...")
    months, snapshots = build_snapshots(db)
    if not months:
        print("  ⚠ No rated matches found; skipping P4P generation")
        return
    print(f"  {len(months)} month(s) archived: {months[0]} -> {months[-1]}")

    os.makedirs(P4P_DIR, exist_ok=True)
    for key in months:
        write_month_page(db, snapshots, months, key)
    write_index_page(db, snapshots, months)

    # Drop month pages that are no longer published (a match date was corrected,
    # or a month fell below the ranking threshold on a re-run).
    keep = {f'{k}.html' for k in months} | {'index.html'}
    for stale in sorted(set(os.listdir(P4P_DIR)) - keep):
        if re.fullmatch(r'\d{4}-\d{2}\.html', stale):
            os.remove(os.path.join(P4P_DIR, stale))
            print(f"  removed stale {stale}")
    print(f"✓ Wrote {len(months)} month page(s) + index in {P4P_DIR}/")

    _replace_between('wrestling/org/ring.html',
                     '<!-- P4Prankings_START -->', '<!-- P4Prankings_END -->',
                     generate_ring_html(db, snapshots, months), 'P4P rankings')

    peak_rank = peak_rankings(snapshots, months)
    peaks = peak_elo(db)
    _replace_between('wrestling/org/pwhof.html',
                     '<!-- HOFMEMBERS_START -->', '<!-- HOFMEMBERS_END -->',
                     generate_hof_html(db, peaks, peak_rank), 'Hall of Fame')

    _replace_between('wrestling/records.html',
                     '<!-- GIANTKILLER_START -->', '<!-- GIANTKILLER_END -->',
                     generate_giant_killer_html(db), 'Giant Killer records')

    update_infoboxes(db, peak_rank, current_rankings(snapshots, months))


def main():
    os.chdir(os.path.dirname(SCRIPT_DIR))
    print(f"Working directory: {os.getcwd()}")
    ppv, weekly = 'wrestling/ppv/list.html', 'wrestling/weekly/list.html'
    db = WrestlingDatabase()
    # Same site date update.py uses, so running this alone can't produce
    # rankings from a different timeline than the rest of the site.
    site_date, why = resolve_site_date(ppv, weekly)
    db.cutoff = site_date
    print(f"Site date: {format_site_date(site_date) or '(none)'} — {why}")
    db.parse_events(ppv, is_weekly=False)
    if os.path.exists(weekly):
        db.parse_events(weekly, is_weekly=True)
    db.events.sort(key=lambda e: _parse_date(e.get('date')) or datetime.min)
    db.reprocess_championships_chronologically()
    db.recalculate_bio_notes()
    db.process_vacancies()
    db.calculate_championship_days()
    print(f"  Loaded {len(db.wrestlers)} wrestlers, {len(db.events)} events")
    run(db)
    print("\n✓ Elo ratings and P4P pages updated!")


if __name__ == '__main__':
    main()
