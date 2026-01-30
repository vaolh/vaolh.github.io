#!/usr/bin/env python3
"""
Wrestling Database Auto-Updater
================================
Reads wrestling/ppv/list.html, extracts SINGLES match data only, updates all HTML files.

Virtual Environment Setup:
=========================

1. Create virtual environment (first time only):
   python3 -m venv venv

2. Activate virtual environment:
   source ~/wrestling-venv/bin/activate

3. Install required packages:
   pip install beautifulsoup4

4. Run the script:
   python3 wrestling/update.py

5. Deactivate when done:
   deactivate

Required packages:
- beautifulsoup4 (for HTML parsing)
- datetime, collections, os, re (built-in, no install needed)

After running, check the changes and git push if everything looks good.
"""

from bs4 import BeautifulSoup, Comment
from datetime import datetime
from collections import defaultdict
import os
import re

class WrestlingDatabase:
    def __init__(self):
        self.wrestlers = {}
        self.ppv_wrestlers = set()  # Track wrestlers who appeared in PPV events
        self.championships = {
            'wwf': {'heavyweight': [], 'bridgerweight': [], 'middleweight': [], 
                   'welterweight': [], 'lightweight': [], 'featherweight': []},
            'wwo': {'heavyweight': [], 'bridgerweight': [], 'middleweight': [], 
                   'welterweight': [], 'lightweight': [], 'featherweight': []},
            'iwb': {'heavyweight': [], 'bridgerweight': [], 'middleweight': [], 
                   'welterweight': [], 'lightweight': [], 'featherweight': []},
            'ring': {'heavyweight': [], 'bridgerweight': [], 'middleweight': [], 
                    'welterweight': [], 'lightweight': [], 'featherweight': []}
        }
        self.events = []
        self.broadcasts = []
        self.tournaments = {'open': [], 'trios': []}
        self.vacancies = []
        self.apuestas = []  # Track Lucha de Apuestas matches

    def parse_date(self, date_str):
        """Parse date from various formats"""
        try:
            # Try "Month DD, YYYY" format (e.g., "July 6, 2000")
            date_obj = datetime.strptime(date_str.strip(), "%B %d, %Y")
            return date_obj
        except:
            try:
                # Try "Month YYYY" format (defaults to 1st of month)
                date_obj = datetime.strptime(date_str.strip(), "%B %Y")
                return date_obj
            except:
                return None

    def days_between(self, date1_str, date2_str):
        """Calculate days between two dates"""
        d1 = self.parse_date(date1_str)
        d2 = self.parse_date(date2_str)
        if d1 and d2:
            return abs((d2 - d1).days)
        return None

    def format_number(self, num):
        """Format number with comma for thousands"""
        if num is None:
            return ""
        return f"{num:,}"

    def get_country(self, element):
        """Extract country code from flag span"""
        flag = element.find('span', class_='fi')
        if flag:
            classes = flag.get('class', [])
            for c in classes:
                if c.startswith('fi-'):
                    return c.replace('fi-', '')
        return 'un'

    def clean_name(self, text):
        """Clean wrestler name (remove (c) champion markers)"""
        text = text.strip()
        text = re.sub(r'\s*\(c\)\s*', '', text, flags=re.IGNORECASE)
        return text.strip()

    def get_wrestler(self, name):
        """Get or create wrestler"""
        if name not in self.wrestlers:
            self.wrestlers[name] = {
                'name': name,
                'country': 'un',
                'matches': [],
                'wins': 0,
                'losses': 0,
                'draws': 0,
                'pinfall_wins': 0,
                'submission_wins': 0,
                'decision_wins': 0,
                'pinfall_losses': 0,
                'submission_losses': 0,
                'decision_losses': 0,
                'lucha_wins': 0,
                'championships': [],
                'main_events': 0,
                'wrestlemania_main_events': 0,
                'libremania_main_events': 0,
                'open_tournament_wins': 0,
                'trios_tournament_wins': 0
            }
        return self.wrestlers[name]

    def parse_vacancy_comments(self, html_content):
        """Parse VACATED comments from HTML"""
        # Find all comments
        soup = BeautifulSoup(html_content, 'html.parser')
        comments = soup.find_all(string=lambda text: isinstance(text, Comment))
        
        for comment in comments:
            comment_text = comment.strip()
            if 'VACATED TITLE' in comment_text.upper():
                # Parse: <!-- VACATED TITLE: WWF Heavyweight. Champion: The Rock. Message: ... Date: 3 December 2028. -->
                vacancy = {}
                
                # Extract org and weight
                if 'WWF' in comment_text.upper():
                    vacancy['org'] = 'wwf'
                elif 'WWO' in comment_text.upper():
                    vacancy['org'] = 'wwo'
                elif 'IWB' in comment_text.upper():
                    vacancy['org'] = 'iwb'
                elif 'RING' in comment_text.upper():
                    vacancy['org'] = 'ring'
                else:
                    continue
                
                # Extract weight class
                weights = ['heavyweight', 'bridgerweight', 'middleweight', 'welterweight', 'lightweight', 'featherweight']
                for weight in weights:
                    if weight in comment_text.lower():
                        vacancy['weight'] = weight
                        break
                
                # Extract champion name
                champion_match = re.search(r'Champion:\s*([^.]+)', comment_text, re.IGNORECASE)
                if champion_match:
                    vacancy['champion'] = champion_match.group(1).strip()
                
                # Extract date
                date_match = re.search(r'Date:\s*([^.]+)', comment_text, re.IGNORECASE)
                if date_match:
                    vacancy['date'] = date_match.group(1).strip()
                
                # Extract message
                message_match = re.search(r'Message:\s*([^.]+(?:\.[^D])*)', comment_text, re.IGNORECASE)
                if message_match:
                    vacancy['message'] = message_match.group(1).strip()
                
                if 'weight' in vacancy and 'date' in vacancy:
                    self.vacancies.append(vacancy)

    def parse_tournament_comments(self, html_content):
        """Parse TOURNAMENT WINNER comments from HTML"""
        soup = BeautifulSoup(html_content, 'html.parser')
        comments = soup.find_all(string=lambda text: isinstance(text, Comment))
        
        for comment in comments:
            comment_text = comment.strip()
            
            # Parse Open Tournament
            if 'OPEN TOURNAMENT WINNER' in comment_text.upper():
                winner_match = re.search(r'Winner:\s*([^.]+)', comment_text, re.IGNORECASE)
                if winner_match:
                    winner_name = self.clean_name(winner_match.group(1).strip())
                    self.tournaments['open'].append(winner_name)
                    
                    # Update wrestler stats
                    wrestler = self.get_wrestler(winner_name)
                    wrestler['open_tournament_wins'] += 1
            
            # Parse Trios Tournament
            if 'TRIOS TOURNAMENT WINNER' in comment_text.upper():
                winner_match = re.search(r'Winner:\s*([^.]+)', comment_text, re.IGNORECASE)
                if winner_match:
                    winner_name = self.clean_name(winner_match.group(1).strip())
                    self.tournaments['trios'].append(winner_name)
                    
                    # Update wrestler stats
                    wrestler = self.get_wrestler(winner_name)
                    wrestler['trios_tournament_wins'] += 1

    def parse_events(self, html_file, is_weekly=False):
        """Parse all events from HTML file"""
        with open(html_file, 'r', encoding='utf-8') as f:
            html_content = f.read()
        
        # Parse vacancy comments first (only for PPV)
        if not is_weekly:
            self.parse_vacancy_comments(html_content)

        # Parse tournament comments (only for PPV)
        if not is_weekly:
            self.parse_tournament_comments(html_content)
        
        soup = BeautifulSoup(html_content, 'html.parser')
        details = soup.find_all('details')
        
        for detail in details:
            summary = detail.find('summary')
            if not summary:
                continue
                
            event_name = summary.get_text().strip()
            table = detail.find('table', class_='match-card')
            
            # For weekly shows, always use "Live TV" as event name
            if is_weekly:
                event_name = "Live TV"
            else:
                event_name = event_name.split(':')[0].strip()
                event_name = re.sub(r'World Title Series (\d+)', r'WTS \1', event_name)
                event_name = re.sub(r'World Championship Wrestling (\d+)', r'WCW \1', event_name)
                # Remove " - Day X" portion for multi-day events
                event_name = re.sub(r'\s*-\s*Day\s+\d+', '', event_name, flags=re.IGNORECASE)

            if table:
                self.parse_match_card(table, event_name, is_weekly=is_weekly)
            

    def parse_match_card(self, table, event_name, is_weekly=False):
        """Parse individual match card - SINGLES MATCHES ONLY"""
        rows = table.find('tbody').find_all('tr')
        info_row = rows[-1]
        match_rows = rows[1:-1]
        
        # Extract event info from last row
        event_date = None
        event_location = None
        event_country = 'un'
        event_venue = None
        audience_metric = None
        broadcast_type = None
        attendance = None
        
        # Parse th cells for both PPV and weekly shows
        th_cells = info_row.find_all('th')
        
        if is_weekly:
            # Weekly shows format: <th>TV</th> <th colspan="2">Location</th> <th colspan="3">Venue</th> <th>Attendance</th> <th>Network</th> <th>Audience</th> <th>Date</th>
            # We only need date and location for wrestler records
            for idx, th in enumerate(th_cells):
                text = th.get_text().strip()
                
                if idx == 1:
                    # Second th is location (with flag)
                    flag = th.find('span', class_='fi')
                    if flag:
                        event_country = self.get_country(th)
                        event_location = text
                elif idx == len(th_cells) - 1:
                    # Last th is date
                    event_date = text
        else:
            # PPV format - full parsing for broadcast records
            # Parse broadcast type from first th
            if th_cells:
                first_th = th_cells[0]
                # Check if there's an anchor tag
                anchor = first_th.find('a')
                if anchor:
                    first_th_text = anchor.get_text().strip().upper()
                else:
                    first_th_text = first_th.get_text().strip().upper()
                
                if 'PPV' in first_th_text:
                    broadcast_type = 'PPV'
                elif 'TV' in first_th_text:
                    broadcast_type = 'TV'
                elif 'STM' in first_th_text:
                    broadcast_type = 'STM'
            
            # Parse each th cell by position
            for idx, th in enumerate(th_cells):
                text = th.get_text().strip()
                
                if idx == 0:
                    # First th is broadcast type (already handled)
                    continue
                elif idx == 1:
                    # Second th is location (with flag)
                    flag = th.find('span', class_='fi')
                    if flag:
                        event_country = self.get_country(th)
                        event_location = text
                elif idx == 2:
                    # Third th is venue
                    event_venue = text
                elif idx == 3:
                    # Fourth th is attendance
                    if 'Attendance' in text or 'attendance' in text:
                        attendance = text
                elif idx == 4:
                    # Fifth th is network (skip for our purposes)
                    pass
                elif idx == 5:
                    # Sixth th is audience metric (Buys/Viewers/Sales)
                    audience_metric = text
                elif idx == 6:
                    # Seventh th is date
                    event_date = text

        event = {
            'name': event_name,
            'date': event_date,
            'location': event_location,
            'country': event_country,
            'venue': event_venue,
            'audience_metric': audience_metric,
            'broadcast_type': broadcast_type,
            'attendance': attendance,
            'matches': []
        }

        singles_match_idx = -1
        
        # Parse matches
        for idx, row in enumerate(match_rows):
            cols = row.find_all(['td', 'th'])
            if len(cols) < 7:
                continue

            match_num = cols[0].get_text().strip()
            match_type = cols[1].get_text().strip()
            weight_class = cols[2].get_text().strip()
            fighter1_cell = cols[3]
            result_cell = cols[4]
            fighter2_cell = cols[5]
            method = cols[6].get_text().strip()
            falls = cols[7].get_text().strip() if len(cols) > 7 else ''
            notes = cols[8].get_text().strip() if len(cols) > 8 else ''

            # ONLY PROCESS SINGLES MATCHES
            if match_type.lower() != 'singles':
                continue
            
            singles_match_idx += 1

            fighter1 = self.clean_name(fighter1_cell.get_text())
            fighter1_country = self.get_country(fighter1_cell)
            fighter2 = self.clean_name(fighter2_cell.get_text())
            fighter2_country = self.get_country(fighter2_cell)
            result = result_cell.get_text().strip().lower()

            winner = None
            loser = None
            is_draw = False
            
            if result in ['def.', 'defeated', 'def']:
                winner = fighter1
                loser = fighter2
            elif result in ['draw', 'vs.', 'vs']:
                is_draw = True

            match = {
                'match_num': int(match_num) if match_num.isdigit() else 0,
                'type': match_type,
                'weight_class': weight_class,
                'fighter1': fighter1,
                'fighter1_country': fighter1_country,
                'fighter2': fighter2,
                'fighter2_country': fighter2_country,
                'winner': winner,
                'loser': loser,
                'is_draw': is_draw,
                'method': method,
                'notes': notes,
                'event': event_name,
                'date': event_date,
                'venue': event_venue,
                'location': event_location,
                'location_country': event_country
            }

            event['matches'].append(match)
            
            # Check if this is the main event (last singles match)
            is_main_event = (idx == len(match_rows) - 1)
            self.record_match(match, is_main_event, is_weekly=is_weekly)

        self.events.append(event)
        
        # Record broadcast if it has audience metrics (skip for weekly shows)
        if not is_weekly and audience_metric and broadcast_type:
            # Get main event info (last singles match)
            main_event_match = event['matches'][-1] if event['matches'] else None
            main_event_text = ""
            main_event_wrestlers = []
            if main_event_match:
                main_event_text = f"{main_event_match['fighter1']} vs. {main_event_match['fighter2']}"
                main_event_wrestlers = [main_event_match['fighter1'], main_event_match['fighter2']]
            
            # Extract network (second to last th cell in info row)
            network = ""
            th_cells = info_row.find_all('th')
            if len(th_cells) >= 2:
                network = th_cells[-2].get_text().strip()
            
            self.broadcasts.append({
                'event': event_name,
                'date': event_date,
                'venue': event_venue,
                'location': event_location,
                'country': event_country,
                'audience_metric': audience_metric,
                'broadcast_type': broadcast_type,
                'network': network,
                'main_event': main_event_text,
                'main_event_wrestlers': main_event_wrestlers,
                'attendance': attendance
            })

    def is_title_match(self, notes):
        """Check if notes indicate a title match"""
        if not notes:
            return False, None
        
        notes_lower = notes.lower()
        orgs = ['wwf', 'wwo', 'iwb', 'ring']
        title_keywords = ['title', 'titles', 'championship', 'championships']
        
        matched_orgs = []
        for org in orgs:
            if org in notes_lower:
                for keyword in title_keywords:
                    if keyword in notes_lower:
                        matched_orgs.append(org)
                        break

        return (len(matched_orgs) > 0), matched_orgs

    def format_orgs_list(self, orgs):
        """Format list of orgs with proper grammar: 'WWF', 'WWF and WWO', 'WWF, WWO, and IWB'"""
        if not orgs:
            return ""
        
        # Apply italics to The Ring
        formatted_orgs = []
        for org in orgs:
            if org == 'The Ring':
                formatted_orgs.append('<i>The Ring</i>')
            else:
                formatted_orgs.append(org)
        
        if len(formatted_orgs) == 1:
            return formatted_orgs[0]
        elif len(formatted_orgs) == 2:
            return f"{formatted_orgs[0]} and {formatted_orgs[1]}"
        else:
            # 3 or more: "A, B, and C"
            return ', '.join(formatted_orgs[:-1]) + f", and {formatted_orgs[-1]}"
    
    def format_title_notes(self, retained_orgs, won_orgs, for_orgs, weight):
        """Format title notes with proper grammar"""
        bio_notes_parts = []
        
        if retained_orgs:
            formatted_orgs = self.format_orgs_list(retained_orgs)
            title_word = "titles" if len(retained_orgs) > 1 else "title"
            bio_notes_parts.append(f"Retained {formatted_orgs} {weight.capitalize()} {title_word}")
        
        if won_orgs:
            formatted_orgs = self.format_orgs_list(won_orgs)
            title_word = "titles" if len(won_orgs) > 1 else "title"
            bio_notes_parts.append(f"Won {formatted_orgs} {weight.capitalize()} {title_word}")
        
        if for_orgs:
            formatted_orgs = self.format_orgs_list(for_orgs)
            title_word = "titles" if len(for_orgs) > 1 else "title"
            bio_notes_parts.append(f"For {formatted_orgs} {weight.capitalize()} {title_word}")
        
        return '<br>'.join(bio_notes_parts) if bio_notes_parts else ""

    def record_match(self, match, is_main_event, is_weekly=False):
        """Record match in wrestler stats"""
        w1 = self.get_wrestler(match['fighter1'])
        w2 = self.get_wrestler(match['fighter2'])
        
        # Track PPV wrestlers (exclude weekly-only talent)
        if not is_weekly:
            self.ppv_wrestlers.add(match['fighter1'])
            self.ppv_wrestlers.add(match['fighter2'])
        
        w1['country'] = match['fighter1_country']
        w2['country'] = match['fighter2_country']

        if is_main_event:
            w1['main_events'] += 1
            w2['main_events'] += 1
            
            if 'wrestlemania' in match['event'].lower():
                w1['wrestlemania_main_events'] += 1
                w2['wrestlemania_main_events'] += 1
            elif 'libremania' in match['event'].lower():
                w1['libremania_main_events'] += 1
                w2['libremania_main_events'] += 1

        # Build enhanced notes for wrestler bio
        is_title, orgs = self.is_title_match(match['notes'])

        if is_title and (match['winner'] or match['is_draw']):  # Include draws!
            weights = ['heavyweight', 'bridgerweight', 'middleweight', 'welterweight', 'lightweight', 'featherweight']
            notes_lower = match['notes'].lower()
            weight = None
            for w in weights:
                if w in notes_lower or w in match['weight_class'].lower():
                    weight = w
                    break
            
            if weight:
                # Check if title can actually change (same logic as check_championship_change)
                method_lower = match['method'].lower()
                can_change_title = 'pinfall' in method_lower or 'submission' in method_lower or ('dq' not in method_lower and 'countout' not in method_lower and 'count out' not in method_lower and 'disqualification' not in method_lower)
                
                # For draws, both fighters retain if they're champions
                if match['is_draw']:
                    # Handle draw - both retain their respective titles
                    fighter1_retained = []
                    fighter2_retained = []
                    
                    for org in orgs:
                        current_reigns = self.championships[org][weight]
                        last_reign = current_reigns[-1] if current_reigns else None
                        
                        if last_reign:
                            if last_reign['champion'] == match['fighter1']:
                                fighter1_retained.append('The Ring' if org == 'ring' else org.upper())
                            elif last_reign['champion'] == match['fighter2']:
                                fighter2_retained.append('The Ring' if org == 'ring' else org.upper())
                    
                    # Build notes for both fighters
                    if fighter1_retained:
                        fighter1_notes = self.format_title_notes(fighter1_retained, [], [], weight)
                    else:
                        fighter1_notes = match['notes']
                    
                    if fighter2_retained:
                        fighter2_notes = self.format_title_notes(fighter2_retained, [], [], weight)
                    else:
                        fighter2_notes = match['notes']
                    
                    bio_notes = fighter1_notes  # Will be overridden per fighter below
                else:
                    # Non-draw title match
                    retained_orgs = []
                    won_orgs = []
                    for_orgs = []  # Titles that were defended but didn't change (DQ/countout)
                    
                    for org in orgs:
                        current_reigns = self.championships[org][weight]
                        last_reign = current_reigns[-1] if current_reigns else None
                        
                        # Check if winner is current champion of this org
                        if last_reign and last_reign['champion'] == match['winner']:
                            # Winner is already champ
                            if can_change_title:
                                retained_orgs.append('The Ring' if org == 'ring' else org.upper())
                            else:
                                # Can't change title (DQ/countout) but winner is champ, so retained
                                retained_orgs.append('The Ring' if org == 'ring' else org.upper())
                        else:
                            # Winner is NOT current champion
                            if can_change_title:
                                # Normal title change
                                won_orgs.append('The Ring' if org == 'ring' else org.upper())
                            else:
                                # Won by DQ/countout - title doesn't change, show as "For"
                                for_orgs.append('The Ring' if org == 'ring' else org.upper())
                    
                    bio_notes = self.format_title_notes(retained_orgs, won_orgs, for_orgs, weight)
            else:
                # Title match but no weight found - keep original notes
                bio_notes = match['notes']
        else:
            # Not a title match - keep original notes
            bio_notes = match['notes']

        if match['is_draw']:
            w1['draws'] += 1
            w2['draws'] += 1
            
            # For draws in title matches, each fighter gets their own notes
            if is_title and weight:
                # Use the fighter-specific notes we built earlier
                w1_notes = fighter1_notes if 'fighter1_notes' in locals() else bio_notes
                w2_notes = fighter2_notes if 'fighter2_notes' in locals() else bio_notes
            else:
                w1_notes = match['notes']
                w2_notes = match['notes']
            
            w1['matches'].append({**match, 'result': 'Draw', 
                                 'record': f"{w1['wins']}-{w1['losses']}-{w1['draws']}",
                                 'bio_notes': w1_notes})
            w2['matches'].append({**match, 'result': 'Draw', 
                                 'record': f"{w2['wins']}-{w2['losses']}-{w2['draws']}",
                                 'bio_notes': w2_notes})
        elif match['winner']:
            winner = w1 if match['winner'] == match['fighter1'] else w2
            loser = w2 if match['winner'] == match['fighter1'] else w1
            
            winner['wins'] += 1
            loser['losses'] += 1

            # Classify method: Pinfall, Submission, Draw, or Decision (anything else)
            method_lower = match['method'].lower()
            if 'pinfall' in method_lower:
                winner['pinfall_wins'] += 1
                loser['pinfall_losses'] += 1
            elif 'submission' in method_lower:
                winner['submission_wins'] += 1
                loser['submission_losses'] += 1
            elif 'draw' not in method_lower:
                # Anything that's not pinfall, submission, or draw = decision
                winner['decision_wins'] += 1
                loser['decision_losses'] += 1
            
            # Check for Lucha de Apuestas in notes
            if 'lucha de apuestas' in match['notes'].lower() or 'apuesta' in match['notes'].lower():
                winner['lucha_wins'] += 1
                
                # Parse wagers from notes (format: "X vs. Y")
                wager_match = re.search(r'(\w+(?:\s+\w+)?)\s+vs\.?\s+(\w+(?:\s+\w+)?)', match['notes'], re.IGNORECASE)
                if wager_match:
                    winner_wager = wager_match.group(1).strip()
                    loser_wager = wager_match.group(2).strip()
                    
                    self.apuestas.append({
                        'event': match['event'],
                        'winner': match['winner'],
                        'winner_wager': winner_wager,
                        'loser': match['loser'],
                        'loser_wager': loser_wager,
                        'venue': match.get('venue', ''),
                        'location': match['location'],
                        'location_country': match['location_country'],
                        'date': match['date']
                    })

            # Build loser notes if it was a title match
            if is_title and weight:
                loser_bio_notes = f"For {', '.join(retained_orgs + won_orgs)} {weight.capitalize()} Championship"
            else:
                loser_bio_notes = bio_notes

            winner['matches'].append({**match, 'result': 'Win', 
                                    'record': f"{winner['wins']}-{winner['losses']}-{winner['draws']}",
                                    'bio_notes': bio_notes})
            loser['matches'].append({**match, 'result': 'Loss', 
                                    'record': f"{loser['wins']}-{loser['losses']}-{loser['draws']}",
                                    'bio_notes': loser_bio_notes})

            # Check for championship
            self.check_championship_change(match)

    def check_championship_change(self, match):
        """Check if match involved a championship and update reigns properly."""
        is_title, orgs = self.is_title_match(match['notes'])
        if not is_title:
            return

        weights = ['heavyweight', 'bridgerweight', 'middleweight', 'welterweight', 'lightweight', 'featherweight']
        notes_lower = match['notes'].lower()
        weight = None
        for w in weights:
            if w in notes_lower or w in match['weight_class'].lower():
                weight = w
                break
        if not weight:
            return

        for org in orgs:
            current_reigns = self.championships[org][weight]
            last_reign = current_reigns[-1] if current_reigns else None

            # Determine if this is a new reign
            # Titles only change on pinfall, submission, or decision (not DQ/countout)
            method_lower = match['method'].lower()
            can_change_title = 'pinfall' in method_lower or 'submission' in method_lower or ('dq' not in method_lower and 'countout' not in method_lower and 'count out' not in method_lower and 'disqualification' not in method_lower)

            if match['winner'] and (not last_reign or last_reign['champion'] != match['winner']) and can_change_title:
                # Start new reign
                self.add_championship_reign(org, weight, match)
                # Set notes to opponent for the first match of reign
                current_reigns[-1]['notes'] = f"Def. {match['fighter2'] if match['winner']==match['fighter1'] else match['fighter1']}"
            elif last_reign:
                # Existing reign - check if champion retained (any result except pinfall/submission loss)
                method_lower = match['method'].lower()
                
                # Determine if champion lost the title (pinfall or submission loss)
                champion_lost = False
                if match['winner'] and match['winner'] != last_reign['champion']:
                    if 'pinfall' in method_lower or 'submission' in method_lower:
                        champion_lost = True
                
                # If champion didn't lose, it's a successful defense
                if not champion_lost:
                    last_reign['defenses'] += 1
                    # Days will be updated in reprocess_championships_chronologically()

    def add_championship_reign(self, org, weight, match):
        """Add new championship reign"""
        winner_country = match['fighter1_country'] if match['winner'] == match['fighter1'] else match['fighter2_country']
            
        champ = {
            'champion': match['winner'],
            'country': winner_country,
            'date': match['date'],
            'event': match['event'],
            'defenses': 0,  # Start at 0 - the win itself is not a defense
            'days': None,
            'notes': match['notes']
        }
        
        self.championships[org][weight].append(champ)
        
        wrestler = self.get_wrestler(match['winner'])
        wrestler['championships'].append({'org': org, 'weight': weight, 'date': match['date']})

    def process_vacancies(self):
        """Process vacancy comments and add them to championship history"""
        for vacancy in self.vacancies:
            org = vacancy['org']
            weight = vacancy['weight']
            
            # Add vacancy note to championship history
            current_reigns = self.championships[org][weight]
            if current_reigns:
                # Find the last reign that matches the vacating champion
                for reign in reversed(current_reigns):
                    if reign['champion'] == vacancy.get('champion', ''):
                        # Calculate days if we have both dates
                        if reign['date'] and vacancy['date']:
                            reign['days'] = self.days_between(reign['date'], vacancy['date'])
                        reign['vacancy_message'] = vacancy.get('message', 'Title vacated')
                        break

    def reprocess_championships_chronologically(self):
        """Reprocess all championship changes in chronological order to fix days calculation"""
        # Clear all championship data
        for org in self.championships:
            for weight in self.championships[org]:
                self.championships[org][weight] = []
        
        # Go through all events in chronological order
        for event in self.events:
            for match in event['matches']:
                # Reprocess this match's championship implications
                is_title, orgs = self.is_title_match(match['notes'])
                if not is_title or not match['winner']:
                    continue
                
                weights = ['heavyweight', 'bridgerweight', 'middleweight', 'welterweight', 'lightweight', 'featherweight']
                notes_lower = match['notes'].lower()
                weight = None
                for w in weights:
                    if w in notes_lower or w in match['weight_class'].lower():
                        weight = w
                        break
                if not weight:
                    continue
                
                for org in orgs:
                    current_reigns = self.championships[org][weight]
                    last_reign = current_reigns[-1] if current_reigns else None
                    
                    method_lower = match['method'].lower()
                    can_change_title = 'pinfall' in method_lower or 'submission' in method_lower or ('dq' not in method_lower and 'countout' not in method_lower and 'count out' not in method_lower and 'disqualification' not in method_lower)
                    
                    if match['winner'] and (not last_reign or last_reign['champion'] != match['winner']) and can_change_title:
                        # Start new reign
                        winner_country = match['fighter1_country'] if match['winner'] == match['fighter1'] else match['fighter2_country']
                        champ = {
                            'champion': match['winner'],
                            'country': winner_country,
                            'date': match['date'],
                            'event': match['event'],
                            'defenses': 0,
                            'days': None,
                            'notes': f"Def. {match['fighter2'] if match['winner']==match['fighter1'] else match['fighter1']}"
                        }
                        self.championships[org][weight].append(champ)
                    elif last_reign:
                        # Existing reign - check if it's a defense
                        champion_lost = False
                        if match['winner'] and match['winner'] != last_reign['champion']:
                            if 'pinfall' in method_lower or 'submission' in method_lower:
                                champion_lost = True
                        
                        if not champion_lost:
                            last_reign['defenses'] += 1
                            # Update days progressively (this is now in chronological order!)
                            if last_reign['date'] and match['date']:
                                last_reign['days'] = self.days_between(last_reign['date'], match['date'])

    def recalculate_bio_notes(self):
        """Recalculate bio_notes for all matches after championship reprocessing"""
        print("Recalculating bio notes in chronological order...")
        
        # Track current champion for each org/weight AS WE GO CHRONOLOGICALLY
        current_champions = {
            'wwf': {'heavyweight': None, 'bridgerweight': None, 'middleweight': None, 
                   'welterweight': None, 'lightweight': None, 'featherweight': None},
            'wwo': {'heavyweight': None, 'bridgerweight': None, 'middleweight': None, 
                   'welterweight': None, 'lightweight': None, 'featherweight': None},
            'iwb': {'heavyweight': None, 'bridgerweight': None, 'middleweight': None, 
                   'welterweight': None, 'lightweight': None, 'featherweight': None},
            'ring': {'heavyweight': None, 'bridgerweight': None, 'middleweight': None, 
                    'welterweight': None, 'lightweight': None, 'featherweight': None}
        }
        
        # Go through all events in chronological order
        for event in self.events:
            for match in event['matches']:
                # Check if this is a title match
                is_title, orgs = self.is_title_match(match['notes'])
                
                if not is_title or (not match['winner'] and not match['is_draw']):
                    continue
                
                # Find weight class
                weights = ['heavyweight', 'bridgerweight', 'middleweight', 'welterweight', 'lightweight', 'featherweight']
                notes_lower = match['notes'].lower()
                weight = None
                for w in weights:
                    if w in notes_lower or w in match['weight_class'].lower():
                        weight = w
                        break
                
                if not weight:
                    continue
                
                method_lower = match['method'].lower()
                can_change_title = 'pinfall' in method_lower or 'submission' in method_lower or ('dq' not in method_lower and 'countout' not in method_lower and 'count out' not in method_lower and 'disqualification' not in method_lower)
                
                if match['is_draw']:
                    # Handle draw - each fighter gets separate notes based on CURRENT state
                    fighter1_retained = []
                    fighter2_retained = []
                    
                    for org in orgs:
                        current_champ = current_champions[org][weight]
                        
                        if current_champ == match['fighter1']:
                            fighter1_retained.append('The Ring' if org == 'ring' else org.upper())
                        elif current_champ == match['fighter2']:
                            fighter2_retained.append('The Ring' if org == 'ring' else org.upper())
                    
                    fighter1_notes = self.format_title_notes(fighter1_retained, [], [], weight) if fighter1_retained else match['notes']
                    fighter2_notes = self.format_title_notes(fighter2_retained, [], [], weight) if fighter2_retained else match['notes']
                    
                    # Update notes in wrestler records
                    w1 = self.wrestlers.get(match['fighter1'])
                    w2 = self.wrestlers.get(match['fighter2'])
                    
                    if w1:
                        for m in w1['matches']:
                            if (m['event'] == match['event'] and 
                                m['date'] == match['date'] and 
                                m['fighter1'] == match['fighter1'] and 
                                m['fighter2'] == match['fighter2']):
                                m['bio_notes'] = fighter1_notes
                    
                    if w2:
                        for m in w2['matches']:
                            if (m['event'] == match['event'] and 
                                m['date'] == match['date'] and 
                                m['fighter1'] == match['fighter1'] and 
                                m['fighter2'] == match['fighter2']):
                                m['bio_notes'] = fighter2_notes
                
                else:
                    # Non-draw title match - check CURRENT championship state
                    retained_orgs = []
                    won_orgs = []
                    for_orgs = []
                    
                    for org in orgs:
                        current_champ = current_champions[org][weight]
                        
                        # Is the winner ALREADY the champion?
                        if current_champ == match['winner']:
                            # Already champ = retained
                            retained_orgs.append('The Ring' if org == 'ring' else org.upper())
                        else:
                            # Not champ = won (or for if can't change title)
                            if can_change_title:
                                won_orgs.append('The Ring' if org == 'ring' else org.upper())
                                # UPDATE championship state since title changed!
                                current_champions[org][weight] = match['winner']
                            else:
                                for_orgs.append('The Ring' if org == 'ring' else org.upper())
                    
                    bio_notes = self.format_title_notes(retained_orgs, won_orgs, for_orgs, weight)
                    
                    # Update notes in wrestler records
                    winner_name = match['winner']
                    loser_name = match['loser']
                    
                    winner = self.wrestlers.get(winner_name)
                    loser = self.wrestlers.get(loser_name)
                    
                    if winner:
                        for m in winner['matches']:
                            if (m['event'] == match['event'] and 
                                m['date'] == match['date'] and 
                                m['fighter1'] == match['fighter1'] and 
                                m['fighter2'] == match['fighter2'] and
                                m['result'] == 'Win'):
                                m['bio_notes'] = bio_notes
                    
                    if loser:
                        # Loser sees "For" version
                        loser_notes = self.format_title_notes([], [], retained_orgs + won_orgs, weight) if (retained_orgs or won_orgs) else bio_notes
                        for m in loser['matches']:
                            if (m['event'] == match['event'] and 
                                m['date'] == match['date'] and 
                                m['fighter1'] == match['fighter1'] and 
                                m['fighter2'] == match['fighter2'] and
                                m['result'] == 'Loss'):
                                m['bio_notes'] = loser_notes

    def calculate_championship_days(self):
        """Calculate days held for each championship reign"""
        # Find the most recent event date across all events
        most_recent_date = None
        for event in self.events:
            if event.get('date'):
                event_date = self.parse_date(event['date'])
                if event_date:
                    if not most_recent_date or event_date > most_recent_date:
                        most_recent_date = event_date
        
        for org in self.championships:
            for weight in self.championships[org]:
                reigns = self.championships[org][weight]
                
                for i in range(len(reigns)):
                    if reigns[i]['days'] is not None:
                        # Days already set (from reprocessing or vacancy)
                        continue
                    
                    # Calculate days to next reign OR to most recent event if current champ
                    if i < len(reigns) - 1:
                        # Not current champ - calculate to next reign
                        reigns[i]['days'] = self.days_between(reigns[i]['date'], reigns[i + 1]['date'])
                    else:
                        # Current champ - calculate to most recent event date
                        if most_recent_date and reigns[i]['date']:
                            start_date = self.parse_date(reigns[i]['date'])
                            if start_date:
                                reigns[i]['days'] = (most_recent_date - start_date).days

    def generate_wrestler_page(self, wrestler_name):
        """Generate wrestler page HTML"""
        w = self.wrestlers[wrestler_name]
        total_bouts = w['wins'] + w['losses'] + w['draws']
        
        # Sort matches in chronological order (oldest first) to calculate running record
        chronological_matches = sorted(
            w['matches'], 
            key=lambda x: self.parse_date(x['date']) if x.get('date') else datetime.min,
            reverse=False  # Oldest first
        )
        
        # Recalculate running record in chronological order
        running_wins = 0
        running_losses = 0
        running_draws = 0
        
        for match in chronological_matches:
            if match['result'] == 'Win':
                running_wins += 1
            elif match['result'] == 'Loss':
                running_losses += 1
            elif match['result'] == 'Draw':
                running_draws += 1
            
            # Update the match with the correct chronological record
            match['record'] = f"{running_wins}-{running_losses}-{running_draws}"
        
        # Now reverse for display (newest first)
        sorted_matches = list(reversed(chronological_matches))

        html = "<h3>Professional wrestling record</h3>\n\n"
        
        # Summary table
        html += '<table class="matchesum">\n'
        html += '    <tbody><tr>\n'
        html += f'        <th>{total_bouts} fights</th>\n'
        html += f'        <th>{w["wins"]} wins</th>\n'
        html += f'        <th>{w["losses"]} losses</th>\n'
        html += '    </tr>\n'
        html += '    <tr>\n'
        html += '        <th style="text-align: left;"> By pinfall</th>\n'
        html += f'        <td class="win">{w["pinfall_wins"]}</td>\n'
        html += f'        <td class="loss">{w["pinfall_losses"]}</td>\n'
        html += '    </tr>\n'
        html += '    <tr>\n'
        html += '        <th style="text-align: left;"> By submission</th>\n'
        html += f'        <td class="win">{w["submission_wins"]}</td>\n'
        html += f'        <td class="loss">{w["submission_losses"]}</td>\n'
        html += '    </tr>\n'
        html += '    <tr>\n'
        html += '        <th style="text-align: left;"> By decision</th>\n'
        html += f'        <td class="win">{w["decision_wins"]}</td>\n'
        html += f'        <td class="loss">{w["decision_losses"]}</td>\n'
        html += '    </tr>\n'
        html += '    <tr>\n'
        html += '        <th style="text-align: left;"> Draws</th>\n'
        html += f'        <td colspan="2" class="draw">{w["draws"]}</td>\n'
        html += '    </tr>\n'
        html += '</tbody></table>\n\n'

        # Matches table
        html += '<table class="matches">\n'
        html += '    <tbody><tr>\n'
        html += '        <th>No.</th>\n'
        html += '        <th>Res.</th>\n'
        html += '        <th>Record</th>\n'
        html += '        <th>Opponent</th>\n'
        html += '        <th>Method</th>\n'
        html += '        <th>Date</th>\n'
        html += '        <th>Event</th>\n'
        html += '        <th>Location</th>\n'
        html += '        <th>Notes</th>\n'
        html += '    </tr>\n'

        for idx, match in enumerate(sorted_matches):
            opponent = match['fighter2'] if match['fighter1'] == w['name'] else match['fighter1']
            opponent_country = match['fighter2_country'] if match['fighter1'] == w['name'] else match['fighter1_country']
            result_class = match['result'].lower()
            
            html += '    <tr>\n'
            html += f'        <th>{total_bouts - idx}</th>\n'
            html += f'        <td class="{result_class}">{match["result"]}</td>\n'
            html += f'        <td>{match["record"]}</td>\n'
            html += f'        <td><span class="fi fi-{opponent_country}"></span> {opponent}</td>\n'
            html += f'        <td>{match["method"]}</td>\n'
            html += f'        <td>{match["date"]}</td>\n'
            html += f'        <td>{match["event"]}</td>\n'
            html += f'        <td><span class="fi fi-{match["location_country"]}"></span> {match["location"]}</td>\n'
            html += f'        <td>{match.get("bio_notes", match["notes"])}</td>\n'
            html += '    </tr>\n'

        html += '</tbody></table>\n'
        return html

    def generate_championship_history_html(self, org, weight):
        """Generate championship history table for an org/weight"""
        reigns = self.championships[org][weight]
        if not reigns:
            return ''
        
        # Calculate totals per wrestler
        totals = defaultdict(lambda: {'reigns': 0, 'days': 0, 'defenses': 0, 'country': 'un'})
        
        for reign in reigns:
            champ = reign['champion']
            totals[champ]['reigns'] += 1
            totals[champ]['days'] += reign['days'] if reign['days'] else 0
            totals[champ]['defenses'] += reign['defenses']
            totals[champ]['country'] = reign['country']
        
        # Sort by total days
        sorted_totals = sorted(totals.items(), key=lambda x: x[1]['days'], reverse=True)
        
        # Build history table
        html = f'    <!-- {org.upper()} {weight.capitalize()} Championship -->\n'
        html += '    <details>\n'
        org_display = 'The Ring' if org == 'ring' else org.upper()
        html += f'    <summary>{org_display} World {weight.capitalize()} Champion</summary>\n'
        html += '        <table class="champ-history">\n'
        html += '        <tr>\n'
        html += '            <th>No.</th>\n'
        html += '            <th>Champion</th>\n'
        html += '            <th>Date</th>\n'
        html += '            <th>Event</th>\n'
        html += '            <th>Days</th>\n'
        html += '            <th>Defenses</th>\n'
        html += '            <th>Notes</th>\n'
        html += '        </tr>\n'
        
        for idx, reign in enumerate(reigns):
            html += '        <tr>\n'
            html += f'            <th>{idx + 1}</th>\n'
            html += f'            <td><span class="fi fi-{reign["country"]}"></span> {reign["champion"]}</td>\n'
            html += f'            <td>{reign["date"]}</td>\n'
            html += f'            <td>{reign["event"]}</td>\n'
            days_display = self.format_number(reign["days"]) if reign["days"] else "0"
            html += f'            <td>{days_display}</td>\n'
            html += f'            <td>{reign["defenses"]}</td>\n'
            html += f'            <td>{reign["notes"]}</td>\n'
            html += '        </tr>\n'
            
            # Add vacancy message if exists
            if 'vacancy_message' in reign:
                html += '        <tr>\n'
                html += f'            <th colspan="7" style="font-size:0.8em; line-height:1.3; text-align:center;">\n'
                html += f'                {reign["vacancy_message"]}\n'
                html += '            </th>\n'
                html += '        </tr>\n'
        
        html += '    </table>\n'
        
        # Totals table
        html += '    <!-- Champ Totals Table -->\n'
        html += '        <table style="width: 75%;" class="totals">\n'
        html += '        <tr>\n'
        html += '            <th>Rank</th>\n'
        html += '            <th>Wrestler</th>\n'
        html += '            <th>No. of reigns</th>\n'
        html += '            <th>Total days</th>\n'
        html += '            <th>Defenses</th>\n'
        html += '        </tr>\n'
        
        for idx, (champ, stats) in enumerate(sorted_totals):
            html += '        <tr>\n'
            html += f'            <th>{idx + 1}</th>\n'
            html += f'            <td><span class="fi fi-{stats["country"]}"></span> {champ}</td>\n'
            html += f'            <td>{stats["reigns"]}</td>\n'
            html += f'            <td>{self.format_number(stats["days"])}</td>\n'
            html += f'            <td>{stats["defenses"]}</td>\n'
            html += '        </tr>\n'
        
        html += '    </table>\n'
        html += '    </details>\n\n'
        
        return html

    def generate_current_champions_html(self):
        """Generate current champions summary"""
        weights = {
            'heavyweight': '(224+ lb / 102+ kg)',
            'bridgerweight': '(224 lb / 102 kg)',
            'middleweight': '(202 lb / 92 kg)',
            'welterweight': '(180 lb / 82 kg)',
            'lightweight': '(+140 lb / +64 kg)',
            'featherweight': '(140 lb / 64 kg)'
        }

        html = ''
        for weight, limit in weights.items():
            html += f'    <!-- {weight.capitalize()} Champions -->\n'
            html += '    <table>\n'
            html += f'    <caption>{weight.capitalize()} {limit}</caption>\n'
            html += '        <tbody><tr>\n'
            html += '            <th style="width: 25%;">WWF</th>\n'
            html += '            <th style="width: 25%;">WWO</th>\n'
            html += '            <th style="width: 25%;">IWB</th>\n'
            html += '            <th style="width: 25%;"><i>The Ring</i></th>\n'
            html += '        </tr>\n'
            html += '        <tr>\n'

            for org in ['wwf', 'wwo', 'iwb', 'ring']:
                reigns = self.championships[org][weight]
                if reigns:
                    current = reigns[-1]
                    wrestler = self.wrestlers.get(current['champion'])
                    if wrestler:
                        record = f"{wrestler['wins']}-{wrestler['losses']}-{wrestler['draws']}"
                    else:
                        record = f"{current['defenses']} Defenses"
                    html += f'            <td style="width: 25%;"> <span class="fi fi-{current["country"]}"></span> {current["champion"]} <br> {record} <br> {current["date"]}</td>\n'
                else:
                    html += '            <td style="width: 25%;"> <span class="fi fi-xx"></span> Vacant <br> Record <br> Date</td>\n'

            html += '        </tr>\n'
            html += '    </tbody></table>\n\n'

        return html

    def generate_records_html(self):
        """Generate all records page HTML"""
        html = self.generate_singles_records_html()
        html += self.generate_statistics_records_html()
        html += self.generate_world_titles_records_html()
        html += self.generate_streaks_records_html()
        html += self.generate_event_records_html()
        html += self.generate_apuestas_html()
        html += self.generate_drawing_power_html()
        html += self.generate_broadcast_records_html()
        html += self.generate_attendance_records_html()
        return html

    def generate_apuestas_html(self):
        """Generate Lucha de Apuestas table"""
        if not self.apuestas:
            return ''
        
        # Sort by date (most recent first)
        sorted_apuestas = sorted(
            self.apuestas,
            key=lambda x: self.parse_date(x['date']) if x.get('date') else datetime.min,
            reverse=True
        )
        
        html = '    <!-- Apuestas Records -->\n'
        html += '    <details>\n'
        html += '    <summary>Lucha de Apuestas</summary>\n'
        html += '    <table class="match-card">\n'
        html += '    <thead>\n'
        html += '        <tr>\n'
        html += '            <th>No.</th>\n'
        html += '            <th>Event</th>\n'
        html += '            <th>Winner</th>\n'
        html += '            <th>Wager</th>\n'
        html += '            <th>Loser</th>\n'
        html += '            <th>Wager</th>\n'
        html += '            <th>Venue</th>\n'
        html += '            <th>Location</th>\n'
        html += '            <th>Date</th>\n'
        html += '        </tr>\n'
        html += '    </thead>\n'
        html += '    <tbody>\n'
        
        for idx, apuesta in enumerate(sorted_apuestas):
            html += '        <tr>\n'
            html += f'            <th>{idx + 1}</th>\n'
            html += f'            <td>{apuesta["event"]}</td>\n'
            html += f'            <td>{apuesta["winner"]}</td>\n'
            html += f'            <td>{apuesta["winner_wager"]}</td>\n'
            html += f'            <td>{apuesta["loser"]}</td>\n'
            html += f'            <td>{apuesta["loser_wager"]}</td>\n'
            html += f'            <td>{apuesta.get("venue", "")}</td>\n'
            html += f'            <td><span class="fi fi-{apuesta["location_country"]}"></span> {apuesta["location"]}</td>\n'
            html += f'            <td>{apuesta["date"]}</td>\n'
            html += '        </tr>\n'
        
        html += '    </tbody>\n'
        html += '    </table>\n'
        html += '    </details>\n\n'
        
        return html

    def generate_streaks_records_html(self):
        """Generate streaks records table - consecutive wins, losses, defenses, days"""
        wrestler_list = list(self.wrestlers.values())
        
        # Calculate consecutive streaks for each wrestler
        max_consecutive_wins = defaultdict(lambda: {'max_wins': 0, 'country': 'xx'})
        max_consecutive_losses = defaultdict(lambda: {'max_losses': 0, 'country': 'xx'})
        
        for w in wrestler_list:
            name = w['name']
            max_consecutive_wins[name]['country'] = w['country']
            max_consecutive_losses[name]['country'] = w['country']
            
            # Calculate consecutive wins and losses from match history
            current_win_streak = 0
            current_loss_streak = 0
            
            # Sort chronologically
            chronological_matches = sorted(
                w['matches'],
                key=lambda x: self.parse_date(x['date']) if x.get('date') else datetime.min,
                reverse=False
            )
            
            for match in chronological_matches:
                if match['result'] == 'Win':
                    current_win_streak += 1
                    current_loss_streak = 0
                    if current_win_streak > max_consecutive_wins[name]['max_wins']:
                        max_consecutive_wins[name]['max_wins'] = current_win_streak
                elif match['result'] == 'Loss':
                    current_loss_streak += 1
                    current_win_streak = 0
                    if current_loss_streak > max_consecutive_losses[name]['max_losses']:
                        max_consecutive_losses[name]['max_losses'] = current_loss_streak
                else:  # Draw
                    current_win_streak = 0
                    current_loss_streak = 0
        
        # Get consecutive title stats from world titles function
        max_cons_defenses = defaultdict(lambda: {'max_defenses': 0, 'country': 'xx'})
        max_cons_days = defaultdict(lambda: {'max_days': 0, 'country': 'xx'})
        
        for org in ['wwf', 'wwo', 'iwb', 'ring']:
            for weight in ['heavyweight', 'bridgerweight', 'middleweight', 'welterweight', 'lightweight', 'featherweight']:
                for reign in self.championships[org][weight]:
                    champ = reign['champion']
                    if champ in self.wrestlers:
                        if reign['defenses'] > max_cons_defenses[champ]['max_defenses']:
                            max_cons_defenses[champ]['max_defenses'] = reign['defenses']
                            max_cons_defenses[champ]['country'] = reign['country']
                        if reign.get('days', 0) > max_cons_days[champ]['max_days']:
                            max_cons_days[champ]['max_days'] = reign.get('days', 0)
                            max_cons_days[champ]['country'] = reign['country']
        
        # Top 5 lists
        top_cons_wins = sorted(max_consecutive_wins.items(), key=lambda x: x[1]['max_wins'], reverse=True)[:5]
        top_cons_losses = sorted(max_consecutive_losses.items(), key=lambda x: x[1]['max_losses'], reverse=True)[:5]
        top_cons_defenses = sorted(max_cons_defenses.items(), key=lambda x: x[1]['max_defenses'], reverse=True)[:5]
        top_cons_days = sorted(max_cons_days.items(), key=lambda x: x[1]['max_days'], reverse=True)[:5]
        
        html = '    <!-- Streaks Records -->\n'
        html += '    <details>\n'
        html += '    <summary>Streaks</summary>\n'
        html += '    <table class="records">\n'
        html += '    <thead>\n'
        html += '        <tr>\n'
        html += '            <th rowspan="2">No.</th>\n'
        html += '            <th colspan="2">Consecutive Wins</th>\n'
        html += '            <th colspan="2">Consecutive Losses</th>\n'
        html += '            <th colspan="2">Consecutive Title Defenses</th>\n'
        html += '            <th colspan="2">Consecutive Days as Champion</th>\n'
        html += '        </tr>\n'
        html += '        <tr>\n'
        html += '            <th>Name</th><th>#</th>\n' * 4
        html += '        </tr>\n'
        html += '    </thead>\n'
        html += '    <tbody>\n'
        
        for i in range(5):
            html += '        <tr>\n'
            html += f'            <th>{i+1}</th>\n'
            
            # Consecutive Wins
            if i < len(top_cons_wins):
                name, stats = top_cons_wins[i]
                html += f'            <td><span class="fi fi-{stats["country"]}"></span> {name} </td><td>{stats["max_wins"]}</td>\n'
            else:
                html += '            <td><span class="fi fi-xx"></span> Vacant </td><td>0</td>\n'
            
            # Consecutive Losses
            if i < len(top_cons_losses):
                name, stats = top_cons_losses[i]
                html += f'            <td><span class="fi fi-{stats["country"]}"></span> {name} </td><td>{stats["max_losses"]}</td>\n'
            else:
                html += '            <td><span class="fi fi-xx"></span> Vacant </td><td>0</td>\n'
            
            # Consecutive Defenses
            if i < len(top_cons_defenses):
                name, stats = top_cons_defenses[i]
                html += f'            <td><span class="fi fi-{stats["country"]}"></span> {name} </td><td>{stats["max_defenses"]}</td>\n'
            else:
                html += '            <td><span class="fi fi-xx"></span> Vacant </td><td>0</td>\n'
            
            # Consecutive Days
            if i < len(top_cons_days):
                name, stats = top_cons_days[i]
                html += f'            <td><span class="fi fi-{stats["country"]}"></span> {name} </td><td>{self.format_number(stats["max_days"])}</td>\n'
            else:
                html += '            <td><span class="fi fi-xx"></span> Vacant </td><td>0</td>\n'
            
            html += '        </tr>\n'
        
        html += '    </tbody>\n'
        html += '    </table>\n'
        html += '    </details>\n\n'
        
        return html

    def generate_singles_records_html(self):
        """Generate singles records table"""
        wrestler_list = list(self.wrestlers.values())

        # Singles Records
        top_bouts = sorted(wrestler_list, key=lambda x: x['wins'] + x['losses'] + x['draws'], reverse=True)[:5]
        top_wins = sorted(wrestler_list, key=lambda x: x['wins'], reverse=True)[:5]
        top_pinfall = sorted(wrestler_list, key=lambda x: x['pinfall_wins'], reverse=True)[:5]
        top_submission = sorted(wrestler_list, key=lambda x: x['submission_wins'], reverse=True)[:5]
        top_lucha = sorted(wrestler_list, key=lambda x: x['lucha_wins'], reverse=True)[:5]

        html = '    <!-- Singles Records -->\n'
        html += '    <details>\n'
        html += '    <summary>Singles</summary>\n'
        html += '    <table class="records">\n'
        html += '    <thead>\n'
        html += '        <tr>\n'
        html += '            <th rowspan="2" style="width: 5%;">No.</th>\n'
        html += '            <th colspan="2" style="width: 19%;">Bouts</th>\n'
        html += '            <th colspan="2" style="width: 19%;">Wins</th>\n'
        html += '            <th colspan="2" style="width: 19%;">Pinfall Wins</th>\n'
        html += '            <th colspan="2" style="width: 19%;">Submission Wins</th>\n'
        html += '            <th colspan="2" style="width: 19%;"><i>Lucha de Apuestas</i> Wins</th>\n'
        html += '        </tr>\n'
        html += '        <tr>\n'
        html += '            <th style="width: 14%;">Name</th><th style="width: 5%;">#</th>\n' * 5
        html += '        </tr>\n'
        html += '    </thead>\n'
        html += '    <tbody>\n'

        for i in range(5):
            html += '        <tr>\n'
            html += f'            <th>{i+1}</th>\n'
            
            for top_list, stat_key in [(top_bouts, None), (top_wins, 'wins'), (top_pinfall, 'pinfall_wins'), 
                                        (top_submission, 'submission_wins'), (top_lucha, 'lucha_wins')]:
                if i < len(top_list):
                    w = top_list[i]
                    if stat_key:
                        stat = w[stat_key]
                    else:
                        stat = w['wins'] + w['losses'] + w['draws']
                    html += f'            <td><span class="fi fi-{w["country"]}"></span> {w["name"]} </td><td>{stat}</td>\n'
                else:
                    html += '            <td><span class="fi fi-xx"></span> Vacant </td><td>0</td>\n'
            
            html += '        </tr>\n'

        html += '    </tbody>\n'
        html += '    </table>\n'
        html += '    </details>\n\n'

        return html

    def generate_statistics_records_html(self):
        """Generate statistics percentage records table"""
        wrestler_list = list(self.wrestlers.values())
        
        # Calculate percentages for wrestlers with at least 5 bouts
        wrestlers_with_stats = []
        for w in wrestler_list:
            total_bouts = w['wins'] + w['losses'] + w['draws']
            if total_bouts >= 5:  # Minimum 5 bouts to qualify
                win_pct = (w['wins'] / total_bouts * 100) if total_bouts > 0 else 0
                loss_pct = (w['losses'] / total_bouts * 100) if total_bouts > 0 else 0
                draw_pct = (w['draws'] / total_bouts * 100) if total_bouts > 0 else 0
                
                total_wins = w['wins']
                pin_win_pct = (w['pinfall_wins'] / total_wins * 100) if total_wins > 0 else 0
                sub_win_pct = (w['submission_wins'] / total_wins * 100) if total_wins > 0 else 0
                
                wrestlers_with_stats.append({
                    'name': w['name'],
                    'country': w['country'],
                    'win_pct': win_pct,
                    'loss_pct': loss_pct,
                    'draw_pct': draw_pct,
                    'pin_win_pct': pin_win_pct,
                    'sub_win_pct': sub_win_pct
                })
        
        # Top 5 lists
        top_win_pct = sorted(wrestlers_with_stats, key=lambda x: x['win_pct'], reverse=True)[:5]
        top_loss_pct = sorted(wrestlers_with_stats, key=lambda x: x['loss_pct'], reverse=True)[:5]
        top_draw_pct = sorted(wrestlers_with_stats, key=lambda x: x['draw_pct'], reverse=True)[:5]
        top_pin_win_pct = sorted(wrestlers_with_stats, key=lambda x: x['pin_win_pct'], reverse=True)[:5]
        top_sub_win_pct = sorted(wrestlers_with_stats, key=lambda x: x['sub_win_pct'], reverse=True)[:5]
        
        html = '    <!-- Statistics Records -->\n'
        html += '    <details>\n'
        html += '    <summary>Percentage</summary>\n'
        html += '    <table class="records">\n'
        html += '    <thead>\n'
        html += '        <tr>\n'
        html += '            <th rowspan="2" style="width: 5%;">No.</th>\n'
        html += '            <th colspan="2" style="width: 19%;">Win %</th>\n'
        html += '            <th colspan="2" style="width: 19%;">Loss %</th>\n'
        html += '            <th colspan="2" style="width: 19%;">Draw %</th>\n'
        html += '            <th colspan="2" style="width: 19%;">Pinfall Win %</th>\n'
        html += '            <th colspan="2" style="width: 19%;">Submission Win %</th>\n'
        html += '        </tr>\n'
        html += '        <tr>\n'
        html += '            <th style="width: 14%;">Name</th><th style="width: 5%;">%</th>\n' * 5
        html += '        </tr>\n'
        html += '    </thead>\n'
        html += '    <tbody>\n'
        
        for i in range(5):
            html += '        <tr>\n'
            html += f'            <th>{i+1}</th>\n'
            
            for top_list, stat_key in [(top_win_pct, 'win_pct'), (top_loss_pct, 'loss_pct'), 
                                        (top_draw_pct, 'draw_pct'), (top_pin_win_pct, 'pin_win_pct'), 
                                        (top_sub_win_pct, 'sub_win_pct')]:
                if i < len(top_list):
                    w = top_list[i]
                    stat = f"{w[stat_key]:.1f}%"
                    html += f'            <td><span class="fi fi-{w["country"]}"></span> {w["name"]} </td><td>{stat}</td>\n'
                else:
                    html += '            <td><span class="fi fi-xx"></span> Vacant </td><td>0.0%</td>\n'
            
            html += '        </tr>\n'
        
        html += '    </tbody>\n'
        html += '    </table>\n'
        html += '    </details>\n\n'
        
        return html

    def generate_world_titles_records_html(self):
        """Generate world titles records table - treating overlapping reigns as ONE continuous reign"""
        # Key insight: If a wrestler holds ANY world title continuously (even if specific belts change),
        # it's ONE reign. Adding a belt mid-reign doesn't create a new reign.
        
        wrestler_reigns = defaultdict(list)
        
        # Collect all reigns organized by wrestler with start and end dates
        for org in ['wwf', 'wwo', 'iwb', 'ring']:
            for weight in ['heavyweight', 'bridgerweight', 'middleweight', 'welterweight', 'lightweight', 'featherweight']:
                for idx, reign in enumerate(self.championships[org][weight]):
                    start_date = self.parse_date(reign['date'])
                    if not start_date:
                        continue
                    
                    # Calculate end date
                    if reign['days']:
                        end_date = start_date + __import__('datetime').timedelta(days=reign['days'])
                    else:
                        # No end date means current champion or missing data - use start date
                        end_date = start_date
                    
                    wrestler_reigns[reign['champion']].append({
                        'org': org,
                        'weight': weight,
                        'start_date': start_date,
                        'end_date': end_date,
                        'defenses': reign['defenses'],
                        'days': reign['days'] if reign['days'] else 0,
                        'country': reign['country']
                    })
        
        # Calculate totals per wrestler by merging overlapping time periods
        totals = defaultdict(lambda: {'total_reigns': 0, 'total_defenses': 0, 'total_days': 0, 'country': 'un', 'unique_opponents': set(), 'title_bouts': 0})
        max_cons_defenses = defaultdict(lambda: {'max_defenses': 0, 'country': 'un'})
        max_cons_days = defaultdict(lambda: {'max_days': 0, 'country': 'un'})
        
        # Also track all title matches for each wrestler
        for event in self.events:
            for match in event['matches']:
                is_title, orgs = self.is_title_match(match['notes'])
                if is_title and match['winner']:
                    # Check if this is a world title (one of our tracked orgs)
                    if any(org in ['wwf', 'wwo', 'iwb', 'ring'] for org in orgs):
                        fighter1 = match['fighter1']
                        fighter2 = match['fighter2']
                        
                        # Track title bouts and unique opponents for both fighters
                        if fighter1 in wrestler_reigns or fighter2 in wrestler_reigns:
                            if fighter1 in wrestler_reigns:
                                totals[fighter1]['title_bouts'] += 1
                                totals[fighter1]['unique_opponents'].add(fighter2)
                            if fighter2 in wrestler_reigns:
                                totals[fighter2]['title_bouts'] += 1
                                totals[fighter2]['unique_opponents'].add(fighter1)
        
        for champ, reigns in wrestler_reigns.items():
            # Sort reigns by start date
            sorted_reigns = sorted(reigns, key=lambda x: x['start_date'])
            
            # Merge overlapping/adjacent reigns into continuous championship periods
            merged_periods = []
            
            for reign in sorted_reigns:
                if not merged_periods:
                    # First reign - start a new period
                    merged_periods.append({
                        'start': reign['start_date'],
                        'end': reign['end_date'],
                        'defenses': reign['defenses'],
                        'country': reign['country'],
                        'belts': [{'org': reign['org'], 'weight': reign['weight'], 'defenses': reign['defenses']}]
                    })
                else:
                    last_period = merged_periods[-1]
                    
                    # Check if this reign overlaps with or is adjacent to the last period
                    # Overlap: new reign starts BEFORE or AT the moment the last one ends
                    if reign['start_date'] <= last_period['end']:
                        # Overlapping - this is part of the same continuous championship period
                        
                        # Extend the end date if this reign goes longer
                        if reign['end_date'] > last_period['end']:
                            last_period['end'] = reign['end_date']
                        
                        # Add this belt to the period
                        last_period['belts'].append({'org': reign['org'], 'weight': reign['weight'], 'defenses': reign['defenses']})
                        
                        # Defenses = MAX defenses from any belt (since they're defended together)
                        last_period['defenses'] = max(b['defenses'] for b in last_period['belts'])
                    else:
                        # Gap between reigns - this is a NEW championship period
                        merged_periods.append({
                            'start': reign['start_date'],
                            'end': reign['end_date'],
                            'defenses': reign['defenses'],
                            'country': reign['country'],
                            'belts': [{'org': reign['org'], 'weight': reign['weight'], 'defenses': reign['defenses']}]
                        })
            
            # Calculate stats from merged periods
            total_belts_won = 0
            for period in merged_periods:
                period_days = (period['end'] - period['start']).days
                
                # Count total belts won in this period
                total_belts_won += len(period['belts'])
                
                # Track totals
                totals[champ]['total_defenses'] += period['defenses']
                totals[champ]['total_days'] += period_days
                totals[champ]['country'] = period['country']
                
                # Track max consecutive values
                if period['defenses'] > max_cons_defenses[champ]['max_defenses']:
                    max_cons_defenses[champ]['max_defenses'] = period['defenses']
                    max_cons_defenses[champ]['country'] = period['country']
                
                if period_days > max_cons_days[champ]['max_days']:
                    max_cons_days[champ]['max_days'] = period_days
                    max_cons_days[champ]['country'] = period['country']
            
            # Total reigns = total number of individual belts won across all periods
            totals[champ]['total_reigns'] = total_belts_won
        
        # Top 5 lists
        top_reigns = sorted(totals.items(), key=lambda x: x[1]['total_reigns'], reverse=True)[:5]
        top_defenses = sorted(totals.items(), key=lambda x: x[1]['total_defenses'], reverse=True)[:5]
        top_days = sorted(totals.items(), key=lambda x: x[1]['total_days'], reverse=True)[:5]
        top_unique_opponents = sorted(totals.items(), key=lambda x: len(x[1]['unique_opponents']), reverse=True)[:5]
        top_title_bouts = sorted(totals.items(), key=lambda x: x[1]['title_bouts'], reverse=True)[:5]
        
        # Build HTML
        html = '    <!-- World Titles Records -->\n'
        html += '    <details>\n'
        html += '    <summary>World Titles</summary>\n'
        html += '    <table class="records">\n'
        html += '    <thead>\n'
        html += '        <tr>\n'
        html += '            <th rowspan="2">No.</th>\n'
        html += '            <th colspan="2">Titles Won</th>\n'
        html += '            <th colspan="2">Title Defenses</th>\n'
        html += '            <th colspan="2">Days as Champion</th>\n'
        html += '            <th colspan="2">Unique Opponents</th>\n'
        html += '            <th colspan="2">Title Bouts</th>\n'
        html += '        </tr>\n'
        html += '        <tr>\n'
        html += '            <th>Name</th><th>#</th>\n' * 5
        html += '        </tr>\n'
        html += '    </thead>\n'
        html += '    <tbody>\n'
        
        for i in range(5):
            html += '        <tr>\n'
            html += f'            <th>{i+1}</th>\n'
            
            # World Titles Won
            if i < len(top_reigns):
                champ, stats = top_reigns[i]
                html += f'            <td><span class="fi fi-{stats["country"]}"></span> {champ} </td><td>{stats["total_reigns"]}</td>\n'
            else:
                html += '            <td><span class="fi fi-xx"></span> Vacant </td><td>0</td>\n'
            
            # World Title Defenses
            if i < len(top_defenses):
                champ, stats = top_defenses[i]
                html += f'            <td><span class="fi fi-{stats["country"]}"></span> {champ} </td><td>{stats["total_defenses"]}</td>\n'
            else:
                html += '            <td><span class="fi fi-xx"></span> Vacant </td><td>0</td>\n'
            
            # Total Days
            if i < len(top_days):
                champ, stats = top_days[i]
                html += f'            <td><span class="fi fi-{stats["country"]}"></span> {champ} </td><td>{self.format_number(stats["total_days"])}</td>\n'
            else:
                html += '            <td><span class="fi fi-xx"></span> Vacant </td><td>0</td>\n'
            
            # Unique Opponents
            if i < len(top_unique_opponents):
                champ, stats = top_unique_opponents[i]
                html += f'            <td><span class="fi fi-{stats["country"]}"></span> {champ} </td><td>{len(stats["unique_opponents"])}</td>\n'
            else:
                html += '            <td><span class="fi fi-xx"></span> Vacant </td><td>0</td>\n'
            
            # Title Bouts
            if i < len(top_title_bouts):
                champ, stats = top_title_bouts[i]
                html += f'            <td><span class="fi fi-{stats["country"]}"></span> {champ} </td><td>{stats["title_bouts"]}</td>\n'
            else:
                html += '            <td><span class="fi fi-xx"></span> Vacant </td><td>0</td>\n'
            
            html += '        </tr>\n'
        
        html += '    </tbody>\n'
        html += '    </table>\n'
        html += '    </details>\n\n'
        
        return html

    def generate_event_records_html(self):
        """Generate event records table"""
        wrestler_list = list(self.wrestlers.values())
        
        top_ppv = sorted(wrestler_list, key=lambda x: x['main_events'], reverse=True)[:5]
        top_wm = sorted(wrestler_list, key=lambda x: x['wrestlemania_main_events'], reverse=True)[:5]
        top_lm = sorted(wrestler_list, key=lambda x: x['libremania_main_events'], reverse=True)[:5]
        top_open = sorted(wrestler_list, key=lambda x: x['open_tournament_wins'], reverse=True)[:5]
        top_trios = sorted(wrestler_list, key=lambda x: x['trios_tournament_wins'], reverse=True)[:5]
        
        html = '    <!-- Event Records -->\n'
        html += '    <details>\n'
        html += '    <summary>Events</summary>\n'
        html += '    <table class="records">\n'
        html += '    <thead>\n'
        html += '        <tr>\n'
        html += '            <th rowspan="2">No.</th>\n'
        html += '            <th colspan="2">PPV Main Events</th>\n'
        html += '            <th colspan="2">WrestleMania Main Events</th>\n'
        html += '            <th colspan="2">LibreMania Main Events</th>\n'
        html += '            <th colspan="2">Open Tournament Wins</th>\n'
        html += '            <th colspan="2">Trios Tournament Wins</th>\n'
        html += '        </tr>\n'
        html += '        <tr>\n'
        html += '            <th>Name</th><th>#</th>\n' * 5
        html += '        </tr>\n'
        html += '    </thead>\n'
        html += '    <tbody>\n'
        
        for i in range(5):
            html += '        <tr>\n'
            html += f'            <th>{i+1}</th>\n'
            
            for top_list, stat_key in [(top_ppv, 'main_events'), (top_wm, 'wrestlemania_main_events'), 
                                        (top_lm, 'libremania_main_events'), (top_open, 'open_tournament_wins'), 
                                        (top_trios, 'trios_tournament_wins')]:
                if i < len(top_list):
                    w = top_list[i]
                    stat = w[stat_key]
                    html += f'            <td><span class="fi fi-{w["country"]}"></span> {w["name"]} </td><td>{stat}</td>\n'
                else:
                    html += '            <td><span class="fi fi-xx"></span> Vacant </td><td>0</td>\n'
            
            html += '        </tr>\n'
        
        html += '    </tbody>\n'
        html += '    </table>\n'
        html += '    </details>\n\n'
        
        return html

    def parse_audience(self, audience_str):
        """Parse audience string like '650K Buys', '1.35M Viewers', '2M Sales' to integer"""
        if not audience_str:
            return 0
        
        # Remove metric words and whitespace
        audience_str = audience_str.replace('Buys', '').replace('buys', '').replace('Viewers', '').replace('viewers', '').replace('Sales', '').replace('sales', '').strip()
        
        # Handle K (thousands)
        if 'K' in audience_str or 'k' in audience_str:
            num = float(audience_str.replace('K', '').replace('k', '').strip())
            return int(num * 1000)
        
        # Handle M (millions)
        if 'M' in audience_str or 'm' in audience_str:
            num = float(audience_str.replace('M', '').replace('m', '').strip())
            return int(num * 1000000)
        
        # Plain number
        try:
            return int(float(audience_str))
        except:
            return 0

    def generate_broadcast_records_html(self):
        """Generate broadcast records tables split by type (PPV, TV, STM)"""
        # Separate broadcasts by type
        ppv_broadcasts = [b for b in self.broadcasts if b.get('broadcast_type') == 'PPV']
        tv_broadcasts = [b for b in self.broadcasts if b.get('broadcast_type') == 'TV']
        stm_broadcasts = [b for b in self.broadcasts if b.get('broadcast_type') == 'STM']
        
        # Sort each by audience metric
        ppv_sorted = sorted(ppv_broadcasts, key=lambda x: self.parse_audience(x.get('audience_metric', '0')), reverse=True)[:10]
        tv_sorted = sorted(tv_broadcasts, key=lambda x: self.parse_audience(x.get('audience_metric', '0')), reverse=True)[:10]
        stm_sorted = sorted(stm_broadcasts, key=lambda x: self.parse_audience(x.get('audience_metric', '0')), reverse=True)[:10]
        
        html = ''
        
        # PPV Records
        if ppv_sorted:
            html += '    <!-- PPV Broadcast Records -->\n'
            html += '    <details>\n'
            html += '    <summary>PPV Broadcast</summary>\n'
            html += '    <table class="match-card">\n'
            html += '    <thead>\n'
            html += '        <tr>\n'
            html += '            <th>No.</th>\n'
            html += '            <th>Event</th>\n'
            html += '            <th>Main Event</th>\n'
            html += '            <th>Sales</th>\n'
            html += '            <th>Venue</th>\n'
            html += '            <th>Location</th>\n'
            html += '            <th>Date</th>\n'
            html += '        </tr>\n'
            html += '    </thead>\n'
            html += '    <tbody>\n'
            
            for idx, broadcast in enumerate(ppv_sorted):
                audience_num = self.parse_audience(broadcast.get('audience_metric', '0'))
                html += '        <tr>\n'
                html += f'            <th>{idx + 1}</th>\n'
                html += f'            <td>{broadcast["event"]}</td>\n'
                html += f'            <td>{broadcast.get("main_event", "")}</td>\n'
                html += f'            <td>{self.format_number(audience_num)}</td>\n'
                html += f'            <td>{broadcast.get("venue", "")}</td>\n'
                html += f'            <td><span class="fi fi-{broadcast.get("country", "un")}"></span> {broadcast.get("location", "")}</td>\n'
                html += f'            <td>{broadcast.get("date", "")}</td>\n'
                html += '        </tr>\n'
            
            html += '    </tbody>\n'
            html += '    </table>\n'
            html += '    </details>\n\n'
        
        # TV Records
        if tv_sorted:
            html += '    <!-- TV Broadcast Records -->\n'
            html += '    <details>\n'
            html += '    <summary>TV Broadcast</summary>\n'
            html += '    <table class="match-card">\n'
            html += '    <thead>\n'
            html += '        <tr>\n'
            html += '            <th>No.</th>\n'
            html += '            <th>Event</th>\n'
            html += '            <th>Main Event</th>\n'
            html += '            <th>Viewers</th>\n'
            html += '            <th>Venue</th>\n'
            html += '            <th>Location</th>\n'
            html += '            <th>Date</th>\n'
            html += '        </tr>\n'
            html += '    </thead>\n'
            html += '    <tbody>\n'
            
            for idx, broadcast in enumerate(tv_sorted):
                audience_num = self.parse_audience(broadcast.get('audience_metric', '0'))
                html += '        <tr>\n'
                html += f'            <th>{idx + 1}</th>\n'
                html += f'            <td>{broadcast["event"]}</td>\n'
                html += f'            <td>{broadcast.get("main_event", "")}</td>\n'
                html += f'            <td>{self.format_number(audience_num)}</td>\n'
                html += f'            <td>{broadcast.get("venue", "")}</td>\n'
                html += f'            <td><span class="fi fi-{broadcast.get("country", "un")}"></span> {broadcast.get("location", "")}</td>\n'
                html += f'            <td>{broadcast.get("date", "")}</td>\n'
                html += '        </tr>\n'
            
            html += '    </tbody>\n'
            html += '    </table>\n'
            html += '    </details>\n\n'
        
        # STM Records
        if stm_sorted:
            html += '    <!-- Streaming Broadcast Records -->\n'
            html += '    <details>\n'
            html += '    <summary>Streaming Broadcast</summary>\n'
            html += '    <table class="match-card">\n'
            html += '    <thead>\n'
            html += '        <tr>\n'
            html += '            <th>No.</th>\n'
            html += '            <th>Event</th>\n'
            html += '            <th>Main Event</th>\n'
            html += '            <th>Viewers</th>\n'
            html += '            <th>Venue</th>\n'
            html += '            <th>Location</th>\n'
            html += '            <th>Date</th>\n'
            html += '        </tr>\n'
            html += '    </thead>\n'
            html += '    <tbody>\n'
            
            for idx, broadcast in enumerate(stm_sorted):
                audience_num = self.parse_audience(broadcast.get('audience_metric', '0'))
                html += '        <tr>\n'
                html += f'            <th>{idx + 1}</th>\n'
                html += f'            <td>{broadcast["event"]}</td>\n'
                html += f'            <td>{broadcast.get("main_event", "")}</td>\n'
                html += f'            <td>{self.format_number(audience_num)}</td>\n'
                html += f'            <td>{broadcast.get("venue", "")}</td>\n'
                html += f'            <td><span class="fi fi-{broadcast.get("country", "un")}"></span> {broadcast.get("location", "")}</td>\n'
                html += f'            <td>{broadcast.get("date", "")}</td>\n'
                html += '        </tr>\n'
            
            html += '    </tbody>\n'
            html += '    </table>\n'
            html += '    </details>\n\n'
        
        return html

    def parse_attendance(self, attendance_str):
        """Parse attendance string like 'Attendance: 13,000' to integer"""
        if not attendance_str:
            return 0
        
        # Remove 'Attendance:' and whitespace
        attendance_str = attendance_str.replace('Attendance:', '').replace('attendance:', '').strip()
        
        # Remove commas
        attendance_str = attendance_str.replace(',', '')
        
        # Handle K (thousands)
        if 'K' in attendance_str or 'k' in attendance_str:
            num = float(attendance_str.replace('K', '').replace('k', '').strip())
            return int(num * 1000)
        
        # Plain number
        try:
            return int(float(attendance_str))
        except:
            return 0

    def generate_attendance_records_html(self):
        """Generate attendance records table"""
        # Filter broadcasts with attendance data
        broadcasts_with_attendance = [b for b in self.broadcasts if b.get('attendance')]
        
        # Sort by attendance
        sorted_attendance = sorted(broadcasts_with_attendance, 
                                   key=lambda x: self.parse_attendance(x.get('attendance', '0')), 
                                   reverse=True)[:10]
        
        if not sorted_attendance:
            return ''
        
        html = '    <!-- Attendance Records -->\n'
        html += '    <details>\n'
        html += '    <summary>Attendance</summary>\n'
        html += '    <table class="match-card">\n'
        html += '    <thead>\n'
        html += '        <tr>\n'
        html += '            <th>No.</th>\n'
        html += '            <th>Event</th>\n'
        html += '            <th>Main Event</th>\n'
        html += '            <th>Attendance</th>\n'
        html += '            <th>Venue</th>\n'
        html += '            <th>Location</th>\n'
        html += '            <th>Date</th>\n'
        html += '        </tr>\n'
        html += '    </thead>\n'
        html += '    <tbody>\n'
        
        for idx, broadcast in enumerate(sorted_attendance):
            attendance_num = self.parse_attendance(broadcast.get('attendance', '0'))
            html += '        <tr>\n'
            html += f'            <th>{idx + 1}</th>\n'
            html += f'            <td>{broadcast["event"]}</td>\n'
            html += f'            <td>{broadcast.get("main_event", "")}</td>\n'
            html += f'            <td>{self.format_number(attendance_num)}</td>\n'
            html += f'            <td>{broadcast.get("venue", "")}</td>\n'
            html += f'            <td><span class="fi fi-{broadcast.get("country", "un")}"></span> {broadcast.get("location", "")}</td>\n'
            html += f'            <td>{broadcast.get("date", "")}</td>\n'
            html += '        </tr>\n'
        
        html += '    </tbody>\n'
        html += '    </table>\n'
        html += '    </details>\n\n'
        
        return html

    def generate_drawing_power_html(self):
        """Generate top 10 drawing wrestlers table"""
        # Calculate drawing stats for each wrestler who main evented
        wrestler_stats = defaultdict(lambda: {
            'name': '',
            'country': 'un',
            'total_attendance': 0,
            'attendance_count': 0,
            'total_ppv': 0,
            'ppv_count': 0,
            'total_tv': 0,
            'tv_count': 0,
            'total_stm': 0,
            'stm_count': 0
        })
        
        for broadcast in self.broadcasts:
            if not broadcast.get('main_event_wrestlers'):
                continue
            
            attendance = self.parse_attendance(broadcast.get('attendance', '0'))
            audience = self.parse_audience(broadcast.get('audience_metric', '0'))
            broadcast_type = broadcast.get('broadcast_type')
            
            for wrestler_name in broadcast.get('main_event_wrestlers', []):
                stats = wrestler_stats[wrestler_name]
                stats['name'] = wrestler_name
                
                # Get country from wrestler database
                if wrestler_name in self.wrestlers:
                    stats['country'] = self.wrestlers[wrestler_name]['country']
                
                # Track attendance
                if attendance > 0:
                    stats['total_attendance'] += attendance
                    stats['attendance_count'] += 1
                
                # Track by broadcast type
                if broadcast_type == 'PPV' and audience > 0:
                    stats['total_ppv'] += audience
                    stats['ppv_count'] += 1
                elif broadcast_type == 'TV' and audience > 0:
                    stats['total_tv'] += audience
                    stats['tv_count'] += 1
                elif broadcast_type == 'STM' and audience > 0:
                    stats['total_stm'] += audience
                    stats['stm_count'] += 1
        
        # Calculate averages
        wrestler_list = []
        for name, stats in wrestler_stats.items():
            avg_attendance = stats['total_attendance'] / stats['attendance_count'] if stats['attendance_count'] > 0 else 0
            avg_ppv = stats['total_ppv'] / stats['ppv_count'] if stats['ppv_count'] > 0 else 0
            avg_tv = stats['total_tv'] / stats['tv_count'] if stats['tv_count'] > 0 else 0
            avg_stm = stats['total_stm'] / stats['stm_count'] if stats['stm_count'] > 0 else 0
            
            wrestler_list.append({
                'name': name,
                'country': stats['country'],
                'avg_attendance': avg_attendance,
                'total_ppv': stats['total_ppv'],
                'avg_ppv': avg_ppv,
                'avg_tv': avg_tv,
                'avg_stm': avg_stm
            })
        
        # Ensure we have at least 1 of each category in top 10
        # Sort by combined score (weighted average)
        for w in wrestler_list:
            w['score'] = (w['avg_attendance'] * 0.25 + 
                         w['total_ppv'] * 0.25 + 
                         w['avg_ppv'] * 0.25 + 
                         w['avg_tv'] * 0.125 + 
                         w['avg_stm'] * 0.125)
        
        top_10 = sorted(wrestler_list, key=lambda x: x['score'], reverse=True)[:10]
        
        if not top_10:
            return ''
        
        html = '    <!-- Drawing Power Records -->\n'
        html += '    <details>\n'
        html += '    <summary>Drawing Power</summary>\n'
        html += '    <table class="match-card">\n'
        html += '    <thead>\n'
        html += '        <tr>\n'
        html += '            <th>No.</th>\n'
        html += '            <th>Wrestler</th>\n'
        html += '            <th>Avg Attendance</th>\n'
        html += '            <th>Total PPV Sales</th>\n'
        html += '            <th>Avg PPV Sales</th>\n'
        html += '            <th>Avg TV Viewers</th>\n'
        html += '            <th>Avg Streaming Viewers</th>\n'
        html += '        </tr>\n'
        html += '    </thead>\n'
        html += '    <tbody>\n'
        
        for idx, wrestler in enumerate(top_10):
            html += '        <tr>\n'
            html += f'            <th>{idx + 1}</th>\n'
            html += f'            <td><span class="fi fi-{wrestler["country"]}"></span> {wrestler["name"]}</td>\n'
            html += f'            <td>{self.format_number(int(wrestler["avg_attendance"]))}</td>\n'
            html += f'            <td>{self.format_number(int(wrestler["total_ppv"]))}</td>\n'
            html += f'            <td>{self.format_number(int(wrestler["avg_ppv"]))}</td>\n'
            html += f'            <td>{self.format_number(int(wrestler["avg_tv"]))}</td>\n'
            html += f'            <td>{self.format_number(int(wrestler["avg_stm"]))}</td>\n'
            html += '        </tr>\n'
        
        html += '    </tbody>\n'
        html += '    </table>\n'
        html += '    </details>\n\n'
        
        return html

    def update_html_files(self):
        """Update all HTML files"""
        print("Updating HTML files...")
        
        # 1. Update wrestling/wiki.html (current champions at #ringchamps, records at #records)
        wiki_path = 'wrestling/wiki.html'
        if os.path.exists(wiki_path):
            with open(wiki_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Update summary championships
            current_champs_html = self.generate_current_champions_html()
            if '<!-- SUMMARYCHAMPS_START -->' in content and '<!-- SUMMARYCHAMPS_END -->' in content:
                before = content.split('<!-- SUMMARYCHAMPS_START -->')[0]
                after = content.split('<!-- SUMMARYCHAMPS_END -->')[1]
                content = before + '<!-- SUMMARYCHAMPS_START -->\n' + current_champs_html + '<!-- SUMMARYCHAMPS_END -->' + after
            
            # Update records
            records_html = self.generate_records_html()
            if '<!-- RECORDS_START -->' in content and '<!-- RECORDS_END -->' in content:
                before = content.split('<!-- RECORDS_START -->')[0]
                after = content.split('<!-- RECORDS_END -->')[1]
                content = before + '<!-- RECORDS_START -->\n' + records_html + '<!-- RECORDS_END -->' + after
            
            with open(wiki_path, 'w', encoding='utf-8') as f:
                f.write(content)
            print(f"✓ Updated {wiki_path}")
        
        # 2. Update org championship pages
        for org in ['wwf', 'wwo', 'iwb', 'ring']:
            org_path = f'wrestling/org/{org}.html'
            if os.path.exists(org_path):
                with open(org_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Generate all championship histories for this org
                org_champs_html = ''
                for weight in ['heavyweight', 'bridgerweight', 'middleweight', 'welterweight', 'lightweight', 'featherweight']:
                    org_champs_html += self.generate_championship_history_html(org, weight)
                
                if f'<!-- {org.upper()}CHAMPS_START -->' in content and f'<!-- {org.upper()}CHAMPS_END -->' in content:
                    before = content.split(f'<!-- {org.upper()}CHAMPS_START -->')[0]
                    after = content.split(f'<!-- {org.upper()}CHAMPS_END -->')[1]
                    content = before + f'<!-- {org.upper()}CHAMPS_START -->\n' + org_champs_html + f'<!-- {org.upper()}CHAMPS_END -->' + after
                    
                    with open(org_path, 'w', encoding='utf-8') as f:
                        f.write(content)
                    print(f"✓ Updated {org_path}")

        HTML_HEADER = """<!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/lipis/flag-icons@7.3.2/css/flag-icons.min.css">
            <title>Wrestling PPV List</title>
            <link rel="stylesheet" href="/css/wiki.css">
        </head>
        <body>
        """

        HTML_FOOTER = """
        </body>
        </html>
        """
        
        # 3. Create/update wrestler pages (ONLY for PPV wrestlers)
        wrestlers_dir = 'wrestling/wrestlers'
        os.makedirs(wrestlers_dir, exist_ok=True)
        for wrestler_name in self.ppv_wrestlers:
            if wrestler_name not in self.wrestlers:
                continue
                
            filename = wrestler_name.lower().replace(' ', '-').replace('.', '')
            filepath = f'{wrestlers_dir}/{filename}.html'
            
            wrestler_html = self.generate_wrestler_page(wrestler_name)
            
            if os.path.exists(filepath):
                # File exists - update between markers only
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                if '<!-- MATCHES_START -->' in content and '<!-- MATCHES_END -->' in content:
                    before = content.split('<!-- MATCHES_START -->')[0]
                    after = content.split('<!-- MATCHES_END -->')[1]
                    content = before + '<!-- MATCHES_START -->\n' + wrestler_html + '<!-- MATCHES_END -->' + after
                    
                    # Update infobox record if it exists
                    wrestler = self.wrestlers[wrestler_name]
                    record = f"{wrestler['wins']}-{wrestler['losses']}-{wrestler['draws']}"
                    # Look for the Record row in infobox and update it
                    import re
                    content = re.sub(
                        r'(<th>Record</th>\s*<td>)[^<]*(</td>)',
                        r'\g<1>' + record + r'\g<2>',
                        content
                    )
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(content)
                    print(f"✓ Updated {filepath}")
                else:
                    # Markers don't exist - wrap content and add markers
                    with open(filepath, 'r', encoding='utf-8') as f:
                        existing_content = f.read()
                    
                    # Extract just the body content (remove header/footer if present)
                    if '<body>' in existing_content and '</body>' in existing_content:
                        body_start = existing_content.find('<body>') + len('<body>')
                        body_end = existing_content.find('</body>')
                        existing_body = existing_content[body_start:body_end].strip()
                    else:
                        existing_body = existing_content
                    
                    # Create new file with markers
                    new_content = HTML_HEADER + '\n<!-- MATCHES_START -->\n' + wrestler_html + '<!-- MATCHES_END -->\n' + HTML_FOOTER
                    
                    with open(filepath, 'w', encoding='utf-8') as f:
                        f.write(new_content)
                    print(f"✓ Added markers to {filepath}")
            else:
                # File doesn't exist - create new with markers
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(HTML_HEADER)
                    f.write(f'\n<h1>{wrestler_name}</h1>\n\n')  # Add h1 BEFORE markers
                    f.write('\n<!-- MATCHES_START -->\n')
                    f.write(wrestler_html)
                    f.write('<!-- MATCHES_END -->\n')
                    f.write(HTML_FOOTER)
                print(f"✓ Created {filepath}")

        # 4. Create/update wrestlers index page (ONLY PPV wrestlers)
        index_path = 'wrestling/wrestlers/index.html'
        sorted_wrestlers = sorted([name for name in self.wrestlers.keys() if name in self.ppv_wrestlers])

        index_html = HTML_HEADER
        index_html += '<h1>Wrestler Directory</h1>\n\n'
        index_html += '<ul style="column-count: 3; column-gap: 20px; list-style: none; padding: 0;">\n'

        for wrestler_name in sorted_wrestlers:
            filename = wrestler_name.lower().replace(' ', '-').replace('.', '')
            wrestler = self.wrestlers[wrestler_name]
            record = f"{wrestler['wins']}-{wrestler['losses']}-{wrestler['draws']}"
            index_html += f'    <li style="margin-bottom: 8px;"><a href="{filename}.html">{wrestler_name}</a> ({record})</li>\n'

        index_html += '</ul>\n'
        index_html += HTML_FOOTER

        with open(index_path, 'w', encoding='utf-8') as f:
            f.write(index_html)
        print(f"✓ Updated {index_path}")

def main():
    db = WrestlingDatabase()
    
    print("Parsing wrestling/ppv/list.html...")
    db.parse_events('wrestling/ppv/list.html', is_weekly=False)
    
    # Parse weekly shows if file exists
    weekly_path = 'wrestling/weekly/list.html'
    if os.path.exists(weekly_path):
        print("Parsing wrestling/weekly/list.html...")
        db.parse_events(weekly_path, is_weekly=True)
    
    print(f"Found {len(db.events)} events")
    print(f"Found {len(db.wrestlers)} wrestlers")
    print(f"Found {len(db.vacancies)} vacancy comments")
    
    # Sort all events chronologically
    print("Sorting events chronologically...")
    db.events.sort(key=lambda e: db.parse_date(e['date']) if e.get('date') else datetime.min)
    
    # Now reprocess all championship changes in chronological order
    print("Reprocessing championship reigns in chronological order...")
    db.reprocess_championships_chronologically()
    
    # Recalculate bio notes now that championship state is correct
    db.recalculate_bio_notes()
    
    # Process vacancies and calculate championship days
    db.process_vacancies()
    db.calculate_championship_days()
    
    db.update_html_files()
    
    print("\n✓ All files updated!")
    print("Review the changes and run 'git add . && git commit -m \"Update wrestling database\" && git push'")

if __name__ == '__main__':
    main()