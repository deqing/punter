"""
TODO

odds-api.py
    a-league odds
    go though all odds to see which is highest
    more accounts?

add germany
add france

check bluebet
add neds.com.au (not easy to get by css)
"""

import re
import pickle
from colorama import Fore, Back, Style
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
import time
import requests
import traceback
import logging
from tempfile import gettempdir
import os
import smtplib
from email.mime.text import MIMEText
import sys

HEAD = '<html lang="en">\n'


class WriteToHtmlFile:
    def __init__(self):
        self.file, self.title, self.urls = None, None, None

    def init(self):
        self.file = open('output.html', 'w')
        self.file.write(HEAD)
        self.title = ''
        self.urls = set()

    def write_line(self, line):
        self.file.write(line + '\n')

    def write_line_in_table(self, line):
        self.file.write('<tr><td>' + line.replace('\t', '</td><td>') + '</td></tr>\n')

    def write_highlight_line(self, line, urls):
        self.file.write('<tr><td><div style=\'background-color:yellow;\'>' + line.replace('\t', '</td><td>') + '</div></td></tr>\n')  # noqa
        self.title += line.split()[0] + ' '
        self.urls.update(urls)

    def close(self):
        self.file.write('</html>')
        self.file.close()
        with open('output_title.txt', 'w') as title_file:
            if len(self.title) is 0:
                title_file.write('None')
            else:
                title_file.write('!'*self.title.count(' ') + ' - ' + self.title)
        self.title = ''

        with open('output_urls.txt', 'w') as urls_file:
            for url in self.urls:
                urls_file.write(url + '\n')
            urls_file.write('<p>')
        self.urls = set()


class WriteToHtmlFileDummy:  # This class is just to keep code clean
    def write_line(self, line):
        pass

    def write_line_in_table(self, line):
        pass

    def write_highlight_line(self, line, urls):
        pass


class Match:
    def __init__(self):
        self.profit = 0
        self.home_team = ''
        self.away_team = ''
        self.odds = ['', '', '']
        self.agents = ['', '', '']
        self.perts = ['', '', '']
        self.earns = ['', '', '']
        self.other_agents = [[], [], []]
        self.urls = ['', '', '']
        self.has_other_agents = False

    def __lt__(self, other):
        return self.home_team < other.home_team

    # To avoid complexity, only supports one website now - no other agents
    def serialize(self):
        return {
            'profit': self.profit,
            'home_team': self.home_team,
            'away_team': self.away_team,
            'odds': self.odds,
            'agents': self.agents,
            'perts': self.perts,
            'earns': self.earns,
            'urls': self.urls,
        }

    # To avoid complexity, only supports one website now - no other agents
    def init_with_json(self, json_):
        self.profit = json_['profit']
        self.home_team = json_['home_team']
        self.away_team = json_['away_team']
        for i in range(3):
            self.odds[i] = json_['odds'][i]
            self.agents[i] = json_['agents'][i]
            self.perts[i] = json_['perts'][i]
            self.earns[i] = json_['earns'][i]
            self.urls[i] = json_['urls'][i]

    @staticmethod
    def color_print(msg, foreground="black", background="white"):
        fground = foreground.upper()
        bground = background.upper()
        style = getattr(Fore, fground) + getattr(Back, bground)
        print(style + msg + Style.RESET_ALL)

    def display(self, html_file=WriteToHtmlFileDummy()):
        msg = '{}\t{}({})({})({})\t{}({})({})({})\t{}({})({})({})\t- {} vs {}'.format(
            round(self.profit, 2),
            self.odds[0], self.agents[0], self.perts[0], self.earns[0],
            self.odds[1], self.agents[1], self.perts[1], self.earns[1],
            self.odds[2], self.agents[2], self.perts[2], self.earns[2],
            self.home_team, self.away_team)
        if self.has_other_agents:
            msg += '\t(' + '|'.join([','.join(x) for x in self.other_agents]) + ')'

        if float(self.profit) > 99.9:
            self.color_print(msg, background='yellow')
            html_file.write_highlight_line(msg, self.urls)
        else:
            print(msg)
            html_file.write_line_in_table(msg)

    def calculate_best_shot(self):
        if '' in self.odds:
            return

        def min_pay(w, d, l, wp, dp, lp):
            if w * wp <= d * dp and w * wp <= l * lp:
                return w * wp
            if d * dp <= w * wp and d * dp <= l * lp:
                return d * dp
            else:
                return l * lp

        for i in range(100):
            for j in range(100 - i):
                try:
                    profit = min_pay(float(self.odds[0]),
                                     float(self.odds[1]),
                                     float(self.odds[2]),
                                     i, j, 100 - i - j)
                    if profit > self.profit:
                        self.profit = profit
                        self.perts[0] = i
                        self.perts[1] = j
                        self.perts[2] = 100 - i - j
                        self.earns[0] = round(i*float(self.odds[0]) - 100, 2)
                        self.earns[1] = round(j*float(self.odds[1]) - 100, 2)
                        self.earns[2] = round((100-i-j)*float(self.odds[2]) - 100, 2)
                except ValueError as e:
                    print('WARNING: calculate_best_shot() has exception: ' + str(e))
                    continue


class MatchMerger:
    def __init__(self,
                 pickles_a,
                 pickles_arg,
                 pickles_eng,
                 pickles_ita,
                 pickles_liga,
                 ):
        self.pickles_a = pickles_a
        self.pickles_arg = pickles_arg
        self.pickles_eng = pickles_eng
        self.pickles_ita = pickles_ita
        self.pickles_liga = pickles_liga

        # Keyword --> Display Name
        # Keyword: a string with lowercase + whitespace removing
        # The map need to be 1:1 as it will be used by home+away as matches key
        self.a_league_map = {
            'adelaide': 'Adelaide Utd',
            'brisbane': 'Brisbane Roar',
            'central': 'Central Coast',
            'perth': 'Perth Glory',
            'melbournecity': 'Melbourne City',
            'melbournevictory': 'Melbourne Victory',
            'newcastle': 'Newcastle Jets',
            'sydneyfc': 'Sydney FC',
            'wellington': 'Wellington Phoenix',
            'westernsydney': 'Western Sydney',
        }
        self.arg_map = {
            'argentinos': 'Argentinos Jrs',
            'arsenal': 'Arsenal de Sarandi',
            'tucu': 'Atletico Tucuman',
            'banfield': 'Banfield',
            'belgrano': 'Belgrano',
            'boca': 'Boca Juniors',
            'independ': 'CA Independiente',
            'talleres': 'CA Talleres de Cordoba',
            'tigre': 'CA Tigre',
            'chacarita': 'Chacarita Juniors',
            'colon': 'Colon',
            'defens': 'Defensa Justicia',
            'estudiantes': 'Estudiantes',
            'gimnasia': 'Gimnasia LP',
            'godoy': 'Godoy Cruz',
            'huracan': 'Huracan',
            'lanus': 'Lanus',
            'newell': 'Newell',
            'blanca': 'Olimpo Blanca',
            'patronato': 'Patronato Parana',
            'racing': 'Racing Club',
            'riverplate': 'River Plate',
            'rosario': 'Rosario Central',
            'lorenzo': 'San Lorenzo',
            'sanmartin': 'San Martin de San Juan',
            'temperley': 'Temperley',
            'santa': 'Union Santa',
            'rsfield': 'Velez Sarsfield'
        }
        self.eng_map = {
            'arsenal': 'Arsenal',
            'bournemouth': 'Bournemouth',
            'brighton': 'Brighton',
            'burnley': 'Burnley',
            'chelsea': 'Chelsea',
            'crystal': 'Crystal Palace',
            'everton': 'Everton',
            'huddersfield': 'Huddersfield',
            'leicester': 'Leicester',
            'liverpool': 'Liverpool',
            'manchestercity': 'Man City',
            'manchesterunited': 'Man Utd',
            'newcastle': 'Newcastle',
            'southampton': 'Southampton',
            'stoke': 'Stoke',
            'swansea': 'Swansea',
            'tottenham': 'Tottenham',
            'watford': 'Watford',
            'westbrom': 'West Brom',
            'westham': 'West Ham',
        }
        self.ita_map = {
            'atalanta': 'Atalanta BC',
            'benevento': 'Benevento',
            'bologna': 'Bologna',
            'cagliari': 'Cagliari',
            'chievo': 'Chievo',
            'crotone': 'Crotone',
            'fiorentina': 'Fiorentina',
            'genoa': 'Genoa',
            'inter': 'FC Internazionale',
            'juventus': 'Juventus',
            'lazio': 'Lazio',
            'milan': 'AC Milan',
            'napoli': 'Napoli',
            'roma': 'AS Roma',
            'sampdoria': 'Sampdoria',
            'sassuolo': 'Sassuolo',
            'spal': 'SPAL',
            'torino': 'Torino',
            'udinese': 'Udinese',
            'verona': 'Hellas Verona FC',
        }
        self.la_liga_map = {
            'bilbao': 'Athletic Bilbao',
            'atlmadrid': 'Atletico Madrid',
            'alav': 'Alaves',
            'barcelona': 'Barcelona',
            'celta': 'Celta Vigo',
            'deportivo': 'Deportivo La Coruna',
            'eibar': 'Eibar',
            'espanyol': 'Espanyol',
            'getafe': 'Getafe',
            'girona': 'Girona',
            'palmas': 'Las Palmas',
            'legan': 'Leganes',
            'levante': 'Levante',
            'laga': 'Malaga',
            'betis': 'Real Betis',
            'realmadrid': 'Real Madrid',
            'realsoc': 'Real Sociedad',
            'sevilla': 'Sevilla',
            'valencia': 'Valencia',
            'villarreal': 'Villarreal CF'
        }
        self.a_league_keys = list(self.a_league_map.keys())
        self.arg_keys = list(self.arg_map.keys())
        self.eng_keys = list(self.eng_map.keys())
        self.ita_keys = list(self.ita_map.keys())
        self.la_liga_keys = list(self.la_liga_map.keys())

    @staticmethod
    def get_id(team_name, keys, league_name):
        converted_name = ''.join(team_name.lower().split())
        if league_name == 'Spanish La Liga':
            if 'tico' in converted_name:
                converted_name = 'atlmadrid'
            elif 'lacoru' in converted_name:
                converted_name = 'deportivo'
        elif league_name == 'English Premier League':
            if 'mancity' == converted_name:
                converted_name = 'manchestercity'
            elif 'manutd' == converted_name or 'manunited' == converted_name:
                converted_name = 'manchesterunited'
            elif 'cpalace' in converted_name:
                converted_name = 'crystal'
        elif league_name == 'Argentina Superliga':
            if 'olimpo' == converted_name:
                converted_name = 'blanca'
            elif 'velez' in converted_name:
                converted_name = 'rsfield'

        for name in keys:
            if name in converted_name:
                return name
        print('WARNING: {}[{}] is not found in the map of {}!'.format(
            team_name, converted_name, league_name))
        return None

    def print_each_match(self):
        for pickles in self.pickles_a, self.pickles_arg, self.pickles_eng, self.pickles_liga:
            print('-'*80)
            for p_name in pickles:
                with open(os.path.join(gettempdir(), p_name), 'rb') as pkl:
                    pickle_matches = pickle.load(pkl)
                    for pm in pickle_matches:
                        print('{} {}\t{}\t[{}] [{}] [{}]'.format(
                            pm.home_team, pm.away_team,
                            pm.agents[0],
                            pm.odds[0], pm.odds[1], pm.odds[2]
                        ))

    def merge_and_print(self, leagues=('a', 'arg', 'eng', 'ita', 'liga'), html_file=WriteToHtmlFileDummy()):  # noqa
        def odds_to_float(match):
            # Convert text to float
            match.odds = list(match.odds)
            for i_ in range(3):
                try:
                    match.odds[i_] = float(match.odds[i_])
                except ValueError as e:
                    print('WARNING when converting [{}]: {}'.format(match.odds[i_], str(e)))
                    match.odds[i_] = 0

        empty_count = 0
        loop = []
        if 'a' in leagues:
            loop.append((self.pickles_a, self.a_league_keys, self.a_league_map, 'Australia League'))
        elif 'arg' in leagues:
            loop.append((self.pickles_arg, self.arg_keys, self.arg_map, 'Argentina Superliga'))
        elif 'eng' in leagues:
            loop.append((self.pickles_eng, self.eng_keys, self.eng_map, 'English Premier League'))
        elif 'ita' in leagues:
            loop.append((self.pickles_ita, self.ita_keys, self.ita_map, 'Italian Serie A'))
        elif 'liga' in leagues:
            loop.append((self.pickles_liga, self.la_liga_keys, self.la_liga_map, 'Spanish La Liga'))
        else:
            print('WARNING: unexpected league in merge_and_print params: ' + str(leagues))

        for pickles, keys, league_map, league_name in loop:
            empty_names = ''
            matches = {}  # hometeam and awayteam = map's key
            for p_name in pickles:
                with open(os.path.join(gettempdir(), p_name), 'rb') as pkl:
                    pickle_matches = pickle.load(pkl)
                    if len(pickle_matches) is 0:
                        empty_names += p_name.split('_')[1].split('.')[0] + ' '
                        empty_count += 1
                    else:
                        for pm in pickle_matches:
                            id1 = self.get_id(pm.home_team, keys, league_name)
                            id2 = self.get_id(pm.away_team, keys, league_name)
                            if id1 is None or id2 is None:
                                continue
                            odds_to_float(pm)

                            key = id1 + id2
                            if key not in matches.keys():
                                m = Match()
                                m.__dict__.update(pm.__dict__)
                                m.odds = list(m.odds)  # Sometimes it's an immutable tuple
                                m.home_team = league_map[self.get_id(pm.home_team, keys, league_name)]  # noqa
                                m.away_team = league_map[self.get_id(pm.away_team, keys, league_name)]  # noqa
                                matches[key] = m
                            else:
                                m = matches[key]
                                for i in range(3):
                                    if pm.odds[i] > m.odds[i]:
                                        m.odds[i] = pm.odds[i]
                                        m.agents[i] = pm.agents[i]
                                        m.urls[i] = pm.urls[i]
                                    elif pm.odds[i] == m.odds[i]:
                                        m.has_other_agents = True
                                        m.other_agents[i].append(pm.agents[i].strip())
            matches = sorted(matches.values())
            if len(matches) is not 0:
                output = '--- {} ---'.format(league_name)
                empty_str = '({} pickles, empty: [{}])'.format(len(pickles), empty_names.rstrip())
                print(output + empty_str)

                html_file.write_line('<b>' + output + '</b>' + empty_str)
                html_file.write_line('<table>')
                for m in matches:
                    m.calculate_best_shot()
                    m.display(html_file)
                html_file.write_line('</table>')

        with open('output_empty_pickles.txt', 'w') as empty_count_file:
            empty_count_file.write('({} empty pickles)'.format(empty_count))


class Website:
    def __init__(self, driver, wait):
        self.driver = driver
        self.wait = wait
        self.use_request = False
        self.a_url = False
        self.arg_url = False
        self.eng_url = False
        self.ita_url = False
        self.liga_url = False
        self.name = ''
        self.current_league = ''
        self.ask_gce = False

    def get_blocks(self, css_string):
        try:
            self.wait.until(expected_conditions.visibility_of_element_located((By.CSS_SELECTOR, css_string)))  # noqa
        except TimeoutException:
            print('[{}] not found'.format(css_string))
            return []
        blocks = self.driver.find_elements_by_css_selector(css_string)
        return blocks

    def get_href_link(self):
        """
        e.g. return <a href='https://www.tab.com.au/sports/betting/Soccer/competitions/A%20League'>tab</a>  # noqa
        """
        return '<a href="' + getattr(self, self.current_league + '_url') + '">' + self.name + '</a>'

    def fetch(self, _):
        print('WARNING: fetch() should be overridden.')


class Bet365(Website):
    def __init__(self, driver, wait):
        super(Bet365, self).__init__(driver, wait)
        self.name = 'bet365'
        self.a_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-27119403-2-18-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=1;anim=1'  # noqa
        self.arg_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-34240206-2-12-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=30;anim=1'  # noqa
        self.eng_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-33577327-2-1-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=30;anim=1'  # noqa
        self.ita_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-34031004-2-6-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=30;anim=1'  # noqa
        self.liga_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-33977144-2-8-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=1;anim=1'  # noqa

    def fetch(self, matches):
        blocks = self.get_blocks('div.podEventRow')
        for b in blocks:
            names = b.find_elements_by_css_selector('div.ippg-Market_CompetitorName')
            odds = b.find_elements_by_css_selector('span.ippg-Market_Odds')
            m = Match()
            m.home_team, m.away_team = names[0].text, names[1].text
            for i in range(3):
                m.odds[i] = odds[i].text
            m.agents = ['Bet365'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Betstar(Website):  # bookmarker uses same odds  TODO try bookmarker's arg and ita
    def __init__(self, driver, wait):
        super(Betstar, self).__init__(driver, wait)
        self.name = 'betstar'
        self.a_url = 'https://www.betstar.com.au/sports/soccer/39922191-football-australia-australian-a-league/'  # noqa
        self.eng_url = 'https://www.betstar.com.au/sports/soccer/41388947-football-england-premier-league/'  # noqa
        self.liga_url = 'https://www.betstar.com.au/sports/soccer/40963090-football-spain-spanish-la-liga/'  # noqa

    def fetch(self, matches):
        blocks = self.get_blocks('table.bettype-group.listings.odds.sports.match.soccer')
        for b in blocks:
            info = b.find_elements_by_css_selector('tr.row')
            if len(info) < 3:
                continue
            m = Match()
            m.home_team, m.odds[0] = info[0].text.split('\n')
            m.away_team, m.odds[2] = info[1].text.split('\n')
            m.odds[1] = info[2].text.split('\n')[1]
            m.agents = ['Betstar'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Crownbet(Website):
    def __init__(self, driver, wait):
        super(Crownbet, self).__init__(driver, wait)
        self.name = 'crownbet'
        self.a_url = 'https://crownbet.com.au/sports-betting/soccer/australia/a-league-matches'
        self.arg_url = 'https://crownbet.com.au/sports-betting/soccer/americas/argentina-primera-division-matches'  # noqa
        self.eng_url = 'https://crownbet.com.au/sports-betting/soccer/united-kingdom/english-premier-league-matches'  # noqa
        self.ita_url = 'https://crownbet.com.au/sports-betting/soccer/italy/italian-serie-a-matches/'  # noqa
        self.liga_url = 'https://crownbet.com.au/sports-betting/soccer/spain/spanish-la-liga-matches/'  # noqa

    def fetch(self, matches):
        blocks = []
        for _ in range(10):
            blocks = self.get_blocks('div.container-fluid')
            if len(blocks) is not 0 and blocks[0].tag_name == 'div':
                break
            time.sleep(1)

        for b in blocks:
            values = b.text.split('\n')
            if len(values) < 10 or 'SEGUNDA' in values[0]:
                continue
            m = Match()
            m.home_team, m.away_team = values[4], values[8]
            m.odds = values[5], values[7], values[9]
            m.agents = ['Crown'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Ladbrokes(Website):
    def __init__(self, driver, wait):
        super(Ladbrokes, self).__init__(driver, wait)
        self.name = 'ladbrokes'
        self.a_url = 'https://www.ladbrokes.com.au/sports/soccer/39445848-football-australia-australian-a-league/?utm_source=%2Fsports%2Fsoccer%2F35326546-australian-a-league-2017-2018%2F35326546-australian-a-league-2017-2018%2F&utm_medium=sport+banner&utm_campaign=a+league+round+4'  # noqa
        self.arg_url = 'https://www.ladbrokes.com.au/sports/soccer/43008934-football-argentina-argentinian-primera-division/'  # noqa
        self.eng_url = 'https://www.ladbrokes.com.au/sports/soccer/41388947-football-england-premier-league/'  # noqa
        self.ita_url = 'https://www.ladbrokes.com.au/sports/soccer/42212441-football-italy-italian-serie-a/'   # noqa
        self.liga_url = 'https://www.ladbrokes.com.au/sports/soccer/40962944-football-spain-spanish-la-liga/'  # noqa

    def fetch(self, matches):
        blocks = self.get_blocks('table.bettype-group.listings.odds.sports.match.soccer')
        for b in blocks:
            if 'Footy Freaks' in b.text:
                continue
            m = Match()
            info = b.find_elements_by_css_selector('tr.row')
            m.home_team, m.odds[0] = info[0].text.split('\n')
            m.away_team, m.odds[2] = info[1].text.split('\n')
            m.odds[1] = info[2].text.split('\n')[1]
            m.agents = ['Ladbroke'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Luxbet(Website):
    def __init__(self, driver, wait):
        super(Luxbet, self).__init__(driver, wait)
        self.name = 'luxbet'
        self.a_url = 'https://www.luxbet.com/?cPath=596&event_id=ALL'
        self.arg_url = 'https://www.luxbet.com/?cPath=6278&event_id=ALL'
        self.eng_url = 'https://www.luxbet.com/?cPath=616&event_id=ALL'
        self.ita_url = 'https://www.luxbet.com/?cPath=1172&event_id=ALL'
        self.liga_url = 'https://www.luxbet.com/?cPath=931&event_id=ALL'

    def fetch(self, matches):
        blocks = self.get_blocks('tr.asian_display_row')
        for b in blocks:
            m = Match()
            teams = b.find_elements_by_css_selector('div.bcg_asian_selection_name')
            m.home_team, m.away_team = teams[0].text, teams[2].text
            odds = b.find_element_by_css_selector('td.asian_market_cell.market_type_template_12')
            m.odds[0], m.odds[1], m.odds[2] = odds.text.split('\n')
            for i in range(3):
                m.odds[i] = m.odds[i].strip()
            m.agents = ['Luxbet'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Madbookie(Website):
    def __init__(self, driver, wait):
        super(Madbookie, self).__init__(driver, wait)
        self.name = 'madbookie'
        self.a_url = 'https://www.madbookie.com.au/Sport/Soccer/Australian_A-League/Matches'
        self.arg_url = 'https://www.madbookie.com.au/Sport/Soccer/Argentinian_Primera_Division/Matches'  # noqa
        self.eng_url = 'https://www.madbookie.com.au/Sport/Soccer/English_Premier_League/Matches'
        self.ita_url = 'https://www.madbookie.com.au/Sport/Soccer/Italian_Serie_A/Matches'
        self.liga_url = 'https://www.madbookie.com.au/Sport/Soccer/Spanish_La_Liga/Matches'

    def fetch(self, matches):
        blocks = self.get_blocks('table.MarketTable.MatchMarket')
        title = 'Team Win Draw O/U'
        for b in blocks:
            if title not in b.text:
                continue
            strings = b.text.split('\n')
            home_team_strs = strings[1].split(' Over ')[0].split(' ')
            away_team_strs = strings[2].split(' Under ')[0].split(' ')
            m = Match()
            m.odds[1] = home_team_strs.pop()
            m.odds[0] = home_team_strs.pop()
            m.home_team = ' '.join(home_team_strs)
            m.odds[2] = away_team_strs.pop()
            m.away_team = ' '.join(away_team_strs)
            m.agents = ['Madbook'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Palmerbet(Website):
    def __init__(self, driver, wait):
        super(Palmerbet, self).__init__(driver, wait)
        self.name = 'palmerbet'
        self.a_url = 'https://www.palmerbet.com/sports/soccer/australia-a_league'
        self.arg_url = 'https://www.palmerbet.com/sports/soccer/argentina-primera-división'
        self.eng_url = 'https://www.palmerbet.com/sports/soccer/england-premier-league'
        self.ita_url = 'https://www.palmerbet.com/sports/soccer/italy-serie-a'
        self.liga_url = 'https://www.palmerbet.com/sports/soccer/spain-primera-division'

    def fetch(self, matches):
        names = self.driver.find_elements_by_css_selector('td.nam')
        odds = self.driver.find_elements_by_css_selector('a.sportproduct')
        show_all = self.driver.find_elements_by_css_selector('td.show-all.last')
        if len(names) is 0:
            return
        names.pop(0)
        for n in names:
            m = Match()
            m.home_team, m.away_team = n.text.split('\n')
            m.odds = odds[0].text, odds[2].text, odds[1].text
            odds = odds[3:] if len(show_all[0].text) is 0 else odds[5:]
            show_all = show_all[1:]
            m.agents = ['Palmer'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Pinnacle(Website):
    def __init__(self, driver, wait):
        super(Pinnacle, self).__init__(driver, wait)
        self.name = 'pinnacle'
        self.a_url = 'https://www.pinnacle.com/en/odds/match/soccer/australia/australia-a-league'
        self.arg_url = 'https://www.pinnacle.com/en/odds/match/soccer/argentina/argentina-primera-division'  # noqa
        self.eng_url = 'https://www.pinnacle.com/en/odds/match/soccer/england/england-premier-league'  # noqa
        self.ita_url = 'https://www.pinnacle.com/en/odds/match/soccer/italy/italy-serie-a'
        self.liga_url = 'https://www.pinnacle.com/en/odds/match/soccer/spain/spain-la-liga'

    def fetch(self, matches):
        blocks = self.get_blocks('tbody.ng-scope')
        for b in blocks:
            if len(b.text) is 0:
                continue
            teams = b.find_elements_by_css_selector('td.game-name.name')
            odds = b.find_elements_by_css_selector('td.oddTip.game-moneyline')
            if len(teams) is not 0 and len(odds) is not 0 and odds[0].text is not '':
                m = Match()
                m.home_team, m.away_team = teams[0].text, teams[1].text
                m.odds[0] = odds[0].text
                m.odds[2] = odds[1].text
                m.odds[1] = odds[2].text
                m.agents = ['pinacle'] * 3
                m.urls = [self.get_href_link()] * 3
                matches.append(m)


class Sportsbet(Website):
    def __init__(self, driver, wait):
        super(Sportsbet, self).__init__(driver, wait)
        self.name = 'sportsbet'
        self.a_url = 'https://www.sportsbet.com.au/betting/soccer/australia/australian-a-league'
        self.arg_url = 'https://www.sportsbet.com.au/betting/soccer/americas/argentinian-primera-division'  # noqa
        self.eng_url = 'https://www.sportsbet.com.au/betting/soccer/united-kingdom/english-premier-league'  # noqa
        self.ita_url = 'https://www.sportsbet.com.au/betting/soccer/italy/italian-serie-a'
        self.liga_url = 'https://www.sportsbet.com.au/betting/soccer/spain/spanish-la-liga'
        self.use_request = True
        self.content = []

    @staticmethod
    def extract(line, regx):
        m = re.search(regx, line)
        return m.group(1) if m else ''

    def fetch(self, matches):
        status = None
        team_name_r = '<span class="team-name.*>(.+)</span>'
        m = Match()
        for line in self.content:
            if status is None and '<div class="price-link ' in line:
                status = 'wait home team'
                continue

            if '<span class="team-name' in line:
                if status == 'wait home team':
                    m.home_team = self.extract(line, team_name_r)
                    status = 'wait win'
                elif status == 'wait away team':
                    m.away_team = self.extract(line, team_name_r)
                    status = 'wait lose'
                elif status != 'wait draw':
                    print('WARNING: sportsbet has unexpected input')
                continue

            if status == 'in win span':
                m.odds[0] = line
                status = 'wait draw'
                continue

            if status == 'in draw span':
                m.odds[1] = line
                status = 'wait away team'
                continue

            if status == 'in lose span':
                m.odds[2] = line
                status = None
                m.agents = ['sports'] * 3
                m.urls = [self.get_href_link()] * 3
                matches.append(m)
                m = Match()
                continue

            if status is not None and '<span class="price-val' in line:
                status = 'in win span' if status == 'wait win' else 'in draw span' \
                    if status == 'wait draw' else 'in lose span'
                continue


class Tab(Website):
    def __init__(self, driver, wait):
        super(Tab, self).__init__(driver, wait)
        self.name = 'tab'
        self.a_url = 'https://www.tab.com.au/sports/betting/Soccer/competitions/A%20League'
        self.eng_url = 'https://www.tab.com.au/sports/betting/Soccer/competitions/English%20Premier%20League'  # noqa
        self.ita_url = 'https://www.tab.com.au/sports/betting/Soccer/competitions/Italian%20Serie%20A'  # noqa
        self.liga_url = 'https://www.tab.com.au/sports/betting/Soccer/competitions/Spanish%20Primera%20Division'  # noqa

    def fetch(self, matches):
        blocks = self.get_blocks('div.template-item.ng-scope')
        for block in blocks:
            m = Match()
            m.home_team, m.away_team = block.find_element_by_css_selector(
                'span.match-name-text.ng-binding').text.split(' v ')
            odds = block.find_elements_by_css_selector('div.animate-odd.ng-binding.ng-scope')
            for i in range(3):
                m.odds[i] = odds[i].text
            m.agents = ['TAB'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Topbetta(Website):
    def __init__(self, driver, wait):
        super(Topbetta, self).__init__(driver, wait)
        self.name = 'topbetta'
        self.a_url = 'https://www.topbetta.com.au/sports/football/hyundai-a-league-regular-season-151825'  # noqa
        # No Argentina
        self.eng_url = self.ita_url = self.liga_url = ' '
        self.eng_urls = [
            'https://www.topbetta.com.au/sports/football/england-premier-league-round-15-146765',
            ]
        self.ita_urls = [
            'https://www.topbetta.com.au/sports/football/serie-a-tim-round-15-153151',
            'https://www.topbetta.com.au/sports/football/serie-a-tim-round-15-153153',
            'https://www.topbetta.com.au/sports/football/serie-a-tim-round-16-153155',
            'https://www.topbetta.com.au/sports/football/serie-a-tim-round-17-153157',
            ]
        self.liga_urls = [
            'https://www.topbetta.com.au/sports/football/liga-de-futbol-profesional-round-14-151371',  # noqa
            ]

    def fetch(self, matches):
        blocks = self.get_blocks('div.head-to-head-event')
        for b in range(len(blocks)):
            m = Match()
            teams = blocks[b].find_elements_by_css_selector('div.team-container')
            odds = blocks[b].find_elements_by_css_selector('button.js_price-button.price')
            m.home_team = teams[0].text
            m.away_team = teams[1].text
            m.odds[0] = odds[0].text
            m.odds[1] = odds[2].text
            m.odds[2] = odds[1].text
            m.agents = ['TopBetta'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Ubet(Website):
    def __init__(self, driver, wait):
        super(Ubet, self).__init__(driver, wait)
        self.name = 'ubet'
        self.a_url = 'https://ubet.com/sports/soccer/australia-a-league/a-league-matches'
        self.arg_url = 'https://ubet.com/sports/soccer/argentina-primera-division/arg-primera-matches'  # noqa
        self.eng_url = 'https://ubet.com/sports/soccer/england-premier-league/premier-league-matches'  # noqa
        self.ita_url = 'https://ubet.com/sports/soccer/italy-serie-a'
        self.liga_url = 'https://ubet.com/sports/soccer/spain-la-liga'

    def fetch(self, matches):
        blocks = self.get_blocks('div.ubet-sub-events-summary')
        for b in blocks:
            odds = b.find_elements_by_css_selector('div.ubet-offer-win-only')
            match = Match()
            m = []
            for i in range(3):
                m.append(odds[i].text.split('\n'))
                match.odds[i] = m[i][1].replace('LIVE ', '')
                match.agents[i] = 'UBET'
                match.urls[i] = self.get_href_link()
            if 'SUSPENDED' in match.odds[0]:
                continue
            match.home_team = m[0][0]
            match.away_team = m[2][0]
            matches.append(match)


class Unibet(Website):
    def __init__(self, driver, wait):
        super(Unibet, self).__init__(driver, wait)
        self.name = 'unibet'
        self.a_url = 'https://www.unibet.com.au/betting#filter/football/australia/a-league'
        # No arg
        self.eng_url = 'https://www.unibet.com.au/betting#filter/football/england/premier_league'
        # No ita
        self.liga_url = 'https://www.unibet.com.au/betting#filter/football/spain/laliga'

    def fetch(self, matches):
        blocks = self.get_blocks('div.KambiBC-event-item__event-wrapper')
        for b in blocks:
            teams = b.find_elements_by_css_selector('div.KambiBC-event-participants__name')
            odds = b.find_elements_by_css_selector('span.KambiBC-mod-outcome__odds')
            m = Match()
            m.home_team, m.away_team = teams[0].text, teams[1].text
            for i in range(3):
                m.odds[i] = odds[i].text
            m.agents = ['Unibet'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Williamhill(Website):
    def __init__(self, driver, wait):
        super(Williamhill, self).__init__(driver, wait)
        self.name = 'williamhill'
        self.a_url = 'https://www.williamhill.com.au/sports/soccer/australia/a-league-matches'
        self.arg_url = 'https://www.williamhill.com.au/sports/soccer/americas/argentine-primera-division-matches'  # noqa
        self.eng_url = 'https://www.williamhill.com.au/sports/soccer/british-irish/english-premier-league-matches'  # noqa
        self.ita_url = 'https://www.williamhill.com.au/sports/soccer/europe/italian-serie-a-matches'
        self.liga_url = 'https://www.williamhill.com.au/sports/soccer/europe/spanish-primera-division-matches'  # noqa

    def fetch(self, matches):
        if 'rimera' in self.driver.current_url and \
           'rimera' not in self.driver.find_elements_by_css_selector('div.Collapse_root_3H1.FilterList_menu_3g7')[0].text:  # noqa
            return  # La Liga is removed
        blocks = self.driver.find_elements_by_css_selector('div.EventBlock_root_1Pn')
        for b in blocks:
            names = b.find_elements_by_css_selector('span.SoccerListing_name_2g4')
            odds = b.find_elements_by_css_selector('span.BetButton_display_3ty')
            m = Match()
            m.home_team, m.away_team = names[0].text, names[2].text
            for i in range(3):
                m.odds[i] = odds[i].text
            m.agents = ['William'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class WebWorker:
    def __init__(self, is_get_data, keep_driver_alive):
        self.driver, self.wait = False, False
        if is_get_data:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            self.driver = webdriver.Chrome(chrome_options=chrome_options)
            self.driver.implicitly_wait(10)
            self.wait = WebDriverWait(self.driver, 10)
        self.is_get_data = is_get_data
        self.keep_driver_alive = keep_driver_alive

    def run(self,
            websites,
            is_get_a=False,
            is_get_arg=False,
            is_get_eng=False,
            is_get_ita=False,
            is_get_liga=False,
            is_get_only=False,
            is_send_email_api=False,
            is_send_email_smtp=False,
            is_send_email_when_found=False,
            loop_minutes=0,
            ask_gce=None,
            gce_ip=None,
            ):
        def save_to(obj, filename):
            file = os.path.join(gettempdir(), filename)
            with open(file, 'wb') as pkl:
                pickle.dump(obj, pkl)
                if len(obj) == 0:
                    print('WARNING:', filename, 'will be truncated.')
                else:
                    print(filename, 'saved.')

        def prepare_email():
            with open('output.html', 'r') as file, \
                    open('output_title.txt', 'r') as t_file, \
                    open('output_empty_pickles.txt', 'r') as empty_pickles_file, \
                    open('output_urls.txt', 'r') as urls_file:
                title = t_file.read() + ' ' + empty_pickles_file.read()
                content = file.read().replace(HEAD, HEAD + '\n' + urls_file.read() + '\n')
                return title, content

        def send_email_by_api():
            with open('api.key', 'r') as apifile:
                api_key = apifile.read().rstrip()
                title, content = prepare_email()
                requests.post(
                    "https://api.mailgun.net/v3/sandbox2923860546b04b2cbbc985925f26535f.mailgun.org/messages",  # noqa
                    auth=("api", api_key),
                    data={
                        "from": "Mailgun Sandbox <postmaster@sandbox2923860546b04b2cbbc985925f26535f.mailgun.org>",  # noqa
                        "to": "Deqing Huang <khingblue@gmail.com>",
                        "subject": title,
                        'html': content})

        def send_email_by_smtp():
            with open('login.name', 'r') as login_name_file, \
                    open('login.pwd', 'r') as login_pwd_file:
                title, content = prepare_email()
                msg = MIMEText(content)
                msg['Subject'] = title
                msg['From'] = "Mailgun Sandbox <postmaster@sandbox2923860546b04b2cbbc985925f26535f.mailgun.org>"  # noqa
                msg['To'] = "Deqing Huang <khingblue@gmail.com>"

                login_name = login_name_file.read()
                login_pwd = login_pwd_file.read()
                s = smtplib.SMTP('smtp.mailgun.org', 2525)
                s.login(login_name, login_pwd)
                s.sendmail(msg['From'], msg['To'], msg.as_string())
                s.quit()

        def fetch_and_save_to_pickle(website, league):
            pkl_name = league + '_' + website.name + '.pkl'
            matches = []
            try:
                if website.ask_gce:
                    matches_json = requests.get(
                        'http://{}:5000/please_tell_me_what_is_the_odds_of_this_website'.format(gce_ip),  # noqa
                        params={'league': league,
                                'website': website.name}).json()['matches']
                    for m_json in matches_json:
                        match = Match()
                        match.init_with_json(m_json)
                        matches.append(match)
                else:
                    urls = [getattr(website, league + '_url')]
                    if hasattr(website, league + '_urls'):  # Currently only Topbetta has loop
                        urls = getattr(website, league + '_urls')

                    for url in urls:
                        if website.use_request:
                            website.content = requests.get(url).text.split('\n')
                        else:
                            self.driver.get(url)
                            time.sleep(2)
                        if hasattr(website, league + '_urls'):
                            setattr(website, league + '_url', url)
                            print('... will get next url after 10 secs...')
                            time.sleep(10)
                        website.current_league = league
                        website.fetch(matches)
                save_to(matches, pkl_name)
            except Exception as e:
                logging.exception(e)
                _, _, eb = sys.exc_info()
                traceback.print_tb(eb)
                save_to([], pkl_name)

        websites_str = websites if websites != 'all' else 'bet365,betstar,crownbet,ladbrokes,luxbet,madbookie,palmerbet,pinnacle,sportsbet,tab,topbetta,ubet,unibet,williamhill'  # noqa
        websites = []
        website_map = {}
        for w in websites_str.split(','):
            # e.g. when w is 'tab': o = Tab(driver, wait)
            o = globals()[w.title()](self.driver, self.wait)
            websites.append(o)
            website_map[w] = o

        if ask_gce is not None:
            for w in ask_gce.split(','):
                website_map[w].ask_gce = True

        def set_pickles(league):
            return [league + '_' + w_.name + '.pkl'
                    for w_ in websites if getattr(w_, league + '_url')]
        pickles_a = set_pickles('a') if is_get_a else []
        pickles_arg = set_pickles('arg') if is_get_arg else []
        pickles_eng = set_pickles('eng') if is_get_eng else []
        pickles_ita = set_pickles('ita') if is_get_ita else []
        pickles_liga = set_pickles('liga') if is_get_liga else []
        match_merger = MatchMerger(pickles_a, pickles_arg, pickles_eng, pickles_ita, pickles_liga)

        html_file = WriteToHtmlFile()
        while True:
            for l in 'a', 'arg', 'eng', 'ita', 'liga':
                if eval('is_get_' + l):
                    for w in websites:
                        if self.is_get_data and getattr(w, l+'_url'):
                            fetch_and_save_to_pickle(w, l)
                    if not is_get_only:
                        html_file.init()
                        match_merger.merge_and_print(leagues=[l], html_file=html_file)
                        html_file.close()
                        if is_send_email_smtp:
                            send_email_by_smtp()
                        if is_send_email_api:
                            send_email_by_api()
                        if is_send_email_when_found:
                            with open('output_title.txt', 'r') as title_file:
                                if title_file.read() != 'None':
                                    send_email_by_api()

            if is_get_only or loop_minutes is 0:
                if self.driver and not self.keep_driver_alive:
                    self.driver.quit()
                break

            for m in range(loop_minutes):
                print('Will rescan in {} minute{} ...'.format(
                    loop_minutes-m, '' if loop_minutes-m == 1 else 's'))
                time.sleep(60)
