#!/usr/bin/env python3
"""
p4p.py — Standalone P4P Rankings + Hall of Fame updater
=========================================================
Run independently from update.py:

    cd /path/to/your/site
    python3 wrestling/p4p.py

Updates:
  - wrestling/org/ring.html   (between <!-- P4Prankings_START/END -->)
  - wrestling/org/pwhof.html  (between <!-- HOFMEMBERS_START/END -->)
  - wrestling/wrestlers/*.html (Career Record + Highest Ranking infobox rows)
"""

import sys
import os
import re
from datetime import datetime
from collections import defaultdict

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from update import WrestlingDatabase

# =============================================================================
# CONSTANTS  — tweak these to tune behaviour
# =============================================================================

WEIGHT_ORDER = ['heavyweight', 'bridgerweight', 'middleweight',
                'welterweight', 'lightweight', 'featherweight']
MAJOR_ORGS   = {'wwf', 'wwo', 'iwb'}
ALL_ORGS     = {'wwf', 'wwo', 'iwb', 'ring'}

# Path to the wiki/org page that contains the #open Open Tournament table
OPEN_WIKI_PATH = 'wrestling/wiki.html'   # adjust if your file is named differently

# Scoring weight for winning The Open in a given year
# This is the biggest single-year achievement — near-guaranteed WOTY
OPEN_WIN_YEARLY_BONUS  = 60   # added directly to year_score (0-100 scale)
OPEN_WIN_GOAT_TITLE_PTS = 40  # championship points per Open win (for GOAT score)

MENS_P4P_START   = 1963
WOMENS_P4P_START = 1980

# Minimum career requirements to appear in a yearly P4P table
P4P_MIN_BOUTS        = 3   # career bouts
P4P_MIN_CAREER_WINS  = 2   # career wins (stops 1-fight title holders from ranking)

# HoF criteria — deliberately strict
HOF_MAX_PER_YEAR     = 3     # max inductees per class (keeps it exclusive)
HOF_MIN_WINS         = 18    # career wins required
HOF_MIN_WIN_PCT      = 0.75  # 68%+ win rate required
HOF_MIN_SCORE        = 45.0  # GOAT score required
HOF_RETIREMENT_YEARS = 5     # years inactive before eligible
HOF_REQUIRE_MAJOR    = True  # must hold a MAJOR title (wwf/wwo/iwb), ring alone doesn't count

# Voter fatigue — diminishing returns for years at peak
# A wrestler who dominates for 8 years doesn't get 8x the credit of one who dominated for 4.
# Each year in the top 3 beyond this cap contributes at half weight to their GOAT score.
HOF_VOTER_FATIGUE_CAP = 6   # full-credit years in top 3; beyond this → diminishing


# =============================================================================
# DATE HELPERS
# =============================================================================

def _parse_date(s):
    if not s:
        return None
    for fmt in ("%B %d, %Y", "%B %Y"):
        try:
            return datetime.strptime(s.strip(), fmt)
        except ValueError:
            pass
    return None

def _year_of(s):
    d = _parse_date(s)
    return d.year if d else 0

def _match_year(m):
    return _year_of(m.get('date', ''))


# =============================================================================
# INFOBOX HEIGHT READER
# =============================================================================

def read_infobox_height(name):
    """Read 'Billed height' from wrestler's HTML infobox. Returns string or ''."""
    filename = name.lower().replace(' ', '-').replace('.', '')
    filepath = f'wrestling/wrestlers/{filename}.html'
    if not os.path.exists(filepath):
        return ''
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()
    m = re.search(r'<th>Billed height</th>\s*<td>([^<]+)</td>', content)
    return m.group(1).strip() if m else ''


# =============================================================================
# OPEN TOURNAMENT PARSER
# =============================================================================

def parse_open_tournament(wiki_path=None):
    """
    Parse The Open Tournament table from the wiki/org page.
    Returns dict: {year: {'winner': name, 'runner_up': name}}
    Each year is a separate entry — winning in different years = separate titles.

    Looks for <h2 id="open"> then reads the first <table class="match-card"> after it.
    Strips flag spans to get plain name text.
    """
    path = wiki_path or OPEN_WIKI_PATH
    if not os.path.exists(path):
        print(f"  ⚠ Open Tournament: {path} not found, skipping")
        return {}

    with open(path, 'r', encoding='utf-8') as f:
        html = f.read()

    # Find the #open section
    open_idx = html.find('id="open"')
    if open_idx == -1:
        open_idx = html.find("id='open'")
    if open_idx == -1:
        print("  ⚠ Open Tournament: #open anchor not found in wiki page")
        return {}

    # Find the next match-card table after that point
    table_start = html.find('<table', open_idx)
    table_end   = html.find('</table>', table_start) + len('</table>')
    if table_start == -1:
        print("  ⚠ Open Tournament: table not found after #open")
        return {}

    table_html = html[table_start:table_end]

    # Parse rows — each <tr> in <tbody>
    results = {}
    tbody_m = re.search(r'<tbody>(.*?)</tbody>', table_html, re.DOTALL)
    if not tbody_m:
        return {}

    for row in re.finditer(r'<tr>(.*?)</tr>', tbody_m.group(1), re.DOTALL):
        cells = re.findall(r'<t[dh]>(.*?)</t[dh]>', row.group(1), re.DOTALL)
        if len(cells) < 3:
            continue

        # Strip HTML tags (flags etc) to get plain text
        def strip_tags(s):
            return re.sub(r'<[^>]+>', '', s).strip()

        try:
            year    = int(strip_tags(cells[0]))   # No. or Year — we want the year column
        except ValueError:
            continue

        # The table has: No. | Year | Winner | Runner-Up | Venue | Location
        # But No. is <th> so cells[0]=No, cells[1]=Year, cells[2]=Winner, cells[3]=Runner-Up
        # Re-parse including th
        all_cells = re.findall(r'<(?:td|th)>(.*?)</(?:td|th)>', row.group(1), re.DOTALL)
        if len(all_cells) < 4:
            continue
        try:
            year = int(strip_tags(all_cells[1]))
        except ValueError:
            continue

        winner    = strip_tags(all_cells[2])
        runner_up = strip_tags(all_cells[3])
        if winner:
            results[year] = {'winner': winner, 'runner_up': runner_up}

    print(f"  Open Tournament: parsed {len(results)} editions "
          f"({min(results) if results else '?'}–{max(results) if results else '?'})")
    return results


# =============================================================================
# PRE-COMPUTE CACHES  (called once)
# =============================================================================

def build_caches(db):
    cache = {}

    # match_results: name → sorted [(year, result, method, match_dict)]
    match_results = defaultdict(list)
    for name, w in db.wrestlers.items():
        for m in w['matches']:
            y = _match_year(m)
            match_results[name].append((y, m['result'], m.get('method', ''), m))
        match_results[name].sort(key=lambda x: x[0])
    cache['match_results'] = match_results

    def cumulative_record(name, up_to_year):
        wins = losses = draws = 0
        for (year, result, method, _) in match_results[name]:
            if year > up_to_year:
                break
            if result == 'Win':    wins += 1
            elif result == 'Loss': losses += 1
            elif result == 'Draw': draws += 1
        return wins, losses, draws
    cache['cumulative_record'] = cumulative_record

    # champ_years: name → set of years they held any title (for opponent rating)
    champ_years = defaultdict(set)
    for org in ALL_ORGS:
        for weight in WEIGHT_ORDER:
            for reign in db.championships[org][weight]:
                champ = reign['champion']
                start = _year_of(reign['date'])
                days  = reign.get('days') or 0
                if start:
                    end_year = start + max(days // 365, 0)
                    for y in range(start, end_year + 1):
                        champ_years[champ].add(y)
    cache['champ_years'] = champ_years

    # all_years: sorted list of years that have events
    all_years = sorted({_year_of(e.get('date', '')) for e in db.events} - {0})
    cache['all_years'] = all_years

    # gender sets: women = fought ≥1 match at lightweight or featherweight
    women = set()
    for name, w in db.wrestlers.items():
        for m in w['matches']:
            wc = m.get('weight_class', '').lower()
            if 'lightweight' in wc or 'featherweight' in wc:
                women.add(name)
                break
    men = set(db.wrestlers.keys()) - women
    cache['women'] = women
    cache['men']   = men

    # open_wins: name → sorted list of years they won The Open Tournament
    # parsed fresh each run from the wiki page
    open_data = parse_open_tournament()
    open_wins = defaultdict(list)   # name → [year, year, ...]
    for year, entry in open_data.items():
        open_wins[entry['winner']].append(year)
    for name in open_wins:
        open_wins[name].sort()
    cache['open_wins'] = open_wins
    cache['open_data'] = open_data   # {year: {winner, runner_up}}

    print(f"  Cache built: {len(db.wrestlers)} wrestlers, "
          f"{len(all_years)} years "
          f"({min(all_years) if all_years else '?'}–{max(all_years) if all_years else '?'}), "
          f"{len(men)} men, {len(women)} women, "
          f"{sum(len(v) for v in open_wins.values())} Open Tournament wins tracked")
    return cache


# =============================================================================
# OPPONENT RATING  (fast via cache)
# =============================================================================

def opponent_rating(db, cache, opp_name, fight_year):
    """Rate an opponent 5–100 based on their record and title history at fight_year."""
    w = db.wrestlers.get(opp_name)
    if not w:
        return 5

    wins, losses, draws = cache['cumulative_record'](opp_name, fight_year)
    total   = wins + losses
    win_pct = wins / total if total else 0

    cy = cache['champ_years'][opp_name]
    was_champ = bool(cy and any(y <= fight_year for y in cy))

    if was_champ:
        return min(80 + win_pct * 20, 100)
    elif win_pct >= 0.70 and total >= 5:
        return 60 + win_pct * 19
    elif win_pct >= 0.50 and total >= 3:
        return 40 + win_pct * 19
    elif win_pct >= 0.40:
        return 20 + win_pct * 19
    else:
        return max(5, win_pct * 19)


_DECAY = [1.0, 0.85, 0.70, 0.55, 0.40]

def freshness(years_back):
    return _DECAY[min(years_back, 4)]


# =============================================================================
# CORE P4P SCORE
# =============================================================================

def compute_score(db, cache, name, ranking_year, goat_mode=False):
    """
    Float P4P score for `name`.

    goat_mode=True  → all-time GOAT: cumulative career stats, no recency/activity.
    goat_mode=False → yearly WOTY:   70% what you did THIS year, 30% career prestige.
                      This means Inoki going 2-0 beating champions beats Santo going
                      1-1 even if Santo has the better career record.
    """
    w = db.wrestlers.get(name)
    if not w:
        return 0.0

    results = cache['match_results'][name]
    matches_to_date = [(y, res, meth, m) for (y, res, meth, m) in results if y <= ranking_year]
    if not matches_to_date:
        return 0.0

    this_year_matches = [(y, res, meth, m) for (y, res, meth, m) in results if y == ranking_year]

    # ── GOAT MODE: pure career cumulative ────────────────────────────────
    if goat_mode:
        # Quality wins: all career wins with no decay
        qw_total = 0.0
        for (fight_year, result, method, m) in matches_to_date:
            if result != 'Win':
                continue
            opp  = m['fighter2'] if m['fighter1'] == name else m['fighter1']
            base = opponent_rating(db, cache, opp, fight_year)
            mult = 1.2 if ('pinfall' in method.lower() or 'submission' in method.lower()) else 1.0
            qw_total += base * mult
        n = max(len(matches_to_date), 1)
        quality_wins_score = min(qw_total / (100 * min(n, 30)), 1.0) * 100

        wins   = sum(1 for (y, r, *_) in matches_to_date if r == 'Win')
        losses = sum(1 for (y, r, *_) in matches_to_date if r == 'Loss')
        draws  = sum(1 for (y, r, *_) in matches_to_date if r == 'Draw')
        total  = wins + losses + 0.5 * draws
        win_pct = wins / total if total else 0
        cur = streak = 0
        for (y, r, *_) in matches_to_date:
            cur = (cur + 1) if r == 'Win' else 0
            streak = max(streak, cur)
        max_def = max(
            (reign.get('defenses', 0)
             for org in ALL_ORGS for weight in WEIGHT_ORDER
             for reign in db.championships[org][weight]
             if reign['champion'] == name and _year_of(reign['date']) <= ranking_year),
            default=0
        )
        dominance_score = min(win_pct * 70 + min(streak * 2, 20) + min(max_def * 5, 30), 100)

        title_pts = total_days = longest_reign = 0
        for org in ALL_ORGS:
            for weight in WEIGHT_ORDER:
                reigns = db.championships[org][weight]
                for i, reign in enumerate(reigns):
                    if reign['champion'] != name: continue
                    if not _year_of(reign['date']) or _year_of(reign['date']) > ranking_year: continue
                    title_pts += 25 if org == 'ring' else (30 if org in MAJOR_ORGS else 10)
                    days = reign.get('days') or 0
                    total_days += days; longest_reign = max(longest_reign, days)
        is_current_champ = any(
            reign['champion'] == name and i == len(db.championships[org][weight]) - 1
            and 'vacancy_message' not in reign
            for org in ALL_ORGS for weight in WEIGHT_ORDER
            for i, reign in enumerate(db.championships[org][weight])
        )
        championship_score = min(
            min(title_pts, 85) + (20 if is_current_champ else 0)
            + min(total_days / 365, 3) * 10 + min(longest_reign / 365, 2) * 5, 100
        )
        draw_score = min(w.get('main_events', 0) * 20, 100)

        # Open Tournament wins — each year won = OPEN_WIN_GOAT_TITLE_PTS prestige
        # Capped at 3 wins worth to prevent runaway stacking
        open_win_years = [y for y in cache['open_wins'].get(name, []) if y <= ranking_year]
        open_bonus = min(len(open_win_years) * OPEN_WIN_GOAT_TITLE_PTS, OPEN_WIN_GOAT_TITLE_PTS * 3)
        championship_score_with_open = min(championship_score + open_bonus, 100)

        return round(
            quality_wins_score          * 0.40 +
            dominance_score             * 0.25 +
            championship_score_with_open * 0.25 +
            draw_score                  * 0.10,
            4
        )

    # ── YEARLY MODE: 70% this year's performance + 30% career prestige ───
    #
    # THIS YEAR component (scored 0-100 each):
    #   - Year quality wins: wins this year against quality opponents
    #   - Year dominance:    win% this year + being champion this year
    #   - Year activity:     fought at all, fought champions, defended titles
    #
    # CAREER PRESTIGE component (scored 0-100):
    #   - Career championship score (titles held, days, prestige)
    #   - This prevents a complete nobody from outranking Santo on one fluke win,
    #     but caps at 30% so a great year always beats a mediocre year.

    # ── YEAR quality wins ─────────────────────────────────────────────────
    yr_qw = 0.0
    for (fight_year, result, method, m) in this_year_matches:
        if result != 'Win':
            continue
        opp  = m['fighter2'] if m['fighter1'] == name else m['fighter1']
        base = opponent_rating(db, cache, opp, fight_year)
        mult = 1.2 if ('pinfall' in method.lower() or 'submission' in method.lower()) else 1.0
        yr_qw += base * mult
    yr_n = max(len(this_year_matches), 1)
    yr_quality_score = min(yr_qw / (100 * min(yr_n, 10)), 1.0) * 100

    # ── YEAR dominance ────────────────────────────────────────────────────
    yr_wins   = sum(1 for (_, r, *_) in this_year_matches if r == 'Win')
    yr_losses = sum(1 for (_, r, *_) in this_year_matches if r == 'Loss')
    yr_draws  = sum(1 for (_, r, *_) in this_year_matches if r == 'Draw')
    yr_total  = yr_wins + yr_losses + 0.5 * yr_draws
    yr_winpct = yr_wins / yr_total if yr_total else 0

    # Title at stake this year
    held_title_this_year = bool(cache['champ_years'][name] & {ranking_year})
    yr_dom_score = min(yr_winpct * 60 + (30 if held_title_this_year else 0)
                       + min(yr_wins * 5, 10), 100)

    # ── YEAR activity ─────────────────────────────────────────────────────
    fought_champ_yr = any(
        opponent_rating(db, cache,
                        m['fighter2'] if m['fighter1'] == name else m['fighter1'],
                        ranking_year) >= 80
        for (_, _, _, m) in this_year_matches
    )
    defended_yr = held_title_this_year and yr_wins > 0
    yr_activity = min(
        len(this_year_matches) * 12 +
        (35 if fought_champ_yr else 0) +
        (20 if defended_yr else 0),
        100
    )

    # ── YEAR composite (0-100) ────────────────────────────────────────────
    year_score = (yr_quality_score * 0.45 +
                  yr_dom_score     * 0.35 +
                  yr_activity      * 0.20)

    # ── CAREER PRESTIGE (0-100, used at 30% weight) ───────────────────────
    title_pts = total_days = longest_reign = 0
    for org in ALL_ORGS:
        for weight in WEIGHT_ORDER:
            reigns = db.championships[org][weight]
            for i, reign in enumerate(reigns):
                if reign['champion'] != name: continue
                if not _year_of(reign['date']) or _year_of(reign['date']) > ranking_year: continue
                title_pts += 25 if org == 'ring' else (30 if org in MAJOR_ORGS else 10)
                days = reign.get('days') or 0
                total_days += days; longest_reign = max(longest_reign, days)
    career_prestige = min(
        min(title_pts, 85) +
        min(total_days / 365, 3) * 10 +
        min(longest_reign / 365, 2) * 5,
        100
    )

    # ── OPEN TOURNAMENT BONUS ─────────────────────────────────────────────
    # Winning The Open this year is the biggest single achievement possible.
    # It bypasses the year_score formula and adds a flat bonus directly,
    # making the winner almost certainly WOTY unless someone had a truly
    # exceptional regular-season year (multiple title defenses vs champions).
    won_open_this_year = ranking_year in cache['open_wins'].get(name, [])
    open_yearly_bonus  = OPEN_WIN_YEARLY_BONUS if won_open_this_year else 0

    # ── FINAL: 70% year + 30% career prestige + Open bonus ───────────────
    raw = year_score * 0.70 + career_prestige * 0.30 + open_yearly_bonus

    # Recency: slight penalty if they didn't fight this year (ranked on prior year)
    if not this_year_matches and not won_open_this_year:
        last_fight = max((y for (y, *_) in results), default=0)
        inactive   = max(ranking_year - last_fight, 0)
        raw *= max(1.0 - inactive * 0.20, 0.5)

    return round(raw, 4)


# =============================================================================
# VOTER FATIGUE ADJUSTED GOAT SCORE
# =============================================================================

def compute_goat_with_fatigue(db, cache, name, current_year):
    """
    For GOAT rankings: raw score, no voter fatigue penalty.
    Santo winning #1 eight times IS the argument for him being GOAT.
    Voter fatigue only makes sense for yearly awards, not all-time lists.
    """
    return compute_score(db, cache, name, current_year, goat_mode=True)


# =============================================================================
# TITLES HELPERS
# =============================================================================

def titles_at_year(db, name, year, cache=None):
    """
    Full title list held during `year`. Includes Open Tournament win if cache provided.
    """
    parts = []
    for org in ['wwf', 'wwo', 'iwb', 'ring']:
        for weight in WEIGHT_ORDER:
            reigns = db.championships[org][weight]
            for i, reign in enumerate(reigns):
                if reign['champion'] != name:
                    continue
                reign_year = _year_of(reign['date'])
                if not reign_year or reign_year > year:
                    continue
                end_year = (
                    _year_of(reigns[i+1]['date']) if i < len(reigns) - 1
                    else _year_of(reign.get('vacancy_date', '')) or 9999
                )
                if end_year < year:
                    continue
                label = '<i>The Ring</i>' if org == 'ring' else org.upper()
                txt = f"{label} {weight.capitalize()}"
                if txt not in parts:
                    parts.append(txt)
    if cache and year in cache['open_wins'].get(name, []):
        parts.append("The Open")
    return ' <br> '.join(parts)


def all_titles_str(db, name, cache=None):
    """
    Full career championship list. Includes Open Tournament wins if cache provided.
    Format: 'WWF Heavyweight <br> The Open (1972, 1976)'
    """
    parts = []
    for org in ['wwf', 'wwo', 'iwb', 'ring']:
        for weight in WEIGHT_ORDER:
            reigns = [r for r in db.championships[org][weight] if r['champion'] == name]
            if not reigns:
                continue
            label = '<i>The Ring</i>' if org == 'ring' else org.upper()
            txt   = f"{label} {weight.capitalize()}"
            if len(reigns) > 1:
                txt += f" ({len(reigns)}x)"
            parts.append(txt)
    if cache:
        wins = cache['open_wins'].get(name, [])
        if wins:
            parts.append(f"The Open ({', '.join(str(y) for y in wins)})")
    return ' <br> '.join(parts)


# =============================================================================
# YEARLY RANKINGS
# =============================================================================

def rank_for_year(db, cache, year, gender_set, top_n=10):
    """
    Top-N wrestlers for a given year within gender_set.
    Strict eligibility: ppv wrestler, active within 2 years,
    ≥ P4P_MIN_BOUTS career bouts, ≥ P4P_MIN_CAREER_WINS career wins.
    Returns list of (name, score, record, primary_weight, titles).
    """
    results = []
    for name in gender_set:
        if name not in db.ppv_wrestlers:
            continue
        mr = cache['match_results'][name]

        matches_to_year = [(y, r, meth, m) for (y, r, meth, m) in mr if y <= year]
        if not matches_to_year:
            continue

        last_fight = max((y for (y, *_) in mr), default=0)
        if last_fight < year - 2:
            continue

        wins_to_year  = sum(1 for (y, r, *_) in matches_to_year if r == 'Win')
        total_to_year = len(matches_to_year)
        # Open Tournament winners are always eligible regardless of bout count
        won_open = year in cache['open_wins'].get(name, [])
        if not won_open:
            if total_to_year < P4P_MIN_BOUTS:
                continue
            if wins_to_year < P4P_MIN_CAREER_WINS:
                continue

        score = compute_score(db, cache, name, year)
        if score <= 0:
            continue

        wins, losses, draws = cache['cumulative_record'](name, year)
        record = f"{wins}-{losses}-{draws}"

        # Record for this year only
        this_year_m = [(y2, r2, meth2, m2) for (y2, r2, meth2, m2) in mr if y2 == year]
        yr_w = sum(1 for (_, r2, *_) in this_year_m if r2 == 'Win')
        yr_l = sum(1 for (_, r2, *_) in this_year_m if r2 == 'Loss')
        yr_d = sum(1 for (_, r2, *_) in this_year_m if r2 == 'Draw')
        year_record = f"{yr_w}-{yr_l}-{yr_d}" if this_year_m else "\u2014"

        wc_count = defaultdict(int)
        for (y2, r2, meth2, m2) in matches_to_year:
            wc_count[m2.get('weight_class', 'Unknown')] += 1
        primary = max(wc_count, key=wc_count.get) if wc_count else 'Unknown'

        titles = titles_at_year(db, name, year, cache)
        results.append((name, score, record, year_record, primary, titles))

    results.sort(key=lambda x: x[1], reverse=True)
    return results[:top_n]


# =============================================================================
# HTML GENERATION
# =============================================================================

def flag(country):
    return f'<span class="fi fi-{country}"></span>'


def p4p_table(db, year, gender_label, rankings):
    if not rankings:
        return ''
    html  = f'    <!-- {year} {gender_label} P4P -->\n'
    html += '    <details>\n'
    html += f"    <summary>{year} {gender_label}'s <i>The Ring</i> P4P Rankings</summary>\n"
    html += '    <table style="width: 65%;" class="p4p">\n'
    html += '        <tbody><tr>\n'
    html += f'            <th>Rank</th><th>Wrestler</th><th>Career Record</th>'
    html += f'<th>{year} Record</th><th>Titles</th>\n'
    html += '        </tr>\n'
    for rank, (name, score, record, year_record, weight, titles) in enumerate(rankings, 1):
        country   = db.wrestlers[name]['country']
        titles_td = f'<td>{titles}</td>' if titles else '<th></th>'
        html += '        <tr>\n'
        html += f'            <th>{rank}</th>\n'
        html += f'            <td>{flag(country)} {name}</td>\n'
        html += f'            <td>{record}</td>\n'
        html += f'            <td>{year_record}</td>\n'
        html += f'            {titles_td}\n'
        html += '        </tr>\n'
    html += '    </tbody></table>\n    </details>\n\n'
    return html


def generate_p4p_html(db, cache):
    men   = cache['men']
    women = cache['women']
    years = cache['all_years']
    current_year = max(years) if years else datetime.now().year

    html = ''

    # All-time GOAT tables (with voter fatigue)
    for gender_label, gset in [("Men", men), ("Women", women)]:
        goat = []
        for name in gset:
            if name not in db.ppv_wrestlers:
                continue
            w = db.wrestlers[name]
            if w['wins'] + w['losses'] + w['draws'] < P4P_MIN_BOUTS:
                continue
            if w['wins'] < P4P_MIN_CAREER_WINS:
                continue
            score = compute_goat_with_fatigue(db, cache, name, current_year)
            if score > 0:
                record = f"{w['wins']}-{w['losses']}-{w['draws']}"
                goat.append((name, score, record))

        goat.sort(key=lambda x: x[1], reverse=True)
        goat = goat[:25]
        if not goat:
            continue

        html += f'    <!-- All-Time {gender_label} GOAT -->\n'
        html += '    <details>\n'
        html += f"    <summary>All-Time {gender_label}'s <i>The Ring</i> P4P GOAT Rankings</summary>\n"
        html += '    <table style="width: 65%;" class="p4p">\n'
        html += '        <tbody><tr>\n'
        html += '            <th>Rank</th><th>Wrestler</th><th>Record</th>'
        html += '<th>Score</th><th>Titles</th>\n'
        html += '        </tr>\n'
        for rank, (name, score, record) in enumerate(goat, 1):
            country   = db.wrestlers[name]['country']
            titles    = all_titles_str(db, name, cache)
            titles_td = f'<td>{titles}</td>' if titles else '<th></th>'
            html += '        <tr>\n'
            html += f'            <th>{rank}</th>\n'
            html += f'            <td>{flag(country)} {name}</td>\n'
            html += f'            <td>{record}</td>\n'
            html += f'            <td>{score:.1f}</td>\n'
            html += f'            {titles_td}\n'
            html += '        </tr>\n'
        html += '    </tbody></table>\n    </details>\n\n'

    # Yearly tables, newest first
    for year in reversed(years):
        if year >= MENS_P4P_START:
            html += p4p_table(db, year, "Men", rank_for_year(db, cache, year, men))
        if year >= WOMENS_P4P_START:
            html += p4p_table(db, year, "Women", rank_for_year(db, cache, year, women))

    return html


# =============================================================================
# HALL OF FAME
# =============================================================================

def hof_eligible(db, cache, induction_year, already_inducted):
    eligible = []

    for name, w in db.wrestlers.items():
        if name in already_inducted:
            continue
        if name not in db.ppv_wrestlers:
            continue

        total = w['wins'] + w['losses'] + w['draws']
        if total == 0:
            continue

        # Retirement check
        mr = cache['match_results'][name]
        last_fight = max((y for (y, *_) in mr), default=0)
        if last_fight > induction_year - HOF_RETIREMENT_YEARS:
            continue

        # Win count
        if w['wins'] < HOF_MIN_WINS:
            continue

        # Win percentage
        if w['wins'] / total < HOF_MIN_WIN_PCT:
            continue

        # Must hold a MAJOR world title
        if HOF_REQUIRE_MAJOR:
            held_major = any(
                reign['champion'] == name
                for org in MAJOR_ORGS
                for weight in WEIGHT_ORDER
                for reign in db.championships[org][weight]
            )
            if not held_major:
                continue

        # GOAT score threshold
        score = compute_score(db, cache, name, induction_year, goat_mode=True)
        if score < HOF_MIN_SCORE:
            continue

        eligible.append((name, score))

    eligible.sort(key=lambda x: x[1], reverse=True)
    return eligible


def compute_hof_classes(db, cache):
    years = cache['all_years']
    if not years:
        return {}, set()

    first_year = min(years) + HOF_RETIREMENT_YEARS + 1
    last_year  = max(years)

    hof_classes      = {}
    already_inducted = set()

    for year in range(first_year, last_year + 1):
        elig      = hof_eligible(db, cache, year, already_inducted)
        inductees = elig[:HOF_MAX_PER_YEAR]
        if inductees:
            hof_classes[year] = [n for n, _ in inductees]
            already_inducted.update(n for n, _ in inductees)

    return hof_classes, already_inducted


def hof_activity_str(db, cache, name):
    mr = cache['match_results'][name]
    if not mr:
        return ''
    return f"Debut: {mr[0][3].get('date', '')} <br> Retired: {mr[-1][3].get('date', '')}"


def generate_hof_html(db, cache):
    hof_classes, _ = compute_hof_classes(db, cache)

    html  = '    <!-- List of PWHOF Members -->\n'
    html += '    <table class="hof-history">\n'
    html += '    <tr>\n'
    html += '        <th>No.</th><th>Class</th><th>Ring name</th>'
    html += '<th>Record</th><th>Height</th><th>Titles</th>'
    html += '<th>Highest Ranking</th><th>Activity</th>\n'
    html += '    </tr>\n'

    row_num = 1
    for year in sorted(hof_classes.keys()):
        for name in hof_classes[year]:
            w = db.wrestlers.get(name)
            if not w:
                continue
            record   = f"{w['wins']}-{w['losses']}-{w['draws']}"
            titles   = all_titles_str(db, name, cache)
            ranking  = compute_highest_ranking(db, cache, name)
            activity = hof_activity_str(db, cache, name)
            country  = w['country']
            height   = read_infobox_height(name)

            html += '    <tr>\n'
            html += f'        <th>{row_num}</th>\n'
            html += f'        <td>Class of {year}</td>\n'
            html += f'        <td>{flag(country)} {name}</td>\n'
            html += f'        <td>{record}</td>\n'
            html += f'        <td>{height}</td>\n' if height else '        <th></th>\n'
            html += f'        <td>{titles}</td>\n' if titles else '        <th></th>\n'
            html += f'        <td>{ranking}</td>\n' if ranking else '        <th></th>\n'
            html += f'        <td>{activity}</td>\n'
            html += '    </tr>\n'
            row_num += 1

    html += '    </table>\n\n'
    html += '    <p>†: In-Ring Death.</p>\n'
    return html


# =============================================================================
# HIGHEST RANKING
# =============================================================================

def compute_highest_ranking(db, cache, name):
    """Return 'No. X (YEAR, YEAR)' or '' if never ranked."""
    men   = cache['men']
    women = cache['women']
    years = cache['all_years']

    best_rank  = None
    best_years = []

    checks = []
    if name in men:
        checks.append((men, MENS_P4P_START))
    if name in women:
        checks.append((women, WOMENS_P4P_START))

    for (gset, start_year) in checks:
        for year in years:
            if year < start_year:
                continue
            rankings = rank_for_year(db, cache, year, gset)
            for rank_idx, (n, *_) in enumerate(rankings, 1):
                if n == name:
                    if best_rank is None or rank_idx < best_rank:
                        best_rank  = rank_idx
                        best_years = [year]
                    elif rank_idx == best_rank and year not in best_years:
                        best_years.append(year)
                    break

    if best_rank is None:
        return ''
    return f"No. {best_rank} ({', '.join(str(y) for y in sorted(best_years))})"


# =============================================================================
# INFOBOX UPDATER
# =============================================================================

def update_infoboxes(db, cache):
    wrestlers_dir = 'wrestling/wrestlers'
    if not os.path.exists(wrestlers_dir):
        print("  ⚠ wrestling/wrestlers/ not found, skipping infobox update")
        return

    updated = 0
    for name in db.ppv_wrestlers:
        w = db.wrestlers.get(name)
        if not w:
            continue
        filename = name.lower().replace(' ', '-').replace('.', '')
        filepath = f'{wrestlers_dir}/{filename}.html'
        if not os.path.exists(filepath):
            continue

        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()

        if '<th>Record</th>' not in content and '<th>Career Record</th>' not in content:
            continue

        record  = f"{w['wins']}-{w['losses']}-{w['draws']}"
        highest = compute_highest_ranking(db, cache, name)

        # Rename Record → Career Record and update value
        content = re.sub(
            r'<th>Record</th>(\s*<td>)[^<]*(</td>)',
            r'<th>Career Record</th>\g<1>' + record + r'\g<2>',
            content
        )
        content = re.sub(
            r'(<th>Career Record</th>\s*<td>)[^<]*(</td>)',
            r'\g<1>' + record + r'\g<2>',
            content
        )

        # Normalise old label name if present
        content = content.replace('<th>Highest P4P Ranking</th>', '<th>Highest Ranking</th>')

        ranking_row = (
            '\n                <tr>\n'
            '                    <th>Highest Ranking</th>\n'
            f'                    <td>{highest}</td>\n'
            '                </tr>'
        )

        if '<th>Highest Ranking</th>' in content:
            if highest:
                content = re.sub(
                    r'(<th>Highest Ranking</th>\s*<td>)[^<]*(</td>)',
                    r'\g<1>' + highest + r'\g<2>',
                    content
                )
            else:
                content = re.sub(
                    r'\s*<tr>\s*<th>Highest Ranking</th>.*?</tr>',
                    '', content, flags=re.DOTALL
                )
        elif highest:
            content = re.sub(
                r'(<th>Career Record</th>\s*<td>[^<]*</td>\s*</tr>)',
                r'\g<1>' + ranking_row,
                content
            )

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        updated += 1

    print(f"✓ Infoboxes updated: {updated} files")


# =============================================================================
# FILE UPDATERS
# =============================================================================

def update_ring(db, cache):
    path  = 'wrestling/org/ring.html'
    START = '<!-- P4Prankings_START -->'
    END   = '<!-- P4Prankings_END -->'

    if not os.path.exists(path):
        print(f"  ⚠ {path} not found"); return

    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    if START not in content or END not in content:
        print(f"  ⚠ Markers not found in {path}")
        print(f"    Add {START} and {END} around your P4P <details> blocks")
        return

    p4p_html = generate_p4p_html(db, cache)
    content  = content.split(START)[0] + START + '\n' + p4p_html + END + content.split(END)[1]

    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✓ Updated P4P rankings in {path}")


def update_hof(db, cache):
    path  = 'wrestling/org/pwhof.html'
    START = '<!-- HOFMEMBERS_START -->'
    END   = '<!-- HOFMEMBERS_END -->'

    if not os.path.exists(path):
        print(f"  ⚠ {path} not found"); return

    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()

    if START not in content or END not in content:
        print(f"  ⚠ Markers not found in {path}")
        print(f"    Add {START} and {END} around your HoF table")
        return

    hof_html = generate_hof_html(db, cache)
    content  = content.split(START)[0] + START + '\n' + hof_html + END + content.split(END)[1]

    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"✓ Updated HoF in {path}")


# =============================================================================
# MAIN
# =============================================================================

def main():
    site_root = os.path.dirname(SCRIPT_DIR)
    os.chdir(site_root)
    print(f"Working directory: {os.getcwd()}")

    print("Loading wrestling data...")
    db = WrestlingDatabase()
    db.parse_events('wrestling/ppv/list.html', is_weekly=False)

    weekly_path = 'wrestling/weekly/list.html'
    if os.path.exists(weekly_path):
        db.parse_events(weekly_path, is_weekly=True)

    db.events.sort(key=lambda e: _parse_date(e.get('date')) or datetime.min)
    db.reprocess_championships_chronologically()
    db.recalculate_bio_notes()
    db.process_vacancies()
    db.calculate_championship_days()
    print(f"  Loaded {len(db.wrestlers)} wrestlers, {len(db.events)} events")

    print("Building caches...")
    cache = build_caches(db)

    print("Updating ring.html (P4P rankings)...")
    update_ring(db, cache)

    print("Updating pwhof.html (Hall of Fame)...")
    update_hof(db, cache)

    print("Updating wrestler infoboxes...")
    update_infoboxes(db, cache)

    print("\n✓ Done! Review changes then git add . && git commit && git push")


if __name__ == '__main__':
    main()