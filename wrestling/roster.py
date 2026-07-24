#!/usr/bin/env python3
"""
roster.py — Seed / refresh wrestling/rosters.csv
================================================
Builds the roster data file the draft (draft.py) reads from. It scans the real
match history (ppv/list.html + weekly/list.html) via update.py's parser and,
for every wrestler who has actually wrestled, fills in:

  - division        most-fought weight class (same rule elo.py uses)
  - gender          'w' if they ever fought a women's division, else 'm'
  - country         flag code from their matches
  - debuted         TRUE (they have a real match on record)
  - champion_org/_weight   the belt they currently hold, if any
  - last_active     date of their most recent match (for inactivity priority)

It is SAFE TO RE-RUN. Anything you have hand-edited is preserved:

  - division_source = manual  -> the division field is never overwritten
  - undebuted wrestlers you added (debuted = FALSE) are kept verbatim; only
    their champion / last_active stay blank.
  - inferred fields on debuted wrestlers are refreshed from the latest results.

WORKFLOW — add undebuted wrestlers by appending ROWS to the CSV:
  1. python3 wrestling/roster.py     # seeds the ~185 real wrestlers
  2. open rosters.csv in any spreadsheet; add one row per undebuted wrestler.
     You only need:  name, country, gender, division, division_source=manual,
     debuted=FALSE.  Leave slug blank — it's filled in on the next run.
     (Also tag any debuted wrestler whose 'division' came out blank.)
  3. python3 wrestling/roster.py     # re-run any time; your edits survive

Run from anywhere; it chdir's to the site root like elo.py does.
"""

import csv
import os
import sys
from collections import defaultdict
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)

from update import WrestlingDatabase, resolve_site_date, format_site_date  # noqa: E402

# Same division ladder elo.py uses (heaviest -> lightest); index = size rank.
WEIGHT_ORDER = ('heavyweight', 'bridgerweight', 'middleweight',
                'welterweight', 'lightweight', 'featherweight')
WEIGHT_INDEX = {w: i for i, w in enumerate(WEIGHT_ORDER)}
WOMENS_WEIGHTS = ('lightweight', 'featherweight')
ORGS = ('wwf', 'wwo', 'iwb')

ROSTER_PATH = os.path.join(SCRIPT_DIR, 'rosters.csv')

# Column order in the CSV. draft.py reads these back. (Per-year org / draft
# assignments do NOT live here — there's a draft every year, so they go in the
# per-year draft records under wrestling/drafts/. This file is the master pool.)
FIELDS = ['slug', 'name', 'country', 'gender', 'division', 'division_source',
          'debuted', 'champion_org', 'champion_weight', 'champion_all',
          'retired', 'retired_reason', 'last_active']


def read_text_any(path):
    """Read a CSV that may carry a stray non-UTF-8 byte from an Excel round-trip.

    The site is UTF-8 (accented luchador names decode correctly that way), so we
    do NOT fall back to a whole-file cp1252 decode: a single bad byte would then
    turn every valid 'ñ'/'é' into mojibake ('Ã±'/'Ã©') and spawn duplicate rows.
    Instead we keep UTF-8 and replace only the genuinely invalid byte(s) with '�'
    so the offending name is easy to spot and retype. roster.py rewrites clean
    UTF-8 on the way out.
    """
    with open(path, 'rb') as f:
        raw = f.read()
    for enc in ('utf-8-sig', 'utf-8'):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode('utf-8', errors='replace')


def slugify(name):
    """Same rule update.py uses to link to a wrestler's page."""
    return name.lower().replace(' ', '-').replace('.', '')


def parse_date(s):
    for fmt in ("%B %d, %Y", "%B %Y", "%b %d, %Y", "%b %Y"):
        try:
            return datetime.strptime((s or '').strip(), fmt)
        except (ValueError, AttributeError):
            continue
    return None


def build_db():
    os.chdir(os.path.dirname(SCRIPT_DIR))
    ppv, weekly = 'wrestling/ppv/list.html', 'wrestling/weekly/list.html'
    db = WrestlingDatabase()
    site_date, why = resolve_site_date(ppv, weekly)
    db.cutoff = site_date
    print(f"Site date: {format_site_date(site_date) or '(none)'} — {why}")
    db.parse_events(ppv, is_weekly=False)
    if os.path.exists(weekly):
        db.parse_events(weekly, is_weekly=True)
    db.events.sort(key=lambda e: parse_date(e.get('date')) or datetime.min)
    db.reprocess_championships_chronologically()
    db.recalculate_bio_notes()
    db.process_vacancies()
    db.calculate_championship_days()
    return db


def infer_from_history(db):
    """Per wrestler: division counts, gender, most-recent match date."""
    div_counts = defaultdict(lambda: defaultdict(int))
    women = set()
    last_active = {}
    for event in db.events:
        edate = parse_date(event.get('date'))
        for m in event['matches']:
            wc = (m.get('weight_class') or '').lower()
            for who in (m.get('fighter1'), m.get('fighter2')):
                if not who:
                    continue
                if wc in WEIGHT_INDEX:
                    div_counts[who][wc] += 1
                if wc in WOMENS_WEIGHTS:
                    women.add(who)
                if edate and (who not in last_active or edate > last_active[who]):
                    last_active[who] = edate
    return div_counts, women, last_active


def most_fought_division(counts):
    if not counts:
        return None
    # Most-fought; ties break heavier (lower index), same as elo.py.
    return min(counts, key=lambda w: (-counts[w], WEIGHT_INDEX[w]))


def current_champions(db):
    """slug -> {'org': ..., 'weight': ...} for every reigning belt holder.
    A unified champ (holds several orgs) is recorded once per org held."""
    champ_of = {}
    for org in ORGS:
        for weight in WEIGHT_ORDER:
            cur = db._current_champion(org, weight)
            if cur:
                champ_of.setdefault(slugify(cur[0]), []).append(
                    {'org': org, 'weight': weight})
    return champ_of


def career_retirements(db):
    """slug -> reason for every wrestler who LOST a Lucha de Apuestas whose
    wager involved a career (career vs. career, mask vs. career, hair vs.
    career). Losing your career = retirement (e.g. Kurt Angle). Ambiguous
    mask/hair-vs-career cases are still flagged; flip 'retired' to FALSE in the
    CSV to override — the override is preserved on re-run."""
    out = {}
    for a in getattr(db, 'apuestas', []):
        wager = (a.get('wager') or '').lower()
        if 'career' in wager and a.get('loser'):
            reason = f"Lost career apuesta ({a.get('wager', '').strip()}) at {a.get('event', '')}".strip()
            out[slugify(a['loser'])] = reason
    return out


def load_existing():
    """slug -> row dict from a previous rosters.csv (empty if none). Rows whose
    slug cell is blank are keyed by slugify(name), so hand-added rows only need
    a name."""
    if not os.path.exists(ROSTER_PATH):
        return {}
    rows = {}
    text = read_text_any(ROSTER_PATH)
    import io
    with io.StringIO(text) as f:
        for r in csv.DictReader(f):
            slug = (r.get('slug') or '').strip() or slugify((r.get('name') or '').strip())
            if slug:
                rows[slug] = {k: (v or '').strip() for k, v in r.items()}
    return rows


def truthy(v):
    return str(v).strip().lower() in ('true', '1', 'yes', 'y')


def main():
    db = build_db()
    print(f"  Loaded {len(db.wrestlers)} wrestlers, {len(db.events)} events")

    div_counts, women, last_active = infer_from_history(db)
    champ_of = current_champions(db)
    retired_of = career_retirements(db)
    existing = load_existing()

    out = {}

    def blank_row():
        return {k: '' for k in FIELDS}

    # 1. Everyone with real matches -> seed / refresh inferred fields.
    for name in sorted(db.wrestlers):
        slug = slugify(name)
        prev = existing.get(slug, {})
        champ = champ_of.get(slug)
        champ = champ[0] if champ else None      # primary belt; extras below

        # Division: never clobber a manual tag.
        if prev.get('division_source') == 'manual' and prev.get('division'):
            division = prev['division']
            div_source = 'manual'
        else:
            division = most_fought_division(div_counts.get(name)) \
                or prev.get('division', '')
            div_source = 'inferred'

        # Retirement: auto-detected career-apuesta loss, unless hand-cleared.
        auto_retire = retired_of.get(slug)
        if prev.get('retired', '').strip():        # user set an explicit value
            retired = 'TRUE' if truthy(prev['retired']) else 'FALSE'
            reason = prev.get('retired_reason', '') or (auto_retire or '')
        elif auto_retire:
            retired, reason = 'TRUE', auto_retire
        else:
            retired, reason = '', ''

        la = last_active.get(name)
        row = blank_row()
        row.update({
            'slug': slug,
            'name': name,
            'country': db.wrestlers[name].get('country', 'un'),
            'gender': 'w' if name in women else 'm',
            'division': division or '',
            'division_source': div_source,
            'debuted': 'TRUE' if name in db.ppv_wrestlers else 'FALSE',
            'champion_org': champ['org'] if champ else '',
            'champion_weight': champ['weight'] if champ else '',
            'champion_all': (';'.join(f"{c['org']}:{c['weight']}" for c in champ_of[slug])
                             if champ_of.get(slug) and len(champ_of[slug]) > 1 else ''),
            'retired': retired,
            'retired_reason': reason,
            'last_active': la.strftime('%Y-%m-%d') if la else prev.get('last_active', ''),
        })
        out[slug] = row

    # 2. Preserve hand-added undebuted wrestlers (no match history).
    kept_manual = 0
    for slug, prev in existing.items():
        if slug in out:
            continue
        row = blank_row()
        row.update(prev)
        row['slug'] = slug
        if not truthy(row.get('debuted')):
            # Genuinely undebuted: no auto champion / last_active.
            row['champion_org'] = row['champion_weight'] = row['champion_all'] = ''
            row['last_active'] = row.get('last_active', '')
        out[slug] = row
        kept_manual += 1

    # Sort: division (heaviest first), then gender, then name — easy to scan.
    def sort_key(r):
        d = r.get('division', '')
        return (WEIGHT_INDEX.get(d, 99), r.get('gender', 'm'), r.get('name', ''))

    ordered = sorted(out.values(), key=sort_key)

    with open(ROSTER_PATH, 'w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for row in ordered:
            w.writerow({k: row.get(k, '') for k in FIELDS})

    debuted_n = sum(1 for r in out.values() if truthy(r.get('debuted')))
    champs_n = sum(1 for r in out.values() if r.get('champion_org'))
    retired_n = sum(1 for r in out.values() if truthy(r.get('retired')))
    no_div = [r['name'] for r in out.values() if not r.get('division')]
    print(f"\n✓ Wrote {ROSTER_PATH}")
    print(f"  {len(out)} wrestlers  ({debuted_n} debuted, "
          f"{len(out) - debuted_n} undebuted/manual, {champs_n} current champions, "
          f"{retired_n} retired)")
    print(f"  {kept_manual} hand-added rows preserved")
    if no_div:
        print(f"  ⚠ {len(no_div)} without a division (tag them): "
              f"{', '.join(no_div[:8])}{' …' if len(no_div) > 8 else ''}")


if __name__ == '__main__':
    main()
