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
fake_mx = Faker('es_MX')
fake_us = Faker('en_US')

# Romanized Japanese name pools (Faker ja_JP outputs kanji)
JP_FIRST_NAMES = [
    'Akira', 'Daisuke', 'Haruki', 'Hiroshi', 'Isamu', 'Junichi', 'Kazuo',
    'Kenji', 'Koji', 'Masahiro', 'Noboru', 'Osamu', 'Ryo', 'Satoshi',
    'Shinji', 'Takeshi', 'Taro', 'Tetsuya', 'Tomohiro', 'Yasuhiro',
    'Yoshiaki', 'Yuji', 'Yukio', 'Tadashi', 'Kenta', 'Shogo', 'Naoki',
    'Ren', 'Shuji', 'Makoto', 'Hideo', 'Goro', 'Jiro', 'Saburo',
    'Ichiro', 'Rokuro', 'Shiro', 'Hayato', 'Ryota', 'Daiki',
]
JP_LAST_NAMES = [
    'Tanaka', 'Yamamoto', 'Suzuki', 'Watanabe', 'Takahashi', 'Nakamura',
    'Kobayashi', 'Saito', 'Kato', 'Yoshida', 'Yamada', 'Sasaki', 'Matsuda',
    'Inoue', 'Kimura', 'Hayashi', 'Shimizu', 'Yamazaki', 'Mori', 'Ikeda',
    'Hashimoto', 'Ishikawa', 'Ogawa', 'Fujita', 'Okada', 'Goto', 'Hasegawa',
    'Murakami', 'Kondo', 'Fukuda', 'Nishimura', 'Aoki', 'Sakamoto', 'Endo',
    'Sugiyama', 'Ueda', 'Morita', 'Hara', 'Miyamoto', 'Ota',
]

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
METHODS_WIN = ['Pinfall', 'Submission', 'Pinfall', 'Pinfall', 'Submission',
               'Pinfall', 'Count Out', 'Disqualification']
METHODS_LOSS = ['Pinfall', 'Submission', 'Pinfall', 'Pinfall', 'Submission']
FALLS_WIN = ['[1-0]', '[2-1]', '[1-0]', '[1-0]']
FALLS_LOSS = ['[0-1]', '[1-2]', '[0-1]', '[0-1]']

# ─── Helpers ────────────────────────────────────────────────────────────────

def generate_jobber_name(nationality):
    """Generate a realistic jobber name based on nationality."""
    if nationality == 'mx':
        first = fake_mx.first_name_male()
        last = fake_mx.last_name()
        return first + ' ' + last, 'mx'
    elif nationality == 'jp':
        # Use romanized Japanese names (Last First order)
        last = random.choice(JP_LAST_NAMES)
        first = random.choice(JP_FIRST_NAMES)
        return last + ' ' + first, 'jp'
    else:
        first = fake_us.first_name_male()
        last = fake_us.last_name()
        return first + ' ' + last, 'us'


def parse_date(date_str):
    """Parse date string -> datetime."""
    try:
        return datetime.strptime(date_str.strip(), "%B %d, %Y")
    except:
        try:
            return datetime.strptime(date_str.strip(), "%B %Y")
        except:
            return None


def format_date(dt):
    """datetime -> 'Month DD, YYYY'."""
    return dt.strftime("%B %-d, %Y")


def get_year_month(dt):
    """Return (year, month) tuple."""
    return (dt.year, dt.month)


def parse_weekly_html(filepath):
    """Parse existing weekly list.html to extract all match dates per wrestler."""
    wrestler_dates = defaultdict(list)  # wrestler_name -> list of (year, month) tuples
    all_event_dates = []  # list of (datetime, line_number_approx) for ordering

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

        # Last row = info row
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

        # Parse match rows for wrestler names
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

                # Determine reign end: next reign's start date, or ongoing
                if i + 1 < len(reigns):
                    next_start = db.parse_date(reigns[i + 1]['date'])
                    reign_end = next_start if next_start else None
                else:
                    reign_end = None  # Still champion

                # Check if reign overlaps with [start_dt, end_dt]
                if reign_end and reign_end < start_dt:
                    continue  # Reign ended before our period
                if reign_start > end_dt:
                    continue  # Reign started after our period

                titles.append({'org': org, 'weight': weight})
                break  # One match per org/weight is enough

    return titles


def generate_match_dates(start_dt, end_dt, count, occupied_months):
    """
    Generate `count` random dates between start_dt and end_dt, respecting
    the 1-match-per-calendar-month constraint.

    occupied_months: dict of (year, month) -> count of existing matches

    Returns sorted list of datetimes, or None if impossible.
    """
    # Build pool of available (year, month) slots
    available_slots = {}  # (year, month) -> max_new_matches

    current = start_dt.replace(day=1)
    end_ym = (end_dt.year, end_dt.month)

    while (current.year, current.month) <= end_ym:
        ym = (current.year, current.month)
        existing = occupied_months.get(ym, 0)
        available = 1 - existing
        if available > 0:
            available_slots[ym] = available
        # Next month
        if current.month == 12:
            current = current.replace(year=current.year + 1, month=1)
        else:
            current = current.replace(month=current.month + 1)

    total_available = sum(available_slots.values())
    if total_available < count:
        return None, total_available

    # Distribute matches evenly across the date range
    months_list = sorted(available_slots.keys())
    selected_dates = []

    # Spread matches evenly: divide available months into `count` segments
    # and pick one month per segment for better distribution
    available_months = [ym for ym in months_list if available_slots.get(ym, 0) > 0]

    if count <= len(available_months):
        # Even spread: divide into `count` equal segments, pick one per segment
        segment_size = len(available_months) / count
        chosen_months = []
        for i in range(count):
            seg_start = int(i * segment_size)
            seg_end = int((i + 1) * segment_size)
            seg_end = max(seg_end, seg_start + 1)
            picked = random.choice(available_months[seg_start:seg_end])
            chosen_months.append(picked)
    else:
        # More matches than months: fill all available months first
        chosen_months = list(available_months)
        remaining = count - len(chosen_months)
        extras = [ym for ym in available_months if available_slots[ym] > 1]
        random.shuffle(extras)
        chosen_months.extend(extras[:remaining])

    # For each chosen (year, month), pick a random day
    for ym in chosen_months:
        year, month = ym
        max_day = calendar.monthrange(year, month)[1]

        # Ensure date is within [start_dt, end_dt]
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
    Returns dict with 'insert_pos' and 'match_count', or None.
    """
    details_pattern = re.compile(r'<details>(.*?)</details>', re.DOTALL)

    for m in details_pattern.finditer(content):
        block_text = m.group(1)
        block_content_start = m.start(1)

        # Check show name match (Wrestling, Lucha Libre, Puroresu)
        if show_name:
            summary_match = re.search(r'<summary>(.*?)</summary>', block_text)
            if summary_match:
                block_show = summary_match.group(1).strip()
                if block_show != show_name:
                    continue

        # Find dates in the block — the info row date is the last date mention
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

        # Count singles matches
        singles_count = block_text.count('<td>Singles</td>')
        if singles_count >= 5:
            continue

        # Find the info row: <tr> with empty <th></th> then <th colspan="2">
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
    """
    Insert a match row into an existing block, right before the info row.
    Returns modified content.
    """
    pos = block_info['insert_pos']

    # pos points to '<tr><th></th>...' (the info row)
    # Find the start of this line so we insert before it
    line_start = content.rfind('\n', 0, pos)
    if line_start == -1:
        line_start = 0

    # Insert the match row before the info row's line
    content = content[:line_start] + '\n' + match_row_html.rstrip('\n') + content[line_start:]
    return content


def build_match_row(match_num, weight_class, wrestler_name, wrestler_country,
                    jobber_name, jobber_country, result, method, falls, notes=''):
    """Build a single HTML <tr> for a match."""
    if result == 'win':
        w1_name, w1_cc = wrestler_name, wrestler_country
        w2_name, w2_cc = jobber_name, jobber_country
        result_text = 'def.'
    else:
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
    """
    Build a full <details> block with up to 5 matches.
    matches_data: list of match row HTML strings.
    """
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
    """
    Find the right place in weekly/list.html to insert a new details block.
    We find the year header and insert after existing details for same/earlier dates
    in that year, or create a new year section.

    Returns (insert_position, year_header_needed).
    """
    target_year = target_date.year
    year_header_h2 = f'<h2>{target_year}</h2>'
    year_header_h3 = f'<h3>{target_year}</h3>'

    # Check if year header exists
    has_h2 = year_header_h2.lower().replace(' ', '') in content.lower().replace(' ', '')
    has_h3 = year_header_h3.lower().replace(' ', '') in content.lower().replace(' ', '')

    if has_h2 or has_h3:
        # Year exists. Find all details blocks and their dates within this year section.
        # Find the year header position
        if has_h2:
            pattern = re.compile(re.escape(f'<h2>{target_year}</h2>'), re.IGNORECASE)
        else:
            pattern = re.compile(re.escape(f'<h3>{target_year}</h3>'), re.IGNORECASE)

        match = pattern.search(content)
        if not match:
            # Shouldn't happen since we checked, but fallback
            return len(content), True

        year_start = match.end()

        # Find next year header or end of file
        next_year_pattern = re.compile(r'<h[23]>\d{4}</h[23]>', re.IGNORECASE)
        next_match = next_year_pattern.search(content, year_start)
        year_end = next_match.start() if next_match else len(content)

        year_section = content[year_start:year_end]

        # Find all </details> positions within this year section and their dates
        details_ends = []
        for m in re.finditer(r'</details>', year_section):
            pos = m.end()
            # Look backwards from this position to find the date in the info row
            block_before = year_section[:pos]
            # Find the last date in this block
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
            # Find the last block whose date <= target_date
            insert_after = None
            for pos, dt in details_ends:
                if dt <= target_date:
                    insert_after = pos

            if insert_after is not None:
                return insert_after, False
            else:
                # All existing blocks are after our target date — insert right after year header
                return year_start, False
        else:
            return year_start, False
    else:
        # Year doesn't exist — find where to insert the year header
        # Find all year headers and insert in order
        year_headers = list(re.finditer(r'<h[23]>(\d{4})</h[23]>', content))

        if not year_headers:
            # No year headers at all — append before closing tags
            body_end = content.rfind('</body>')
            if body_end == -1:
                return len(content), True
            return body_end, True

        # Find where our year fits
        insert_pos = None
        for m in year_headers:
            header_year = int(m.group(1))
            if header_year > target_year:
                insert_pos = m.start()
                break

        if insert_pos is None:
            # Our year is after all existing — insert at end
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
    For each match, tries to aggregate into an existing block in the same month
    (up to 5 matches per block). Otherwise creates a new block.
    matches: list of dicts with match data including 'date'.
    """
    with open(weekly_path, 'r', encoding='utf-8') as f:
        content = f.read()

    all_matches = sorted(matches, key=lambda x: x['date'])
    added_years = set()

    for match in all_matches:
        dt = match['date']

        # Try to find an existing block in the same month with matching show
        block_info = find_block_for_month(content, dt.year, dt.month, match['show_name'])

        if block_info:
            # Add match to existing block
            match_num = block_info['match_count'] + 1
            match_row = build_match_row(
                match_num, weight_class, match['w_name_display'],
                wrestler_country, match['jobber_name'], match['jobber_cc'],
                result_type, match['method'], match['falls'], match['notes']
            )
            content = add_match_to_block(content, block_info, match_row)
        else:
            # Create new 1-match block
            match_row = build_match_row(
                1, weight_class, match['w_name_display'],
                wrestler_country, match['jobber_name'], match['jobber_cc'],
                result_type, match['method'], match['falls'], match['notes']
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

    # 2. Win or Loss
    print()
    result_input = input("  Result type — (w)ins or (l)osses? [w]: ").strip().lower()
    result_type = 'loss' if result_input == 'l' else 'win'
    print(f"  → Generating {result_type}{'es' if result_type == 'loss' else 's'}")

    # 3. Weight class
    print("\n  Weight class options:")
    for i, w in enumerate(WEIGHT_CLASSES, 1):
        print(f"    {i}. {w}")
    wc_input = input("  Pick number [2=Bridgerweight]: ").strip()
    if wc_input.isdigit() and 1 <= int(wc_input) <= len(WEIGHT_CLASSES):
        weight_class = WEIGHT_CLASSES[int(wc_input) - 1]
    else:
        weight_class = 'Bridgerweight'
    print(f"  → {weight_class}")

    # 4. Date range
    print()
    start_str = input("  Start date (e.g. February 1970 or February 1, 1970): ").strip()
    start_dt = parse_date(start_str)
    if not start_dt:
        print("  ERROR: Could not parse start date.")
        return

    end_str = input("  End date (e.g. February 1971 or February 28, 1971): ").strip()
    end_dt = parse_date(end_str)
    if not end_dt:
        print("  ERROR: Could not parse end date.")
        return

    if end_dt <= start_dt:
        print("  ERROR: End date must be after start date.")
        return

    # If month-only format, set end to last day of that month
    if end_dt.day == 1 and 'February' in end_str and ',' not in end_str:
        end_dt = end_dt.replace(day=calendar.monthrange(end_dt.year, end_dt.month)[1])
    elif ',' not in end_str:
        end_dt = end_dt.replace(day=calendar.monthrange(end_dt.year, end_dt.month)[1])

    print(f"  → Range: {format_date(start_dt)} to {format_date(end_dt)}")

    # 5. Check championship titles during this period
    is_defense = False
    defense_orgs = []
    defense_weight = None

    if result_type == 'win':
        print("\n  Checking championship holdings for this period...")
        period_titles = get_titles_for_period(wrestler_name, start_dt, end_dt,
                                              weekly_path, ppv_path)

        if period_titles:
            print(f"\n  🏆 {wrestler_name} held title(s) during this period:")
            for i, t in enumerate(period_titles, 1):
                org_display = 'The Ring' if t['org'] == 'ring' else t['org'].upper()
                print(f"    {i}. {org_display} {t['weight'].capitalize()}")

            defense_input = input("\n  Generate these as title defenses? (y/n): ").strip().lower()
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

    # 6. Count
    count_str = input("  Number of matches to generate: ").strip()
    if not count_str.isdigit() or int(count_str) < 1:
        print("  ERROR: Must be a positive integer.")
        return
    count = int(count_str)

    # 7. Parse existing schedule to check constraints
    print("\n  Parsing existing schedule...")
    weekly_dates, _ = parse_weekly_html(weekly_path)
    ppv_dates = parse_ppv_html(ppv_path)

    # Merge all (year, month) occurrences for this wrestler
    occupied_months = defaultdict(int)
    for ym in weekly_dates.get(wrestler_name, []):
        occupied_months[ym] += 1
    for ym in ppv_dates.get(wrestler_name, []):
        occupied_months[ym] += 1

    # Generate dates
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

    # 8. Location preference
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

    # 9. Build individual matches (one per date)
    matches_to_insert = []

    for dt in match_dates:
        nat = random.choice(nationalities)
        loc_data = LOCATIONS[nat]
        city, venue = random.choice(loc_data['cities'])

        jobber_name, jobber_cc = generate_jobber_name(nat)
        if result_type == 'win':
            method = random.choice(METHODS_WIN)
            falls = random.choice(FALLS_WIN)
        else:
            method = random.choice(METHODS_LOSS)
            falls = random.choice(FALLS_LOSS)

        # Build notes for title defenses
        notes = ''
        if is_defense and result_type == 'win':
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

            method = random.choice(['Pinfall', 'Submission', 'Pinfall', 'Pinfall', 'Submission'])
            falls = random.choice(FALLS_WIN)

        w_name_display = wrestler_name
        if is_defense:
            w_name_display = wrestler_name + ' (c)'

        matches_to_insert.append({
            'date': dt,
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

    # 9. Preview
    print(f"\n  Preview of {len(matches_to_insert)} match(es):")
    print("  " + "-" * 56)
    for m in matches_to_insert:
        date_str = format_date(m['date'])
        print(f"    {date_str} — {m['w_name_display']} vs {m['jobber_name']} ({m['method']})")

    # 10. Confirm
    confirm = input("\n  Insert into weekly/list.html? (y/n): ").strip().lower()
    if confirm != 'y':
        print("  Cancelled.")
        return

    # 11. Insert (aggregates into existing blocks when possible)
    print("\n  Inserting into weekly/list.html...")
    insert_matches_into_weekly(weekly_path, matches_to_insert, wrestler_name,
                               wrestler_country, weight_class, result_type)
    print("  ✓ Matches inserted!")

    print("\n" + "=" * 60)
    print(f"  ✓ Done! Added {count} jobber {'losses' if result_type == 'loss' else 'wins'} "
          f"for {wrestler_name}")
    print(f"  Remember to run update.py to rebuild wrestler pages.")
    print("=" * 60)


if __name__ == '__main__':
    main()
