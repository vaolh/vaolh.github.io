#!/usr/bin/env python3
"""
roster.py — Seed / refresh wrestling/rosters.json
=================================================
Builds the roster data file the draft (draft.py) reads from. It scans the real
match history (ppv/list.html + weekly/list.html) via update.py's parser and,
for every wrestler who has actually wrestled, fills in:

  - division      most-fought weight class (same rule elo.py uses)
  - gender        'w' if they ever fought a women's division, else 'm'
  - country       flag code from their matches
  - debuted       True (they have a real match on record)
  - champion      {org, weight} if they currently hold a belt, else null
  - last_active   date of their most recent match (for inactivity priority)

It is SAFE TO RE-RUN. Anything you have hand-edited is preserved:

  - "division_source": "manual"  -> the division field is never overwritten
  - undebuted wrestlers you added (debuted:false) are kept verbatim; only their
    champion/last_active stay null.
  - inferred fields on debuted wrestlers are refreshed from the latest results.

So the workflow is:
  1. python3 wrestling/roster.py         # seeds the 191 real wrestlers
  2. hand-add the ~110 undebuted names in rosters.json (see _TEMPLATE below),
     tagging each with a division and "division_source": "manual"
  3. python3 wrestling/roster.py         # re-run any time; your edits survive

Run from anywhere; it chdir's to the site root like elo.py does.
"""

import json
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

ROSTER_PATH = os.path.join(SCRIPT_DIR, 'rosters.json')

# What a hand-added undebuted entry should look like. Copied into _meta so the
# schema is documented right inside the file you edit.
_TEMPLATE = {
    "name": "Full Name",
    "country": "us",
    "gender": "m",
    "division": "heavyweight",
    "division_source": "manual",
    "debuted": False,
    "champion": None,
    "org": None,
    "drafted_year": None,
    "last_active": None,
}


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


def load_existing():
    if not os.path.exists(ROSTER_PATH):
        return {}
    with open(ROSTER_PATH, 'r', encoding='utf-8') as f:
        try:
            data = json.load(f)
        except json.JSONDecodeError as e:
            sys.exit(f"rosters.json is not valid JSON ({e}). Fix or delete it.")
    return data.get('wrestlers', {})


def main():
    db = build_db()
    print(f"  Loaded {len(db.wrestlers)} wrestlers, {len(db.events)} events")

    div_counts, women, last_active = infer_from_history(db)
    champ_of = current_champions(db)
    existing = load_existing()

    out = {}

    # 1. Everyone with real matches -> seed / refresh inferred fields.
    for name in sorted(db.wrestlers):
        slug = slugify(name)
        prev = existing.get(slug, {})
        debuted = name in db.ppv_wrestlers
        champ = champ_of.get(slug)
        champ = champ[0] if champ else None      # primary belt; extras below

        # Division: never clobber a manual tag.
        if prev.get('division_source') == 'manual' and prev.get('division'):
            division = prev['division']
            div_source = 'manual'
        else:
            division = most_fought_division(div_counts.get(name)) \
                or prev.get('division')
            div_source = 'inferred'

        la = last_active.get(name)
        entry = {
            'name': name,
            'country': db.wrestlers[name].get('country', 'un'),
            'gender': 'w' if name in women else 'm',
            'division': division,
            'division_source': div_source,
            'debuted': debuted,
            'champion': champ,
            'org': (champ['org'] if champ else prev.get('org')),
            'drafted_year': prev.get('drafted_year'),
            'last_active': la.strftime('%Y-%m-%d') if la else prev.get('last_active'),
        }
        if champ_of.get(slug) and len(champ_of[slug]) > 1:
            entry['champion_all'] = champ_of[slug]   # unified: every belt held
        out[slug] = entry

    # 2. Preserve hand-added undebuted wrestlers (no match history).
    kept_manual = 0
    for slug, prev in existing.items():
        if slug in out:
            continue
        if prev.get('debuted'):
            # Was debuted before but has no matches now? Data changed; drop the
            # stale champion/last_active but keep the record for review.
            prev = {**prev, 'champion': None}
        prev.setdefault('drafted_year', None)
        prev.setdefault('last_active', None)
        out[slug] = prev
        kept_manual += 1

    payload = {
        '_meta': {
            'generated': format_site_date(db.cutoff) or datetime.now().strftime('%Y-%m-%d'),
            'orgs': list(ORGS),
            'divisions': list(WEIGHT_ORDER),
            'womens_divisions': list(WOMENS_WEIGHTS),
            'help': ("Add undebuted wrestlers as new keys under 'wrestlers' using "
                     "the slug (lowercase, spaces->'-', dots removed). Tag each "
                     "with a division and set 'division_source' to 'manual' so a "
                     "re-run never overwrites it. Template below."),
            'entry_template': _TEMPLATE,
        },
        'wrestlers': out,
    }

    with open(ROSTER_PATH, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write('\n')

    debuted_n = sum(1 for e in out.values() if e.get('debuted'))
    champs_n = sum(1 for e in out.values() if e.get('champion'))
    no_div = [s for s, e in out.items() if not e.get('division')]
    print(f"\n✓ Wrote {ROSTER_PATH}")
    print(f"  {len(out)} wrestlers  ({debuted_n} debuted, "
          f"{len(out) - debuted_n} undebuted/manual, {champs_n} current champions)")
    print(f"  {kept_manual} hand-added entries preserved")
    if no_div:
        print(f"  ⚠ {len(no_div)} without a division (tag them manually): "
              f"{', '.join(no_div[:8])}{' …' if len(no_div) > 8 else ''}")


if __name__ == '__main__':
    main()
