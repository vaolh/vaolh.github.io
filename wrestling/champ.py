#!/usr/bin/env python3
"""
Wrestling Championship Changer
================================
Injects mid-history title changes into wrestling/weekly/list.html ONLY.
The PPV list is sacred canon and is NEVER modified.

The tool:
  1. Reads ppv/list.html to understand the ground-truth championship history.
  2. Lets you define a chain of weekly title changes in a window between two
     PPV events (e.g. Thesz → Carpentier for 100 days → Race).
  3. Detects if the final holder would conflict with an upcoming PPV result
     and AUTO-INSERTS a corrective return match so the PPV champion still
     enters their event with the belt.
  4. Writes all blocks to weekly/list.html using exactly the same HTML
     structure and date-sorting logic as jobber.py.

Usage:
  source ~/wrestling-venv/bin/activate
  python3 wrestling/champ.py

Then run update.py to rebuild all stats.
"""

from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from collections import defaultdict
import random
import re
import os
import calendar

# ─── Location pools (identical to jobber.py) ────────────────────────────────
LOCATIONS = {
    'mx': {
        'country_code': 'mx',
        'cities': [
            ('Mexico City, Mexico',    'Arena Coliseo'),
            ('Mexico City, Mexico',    'Arena Mexico'),
            ('Guadalajara, Mexico',    'Arena Coliseo Guadalajara'),
            ('Monterrey, Mexico',      'Arena Monterrey'),
            ('Puebla, Mexico',         'Arena Puebla'),
            ('Acapulco, Mexico',       'Arena Acapulco'),
            ('Veracruz, Mexico',       'Arena Veracruz'),
            ('Toluca, Mexico',         'Arena Toluca'),
            ('Tijuana, Mexico',        'Auditorio de Tijuana'),
            ('Leon, Mexico',           'Arena Leon'),
        ],
        'show_name': 'Lucha Libre',
    },
    'jp': {
        'country_code': 'jp',
        'cities': [
            ('Tokyo, Japan',           'Kuramae Kokugikan'),
            ('Tokyo, Japan',           'Korakuen Hall'),
            ('Osaka, Japan',           'Osaka Prefectural Gymnasium'),
            ('Yokohama, Japan',        'Bunka Gymnasium'),
            ('Nagoya, Japan',          'Aichi Prefectural Gymnasium'),
            ('Sapporo, Japan',         'Nakajima Sports Center'),
            ('Fukuoka, Japan',         'Fukuoka Civic Center'),
            ('Shizuoka, Japan',        'Shizuoka Arena'),
            ('Sendai, Japan',          'Miyagi Prefectural Gymnasium'),
            ('Kobe, Japan',            'Kobe World Memorial Hall'),
        ],
        'show_name': 'Puroresu',
    },
    'us': {
        'country_code': 'us',
        'cities': [
            ('New York, United States',     'Madison Square Garden'),
            ('Chicago, United States',      'Chicago Arena'),
            ('Los Angeles, United States',  'Olympic Auditorium'),
            ('Philadelphia, United States', 'Philadelphia Arena'),
            ('Boston, United States',       'Boston Square Garden'),
            ('Dallas, United States',       'Sportatorium'),
            ('Houston, United States',      'Sam Houston Coliseum'),
            ('Pittsburgh, United States',   'Civic Arena'),
            ('San Antonio, United States',  'Municipal Auditorium'),
            ('Minneapolis, United States',  'Auditorium'),
            ('Buffalo, United States',      'Buffalo Memorial Auditorium'),
            ('Detroit, United States',      'Cobo Hall'),
            ('St. Louis, United States',    'Kiel Auditorium'),
        ],
        'show_name': 'Wrestling',
    },
}

WEIGHT_CLASSES = ['Heavyweight', 'Bridgerweight', 'Middleweight', 'Welterweight',
                  'Lightweight', 'Featherweight']

ORGS       = ['wwf', 'wwo', 'iwb', 'ring']
ORG_LABELS = {'wwf': 'WWF', 'wwo': 'WWO', 'iwb': 'IWB', 'ring': 'The Ring'}

METHODS_WIN = ['Pinfall', 'Submission', 'Pinfall', 'Pinfall', 'Submission',
               'Pinfall', 'Pinfall', 'Submission', 'Pinfall', 'Pinfall']
FALLS_WIN   = ['[1-0]', '[2-1]', '[1-0]', '[1-0]']


# ─── Date helpers ────────────────────────────────────────────────────────────

def parse_date(date_str):
    if not date_str:
        return None
    s = date_str.strip()
    for fmt in ("%B %d, %Y", "%B %Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    return None


def format_date(dt):
    """datetime → 'Month D, YYYY' with no leading zero."""
    # strftime gives leading zero on some platforms; strip manually
    s = dt.strftime("%B %d, %Y")
    parts = s.split()
    parts[1] = parts[1].lstrip('0')
    return ' '.join(parts)


def get_year_month(dt):
    return (dt.year, dt.month)


# ─── PPV history reader ───────────────────────────────────────────────────────

def parse_ppv_title_history(ppv_path, org, weight):
    """
    Walk ppv/list.html chronologically.
    Return list of dicts for every DECISIVE title change for org/weight.
    Each dict: champion, country, date (datetime), date_str, event.
    """
    if not os.path.exists(ppv_path):
        return []

    with open(ppv_path, 'r', encoding='utf-8') as f:
        content = f.read()

    soup = BeautifulSoup(content, 'html.parser')
    raw = []

    for detail in soup.find_all('details'):
        summary   = detail.find('summary')
        event_name = summary.get_text().strip() if summary else 'Unknown'
        table = detail.find('table', class_='match-card')
        if not table:
            continue
        tbody = table.find('tbody')
        if not tbody:
            continue
        rows = tbody.find_all('tr')
        if len(rows) < 2:
            continue

        # date is in the last row
        info_row = rows[-1]
        event_date_str = None
        for th in info_row.find_all('th'):
            t = th.get_text().strip()
            if parse_date(t):
                event_date_str = t
                break
        if not event_date_str:
            continue
        event_dt = parse_date(event_date_str)

        for row in rows[1:-1]:
            cols = row.find_all(['td', 'th'])
            if len(cols) < 8:
                continue
            if cols[1].get_text().strip().lower() != 'singles':
                continue

            notes  = cols[8].get_text().strip() if len(cols) > 8 else ''
            method = cols[6].get_text().strip()
            result = cols[4].get_text().strip().lower()

            if org.lower() not in notes.lower():
                continue
            if not any(kw in notes.lower() for kw in ('title', 'championship')):
                continue
            if (weight.lower() not in notes.lower()
                    and weight.lower() not in cols[2].get_text().strip().lower()):
                continue
            if result not in ('def.', 'defeated', 'def'):
                continue

            method_l = method.lower()
            can_change = ('pinfall' in method_l or 'submission' in method_l or
                          ('dq' not in method_l
                           and 'count out' not in method_l
                           and 'disqualification' not in method_l))
            if not can_change:
                continue

            winner_cell = cols[3]
            winner = re.sub(r'\s*\(c\)\s*', '', winner_cell.get_text()).strip()
            cc = 'un'
            flag = winner_cell.find('span', class_='fi')
            if flag:
                for c in flag.get('class', []):
                    if c.startswith('fi-'):
                        cc = c.replace('fi-', '')

            raw.append({
                'champion': winner,
                'country':  cc,
                'date':     event_dt,
                'date_str': event_date_str,
                'event':    event_name,
            })

    raw.sort(key=lambda x: x['date'])

    # Deduplicate — keep only actual changes
    history = []
    last = None
    for ev in raw:
        if ev['champion'] != last:
            history.append(ev)
            last = ev['champion']
    return history


# ─── Wrestler helpers ─────────────────────────────────────────────────────────

def get_all_wrestler_names(ppv_path, weekly_path=None):
    names = set()
    for fp in [ppv_path, weekly_path]:
        if not fp or not os.path.exists(fp):
            continue
        with open(fp, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')
        for detail in soup.find_all('details'):
            table = detail.find('table', class_='match-card')
            if not table:
                continue
            tbody = table.find('tbody')
            if not tbody:
                continue
            for row in tbody.find_all('tr'):
                cols = row.find_all(['td', 'th'])
                if len(cols) < 7:
                    continue
                if cols[1].get_text().strip().lower() != 'singles':
                    continue
                for ci in (3, 5):
                    names.add(re.sub(r'\s*\(c\)\s*', '', cols[ci].get_text()).strip())
    return sorted(names)


def get_wrestler_country(name, ppv_path, weekly_path=None):
    for fp in [ppv_path, weekly_path]:
        if not fp or not os.path.exists(fp):
            continue
        with open(fp, 'r', encoding='utf-8') as f:
            soup = BeautifulSoup(f.read(), 'html.parser')
        for detail in soup.find_all('details'):
            table = detail.find('table', class_='match-card')
            if not table:
                continue
            tbody = table.find('tbody')
            if not tbody:
                continue
            for row in tbody.find_all('tr'):
                cols = row.find_all(['td', 'th'])
                if len(cols) < 7:
                    continue
                for ci in (3, 5):
                    cell = cols[ci]
                    n = re.sub(r'\s*\(c\)\s*', '', cell.get_text()).strip()
                    if n == name:
                        flag = cell.find('span', class_='fi')
                        if flag:
                            for c in flag.get('class', []):
                                if c.startswith('fi-'):
                                    return c.replace('fi-', '')
    return 'un'


def pick_wrestler(prompt, all_names):
    """Interactive fuzzy picker. Returns chosen name string."""
    while True:
        query = input(f"  {prompt}: ").strip()
        if not query:
            continue
        matches = [n for n in all_names if query.lower() in n.lower()]
        if not matches:
            print("    No matches. Try again.")
            continue
        if len(matches) == 1:
            print(f"    → {matches[0]}")
            return matches[0]
        print(f"    Found {len(matches)}:")
        for i, m in enumerate(matches, 1):
            print(f"      {i}. {m}")
        choice = input("    Pick number (or refine): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(matches):
            name = matches[int(choice) - 1]
            print(f"    → {name}")
            return name


# ─── Weekly HTML helpers (verbatim from jobber.py logic) ─────────────────────

def find_block_for_month(content, year, month, show_name):
    """
    Find an existing <details> block for the same month + show_name with < 5 matches.
    Returns dict {insert_pos, match_count} or None.
    """
    for m in re.finditer(r'<details>(.*?)</details>', content, re.DOTALL):
        block_text          = m.group(1)
        block_content_start = m.start(1)

        summary_m = re.search(r'<summary>(.*?)</summary>', block_text)
        if not summary_m or summary_m.group(1).strip() != show_name:
            continue

        date_strs = re.findall(
            r'(?:January|February|March|April|May|June|July|August|September|'
            r'October|November|December)\s+\d{1,2},\s+\d{4}',
            block_text
        )
        if not date_strs:
            continue
        block_date = parse_date(date_strs[-1])
        if not block_date or block_date.year != year or block_date.month != month:
            continue

        singles_count = block_text.count('<td>Singles</td>')
        if singles_count >= 5:
            continue

        info_m = re.search(r'<tr>\s*<th>\s*</th>\s*<th\s+colspan="2">', block_text)
        if not info_m:
            continue

        return {
            'insert_pos': block_content_start + info_m.start(),
            'match_count': singles_count,
        }
    return None


def find_insertion_point_weekly(content, target_date):
    """
    Insertion point in weekly/list.html. Returns (position, needs_year_header).
    Identical logic to jobber.py's find_insertion_point.
    """
    target_year = target_date.year
    has_h2 = f'<h2>{target_year}</h2>' in content
    has_h3 = f'<h3>{target_year}</h3>' in content

    if has_h2 or has_h3:
        pattern = re.compile(
            re.escape(f'<h2>{target_year}</h2>' if has_h2 else f'<h3>{target_year}</h3>'),
            re.IGNORECASE
        )
        match = pattern.search(content)
        if not match:
            return len(content), True

        year_start = match.end()
        next_year  = re.compile(r'<h[23]>\d{4}</h[23]>', re.IGNORECASE)
        nx         = next_year.search(content, year_start)
        year_end   = nx.start() if nx else len(content)
        year_section = content[year_start:year_end]

        details_ends = []
        for m in re.finditer(r'</details>', year_section):
            pos        = m.end()
            block_prev = year_section[:pos]
            dms = list(re.finditer(
                r'(?:January|February|March|April|May|June|July|August|September|'
                r'October|November|December)\s+\d{1,2},\s+\d{4}',
                block_prev
            ))
            if dms:
                bd = parse_date(dms[-1].group())
                if bd:
                    details_ends.append((pos + year_start, bd))

        if details_ends:
            insert_after = None
            for pos, dt in details_ends:
                if dt <= target_date:
                    insert_after = pos
            if insert_after is not None:
                return insert_after, False
            return year_start, False
        return year_start, False

    else:
        year_headers = list(re.finditer(r'<h[23]>(\d{4})</h[23]>', content))
        if not year_headers:
            body_end = content.rfind('</body>')
            return (body_end if body_end != -1 else len(content)), True

        insert_pos = None
        for m in year_headers:
            if int(m.group(1)) > target_year:
                insert_pos = m.start()
                break
        if insert_pos is None:
            body_end = content.rfind('</body>')
            insert_pos = body_end if body_end != -1 else len(content)
        return insert_pos, True


def build_match_row(match_num, weight_class,
                    winner, winner_cc,
                    loser,  loser_cc,
                    method, falls, notes):
    """Single <tr> for a singles title match (winner is shown as (c) on left)."""
    return (
        f'    <tr>'
        f'<th>{match_num}</th>'
        f'<td>Singles</td>'
        f'<td>{weight_class}</td>'
        f'<td><span class="fi fi-{winner_cc}"></span> {winner} (c)</td>'
        f'<td>def.</td>'
        f'<td><span class="fi fi-{loser_cc}"></span> {loser} (c)</td>'
        f'<td>{method}</td>'
        f'<td>{falls}</td>'
        f'<td>{notes}</td>'
        f'</tr>\n'
    )


def build_details_block(match_rows, show_name, city, country_code, venue, date_str):
    """Full <details> block. Same structure as jobber.py."""
    parts         = date_str.split()
    month_label   = parts[0].upper()
    year_label    = parts[-1]
    country_map   = {'mx': 'MEXICO', 'jp': 'JAPAN', 'us': 'USA'}
    country_label = country_map.get(country_code, country_code.upper())

    html  = f'\n    <!-- {month_label} {year_label} | {country_label} -->\n'
    html += f'    <details>\n'
    html += f'    <summary>{show_name}</summary>\n'
    html += f'    <table class="match-card"><tbody>\n'
    html += (f'    <tr><th>No.</th><th>Match Type</th><th>Weight Class</th>'
             f'<th></th><th>vs.</th><th></th><th>Method</th><th>Falls</th><th>Notes</th></tr>\n')
    for row in match_rows:
        html += row
    html += (f'    <tr><th></th>'
             f'<th colspan="2"><span class="fi fi-{country_code}"></span> {city}</th>'
             f'<th colspan="2">{venue}</th>'
             f'<th></th><th></th><th></th>'
             f'<th>{date_str}</th></tr>\n')
    html += f'    </tbody></table>\n'
    html += f'    </details>\n'
    return html


def write_match_to_weekly(content, change, show_name, weight_class, notes_text, added_years):
    """
    Insert one title-change match into the weekly content string.
    Returns updated content string.
    """
    dt = change['date']
    nat       = change['nat']
    loc_data  = LOCATIONS[nat]
    city      = change['city']
    venue     = change['venue']
    cc        = loc_data['country_code']
    method    = random.choice(METHODS_WIN)
    falls     = random.choice(FALLS_WIN)

    block_info = find_block_for_month(content, dt.year, dt.month, show_name)

    if block_info:
        match_num = block_info['match_count'] + 1
        row = build_match_row(
            match_num, weight_class,
            change['winner'], change['winner_cc'],
            change['loser'],  change['loser_cc'],
            method, falls, notes_text
        )
        pos        = block_info['insert_pos']
        line_start = content.rfind('\n', 0, pos)
        if line_start == -1:
            line_start = 0
        content = content[:line_start] + '\n' + row.rstrip('\n') + content[line_start:]
    else:
        row = build_match_row(
            1, weight_class,
            change['winner'], change['winner_cc'],
            change['loser'],  change['loser_cc'],
            method, falls, notes_text
        )
        block_html = build_details_block(
            [row], show_name, city, cc, venue, format_date(dt)
        )
        pos, needs_year = find_insertion_point_weekly(content, dt)
        insert_text = ''
        if needs_year and dt.year not in added_years:
            hdr = 'h3' if dt.year < 1968 else 'h2'
            insert_text = f'\n    <{hdr}>{dt.year}</{hdr}>\n'
            added_years.add(dt.year)
        insert_text += block_html
        content = content[:pos] + insert_text + content[pos:]

    return content


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    ppv_path    = 'wrestling/ppv/list.html'
    weekly_path = 'wrestling/weekly/list.html'

    print("=" * 60)
    print("  WRESTLING CHAMPIONSHIP CHANGER")
    print("  (weekly/list.html only — PPV canon untouched)")
    print("=" * 60)

    # ── 1. Org ───────────────────────────────────────────────────────────────
    print("\n  Organizations:")
    for i, org in enumerate(ORGS, 1):
        print(f"    {i}. {ORG_LABELS[org]}")
    org_input = input("  Pick org: ").strip()
    if not org_input.isdigit() or not (1 <= int(org_input) <= len(ORGS)):
        print("  ERROR: invalid org.")
        return
    org = ORGS[int(org_input) - 1]
    print(f"  → {ORG_LABELS[org]}")

    # ── 2. Weight class ───────────────────────────────────────────────────────
    print("\n  Weight classes:")
    for i, w in enumerate(WEIGHT_CLASSES, 1):
        print(f"    {i}. {w}")
    wc_input = input("  Pick weight [2=Bridgerweight]: ").strip()
    weight_class = (WEIGHT_CLASSES[int(wc_input) - 1]
                    if wc_input.isdigit() and 1 <= int(wc_input) <= len(WEIGHT_CLASSES)
                    else 'Bridgerweight')
    print(f"  → {weight_class}")

    # ── 3. Load PPV history ───────────────────────────────────────────────────
    print(f"\n  Loading PPV title history for {ORG_LABELS[org]} {weight_class}...")
    ppv_history = parse_ppv_title_history(ppv_path, org, weight_class.lower())

    if ppv_history:
        print(f"  {len(ppv_history)} PPV title change(s) found:")
        for i, ev in enumerate(ppv_history):
            print(f"    {i+1}. {ev['champion']:<25}  {ev['date_str']}  ({ev['event']})")
    else:
        print("  No PPV title history found.")

    # ── 4. Window start ───────────────────────────────────────────────────────
    print()
    ws_input = input("  Start of window (e.g. January 28, 1967 or January 1967): ").strip()
    window_start = parse_date(ws_input)
    if not window_start:
        print("  ERROR: bad date.")
        return
    if ',' not in ws_input:
        window_start = window_start.replace(day=1)
    print(f"  → Window opens: {format_date(window_start)}")

    # ── 5. Who holds the belt at window start? ────────────────────────────────
    holder      = None
    holder_cc   = 'un'
    for ev in ppv_history:
        if ev['date'] <= window_start:
            holder    = ev['champion']
            holder_cc = ev['country']

    if holder:
        print(f"  Champion at window start: {holder}")
    else:
        print("  No PPV champion before that date.")
        all_names = get_all_wrestler_names(ppv_path, weekly_path)
        holder    = pick_wrestler("Enter champion manually", all_names)
        holder_cc = get_wrestler_country(holder, ppv_path, weekly_path)

    # ── 6. Upcoming PPV deadline ───────────────────────────────────────────────
    # Find the next PPV event AFTER window_start where the title moves off `holder`
    next_ppv = None
    for ev in ppv_history:
        if ev['date'] > window_start and ev['champion'] != holder:
            next_ppv = ev
            break

    if next_ppv:
        hard_deadline = next_ppv['date'] - timedelta(days=1)
        print(f"\n  ⚠️  Next PPV constraint:")
        print(f"      {next_ppv['champion']} wins at '{next_ppv['event']}' on {next_ppv['date_str']}")
        print(f"      All weekly changes must be before {format_date(hard_deadline)}")
        print(f"      and {holder} must hold the belt going into that event.")
    else:
        hard_deadline = None
        print("\n  No upcoming PPV deadline — window is open-ended.")

    # ── 7. Location preference (asked once, applies to all matches) ───────────
    print("\n  Location preference for all matches:")
    print("    1. Mexico  (Lucha Libre)")
    print("    2. Japan   (Puroresu)")
    print("    3. USA     (Wrestling)")
    print("    4. Mix (random per match)")
    loc_pref = input("  Pick [4=Mix]: ").strip()
    nat_pool = {'1': ['mx'], '2': ['jp'], '3': ['us']}.get(loc_pref, ['mx', 'jp', 'us'])

    # ── 8. Build chain of changes ─────────────────────────────────────────────
    all_names       = get_all_wrestler_names(ppv_path, weekly_path)
    changes         = []          # final list of changes to write
    current_holder    = holder
    current_holder_cc = holder_cc
    after_date        = window_start  # next change must be strictly after this

    print()
    print("  Define your weekly title change chain.")
    print("  You can do A→B→A, A→B→C→A, etc.")
    print("  Type 'done' (or just hit Enter) when finished.\n")

    while True:
        print(f"  Current holder: {current_holder}")
        inp = input("  Add another change? (y / done): ").strip().lower()
        if inp in ('done', 'd', 'n', ''):
            break
        if inp != 'y':
            continue

        # New champion
        new_champ    = pick_wrestler("New champion", all_names)
        new_champ_cc = get_wrestler_country(new_champ, ppv_path, weekly_path)

        # Date
        while True:
            d_inp = input(f"  Date of change (after {format_date(after_date)}): ").strip()
            dt = parse_date(d_inp)
            if not dt:
                print("  Bad date.")
                continue
            # month-only → random day
            if ',' not in d_inp:
                max_d = calendar.monthrange(dt.year, dt.month)[1]
                dt = dt.replace(day=random.randint(3, max_d - 3))
            if dt <= after_date:
                print(f"  Must be after {format_date(after_date)}.")
                continue
            if hard_deadline and dt >= next_ppv['date']:
                print(f"  Must be before PPV on {next_ppv['date_str']}.")
                continue
            break

        # Pick location for this change
        nat       = random.choice(nat_pool)
        loc_data  = LOCATIONS[nat]
        city, venue = random.choice(loc_data['cities'])

        changes.append({
            'winner':    new_champ,
            'winner_cc': new_champ_cc,
            'loser':     current_holder,
            'loser_cc':  current_holder_cc,
            'date':      dt,
            'nat':       nat,
            'city':      city,
            'venue':     venue,
            'auto':      False,
        })
        print(f"  ✓ {new_champ} def. {current_holder} on {format_date(dt)}")

        current_holder    = new_champ
        current_holder_cc = new_champ_cc
        after_date        = dt

    if not changes:
        print("\n  No changes entered. Exiting.")
        return

    # ── 9. Conflict check → auto-corrective return ────────────────────────────
    if next_ppv and current_holder != holder:
        print(f"\n  ⚠️  CONFLICT: {current_holder} would hold the belt going into")
        print(f"      '{next_ppv['event']}', but that PPV needs {holder} as champion.")
        print(f"      → Auto-inserting corrective return match.")

        auto_start = after_date + timedelta(days=1)
        auto_end   = next_ppv['date'] - timedelta(days=1)

        if auto_start > auto_end:
            print("  ERROR: No room for corrective match. Please adjust your dates.")
            return

        # Try to find a month not already used
        used_yms = {get_year_month(c['date']) for c in changes}
        gap_months = []
        cur = auto_start.replace(day=1)
        end_ym = (auto_end.year, auto_end.month)
        while (cur.year, cur.month) <= end_ym:
            ym = (cur.year, cur.month)
            if ym not in used_yms:
                gap_months.append(ym)
            cur = (cur.replace(year=cur.year + 1, month=1)
                   if cur.month == 12 else cur.replace(month=cur.month + 1))

        if gap_months:
            ym        = random.choice(gap_months)
            year, mth = ym
            max_d = calendar.monthrange(year, mth)[1]
            lo    = auto_start.day if (year, mth) == get_year_month(auto_start) else 1
            hi    = auto_end.day   if (year, mth) == get_year_month(auto_end)   else max_d
            corr_dt = datetime(year, mth, random.randint(max(1, lo), min(max_d, hi)))
        else:
            delta   = (auto_end - auto_start).days
            corr_dt = auto_start + timedelta(days=random.randint(0, max(0, delta)))

        nat       = random.choice(nat_pool)
        loc_data  = LOCATIONS[nat]
        city, venue = random.choice(loc_data['cities'])

        auto_change = {
            'winner':    holder,
            'winner_cc': holder_cc,
            'loser':     current_holder,
            'loser_cc':  current_holder_cc,
            'date':      corr_dt,
            'nat':       nat,
            'city':      city,
            'venue':     venue,
            'auto':      True,
        }
        changes.append(auto_change)
        print(f"      → {holder} def. {current_holder} on {format_date(corr_dt)}")

    # Sort final list chronologically
    changes.sort(key=lambda x: x['date'])

    # ── 10. Preview ────────────────────────────────────────────────────────────
    org_label = 'The Ring' if org == 'ring' else org.upper()
    print(f"\n  Preview — {len(changes)} match(es) → weekly/list.html:")
    print("  " + "─" * 54)
    for c in changes:
        tag = "  [AUTO]" if c['auto'] else ""
        loc_tag = f"{c['city']} / {LOCATIONS[c['nat']]['show_name']}"
        print(f"    {format_date(c['date']):<20}  {c['winner']} def. {c['loser']} (c){tag}")
        print(f"    {'':20}  {org_label} {weight_class} · {loc_tag}")
    print()

    confirm = input("  Insert into weekly/list.html? (y/n): ").strip().lower()
    if confirm != 'y':
        print("  Cancelled.")
        return

    # ── 11. Write ──────────────────────────────────────────────────────────────
    with open(weekly_path, 'r', encoding='utf-8') as f:
        content = f.read()

    org_notes = f'<i>The Ring</i>' if org == 'ring' else org.upper()
    notes_text = f'{org_notes} {weight_class} championship'
    added_years = set()

    for c in changes:
        show_name = LOCATIONS[c['nat']]['show_name']
        content   = write_match_to_weekly(
            content, c, show_name, weight_class, notes_text, added_years
        )
        tag = " [AUTO]" if c['auto'] else ""
        print(f"  ✓ {c['winner']} def. {c['loser']} on {format_date(c['date'])}{tag}")

    with open(weekly_path, 'w', encoding='utf-8') as f:
        f.write(content)

    print("\n" + "=" * 60)
    print(f"  ✓ Done! {len(changes)} match(es) added.")
    auto_count = sum(1 for c in changes if c['auto'])
    if auto_count:
        print(f"  ✓ {auto_count} auto-corrective return(s) inserted to protect PPV canon.")
    print(f"  Run update.py to rebuild all pages.")
    print("=" * 60)


if __name__ == '__main__':
    main()