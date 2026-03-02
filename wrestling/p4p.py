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
# CONSTANTS
# =============================================================================

# Deterministic iteration order — tuples, NOT sets.
WEIGHT_ORDER = ('heavyweight', 'bridgerweight', 'middleweight',
                'welterweight', 'lightweight', 'featherweight')
ALL_ORGS     = ('wwf', 'wwo', 'iwb', 'ring')
MAJOR_ORGS   = ('wwf', 'wwo', 'iwb')

# Open Tournament scoring
OPEN_WIN_YEARLY_BONUS   = 60   # added to year_score (0-100 scale)
OPEN_WIN_GOAT_TITLE_PTS = 40   # championship pts per Open win (GOAT mode)

# Trios Tournament scoring (GOAT only — no yearly P4P bonus)
TRIOS_WIN_GOAT_TITLE_PTS = 25  # championship pts per Trios win (GOAT mode)

# P4P start years
MENS_P4P_START   = 1963
WOMENS_P4P_START = 1980

# Eligibility thresholds
P4P_MIN_BOUTS       = 3
P4P_MIN_CAREER_WINS = 2

# Quality score normalization ceiling (yearly mode)
WOTY_MAX_WINS = 3

# Title prestige bonuses
TITLE_PRESTIGE = {
    ('wwo', 'middleweight'): 10,
    ('wwf', 'heavyweight'):  10,
}

# Low-volume penalty
LOW_VOLUME_THRESHOLD = 1
LOW_VOLUME_MULT      = 0.85

# Voter fatigue cap for yearly WOTY
WOTY_MAX_TIMES = 5

# Hall of Fame criteria
HOF_MAX_PER_YEAR     = 3
HOF_MIN_WINS         = 15
HOF_MIN_WIN_PCT      = 0.68
HOF_MIN_SCORE        = 45.0
HOF_RETIREMENT_YEARS = 5
HOF_REQUIRE_MAJOR    = True
HOF_VOTER_FATIGUE_CAP = 5


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
    """Read 'Billed height' from wrestler's HTML infobox."""
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

def parse_open_tournament_from_db(db):
    """
    Derive Open Tournament winners from match data.
    Returns dict: {(year, gender): {'winner', 'runner_up', 'gender'}}
    """
    results = {}
    for event in db.events:
        for match in event.get('matches', []):
            notes = match.get('notes', '')
            if 'open tournament finals' not in notes.lower():
                continue
            if not match.get('winner'):
                continue
            d = _parse_date(match.get('date', ''))
            if not d:
                continue
            runner_up = (match['fighter2'] if match['winner'] == match['fighter1']
                         else match['fighter1'])
            nl = notes.lower()
            gender = 'women' if 'women' in nl else 'men'
            results[(d.year, gender)] = {
                'winner': match['winner'],
                'runner_up': runner_up,
                'gender': gender,
            }
    if results:
        years = [k[0] for k in results]
        print(f"  Open Tournament: found {len(results)} winners from PPV data "
              f"({min(years)}\u2013{max(years)})")
    return results


# =============================================================================
# CACHE BUILDER
# =============================================================================

def build_caches(db):
    cache = {}

    # match_results: name → sorted [(year, result, method, match_dict)]
    match_results = defaultdict(list)
    for name in sorted(db.wrestlers):
        for m in db.wrestlers[name]['matches']:
            y = _match_year(m)
            match_results[name].append((y, m['result'], m.get('method', ''), m))
        match_results[name].sort(key=lambda x: x[0])
    cache['match_results'] = match_results

    # cumulative_record closure
    def cumulative_record(name, up_to_year):
        wins = losses = draws = 0
        for (year, result, _, _) in match_results[name]:
            if year > up_to_year:
                break
            if result == 'Win':    wins += 1
            elif result == 'Loss': losses += 1
            elif result == 'Draw': draws += 1
        return wins, losses, draws
    cache['cumulative_record'] = cumulative_record

    # champ_years: name → frozenset of years they held any title
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
    cache['champ_years'] = {k: frozenset(v) for k, v in champ_years.items()}

    # all_years: sorted list of years with events
    all_years = sorted({_year_of(e.get('date', '')) for e in db.events} - {0})
    cache['all_years'] = all_years

    # Gender classification: women = fought ≥1 match at lightweight/featherweight
    # Stored as SORTED LISTS for deterministic iteration.
    women_set = set()
    for name, w in db.wrestlers.items():
        for m in w['matches']:
            wc = m.get('weight_class', '').lower()
            if 'lightweight' in wc or 'featherweight' in wc:
                women_set.add(name)
                break
    men_set = set(db.wrestlers.keys()) - women_set
    cache['men']   = sorted(men_set)
    cache['women'] = sorted(women_set)

    # Open Tournament wins: name → sorted list of years
    open_data = parse_open_tournament_from_db(db)
    open_wins = defaultdict(list)
    for (year, gender), entry in sorted(open_data.items()):
        open_wins[entry['winner']].append(year)
    for name in open_wins:
        open_wins[name].sort()
    cache['open_wins'] = dict(open_wins)
    cache['open_data'] = open_data

    # Trios Tournament wins: name → sorted list of years
    trios_wins = defaultdict(list)
    for event in db.events:
        for mm in event.get('multi_man_matches', []):
            notes = mm.get('notes', '')
            nl = notes.lower()
            if 'trios finals' not in nl and 'trios tournament finals' not in nl:
                continue
            winners = mm.get('winners', [])
            if not winners:
                continue
            d = _parse_date(mm.get('date', ''))
            if not d:
                continue
            for f in winners:
                trios_wins[f['name']].append(d.year)
    for name in trios_wins:
        trios_wins[name].sort()
    cache['trios_wins'] = dict(trios_wins)

    n_open  = sum(len(v) for v in cache['open_wins'].values())
    n_trios = sum(len(v) for v in cache['trios_wins'].values())
    yr_lo = min(all_years) if all_years else '?'
    yr_hi = max(all_years) if all_years else '?'
    print(f"  Cache built: {len(db.wrestlers)} wrestlers, "
          f"{len(all_years)} years ({yr_lo}\u2013{yr_hi}), "
          f"{len(cache['men'])} men, {len(cache['women'])} women, "
          f"{n_open} Open Tournament wins, {n_trios} Trios Tournament wins tracked")
    return cache


# =============================================================================
# OPPONENT RATING
# =============================================================================

def opponent_rating(db, cache, opp_name, fight_year):
    """Rate an opponent 5-100 based on record and title history."""
    if opp_name not in db.wrestlers:
        return 5
    wins, losses, draws = cache['cumulative_record'](opp_name, fight_year)
    total   = wins + losses
    win_pct = wins / total if total else 0
    cy = cache['champ_years'].get(opp_name, frozenset())
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


# =============================================================================
# CORE SCORING
# =============================================================================

def _collect_reign_intervals(db, name, ranking_year):
    """
    Collect all title reign intervals overlapping ranking_year.
    Iterates ALL_ORGS × WEIGHT_ORDER in fixed tuple order for determinism.
    """
    intervals = []
    for org in ALL_ORGS:
        for weight in WEIGHT_ORDER:
            reigns = db.championships[org][weight]
            for i, reign in enumerate(reigns):
                if reign['champion'] != name:
                    continue
                ry = _year_of(reign['date'])
                if not ry or ry > ranking_year:
                    continue
                if i < len(reigns) - 1:
                    end_d    = _parse_date(reigns[i + 1]['date'])
                    end_year = _year_of(reigns[i + 1]['date'])
                elif 'vacancy_date' in reign:
                    end_d    = _parse_date(reign['vacancy_date'])
                    end_year = _year_of(reign['vacancy_date'])
                else:
                    end_d    = None
                    end_year = 9999
                if end_year < ranking_year:
                    continue
                intervals.append({
                    'win_date':   _parse_date(reign['date']),
                    'end_date':   end_d,
                    'end_year':   end_year,
                    'org':        org,
                    'weight':     weight,
                    'reign_year': ry,
                    'prestige':   TITLE_PRESTIGE.get((org, weight), 0),
                    'days':       reign.get('days') or 0,
                    'defenses':   reign.get('defenses', 0),
                })
    return intervals


def compute_score(db, cache, name, ranking_year, goat_mode=False):
    """
    P4P score for a wrestler.
    goat_mode=True  → all-time GOAT (cumulative career, no recency).
    goat_mode=False → yearly WOTY (year performance + career prestige).
    """
    w = db.wrestlers.get(name)
    if not w:
        return 0.0

    results = cache['match_results'][name]
    matches_to_date  = [(y, r, meth, m) for (y, r, meth, m) in results if y <= ranking_year]
    if not matches_to_date:
        return 0.0

    this_year_matches = [(y, r, meth, m) for (y, r, meth, m) in results if y == ranking_year]

    # ── GOAT MODE ────────────────────────────────────────────────────────
    if goat_mode:
        # Quality wins
        qw_total = 0.0
        qw_wins  = 0
        for (fy, result, method, m) in matches_to_date:
            if result != 'Win':
                continue
            opp  = m['fighter2'] if m['fighter1'] == name else m['fighter1']
            base = opponent_rating(db, cache, opp, fy)
            mult = 1.2 if ('pinfall' in method.lower() or 'submission' in method.lower()) else 1.0
            qw_total += base * mult
            qw_wins  += 1
        quality_wins_score = min(qw_total / (100 * min(max(qw_wins, 1), 30)), 1.0) * 100

        # Dominance
        wins   = sum(1 for (_, r, *_) in matches_to_date if r == 'Win')
        losses = sum(1 for (_, r, *_) in matches_to_date if r == 'Loss')
        draws  = sum(1 for (_, r, *_) in matches_to_date if r == 'Draw')
        total  = wins + losses + 0.5 * draws
        win_pct = wins / total if total else 0
        cur = streak = 0
        for (_, r, *_) in matches_to_date:
            cur = (cur + 1) if r == 'Win' else 0
            streak = max(streak, cur)
        max_def = max(
            (reign.get('defenses', 0)
             for org in ALL_ORGS for weight in WEIGHT_ORDER
             for reign in db.championships[org][weight]
             if reign['champion'] == name and _year_of(reign['date']) <= ranking_year),
            default=0,
        )
        dominance_score = min(win_pct * 70 + min(streak * 2, 20) + min(max_def * 5, 30), 100)

        # Championship score
        title_pts = total_days = longest_reign = 0
        for org in ALL_ORGS:
            for weight in WEIGHT_ORDER:
                for reign in db.championships[org][weight]:
                    if reign['champion'] != name:
                        continue
                    if not _year_of(reign['date']) or _year_of(reign['date']) > ranking_year:
                        continue
                    base = 25 if org == 'ring' else (30 if org in MAJOR_ORGS else 10)
                    title_pts += base + TITLE_PRESTIGE.get((org, weight), 0)
                    days = reign.get('days') or 0
                    total_days += days
                    longest_reign = max(longest_reign, days)
        is_current_champ = any(
            reign['champion'] == name
            and i == len(db.championships[org][weight]) - 1
            and 'vacancy_message' not in reign
            for org in ALL_ORGS for weight in WEIGHT_ORDER
            for i, reign in enumerate(db.championships[org][weight])
        )
        championship_score = min(
            min(title_pts, 85)
            + (20 if is_current_champ else 0)
            + min(total_days / 365, 3) * 10
            + min(longest_reign / 365, 2) * 5,
            100,
        )

        # Tournament bonuses (GOAT mode only)
        open_win_years = [y for y in cache['open_wins'].get(name, []) if y <= ranking_year]
        open_bonus = min(len(open_win_years) * OPEN_WIN_GOAT_TITLE_PTS,
                         OPEN_WIN_GOAT_TITLE_PTS * 3)
        trios_win_years = [y for y in cache['trios_wins'].get(name, []) if y <= ranking_year]
        trios_bonus = min(len(trios_win_years) * TRIOS_WIN_GOAT_TITLE_PTS,
                          TRIOS_WIN_GOAT_TITLE_PTS * 3)
        championship_with_tournaments = min(championship_score + open_bonus + trios_bonus, 100)

        # Draw / main-event score
        draw_score = min(w.get('main_events', 0) * 20, 100)

        return round(
            quality_wins_score              * 0.40
            + dominance_score               * 0.25
            + championship_with_tournaments * 0.25
            + draw_score                    * 0.10,
            4,
        )

    # ── YEARLY MODE ──────────────────────────────────────────────────────
    yr_wins   = sum(1 for (_, r, *_) in this_year_matches if r == 'Win')
    yr_losses = sum(1 for (_, r, *_) in this_year_matches if r == 'Loss')
    yr_draws  = sum(1 for (_, r, *_) in this_year_matches if r == 'Draw')
    yr_total  = yr_wins + yr_losses + yr_draws

    # Title analysis for this year
    intervals = _collect_reign_intervals(db, name, ranking_year)

    titles_held_yr     = 0
    titles_entering_yr = 0
    title_pts_yr       = 0

    for iv in intervals:
        titles_held_yr += 1
        if iv['end_year'] > ranking_year:
            base_pts = max(30 - (titles_held_yr - 1) * 10, 10)
            title_pts_yr += base_pts + iv['prestige']
        if iv['reign_year'] < ranking_year:
            titles_entering_yr += 1

    title_pts_yr     = min(title_pts_yr, 80)
    held_title_yr    = titles_held_yr > 0
    entered_as_champ = titles_entering_yr > 0

    # Count defenses: wins while holding a title
    defenses_this_yr = 0
    for (_, result, _, m) in this_year_matches:
        if result != 'Win':
            continue
        match_d = _parse_date(m.get('date', ''))
        if not match_d:
            continue
        if any(iv['win_date'] and iv['win_date'] < match_d
               and (iv['end_date'] is None or match_d < iv['end_date'])
               for iv in intervals):
            defenses_this_yr += 1

    def is_top_calibre(opp_name, as_of_year):
        cy = cache['champ_years'].get(opp_name, frozenset())
        if cy and any(y <= as_of_year for y in cy):
            return True
        w2, l2, _ = cache['cumulative_record'](opp_name, as_of_year)
        t2 = w2 + l2
        return t2 >= 5 and w2 / t2 >= 0.70

    # Quality score
    yr_qw       = 0.0
    yr_qw_count = 0.0
    for (fy, result, method, m) in this_year_matches:
        if result not in ('Win', 'Draw'):
            continue
        opp  = m['fighter2'] if m['fighter1'] == name else m['fighter1']
        base = opponent_rating(db, cache, opp, fy)
        if result == 'Win':
            mult = 1.2 if ('pinfall' in method.lower() or 'submission' in method.lower()) else 1.0
            h2h  = 1.4 if is_top_calibre(opp, fy) else 1.0
            match_d = _parse_date(m.get('date', ''))
            was_champ = match_d and any(
                iv['win_date'] and iv['win_date'] <= match_d
                and (iv['end_date'] is None or match_d < iv['end_date'])
                for iv in intervals
            )
            def_mult = 1.3 if was_champ else 1.0
            yr_qw       += base * mult * h2h * def_mult
            yr_qw_count += 1.0
        else:  # Draw
            yr_qw       += base * 0.40
            yr_qw_count += 0.4

    norm = max(min(yr_qw_count, WOTY_MAX_WINS), 1)
    yr_quality_score = min(yr_qw / (100 * norm), 1.0) * 100
    yr_quality_score = min(yr_quality_score + title_pts_yr * 0.3, 100)

    # Dominance
    title_losses_yr = 0
    for (_, result, _, m) in this_year_matches:
        if result != 'Loss':
            continue
        match_d = _parse_date(m.get('date', ''))
        if not match_d:
            continue
        if any(iv['win_date'] and iv['win_date'] <= match_d
               and (iv['end_date'] is None or match_d <= iv['end_date'])
               for iv in intervals):
            title_losses_yr += 1

    yr_winpct            = yr_wins / yr_total if yr_total else 0
    defense_bonus        = min(defenses_this_yr * 10, 50)
    entering_champ_bonus = min(titles_entering_yr * 20, 40)
    won_title_this_yr    = held_title_yr and not entered_as_champ
    mid_year_def_bonus   = min(defenses_this_yr * 10, 20) if won_title_this_yr else 0
    title_loss_penalty   = title_losses_yr * 25

    yr_dom_score = min(
        yr_winpct * 30
        + entering_champ_bonus
        + mid_year_def_bonus
        + (10 if held_title_yr and not entered_as_champ else 0)
        + defense_bonus
        + titles_held_yr * 3,
        100,
    ) - title_loss_penalty
    yr_dom_score = max(yr_dom_score, 0)

    title_loss_mult = max(1.0 - title_losses_yr * 0.25, 0.40)

    # Activity
    fought_champ_yr = any(
        opponent_rating(db, cache,
                        m['fighter2'] if m['fighter1'] == name else m['fighter1'],
                        fy) >= 80
        for (fy, _, _, m) in this_year_matches
    )
    yr_activity = min(
        yr_total * 10
        + (25 if fought_champ_yr else 0)
        + (15 if yr_draws > 0 else 0),
        100,
    )

    year_score = (yr_quality_score * 0.50
                  + yr_dom_score   * 0.30
                  + yr_activity    * 0.20) * title_loss_mult

    if yr_total <= LOW_VOLUME_THRESHOLD:
        year_score *= LOW_VOLUME_MULT

    # Career prestige (tiebreaker)
    cp_title_pts = cp_days = cp_longest = 0
    for org in ALL_ORGS:
        for weight in WEIGHT_ORDER:
            for reign in db.championships[org][weight]:
                if reign['champion'] != name:
                    continue
                if not _year_of(reign['date']) or _year_of(reign['date']) > ranking_year:
                    continue
                base = 25 if org == 'ring' else (30 if org in MAJOR_ORGS else 10)
                cp_title_pts += base + TITLE_PRESTIGE.get((org, weight), 0)
                days = reign.get('days') or 0
                cp_days += days
                cp_longest = max(cp_longest, days)
    career_prestige = min(
        min(cp_title_pts, 70)
        + min(cp_days / 365, 3) * 8
        + min(cp_longest / 365, 2) * 4,
        100,
    )

    # Open Tournament yearly bonus (Trios intentionally excluded from yearly)
    won_open_this_year = ranking_year in cache['open_wins'].get(name, [])
    open_yearly_bonus  = OPEN_WIN_YEARLY_BONUS if won_open_this_year else 0

    raw = year_score * 0.85 + career_prestige * 0.15 + open_yearly_bonus

    if not this_year_matches and not won_open_this_year:
        last_fight = max((y for (y, *_) in results), default=0)
        inactive   = max(ranking_year - last_fight, 0)
        raw *= max(1.0 - inactive * 0.20, 0.5)

    return round(raw, 4)


def compute_goat_score(db, cache, name, current_year):
    """GOAT score — no voter fatigue, pure career cumulative."""
    return compute_score(db, cache, name, current_year, goat_mode=True)


# =============================================================================
# TITLE DISPLAY HELPERS
# =============================================================================

def titles_at_year(db, name, year, cache=None):
    """Full title list held during `year`."""
    parts = []
    for org in ('wwf', 'wwo', 'iwb', 'ring'):
        for weight in WEIGHT_ORDER:
            reigns = db.championships[org][weight]
            for i, reign in enumerate(reigns):
                if reign['champion'] != name:
                    continue
                ry = _year_of(reign['date'])
                if not ry or ry > year:
                    continue
                end_year = (
                    _year_of(reigns[i + 1]['date']) if i < len(reigns) - 1
                    else _year_of(reign.get('vacancy_date', '')) or 9999
                )
                if end_year <= year:
                    continue
                label = '<i>The Ring</i>' if org == 'ring' else org.upper()
                txt = f"{label} {weight.capitalize()}"
                if txt not in parts:
                    parts.append(txt)
    if cache:
        if year in cache['open_wins'].get(name, []):
            parts.append(f"{year} Open Tournament")
        if year in cache['trios_wins'].get(name, []):
            parts.append(f"{year} Trios Tournament")
    return ' <br> '.join(parts)


def all_titles_str(db, name, cache=None):
    """Full career championship list."""
    parts = []
    for org in ('wwf', 'wwo', 'iwb', 'ring'):
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
        for y in sorted(cache['open_wins'].get(name, [])):
            parts.append(f"{y} Open Tournament")
        for y in sorted(cache['trios_wins'].get(name, [])):
            parts.append(f"{y} Trios Tournament")
    return ' <br> '.join(parts)


# =============================================================================
# YEARLY RANKINGS
# =============================================================================

def rank_for_year(db, cache, year, gender_list, top_n=10, woty_count=None):
    """
    Top-N wrestlers for a given year.
    gender_list: sorted list of names (deterministic iteration).
    woty_count: {name: times_been_no1} for voter fatigue.
    """
    candidates = []
    for name in gender_list:
        if name not in db.ppv_wrestlers:
            continue
        mr = cache['match_results'][name]
        matches_to_year = [(y, r, meth, m) for (y, r, meth, m) in mr if y <= year]
        if not matches_to_year:
            continue

        last_fight = max(y for (y, *_) in mr)
        if last_fight < year - 2:
            continue

        wins_to_year  = sum(1 for (_, r, *_) in matches_to_year if r == 'Win')
        total_to_year = len(matches_to_year)
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

        this_year_m = [(y2, r2, me2, m2) for (y2, r2, me2, m2) in mr if y2 == year]
        yr_w = sum(1 for (_, r2, *_) in this_year_m if r2 == 'Win')
        yr_l = sum(1 for (_, r2, *_) in this_year_m if r2 == 'Loss')
        yr_d = sum(1 for (_, r2, *_) in this_year_m if r2 == 'Draw')
        year_record = f"{yr_w}-{yr_l}-{yr_d}" if this_year_m else "\u2014"

        wc_count = defaultdict(int)
        for (_, _, _, m2) in matches_to_year:
            wc_count[m2.get('weight_class', 'Unknown')] += 1
        primary = max(wc_count, key=wc_count.get) if wc_count else 'Unknown'

        titles = titles_at_year(db, name, year, cache)
        candidates.append((name, score, record, year_record, primary, titles))

    # Deterministic sort: score desc, name asc
    candidates.sort(key=lambda x: (-x[1], x[0]))

    # Voter fatigue: demote #1 if they've won too many times
    if woty_count and len(candidates) >= 2:
        top_name = candidates[0][0]
        if woty_count.get(top_name, 0) >= WOTY_MAX_TIMES:
            second_score = candidates[1][1]
            demoted = (candidates[0][0], second_score - 0.0001) + candidates[0][2:]
            candidates[0] = demoted
            candidates.sort(key=lambda x: (-x[1], x[0]))

    return candidates[:top_n]


# =============================================================================
# HTML GENERATION
# =============================================================================

def flag(country):
    return f'<span class="fi fi-{country}"></span>'


def p4p_table_html(db, year, gender_label, rankings):
    if not rankings:
        return ''
    lines = [
        f'    <!-- {year} {gender_label} P4P -->',
        '    <details>',
        f"    <summary>{year} {gender_label}'s <i>The Ring</i> P4P Rankings</summary>",
        '    <table style="width: 65%;" class="p4p">',
        '        <tbody><tr>',
        f'            <th>Rank</th><th>Wrestler</th><th>Career Record</th>'
        f'<th>{year} Record</th><th>Titles</th>',
        '        </tr>',
    ]
    for rank, (name, score, record, year_record, weight, titles) in enumerate(rankings, 1):
        country   = db.wrestlers[name]['country']
        titles_td = f'<td>{titles}</td>' if titles else '<th></th>'
        lines += [
            '        <tr>',
            f'            <th>{rank}</th>',
            f'            <td>{flag(country)} {name}</td>',
            f'            <td>{record}</td>',
            f'            <td>{year_record}</td>',
            f'            {titles_td}',
            '        </tr>',
        ]
    lines += ['    </tbody></table>', '    </details>', '', '']
    return '\n'.join(lines)


def generate_p4p_html(db, cache):
    men   = cache['men']
    women = cache['women']
    years = cache['all_years']
    current_year = max(years) if years else datetime.now().year

    parts = []

    # GOAT tables
    for gender_label, glist in [('Men', men), ('Women', women)]:
        goat = []
        for name in glist:
            if name not in db.ppv_wrestlers:
                continue
            w = db.wrestlers[name]
            if w['wins'] + w['losses'] + w['draws'] < P4P_MIN_BOUTS:
                continue
            if w['wins'] < P4P_MIN_CAREER_WINS:
                continue
            score = compute_goat_score(db, cache, name, current_year)
            if score > 0:
                record = f"{w['wins']}-{w['losses']}-{w['draws']}"
                goat.append((name, score, record))
        goat.sort(key=lambda x: (-x[1], x[0]))
        goat = goat[:25]
        if not goat:
            continue

        lines = [
            f'    <!-- All-Time {gender_label} GOAT -->',
            '    <details>',
            f"    <summary>All-Time {gender_label}'s <i>The Ring</i> P4P GOAT Rankings</summary>",
            '    <table style="width: 65%;" class="p4p">',
            '        <tbody><tr>',
            '            <th>Rank</th><th>Wrestler</th><th>Record</th>'
            '<th>Score</th><th>Titles</th>',
            '        </tr>',
        ]
        for rank, (name, score, record) in enumerate(goat, 1):
            country   = db.wrestlers[name]['country']
            titles    = all_titles_str(db, name, cache)
            titles_td = f'<td>{titles}</td>' if titles else '<th></th>'
            lines += [
                '        <tr>',
                f'            <th>{rank}</th>',
                f'            <td>{flag(country)} {name}</td>',
                f'            <td>{record}</td>',
                f'            <td>{score:.1f}</td>',
                f'            {titles_td}',
                '        </tr>',
            ]
        lines += ['    </tbody></table>', '    </details>', '', '']
        parts.append('\n'.join(lines))

    # Yearly tables (compute oldest→newest, display newest→oldest)
    men_woty   = defaultdict(int)
    women_woty = defaultdict(int)
    yearly_men   = {}
    yearly_women = {}

    for year in sorted(years):
        if year >= MENS_P4P_START:
            ranks = rank_for_year(db, cache, year, men, woty_count=men_woty)
            yearly_men[year] = ranks
            if ranks:
                men_woty[ranks[0][0]] += 1
        if year >= WOMENS_P4P_START:
            ranks = rank_for_year(db, cache, year, women, woty_count=women_woty)
            yearly_women[year] = ranks
            if ranks:
                women_woty[ranks[0][0]] += 1

    for year in reversed(sorted(years)):
        if year >= MENS_P4P_START and yearly_men.get(year):
            parts.append(p4p_table_html(db, year, 'Men', yearly_men[year]))
        if year >= WOMENS_P4P_START and yearly_women.get(year):
            parts.append(p4p_table_html(db, year, 'Women', yearly_women[year]))

    return ''.join(parts)


# =============================================================================
# HALL OF FAME
# =============================================================================

def hof_eligible(db, cache, induction_year, already_inducted):
    eligible = []
    for name in sorted(db.wrestlers):
        if name in already_inducted or name not in db.ppv_wrestlers:
            continue
        w = db.wrestlers[name]
        total = w['wins'] + w['losses'] + w['draws']
        if total == 0:
            continue

        mr = cache['match_results'][name]
        last_fight = max((y for (y, *_) in mr), default=0)
        if last_fight > induction_year - HOF_RETIREMENT_YEARS:
            continue
        if w['wins'] < HOF_MIN_WINS:
            continue
        if w['wins'] / total < HOF_MIN_WIN_PCT:
            continue

        if HOF_REQUIRE_MAJOR:
            held_major = any(
                reign['champion'] == name
                for org in MAJOR_ORGS
                for weight in WEIGHT_ORDER
                for reign in db.championships[org][weight]
            )
            if not held_major:
                continue

        score = compute_score(db, cache, name, induction_year, goat_mode=True)
        if score < HOF_MIN_SCORE:
            continue
        eligible.append((name, score))

    eligible.sort(key=lambda x: (-x[1], x[0]))
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


def generate_hof_html(db, cache):
    hof_classes, _ = compute_hof_classes(db, cache)

    lines = [
        '    <!-- List of PWHOF Members -->',
        '    <table class="hof-history">',
        '    <tr>',
        '        <th>No.</th><th>Class</th><th>Ring name</th>'
        '<th>Record</th><th>Height</th><th>Titles</th>'
        '<th>Highest Ranking</th><th>Activity</th>',
        '    </tr>',
    ]
    row_num = 1
    for year in sorted(hof_classes):
        for name in hof_classes[year]:
            w = db.wrestlers.get(name)
            if not w:
                continue
            record   = f"{w['wins']}-{w['losses']}-{w['draws']}"
            titles   = all_titles_str(db, name, cache)
            ranking  = compute_highest_ranking(db, cache, name)
            mr       = cache['match_results'][name]
            activity = (f"Debut: {mr[0][3].get('date', '')} <br> "
                        f"Retired: {mr[-1][3].get('date', '')}") if mr else ''
            country  = w['country']
            height   = read_infobox_height(name)

            lines.append('    <tr>')
            lines.append(f'        <th>{row_num}</th>')
            lines.append(f'        <td>Class of {year}</td>')
            lines.append(f'        <td>{flag(country)} {name}</td>')
            lines.append(f'        <td>{record}</td>')
            lines.append(f'        <td>{height}</td>' if height else '        <th></th>')
            lines.append(f'        <td>{titles}</td>' if titles else '        <th></th>')
            lines.append(f'        <td>{ranking}</td>' if ranking else '        <th></th>')
            lines.append(f'        <td>{activity}</td>')
            lines.append('    </tr>')
            row_num += 1

    lines.append('    </table>')
    lines.append('')
    return '\n'.join(lines) + '\n'


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

    for glist, start_year in checks:
        woty_count = defaultdict(int)
        for year in sorted(years):
            if year < start_year:
                continue
            rankings = rank_for_year(db, cache, year, glist, woty_count=woty_count)
            if rankings:
                woty_count[rankings[0][0]] += 1
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
        print("  \u26a0 wrestling/wrestlers/ not found, skipping infobox update")
        return

    updated = 0
    for name in sorted(db.ppv_wrestlers):
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

        content = re.sub(
            r'<th>Record</th>(\s*<td>)[^<]*(</td>)',
            r'<th>Career Record</th>\g<1>' + record + r'\g<2>',
            content,
        )
        content = re.sub(
            r'(<th>Career Record</th>\s*<td>)[^<]*(</td>)',
            r'\g<1>' + record + r'\g<2>',
            content,
        )
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
                    content,
                )
            else:
                content = re.sub(
                    r'\s*<tr>\s*<th>Highest Ranking</th>.*?</tr>',
                    '', content, flags=re.DOTALL,
                )
        elif highest:
            content = re.sub(
                r'(<th>Career Record</th>\s*<td>[^<]*</td>\s*</tr>)',
                r'\g<1>' + ranking_row,
                content,
            )

        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        updated += 1

    print(f"\u2713 Infoboxes updated: {updated} files")


# =============================================================================
# FILE UPDATERS
# =============================================================================

def update_ring(db, cache):
    path  = 'wrestling/org/ring.html'
    START = '<!-- P4Prankings_START -->'
    END   = '<!-- P4Prankings_END -->'

    if not os.path.exists(path):
        print(f"  \u26a0 {path} not found"); return
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    if START not in content or END not in content:
        print(f"  \u26a0 Markers not found in {path}"); return

    html = generate_p4p_html(db, cache)
    content = content.split(START)[0] + START + '\n' + html + END + content.split(END)[1]
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"\u2713 Updated P4P rankings in {path}")


def update_hof(db, cache):
    path  = 'wrestling/org/pwhof.html'
    START = '<!-- HOFMEMBERS_START -->'
    END   = '<!-- HOFMEMBERS_END -->'

    if not os.path.exists(path):
        print(f"  \u26a0 {path} not found"); return
    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    if START not in content or END not in content:
        print(f"  \u26a0 Markers not found in {path}"); return

    html = generate_hof_html(db, cache)
    content = content.split(START)[0] + START + '\n' + html + END + content.split(END)[1]
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print(f"\u2713 Updated HoF in {path}")


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

    print("\n\u2713 Done! Review changes then git add . && git commit && git push")


if __name__ == '__main__':
    main()
