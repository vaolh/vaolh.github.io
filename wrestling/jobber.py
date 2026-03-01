#!/usr/bin/env python3
"""
Wrestling Jobber Match Generator
=================================
Generates filler wins (or losses) against random jobbers for a wrestler.
Inserts matches into wrestling/weekly/list.html grouped into <details> blocks
(max 5 matches per block). Then runs update.py to rebuild all stats.

Usage:
  source ~/wrestling-venv/bin/activate
  python3 wrestling/jobber.py

Required packages (in wrestling-venv):
  pip install beautifulsoup4 faker
"""

from bs4 import BeautifulSoup
from faker import Faker
from datetime import datetime, timedelta
from collections import defaultdict
import random
import re
import os
import calendar

# ─── Faker locales ───────────────────────────────────────────────────────────
fake_us = Faker('en_US')
fake_jp = Faker('ja_JP')
fake_mx = Faker('es_ES')

# ─── Location pools ─────────────────────────────────────────────────────────
LOCATIONS = {
    'mx': {
        'country_code': 'mx',
        'cities': [
            ('Mexico City, Mexico', 'Arena Coliseo'),
            ('Mexico City, Mexico', 'Arena Mexico'),
            ('Guadalajara, Mexico', 'Arena Coliseo Guadalajara'),
            ('Monterrey, Mexico', 'Arena Monterrey'),
            ('Puebla, Mexico', 'Arena Puebla'),
            ('Acapulco, Mexico', 'Arena Acapulco'),
            ('Veracruz, Mexico', 'Arena Veracruz'),
            ('Toluca, Mexico', 'Arena Toluca'),
            ('Tijuana, Mexico', 'Auditorio de Tijuana'),
            ('Leon, Mexico', 'Arena Leon'),
        ],
        'show_name': 'Lucha Libre',
    },
    'jp': {
        'country_code': 'jp',
        'cities': [
            ('Tokyo, Japan', 'Kuramae Kokugikan'),
            ('Tokyo, Japan', 'Korakuen Hall'),
            ('Osaka, Japan', 'Osaka Prefectural Gymnasium'),
            ('Yokohama, Japan', 'Bunka Gymnasium'),
            ('Nagoya, Japan', 'Aichi Prefectural Gymnasium'),
            ('Sapporo, Japan', 'Nakajima Sports Center'),
            ('Fukuoka, Japan', 'Fukuoka Civic Center'),
            ('Shizuoka, Japan', 'Shizuoka Arena'),
            ('Sendai, Japan', 'Miyagi Prefectural Gymnasium'),
            ('Kobe, Japan', 'Kobe World Memorial Hall'),
        ],
        'show_name': 'Puroresu',
    },
    'us': {
        'country_code': 'us',
        'cities': [
            ('New York, United States', 'Madison Square Garden'),
            ('Chicago, United States', 'Chicago Arena'),
            ('Los Angeles, United States', 'Olympic Auditorium'),
            ('Philadelphia, United States', 'Philadelphia Arena'),
            ('Boston, United States', 'Boston Square Garden'),
            ('Dallas, United States', 'Sportatorium'),
            ('Houston, United States', 'Sam Houston Coliseum'),
            ('Pittsburgh, United States', 'Civic Arena'),
            ('San Antonio, United States', 'Municipal Auditorium'),
            ('Minneapolis, United States', 'Auditorium'),
            ('Buffalo, United States', 'Buffalo Memorial Auditorium'),
            ('Detroit, United States', 'Cobo Hall'),
            ('St. Louis, United States', 'Kiel Auditorium'),
        ],
        'show_name': 'Wrestling',
    },
}

WEIGHT_CLASSES = ['Heavyweight', 'Bridgerweight', 'Middleweight', 'Welterweight',
                  'Lightweight', 'Featherweight']
METHODS_WIN  = ['Pinfall', 'Submission', 'Pinfall', 'Pinfall', 'Submission',
                'Pinfall', 'Pinfall', 'Submission', 'Pinfall', 'Pinfall',
                'Count Out', 'Disqualification']
METHODS_LOSS = ['Pinfall', 'Submission', 'Pinfall', 'Pinfall', 'Submission']
METHODS_DRAW = ['Time Limit', 'Decision', 'Count Out']
FALLS_WIN    = ['[1-0]', '[2-1]', '[1-0]', '[1-0]']
FALLS_LOSS   = ['[0-1]', '[1-2]', '[0-1]', '[0-1]']
FALLS_DRAW   = ['[1-1]', '[0-0]', '[1-1]', '[1-1]']

# ─── Helpers ────────────────────────────────────────────────────────────────

def generate_jobber_name(nationality, gender='m'):
    """Generate a realistic jobber name based on nationality and gender."""
    if nationality == 'mx':
        if gender == 'f':
            first = fake_mx.first_name_female()
        else:
            first = fake_mx.first_name_male()
        last = fake_mx.last_name()
        return first + ' ' + last, 'mx'
    elif nationality == 'jp':
        last = fake_jp.last_romanized_name()
        if gender == 'f':
            first = fake_jp.first_romanized_name_female()
        else:
            first = fake_jp.first_romanized_name_male()
        return last + ' ' + first, 'jp'
    else:
        if gender == 'f':
            first = fake_us.first_name_female()
        else:
            first = fake_us.first_name_male()
        last = fake_us.last_name()
        return first + ' ' + last, 'us'


# Mapping of month abbreviations / alternate spellings → full month name
MONTH_ALIASES = {
    'jan': 'January', 'feb': 'February', 'mar': 'March', 'apr': 'April',
    'may': 'May',     'jun': 'June',     'jul': 'July',  'aug': 'August',
    'sep': 'September', 'sept': 'September', 'oct': 'October',
    'nov': 'November', 'dec': 'December',
    # full names map to themselves for completeness
    'january': 'January', 'february': 'February', 'march': 'March',
    'april': 'April', 'june': 'June', 'july': 'July', 'august': 'August',
    'september': 'September', 'october': 'October', 'november': 'November',
    'december': 'December',
}


def normalise_date_str(date_str):
    """
    Expand month abbreviations so that strptime can handle them.
    e.g. 'Feb 1970' → 'February 1970', 'Feb 1, 1970' → 'February 1, 1970'
    """
    date_str = date_str.strip()
    # Match a leading word that could be an abbreviated month
    m = re.match(r'^([A-Za-z]+)([\s,].*)?$', date_str)
    if m:
        word = m.group(1).lower()
        rest = m.group(2) or ''
        if word in MONTH_ALIASES:
            return MONTH_ALIASES[word] + rest
    return date_str


def parse_date(date_str):
    """Parse date string → datetime (supports full and abbreviated month names)."""
    normalised = normalise_date_str(date_str.strip())
    for fmt in ("%B %d, %Y", "%B %Y"):
        try:
            return datetime.strptime(normalised, fmt)
        except ValueError:
            pass
    return None


def format_date(dt):
    """datetime → 'Month DD, YYYY'."""
    return dt.strftime("%B %-d, %Y")


def get_year_month(dt):
    """Return (year, month) tuple."""
    return (dt.year, dt.month)


def parse_weekly_html(filepath):
    """Parse existing weekly list.html to extract all match dates per wrestler."""
    wrestler_dates = defaultdict(list)
    all_event_dates = []

    if not os.path.exists(filepath):
        return wrestler_dates, all_event_dates

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    soup = BeautifulSoup(content, 'html.parser')
    details_list = soup.find_all('details')

    for detail in details_list:
        table = detail.find('table', class_='match-card')
        if not table:
            continue

        tbody = table.find('tbody')
        if not tbody:
            continue
        rows = tbody.find_all('tr')
        if not rows:
            continue

        info_row = rows[-1]
        th_cells = info_row.find_all('th')
        event_date_str = None
        for th in th_cells:
            text = th.get_text().strip()
            dt = parse_date(text)
            if dt:
                event_date_str = text
                break

        if not event_date_str:
            continue

        event_dt = parse_date(event_date_str)
        if not event_dt:
            continue

        all_event_dates.append(event_dt)

        match_rows = rows[1:-1]
        for row in match_rows:
            cols = row.find_all(['td', 'th'])
            if len(cols) < 7:
                continue
            match_type = cols[1].get_text().strip()
            if match_type.lower() != 'singles':
                continue

            f1 = re.sub(r'\s*\(c\)\s*', '', cols[3].get_text().strip()).strip()
            f2 = re.sub(r'\s*\(c\)\s*', '', cols[5].get_text().strip()).strip()

            ym = get_year_month(event_dt)
            wrestler_dates[f1].append(ym)
            wrestler_dates[f2].append(ym)

    return wrestler_dates, all_event_dates


def parse_ppv_html(filepath):
    """Parse PPV list.html to extract match dates per wrestler."""
    wrestler_dates = defaultdict(list)

    if not os.path.exists(filepath):
        return wrestler_dates

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    soup = BeautifulSoup(content, 'html.parser')
    details_list = soup.find_all('details')

    for detail in details_list:
        table = detail.find('table', class_='match-card')
        if not table:
            continue

        tbody = table.find('tbody')
        if not tbody:
            continue
        rows = tbody.find_all('tr')
        if not rows:
            continue

        info_row = rows[-1]
        th_cells = info_row.find_all('th')
        event_date_str = None
        for th in th_cells:
            text = th.get_text().strip()
            dt = parse_date(text)
            if dt:
                event_date_str = text
                break

        if not event_date_str:
            continue

        event_dt = parse_date(event_date_str)
        if not event_dt:
            continue

        match_rows = rows[1:-1]
        for row in match_rows:
            cols = row.find_all(['td', 'th'])
            if len(cols) < 7:
                continue
            match_type = cols[1].get_text().strip()
            if match_type.lower() != 'singles':
                continue

            f1 = re.sub(r'\s*\(c\)\s*', '', cols[3].get_text().strip()).strip()
            f2 = re.sub(r'\s*\(c\)\s*', '', cols[5].get_text().strip()).strip()

            ym = get_year_month(event_dt)
            wrestler_dates[f1].append(ym)
            wrestler_dates[f2].append(ym)

    return wrestler_dates


def get_wrestler_country(wrestler_name, weekly_path, ppv_path):
    """Find the country code for a wrestler from existing HTML files."""
    for filepath in [ppv_path, weekly_path]:
        if not os.path.exists(filepath):
            continue
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        soup = BeautifulSoup(content, 'html.parser')
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
                for cell_idx in [3, 5]:
                    cell = cols[cell_idx]
                    name = re.sub(r'\s*\(c\)\s*', '', cell.get_text().strip()).strip()
                    if name == wrestler_name:
                        flag = cell.find('span', class_='fi')
                        if flag:
                            for c in flag.get('class', []):
                                if c.startswith('fi-'):
                                    return c.replace('fi-', '')
    return 'un'


def get_titles_for_period(wrestler_name, start_dt, end_dt, weekly_path, ppv_path):
    """
    Run the WrestlingDatabase engine to find title holdings for a wrestler
    during a specific date range. Checks all reigns that overlap the period.
    Returns list of dicts: [{'org': 'wwf', 'weight': 'bridgerweight'}, ...]
    """
    import sys
    script_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(script_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    from update import WrestlingDatabase

    db = WrestlingDatabase()
    db.parse_events(ppv_path, is_weekly=False)
    if os.path.exists(weekly_path):
        db.parse_events(weekly_path, is_weekly=True)

    db.events.sort(key=lambda e: db.parse_date(e['date']) if e.get('date') else datetime.min)
    db.reprocess_championships_chronologically()
    db.process_vacancies()

    titles = []
    for org in ['wwf', 'wwo', 'iwb', 'ring']:
        for weight in ['heavyweight', 'bridgerweight', 'middleweight', 'welterweight',
                        'lightweight', 'featherweight']:
            reigns = db.championships[org][weight]
            for i, reign in enumerate(reigns):
                if reign['champion'] != wrestler_name:
                    continue
                if 'vacancy_message' in reign:
                    continue

                reign_start = db.parse_date(reign['date'])
                if not reign_start:
                    continue

                if i + 1 < len(reigns):
                    next_start = db.parse_date(reigns[i + 1]['date'])
                    reign_end = next_start if next_start else None
                else:
                    reign_end = None

                if reign_end and reign_end < start_dt:
                    continue
                if reign_start > end_dt:
                    continue

                titles.append({'org': org, 'weight': weight})
                break

    return titles


def generate_match_dates(start_dt, end_dt, count, occupied_months):
    """
    Generate `count` random dates between start_dt and end_dt, respecting
    the 1-match-per-calendar-month constraint.
    """
    available_slots = {}

    current = start_dt.replace(day=1)
    end_ym = (end_dt.year, end_dt.month)

    while (current.year, current.month) <= end_ym:
        ym = (current.year, current.month)
        existing = occupied_months.get(ym, 0)
        available = 1 - existing
        if available > 0:
            available_slots[ym] = available
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    total_available = sum(available_slots.values())
    if total_available < count:
        return None, total_available

    months_list = sorted(available_slots.keys())
    selected_dates = []

    available_months = [ym for ym in months_list if available_slots.get(ym, 0) > 0]

    if count <= len(available_months):
        segment_size = len(available_months) / count
        chosen_months = []
        for i in range(count):
            seg_start = int(i * segment_size)
            seg_end = int((i + 1) * segment_size)
            seg_end = max(seg_end, seg_start + 1)
            picked = random.choice(available_months[seg_start:seg_end])
            chosen_months.append(picked)
    else:
        chosen_months = list(available_months)
        remaining = count - len(chosen_months)
        extras = [ym for ym in available_months if available_slots[ym] > 1]
        random.shuffle(extras)
        chosen_months.extend(extras[:remaining])

    for ym in chosen_months:
        year, month = ym
        max_day = calendar.monthrange(year, month)[1]

        min_day = start_dt.day if (year, month) == get_year_month(start_dt) else 1
        max_day_bound = end_dt.day if (year, month) == get_year_month(end_dt) else max_day

        day = random.randint(min_day, max_day_bound)
        selected_dates.append(datetime(year, month, day))

    selected_dates.sort()
    return selected_dates, total_available


def find_block_for_month(content, year, month, show_name=None):
    """
    Find an existing <details> block whose date falls in the given (year, month)
    that has fewer than 5 singles matches and matches the show_name.
    """
    details_pattern = re.compile(r'<details>(.*?)</details>', re.DOTALL)

    for m in details_pattern.finditer(content):
        block_text = m.group(1)
        block_content_start = m.start(1)

        if show_name:
            summary_match = re.search(r'<summary>(.*?)</summary>', block_text)
            if summary_match:
                block_show = summary_match.group(1).strip()
                if block_show != show_name:
                    continue

        date_matches = re.findall(
            r'(?:January|February|March|April|May|June|July|August|September|'
            r'October|November|December)\s+\d{1,2},\s+\d{4}',
            block_text
        )
        if not date_matches:
            continue

        block_date = parse_date(date_matches[-1])
        if not block_date:
            continue

        if block_date.year != year or block_date.month != month:
            continue

        singles_count = block_text.count('<td>Singles</td>')
        if singles_count >= 5:
            continue

        info_pattern = re.compile(r'<tr>\s*<th>\s*</th>\s*<th\s+colspan="2">')
        info_match = info_pattern.search(block_text)
        if not info_match:
            continue

        insert_pos = block_content_start + info_match.start()

        return {
            'insert_pos': insert_pos,
            'match_count': singles_count,
        }

    return None


def add_match_to_block(content, block_info, match_row_html):
    """Insert a match row into an existing block, right before the info row."""
    pos = block_info['insert_pos']
    line_start = content.rfind('\n', 0, pos)
    if line_start == -1:
        line_start = 0
    content = content[:line_start] + '\n' + match_row_html.rstrip('\n') + content[line_start:]
    return content


def build_match_row(match_num, weight_class, wrestler_name, wrestler_country,
                    jobber_name, jobber_country, result, method, falls, notes=''):
    """
    Build a single HTML <tr> for a match.
    result: 'win', 'loss', or 'draw'
    """
    if result == 'draw':
        # For draws the wrestler is listed first, separator is 'vs.'
        w1_name, w1_cc = wrestler_name, wrestler_country
        w2_name, w2_cc = jobber_name, jobber_country
        result_text = 'vs.'
    elif result == 'win':
        w1_name, w1_cc = wrestler_name, wrestler_country
        w2_name, w2_cc = jobber_name, jobber_country
        result_text = 'def.'
    else:  # loss
        w1_name, w1_cc = jobber_name, jobber_country
        w2_name, w2_cc = wrestler_name, wrestler_country
        result_text = 'def.'

    notes_cell = f'<td>{notes}</td>' if notes else '<td></td>'

    return (
        f'    <tr>'
        f'<th>{match_num}</th>'
        f'<td>Singles</td>'
        f'<td>{weight_class}</td>'
        f'<td><span class="fi fi-{w1_cc}"></span> {w1_name}</td>'
        f'<td>{result_text}</td>'
        f'<td><span class="fi fi-{w2_cc}"></span> {w2_name}</td>'
        f'<td>{method}</td>'
        f'<td>{falls}</td>'
        f'{notes_cell}'
        f'</tr>\n'
    )


def build_details_block(matches_data, show_name, location_str, country_code,
                         venue, date_str):
    """Build a full <details> block with up to 5 matches."""
    date_parts = date_str.split()
    month_label = date_parts[0].upper()
    year_label = date_parts[-1]
    country_map = {'mx': 'MEXICO', 'jp': 'JAPAN', 'us': 'USA'}
    country_label = country_map.get(country_code, '')

    html = f'\n    <!-- {month_label} {year_label} | {country_label} -->\n'
    html += f'    <details>\n'
    html += f'    <summary>{show_name}</summary>\n'
    html += f'    <table class="match-card"><tbody>\n'
    html += (f'    <tr><th>No.</th><th>Match Type</th><th>Weight Class</th>'
             f'<th></th><th>vs.</th><th></th><th>Method</th><th>Falls</th><th>Notes</th></tr>\n')

    for m in matches_data:
        html += m

    html += (f'    <tr><th></th>'
             f'<th colspan="2"><span class="fi fi-{country_code}"></span> {location_str}</th>'
             f'<th colspan="2">{venue}</th>'
             f'<th></th><th></th><th></th>'
             f'<th>{date_str}</th></tr>\n')
    html += f'    </tbody></table>\n'
    html += f'    </details>\n'

    return html


def find_insertion_point(content, target_date):
    """Find the right place in weekly/list.html to insert a new details block."""
    target_year = target_date.year
    year_header_h2 = f'<h2>{target_year}</h2>'
    year_header_h3 = f'<h3>{target_year}</h3>'

    has_h2 = year_header_h2.lower().replace(' ', '') in content.lower().replace(' ', '')
    has_h3 = year_header_h3.lower().replace(' ', '') in content.lower().replace(' ', '')

    if has_h2 or has_h3:
        if has_h2:
            pattern = re.compile(re.escape(f'<h2>{target_year}</h2>'), re.IGNORECASE)
        else:
            pattern = re.compile(re.escape(f'<h3>{target_year}</h3>'), re.IGNORECASE)

        match = pattern.search(content)
        if not match:
            return len(content), True

        year_start = match.end()

        next_year_pattern = re.compile(r'<h[23]>\d{4}</h[23]>', re.IGNORECASE)
        next_match = next_year_pattern.search(content, year_start)
        year_end = next_match.start() if next_match else len(content)

        year_section = content[year_start:year_end]

        details_ends = []
        for m in re.finditer(r'</details>', year_section):
            pos = m.end()
            block_before = year_section[:pos]
            date_matches = list(re.finditer(
                r'(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}',
                block_before
            ))
            if date_matches:
                last_date_str = date_matches[-1].group()
                block_date = parse_date(last_date_str)
                if block_date:
                    details_ends.append((pos + year_start, block_date))

        if details_ends:
            insert_after = None
            for pos, dt in details_ends:
                if dt <= target_date:
                    insert_after = pos

            if insert_after is not None:
                return insert_after, False
            else:
                return year_start, False
        else:
            return year_start, False
    else:
        year_headers = list(re.finditer(r'<h[23]>(\d{4})</h[23]>', content))

        if not year_headers:
            body_end = content.rfind('</body>')
            if body_end == -1:
                return len(content), True
            return body_end, True

        insert_pos = None
        for m in year_headers:
            header_year = int(m.group(1))
            if header_year > target_year:
                insert_pos = m.start()
                break

        if insert_pos is None:
            body_end = content.rfind('</body>')
            if body_end == -1:
                insert_pos = len(content)
            else:
                insert_pos = body_end

        return insert_pos, True


def insert_matches_into_weekly(weekly_path, matches, wrestler_name,
                                wrestler_country, weight_class, result_type):
    """
    Insert matches into weekly/list.html.
    result_type: 'win', 'loss', 'draw', or 'mix'
    For 'mix', each match dict already carries its own resolved result.
    """
    with open(weekly_path, 'r', encoding='utf-8') as f:
        content = f.read()

    all_matches = sorted(matches, key=lambda x: x['date'])
    added_years = set()

    for match in all_matches:
        dt = match['date']
        resolved_result = match['result']

        block_info = find_block_for_month(content, dt.year, dt.month, match['show_name'])

        if block_info:
            match_num = block_info['match_count'] + 1
            match_row = build_match_row(
                match_num, weight_class, match['w_name_display'],
                wrestler_country, match['jobber_name'], match['jobber_cc'],
                resolved_result, match['method'], match['falls'], match['notes']
            )
            content = add_match_to_block(content, block_info, match_row)
        else:
            match_row = build_match_row(
                1, weight_class, match['w_name_display'],
                wrestler_country, match['jobber_name'], match['jobber_cc'],
                resolved_result, match['method'], match['falls'], match['notes']
            )

            html = build_details_block(
                [match_row], match['show_name'], match['city'],
                match['country_code'], match['venue'], format_date(dt)
            )

            pos, needs_year = find_insertion_point(content, dt)

            insert_text = ''
            if needs_year and dt.year not in added_years:
                if dt.year < 1968:
                    insert_text = f'\n    <h3>{dt.year}</h3>\n'
                else:
                    insert_text = f'\n    <h2>{dt.year}</h2>\n'
                added_years.add(dt.year)
            insert_text += html

            content = content[:pos] + insert_text + content[pos:]

    with open(weekly_path, 'w', encoding='utf-8') as f:
        f.write(content)


def get_all_wrestler_names(weekly_path, ppv_path):
    """Get sorted list of all wrestler names from both files."""
    names = set()
    for filepath in [ppv_path, weekly_path]:
        if not os.path.exists(filepath):
            continue
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        soup = BeautifulSoup(content, 'html.parser')
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
                mtype = cols[1].get_text().strip()
                if mtype.lower() != 'singles':
                    continue
                f1 = re.sub(r'\s*\(c\)\s*', '', cols[3].get_text().strip()).strip()
                f2 = re.sub(r'\s*\(c\)\s*', '', cols[5].get_text().strip()).strip()
                names.add(f1)
                names.add(f2)
    return sorted(names)


def pick_result_for_match(result_type):
    """Return 'win', 'loss', or 'draw' for a single match given the mode."""
    if result_type == 'mix':
        return random.choice(['win', 'loss', 'draw'])
    return result_type


def build_method_and_falls(resolved_result, is_defense):
    """Return (method, falls) strings appropriate for the resolved result."""
    if resolved_result == 'win' or (is_defense and resolved_result != 'loss'):
        method = random.choice(['Pinfall', 'Submission', 'Pinfall', 'Pinfall',
                                'Submission']) if is_defense else random.choice(METHODS_WIN)
        falls = random.choice(FALLS_WIN)
    elif resolved_result == 'loss':
        method = random.choice(METHODS_LOSS)
        falls = random.choice(FALLS_LOSS)
    else:  # draw
        method = random.choice(METHODS_DRAW)
        falls = random.choice(FALLS_DRAW)
    return method, falls


# ─── Main Interactive Flow ──────────────────────────────────────────────────

def main():
    weekly_path = 'wrestling/weekly/list.html'
    ppv_path = 'wrestling/ppv/list.html'

    print("=" * 60)
    print("  WRESTLING JOBBER MATCH GENERATOR")
    print("=" * 60)

    # 1. Select wrestler
    all_names = get_all_wrestler_names(weekly_path, ppv_path)
    print(f"\nFound {len(all_names)} wrestlers. Type to search:\n")

    while True:
        query = input("Wrestler name (or partial): ").strip()
        if not query:
            continue
        matches = [n for n in all_names if query.lower() in n.lower()]
        if not matches:
            print("  No matches found. Try again.")
            continue
        if len(matches) == 1:
            wrestler_name = matches[0]
            print(f"  → Selected: {wrestler_name}")
            break
        print(f"  Found {len(matches)} matches:")
        for i, m in enumerate(matches, 1):
            print(f"    {i}. {m}")
        choice = input("  Pick number (or refine search): ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(matches):
            wrestler_name = matches[int(choice) - 1]
            print(f"  → Selected: {wrestler_name}")
            break

    wrestler_country = get_wrestler_country(wrestler_name, weekly_path, ppv_path)
    print(f"  Country: {wrestler_country}")

    # 2. Jobber gender
    gender_input = input("  Jobber gender — (m)ale or (f)emale? [m]: ").strip().lower()
    jobber_gender = 'f' if gender_input == 'f' else 'm'
    print(f"  → {'Female' if jobber_gender == 'f' else 'Male'} jobbers")

    # 3. Result type (win / loss / draw / mix)
    print()
    print("  Result type:")
    print("    w = wins only")
    print("    l = losses only")
    print("    d = draws only")
    print("    m = mix (random wins, losses, and draws)")
    result_input = input("  Pick [w/l/d/m, default w]: ").strip().lower()
    if result_input == 'l':
        result_type = 'loss'
        result_label = 'losses'
    elif result_input == 'd':
        result_type = 'draw'
        result_label = 'draws'
    elif result_input == 'm':
        result_type = 'mix'
        result_label = 'mixed results'
    else:
        result_type = 'win'
        result_label = 'wins'
    print(f"  → Generating {result_label}")

    # 4. Weight class
    print("\n  Weight class options:")
    for i, w in enumerate(WEIGHT_CLASSES, 1):
        print(f"    {i}. {w}")
    wc_input = input("  Pick number [2=Bridgerweight]: ").strip()
    if wc_input.isdigit() and 1 <= int(wc_input) <= len(WEIGHT_CLASSES):
        weight_class = WEIGHT_CLASSES[int(wc_input) - 1]
    else:
        weight_class = 'Bridgerweight'
    print(f"  → {weight_class}")

    # 5. Date range (accepts full or abbreviated month names)
    print()
    print("  Date format: full or abbreviated month accepted")
    print("  e.g.  February 1970 / Feb 1970 / Feb 1, 1970 / February 1, 1970")
    start_str = input("  Start date: ").strip()
    start_dt = parse_date(start_str)
    if not start_dt:
        print("  ERROR: Could not parse start date.")
        return

    end_str = input("  End date: ").strip()
    end_dt = parse_date(end_str)
    if not end_dt:
        print("  ERROR: Could not parse end date.")
        return

    if end_dt <= start_dt:
        print("  ERROR: End date must be after start date.")
        return

    # If month-only format, set end to last day of that month
    if ',' not in normalise_date_str(end_str):
        end_dt = end_dt.replace(day=calendar.monthrange(end_dt.year, end_dt.month)[1])

    print(f"  → Range: {format_date(start_dt)} to {format_date(end_dt)}")

    # 6. Championship title logic (only relevant when wins or mix can produce wins)
    is_defense = False
    defense_orgs = []
    defense_weight = None

    can_have_wins = result_type in ('win', 'mix')

    if can_have_wins:
        print("\n  Checking championship holdings for this period...")
        period_titles = get_titles_for_period(wrestler_name, start_dt, end_dt,
                                              weekly_path, ppv_path)

        if period_titles:
            print(f"\n  🏆 {wrestler_name} held title(s) during this period:")
            for i, t in enumerate(period_titles, 1):
                org_display = 'The Ring' if t['org'] == 'ring' else t['org'].upper()
                print(f"    {i}. {org_display} {t['weight'].capitalize()}")

            defense_input = input("\n  Generate wins as title defenses? (y/n): ").strip().lower()
            if defense_input == 'y':
                is_defense = True
                weights_held = defaultdict(list)
                for t in period_titles:
                    weights_held[t['weight']].append(t)

                if len(weights_held) == 1:
                    defense_weight = list(weights_held.keys())[0]
                    defense_orgs = [t['org'] for t in period_titles]
                    weight_class = defense_weight.capitalize()
                    print(f"  Weight class (from title): {weight_class}")
                else:
                    print("\n  Multiple weight classes held. Select division:")
                    weight_list = list(weights_held.keys())
                    for i, w in enumerate(weight_list, 1):
                        orgs = [('The Ring' if t['org'] == 'ring' else t['org'].upper()) for t in weights_held[w]]
                        print(f"    {i}. {w.capitalize()} ({', '.join(orgs)})")
                    wc = input("  Pick number: ").strip()
                    if wc.isdigit() and 1 <= int(wc) <= len(weight_list):
                        defense_weight = weight_list[int(wc) - 1]
                        defense_orgs = [t['org'] for t in weights_held[defense_weight]]
                        weight_class = defense_weight.capitalize()
                        print(f"  Weight class (from title): {weight_class}")
                    else:
                        print("  Invalid choice. Generating non-title matches.")
                        is_defense = False
        else:
            print(f"\n  {wrestler_name} did not hold any titles in this period.")
            force = input("  Force title defense mode anyway? (y/n): ").strip().lower()
            if force == 'y':
                is_defense = True
                print("\n  Select org(s) for defenses:")
                all_orgs = ['wwf', 'wwo', 'iwb', 'ring']
                org_labels = ['WWF', 'WWO', 'IWB', 'The Ring']
                for i, label in enumerate(org_labels, 1):
                    print(f"    {i}. {label}")
                org_input = input("  Pick number(s), comma-separated (e.g. 1,3): ").strip()
                defense_orgs = []
                for part in org_input.split(','):
                    part = part.strip()
                    if part.isdigit() and 1 <= int(part) <= 4:
                        defense_orgs.append(all_orgs[int(part) - 1])
                if not defense_orgs:
                    print("  No valid orgs selected. Generating non-title matches.")
                    is_defense = False
                else:
                    defense_weight = weight_class.lower()
                    chosen = [('The Ring' if o == 'ring' else o.upper()) for o in defense_orgs]
                    print(f"  → Defending: {', '.join(chosen)} {weight_class}")

    # 7. Count
    count_str = input("  Number of matches to generate: ").strip()
    if not count_str.isdigit() or int(count_str) < 1:
        print("  ERROR: Must be a positive integer.")
        return
    count = int(count_str)

    # 8. Parse existing schedule to check constraints
    print("\n  Parsing existing schedule...")
    weekly_dates, _ = parse_weekly_html(weekly_path)
    ppv_dates = parse_ppv_html(ppv_path)

    occupied_months = defaultdict(int)
    for ym in weekly_dates.get(wrestler_name, []):
        occupied_months[ym] += 1
    for ym in ppv_dates.get(wrestler_name, []):
        occupied_months[ym] += 1

    match_dates, max_available = generate_match_dates(start_dt, end_dt, count, occupied_months)
    if match_dates is None:
        print(f"\n  ❌ IMPOSSIBLE: Requested {count} matches but only {max_available} "
              f"slots available in {format_date(start_dt)} – {format_date(end_dt)}.")
        print(f"     (Wrestlers can fight at most 1× per calendar month.)")
        if max_available > 0:
            retry = input(f"     Generate {max_available} instead? (y/n): ").strip().lower()
            if retry == 'y':
                count = max_available
                match_dates, _ = generate_match_dates(start_dt, end_dt, count, occupied_months)
            else:
                return
        else:
            return

    print(f"\n  ✓ Generated {len(match_dates)} match dates")

    # 9. Location preference
    print("\n  Match locations:")
    print("    1. Mexico")
    print("    2. Japan")
    print("    3. USA")
    print("    4. Mix (random)")
    loc_input = input("  Pick number [4=Mix]: ").strip()
    if loc_input == '1':
        nationalities = ['mx']
        print("  → Mexico only")
    elif loc_input == '2':
        nationalities = ['jp']
        print("  → Japan only")
    elif loc_input == '3':
        nationalities = ['us']
        print("  → USA only")
    else:
        nationalities = ['mx', 'jp', 'us']
        print("  → Mix of all three")

    # 10. Build individual matches (one per date)
    matches_to_insert = []

    for dt in match_dates:
        nat = random.choice(nationalities)
        loc_data = LOCATIONS[nat]
        city, venue = random.choice(loc_data['cities'])

        jobber_name, jobber_cc = generate_jobber_name(nat, jobber_gender)

        # Resolve result for this specific match
        resolved_result = pick_result_for_match(result_type)

        method, falls = build_method_and_falls(resolved_result, is_defense)

        # Build notes for title defenses (only on wins)
        notes = ''
        if is_defense and resolved_result == 'win':
            org_labels = []
            for org in defense_orgs:
                if org == 'ring':
                    org_labels.append('<i>The Ring</i>')
                else:
                    org_labels.append(org.upper())
            if len(org_labels) == 1:
                notes = f'{org_labels[0]} championship'
            elif len(org_labels) == 2:
                notes = f'{org_labels[0]} and {org_labels[1]} titles'
            else:
                notes = ', '.join(org_labels[:-1]) + f' and {org_labels[-1]} titles'

        # Show (c) on the wrestler's name for wins and draws when defending
        w_name_display = wrestler_name
        if is_defense and resolved_result in ('win', 'draw'):
            w_name_display = wrestler_name + ' (c)'

        matches_to_insert.append({
            'date': dt,
            'result': resolved_result,
            'jobber_name': jobber_name,
            'jobber_cc': jobber_cc,
            'method': method,
            'falls': falls,
            'notes': notes,
            'nat': nat,
            'city': city,
            'venue': venue,
            'show_name': loc_data['show_name'],
            'country_code': loc_data['country_code'],
            'w_name_display': w_name_display,
        })

    # 11. Preview
    print(f"\n  Preview of {len(matches_to_insert)} match(es):")
    print("  " + "-" * 56)
    result_symbols = {'win': '✓', 'loss': '✗', 'draw': '='}
    for m in matches_to_insert:
        date_str = format_date(m['date'])
        sym = result_symbols.get(m['result'], '?')
        print(f"    [{sym}] {date_str} — {m['w_name_display']} vs {m['jobber_name']} "
              f"({m['method']}, {m['falls']})")

    # 12. Confirm
    confirm = input("\n  Insert into weekly/list.html? (y/n): ").strip().lower()
    if confirm != 'y':
        print("  Cancelled.")
        return

    # 13. Insert
    print("\n  Inserting into weekly/list.html...")
    insert_matches_into_weekly(weekly_path, matches_to_insert, wrestler_name,
                               wrestler_country, weight_class, result_type)
    print("  ✓ Matches inserted!")

    # Summary count
    win_count  = sum(1 for m in matches_to_insert if m['result'] == 'win')
    loss_count = sum(1 for m in matches_to_insert if m['result'] == 'loss')
    draw_count = sum(1 for m in matches_to_insert if m['result'] == 'draw')

    print("\n" + "=" * 60)
    print(f"  ✓ Done! Added {count} match(es) for {wrestler_name}")
    if result_type == 'mix':
        print(f"     Wins: {win_count}  Losses: {loss_count}  Draws: {draw_count}")
    print(f"  Remember to run update.py to rebuild wrestler pages.")
    print("=" * 60)


if __name__ == '__main__':
    main()