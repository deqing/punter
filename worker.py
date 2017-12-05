"""
TODO

add champions league
add germany
add france

restarting aws:
https://aws.amazon.com/premiumsupport/knowledge-center/start-stop-lambda-cloudwatch/
http://boto3.readthedocs.io/en/latest/reference/services/ec2.html?highlight=start_instances#EC2.Client.reboot_instances

cronjob (when python able to write to file)
https://www.taniarascia.com/setting-up-a-basic-cron-job-in-linux/

Don't do:
- calculator - live is Phone only
- add neds.com.au (not easy to get by css)
"""

import re
import pickle
from colorama import Fore, Back, Style
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException, \
    StaleElementReferenceException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions
import time
import requests
import traceback
from tempfile import gettempdir
import os
import smtplib
from email.mime.text import MIMEText
import sys
from datetime import datetime
import logging
from logging.handlers import RotatingFileHandler


HEAD = '<html lang="en">\n'
log_to_file = False
g_leagues = ('a', 'arg', 'eng', 'gem', 'ita', 'liga', 'uefa', 'w')
g_websites_str = 'bet365,bluebet,crownbet,ladbrokes,luxbet,madbookie,palmerbet,pinnacle,sportsbet,tab,topbetta,ubet,unibet,williamhill'  # noqa


def log_init():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)

    # Set up logging to file
    log_file_name = os.path.join(gettempdir(), 'worker.log')
    handler = RotatingFileHandler(log_file_name, 'a', 2000, 5)
    formatter = logging.Formatter(fmt='[%(asctime)s] %(message)s', datefmt='%Y-%m-%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    print('Log file: ' + log_file_name)


def color_print(msg, foreground='black', background='white'):
    fground = foreground.upper()
    bground = background.upper()
    style = getattr(Fore, fground) + getattr(Back, bground)
    print(style + msg + Style.RESET_ALL)


def log_and_print(s, highlight=False):
    if highlight:
        color_print(s, background='yellow')
    else:
        print(s)
    if log_to_file:
        logging.getLogger().info(s)


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

    def display(self, html_file=WriteToHtmlFileDummy()):
        msg = '{:.2f}\t{:.2f}({})({})({})\t{:.2f}({})({})({})\t{:.2f}({})({})({})\t' \
              '- {} vs {}'.format(
                self.profit,
                float(self.odds[0]), self.agents[0], self.perts[0], self.earns[0],
                float(self.odds[1]), self.agents[1], self.perts[1], self.earns[1],
                float(self.odds[2]), self.agents[2], self.perts[2], self.earns[2],
                self.home_team, self.away_team)
        if self.has_other_agents:
            msg += '\t(' + '|'.join([','.join(x) for x in self.other_agents]) + ')'

        if float(self.profit) > 99.9:
            log_and_print(msg, highlight=True)
            html_file.write_highlight_line(msg, self.urls)
        else:
            log_and_print(msg)
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
                    log_and_print('WARNING: calculate_best_shot() exception: ' + str(e))
                    continue


class MatchMerger:
    def __init__(self,
                 pickles_a,
                 pickles_arg,
                 pickles_eng,
                 pickles_gem,
                 pickles_ita,
                 pickles_liga,
                 pickles_uefa,
                 pickles_w,
                 ):
        self.pickles_a = pickles_a
        self.pickles_arg = pickles_arg
        self.pickles_eng = pickles_eng
        self.pickles_gem = pickles_gem
        self.pickles_ita = pickles_ita
        self.pickles_liga = pickles_liga
        self.pickles_uefa = pickles_uefa
        self.pickles_w = pickles_w

        # Keyword --> Display Name
        # Keyword: a string with lowercase + whitespace removing
        # The map need to be 1:1 as it will be used by home+away as matches key !IMPORTANT!
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
        self.gem_map = {
            'augsburg': 'Augsburg',
            'hertha': 'Hertha Berlin',
            'bremen': 'Werder Bremen',
            'dortmund': 'Borussia Dortmund',
            'frankfurt': 'Eintracht Frankfurt',
            'freiburg': 'Freiburg',
            'hamburg': 'Hamburger SV',
            'hannover': 'Hannover 96',
            'hoffenheim': 'Hoffenheim',
            'koln': 'FC Koln',
            'leipzig': 'RB Leipzig',
            'leverkusen': 'Bayer Leverkusen',
            'mainz': 'Mainz 05',
            'nchengladbach': 'Borussia Monchengladbach',
            'bayern': 'Bayern Munich',
            'schalke': 'Schalke 04',
            'stuttgart': 'Stuttgart',
            'wolfsburg': 'Wolfsburg',
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
        self.uefa_map = {
            'anderlecht': 'Anderlecht',
            'apoel': 'APOEL Nicosia',
            'atleticomadrid': 'Atletico Madrid',
            'barcelona': 'Barcelona',
            'basel': 'FC Basel',
            'bayern': 'Bayern Munich',
            'benfica': 'Benfica',
            'besiktas': 'Besiktas JK',
            'celtic': 'Celtic',
            'chelsea': 'Chelsea',
            'cska': 'CSKA Moscow',
            'dortmund': 'Borussia Dortmund',
            'feyenoord': 'Feyenoord',
            'juventus': 'Juventus',
            'leipzig': 'RB Leipzig',
            'sporting': 'Sporting Lisbon',
            'liverpool': 'Liverpool',
            'mancity': 'Manchester City',
            'manutd': 'Manchester United',
            'maribor': 'NK Maribor',
            'monaco': 'AS Monaco',
            'napoli': 'Napoli',
            'olympia': 'Olympiakos',
            'paris': 'Paris Saint Germain',
            'porto': 'FC Porto',
            'qarabag': 'FK Qarabag',
            'realmad': 'Real Madrid',
            'roma': 'AS Roma',
            'sevilla': 'Sevilla',
            'shakhtar': 'Shakhtar Donetsk',
            'spartak': 'Spartak Moscow',
            'tottenham': 'Tottenham Hotspur',
        }
        self.w_map = {
            'adelaide': 'Adelaide United',
            'brisbane': 'Brisbane Roar',
            'canberra': 'Canberra United',
        }
        self.a_league_keys = list(self.a_league_map.keys())
        self.arg_keys = list(self.arg_map.keys())
        self.eng_keys = list(self.eng_map.keys())
        self.gem_keys = list(self.gem_map.keys())
        self.ita_keys = list(self.ita_map.keys())
        self.la_liga_keys = list(self.la_liga_map.keys())
        self.uefa_keys = list(self.uefa_map.keys())
        self.w_keys = list(self.w_map.keys())

    @staticmethod
    def get_id(team_name, keys, league_name, p_name):
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
            if 'olimpo' in converted_name:
                converted_name = 'blanca'
            elif 'velez' in converted_name:
                converted_name = 'rsfield'
            elif 'lanús' == converted_name:
                converted_name = 'lanus'
            elif 'colón' == converted_name:
                converted_name = 'colon'
        elif league_name == 'UEFA Champions League':
            if 'manchestercity' == converted_name:
                converted_name = 'mancity'
            elif 'lisbon' in converted_name:
                converted_name = 'sporting'
            elif 'psg' in converted_name:
                converted_name = 'paris'
            elif 'ticodemadrid' in converted_name or 'atlmadrid' == converted_name \
                    or 'ticomadrid' in converted_name:
                converted_name = 'atleticomadrid'
            elif 'manchesterunited' in converted_name or 'manunited' == converted_name:
                converted_name = 'manutd'
            elif 'karabakh' in converted_name or 'qaraba' in converted_name:
                converted_name = 'qarabag'
        elif league_name == 'German Bundesliga':
            if 'fcköln' in converted_name or 'koeln' in converted_name or \
                    'cologne' == converted_name:
                converted_name = 'koln'
            elif 'mgladbach' == converted_name or 'bormonch' == converted_name or \
                            'gladbach' in converted_name:
                converted_name = 'nchengladbach'

        for name in keys:
            if name in converted_name:
                return name
        log_and_print('WARNING: [{}] - {}[{}] is not found in the map of {}!'.format(
            p_name, team_name, converted_name, league_name))
        return None

    def merge_and_print(self, leagues, html_file):
        def odds_to_float(match, league_name_):
            # Convert text to float
            match.odds = list(match.odds)
            for i_ in range(3):
                try:
                    match.odds[i_] = float(match.odds[i_])
                except ValueError:
                    log_and_print('WARNING converting website [{}] league [{}] odds [{}]'
                                  .format(match.agents[0], league_name_, match.odds[i_]))
                    match.odds[i_] = 0

        empty_count = 0
        loop = []
        if 'a' in leagues:
            loop.append((self.pickles_a, self.a_league_keys, self.a_league_map, 'Australia League'))
        elif 'arg' in leagues:
            loop.append((self.pickles_arg, self.arg_keys, self.arg_map, 'Argentina Superliga'))
        elif 'eng' in leagues:
            loop.append((self.pickles_eng, self.eng_keys, self.eng_map, 'English Premier League'))
        elif 'gem' in leagues:
            loop.append((self.pickles_gem, self.gem_keys, self.gem_map, 'German Bundesliga'))
        elif 'ita' in leagues:
            loop.append((self.pickles_ita, self.ita_keys, self.ita_map, 'Italian Serie A'))
        elif 'liga' in leagues:
            loop.append((self.pickles_liga, self.la_liga_keys, self.la_liga_map, 'Spanish La Liga'))
        elif 'uefa' in leagues:
            loop.append((self.pickles_uefa, self.uefa_keys, self.uefa_map, 'UEFA Champions League'))
        elif 'w' in leagues:
            loop.append((self.pickles_w, self.w_keys, self.w_map, 'Australia W-League'))
        else:
            log_and_print('WARNING: merge_and_print unexpected league: ' + str(leagues))

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
                            id1 = self.get_id(pm.home_team, keys, league_name, p_name)
                            id2 = self.get_id(pm.away_team, keys, league_name, p_name)
                            if id1 is None or id2 is None:
                                continue
                            odds_to_float(pm, league_name)

                            key = id1 + id2
                            if key not in matches.keys():
                                m = Match()
                                m.__dict__.update(pm.__dict__)
                                m.odds = list(m.odds)  # Sometimes it's an immutable tuple
                                m.home_team = league_map[self.get_id(pm.home_team, keys, league_name, p_name)]  # noqa
                                m.away_team = league_map[self.get_id(pm.away_team, keys, league_name, p_name)]  # noqa
                                matches[key] = m
                            else:
                                m = matches[key]
                                for i in range(3):
                                    if pm.odds[i] > m.odds[i]:
                                        m.odds[i] = pm.odds[i]
                                        m.agents[i] = pm.agents[i]
                                        m.urls[i] = pm.urls[i]
                                        m.has_other_agents = False
                                        m.other_agents[i] = []
                                    elif pm.odds[i] == m.odds[i]:
                                        m.has_other_agents = True
                                        m.other_agents[i].append(pm.agents[i].strip())
            matches = sorted(matches.values())
            if len(matches) is not 0:
                output = '--- {} ---'.format(league_name)
                empty_str = '({} pickles, empty: [{}])'.format(len(pickles), empty_names.rstrip())
                log_and_print(output + empty_str)

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
        self.gem_url = False
        self.ita_url = False
        self.liga_url = False
        self.uefa_url = False
        self.w_url = False
        self.name = ''
        self.current_league = ''
        self.ask_gce = False

    def get_blocks(self, css_string):
        try:
            self.wait.until(expected_conditions.visibility_of_element_located((By.CSS_SELECTOR, css_string)))  # noqa
        except TimeoutException:
            log_and_print('[{}] not found'.format(css_string))
            return []
        blocks = self.driver.find_elements_by_css_selector(css_string)
        return blocks

    # In Pinnacle, the url that unlogined account can see is different with logined account
    def get_href_link(self, get_logined=False):
        """
        e.g. return <a href='https://www.tab.com.au/sports/betting/Soccer/competitions/A%20League'>tab</a>  # noqa
        """
        url = '_url_logined' if get_logined else '_url'
        return '<a href="' + getattr(self, self.current_league + url) + '">' + self.name + '</a>'

    def fetch(self, _):
        log_and_print('WARNING: fetch() should be overridden.')


class Bet365(Website):
    def __init__(self, driver, wait):
        super(Bet365, self).__init__(driver, wait)
        self.name = 'bet365'
        self.a_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-27119403-2-18-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=1;anim=1'  # noqa
        self.arg_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-34240206-2-12-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=30;anim=1'  # noqa
        self.eng_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-33577327-2-1-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=30;anim=1'  # noqa
        self.gem_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-33754901-2-7-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=30;anim=1'  # noqa
        self.ita_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-34031004-2-6-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=30;anim=1'  # noqa
        self.liga_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-33977144-2-8-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=1;anim=1'  # noqa
        self.uefa_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-34343042-2-3-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=30;anim=1'  # noqa
        self.w_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-34948113-2-18-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=30;anim=1'  # noqa

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


class Bluebet(Website):
    def __init__(self, driver, wait):
        super(Bluebet, self).__init__(driver, wait)
        self.name = 'bluebet'
        self.a_url = 'https://www.bluebet.com.au/sports/Soccer/Australia/Hyundai-A-League/38925'
        self.arg_url = 'https://www.bluebet.com.au/sports/Soccer/Argentina/Primera-Divisi%C3%B3n/28907'  # noqa
        self.eng_url = 'https://www.bluebet.com.au/sports/Soccer/England/English-Premier-League/36715'  # noqa
        self.gem_url = 'https://www.bluebet.com.au/sports/Soccer/Germany/Bundesliga/27243'
        self.ita_url = 'https://www.bluebet.com.au/sports/Soccer/Italy/Serie-A-TIM/27245'
        self.liga_url = 'https://www.bluebet.com.au/sports/Soccer/Spain/Liga-de-F%C3%BAtbol-Profesional/27225'  # noqa
        self.uefa_url = 'https://www.bluebet.com.au/sports/Soccer/Europe/UEFA-Champions-League/25325'  # noqa
        self.w_url = 'https://www.bluebet.com.au/sports/Soccer/Australia/Westfield-W-League/40620'

    def fetch(self, matches):
        blocks = self.get_blocks('section.push--bottom.ng-scope')
        for b in blocks:
            info = b.find_elements_by_css_selector('div.flag-object.flag--tight')
            if len(info) != 3:
                log_and_print('bluebet - unexpected info: [{}]'.format(info.text))
            info0 = info[0].text.split('\n')
            info1 = info[1].text.split('\n')
            info2 = info[2].text.split('\n')
            m = Match()
            m.home_team, m.away_team = info0[0], info2[0]
            m.odds[0] = info0[1]
            m.odds[1] = info1[1]
            m.odds[2] = info2[1]

            m.agents = ['Bluebet'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Crownbet(Website):
    def __init__(self, driver, wait):
        super(Crownbet, self).__init__(driver, wait)
        self.name = 'crownbet'
        self.a_url = 'https://crownbet.com.au/sports-betting/soccer/australia/a-league-matches'
        self.arg_url = 'https://crownbet.com.au/sports-betting/soccer/americas/argentina-primera-division-matches'  # noqa
        self.eng_url = 'https://crownbet.com.au/sports-betting/soccer/united-kingdom/english-premier-league-matches'  # noqa
        self.gem_url = 'https://crownbet.com.au/sports-betting/soccer/germany/german-bundesliga-matches'  # noqa
        self.ita_url = 'https://crownbet.com.au/sports-betting/soccer/italy/italian-serie-a-matches/'  # noqa
        self.liga_url = 'https://crownbet.com.au/sports-betting/soccer/spain/spanish-la-liga-matches/'  # noqa
        self.uefa_url = 'https://crownbet.com.au/sports-betting/soccer/uefa-competitions/champions-league-matches/'  # noqa
        self.w_url = 'https://crownbet.com.au/sports-betting/soccer/australia/w-league-matches/'

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


class Ladbrokes(Website):  # BetStar (and Bookmarker?) are the same
    def __init__(self, driver, wait):
        super(Ladbrokes, self).__init__(driver, wait)
        self.name = 'ladbrokes'
        self.a_url = 'https://www.ladbrokes.com.au/sports/soccer/39445848-football-australia-australian-a-league/?utm_source=%2Fsports%2Fsoccer%2F35326546-australian-a-league-2017-2018%2F35326546-australian-a-league-2017-2018%2F&utm_medium=sport+banner&utm_campaign=a+league+round+4'  # noqa
        self.arg_url = 'https://www.ladbrokes.com.au/sports/soccer/43008934-football-argentina-argentinian-primera-division/'  # noqa
        self.eng_url = 'https://www.ladbrokes.com.au/sports/soccer/41388947-football-england-premier-league/'  # noqa
        self.gem_url = 'https://www.ladbrokes.com.au/sports/soccer/42213482-football-germany-german-bundesliga/'  # noqa
        self.ita_url = 'https://www.ladbrokes.com.au/sports/soccer/42212441-football-italy-italian-serie-a/'   # noqa
        self.liga_url = 'https://www.ladbrokes.com.au/sports/soccer/40962944-football-spain-spanish-la-liga/'  # noqa
        self.uefa_url = 'https://www.ladbrokes.com.au/sports/soccer/43625772-football-uefa-club-competitions-uefa-champions-league/'  # noqa

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
        self.gem_url = 'https://www.luxbet.com/?cPath=624&event_id=ALL'
        self.ita_url = 'https://www.luxbet.com/?cPath=1172&event_id=ALL'
        self.liga_url = 'https://www.luxbet.com/?cPath=931&event_id=ALL'
        self.uefa_url = 'https://www.luxbet.com/?cPath=6781&event_id=ALL'
        self.w_url = 'https://www.luxbet.com/?cPath=2436&event_id=ALL'

    def fetch(self, matches):
        if self.current_league == 'w':
            blocks = self.get_blocks('table.eaw_group')
            for b in blocks:
                info = b.text.split('\n')
                if info[0] != 'Match Result':
                    continue
                if len(info) != 6:
                    log_and_print('luxbet - unexpected info: ' + b.text)
                info3 = info[3].split(' ')
                info4 = info[4].split(' ')
                info5 = info[5].split(' ')
                m = Match()
                m.odds[0] = info3.pop()
                m.odds[1] = info5.pop()
                m.odds[2] = info4.pop()
                m.home_team = ' '.join(info3)
                m.away_team = ' '.join(info4)

                m.agents = ['Luxbet'] * 3
                m.urls = [self.get_href_link()] * 3
                matches.append(m)
        else:
            blocks = self.get_blocks('tr.asian_display_row')
            for b in blocks:
                if b.text.split('\n')[0] == 'IN PLAY':
                    continue
                m = Match()
                teams = b.find_elements_by_css_selector('div.bcg_asian_selection_name')
                if len(teams) < 3:
                    log_and_print('luxbet - unexpected team info ' + b.text)
                    continue
                m.home_team, m.away_team = teams[0].text, teams[2].text

                try:
                    odds_text = b.find_element_by_css_selector('td.asian_market_cell.market_type_template_12').text  # noqa
                except NoSuchElementException:
                    log_and_print('luxbet - unexpected odds in ' + b.text)
                    continue
                odds = odds_text.split('\n')
                if len(odds) < 3:
                    log_and_print('luxbet: there are no 3 odds in ' + odds_text)
                    continue
                for i in range(3):
                    m.odds[i] = odds[i].strip()

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
        self.gem_url = 'https://www.madbookie.com.au/Sport/Soccer/German_Bundesliga/Matches'
        self.ita_url = 'https://www.madbookie.com.au/Sport/Soccer/Italian_Serie_A/Matches'
        self.liga_url = 'https://www.madbookie.com.au/Sport/Soccer/Spanish_La_Liga/Matches'
        self.uefa_url = 'https://www.madbookie.com.au/Sport/Soccer/UEFA_Champions_League/Matches'
        self.w_url = 'https://www.madbookie.com.au/Sport/Soccer/Australian_W-League/Matches'

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
        self.gem_url = 'https://www.palmerbet.com/sports/soccer/germany-bundesliga'
        self.ita_url = 'https://www.palmerbet.com/sports/soccer/italy-serie-a'
        self.liga_url = 'https://www.palmerbet.com/sports/soccer/spain-primera-division'
        self.uefa_url = 'https://www.palmerbet.com/sports/soccer/uefa-champions-league'
        self.w_url = 'https://www.palmerbet.com/sports/soccer/australia-w_league'

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
        self.gem_url = 'https://www.pinnacle.com/en/odds/match/soccer/germany/bundesliga'
        self.ita_url = 'https://www.pinnacle.com/en/odds/match/soccer/italy/italy-serie-a'
        self.liga_url = 'https://www.pinnacle.com/en/odds/match/soccer/spain/spain-la-liga'
        self.uefa_url = 'https://www.pinnacle.com/en/odds/match/soccer/uefa/uefa-champions-league'
        self.a_url_logined = 'https://beta.pinnacle.com/en/Sports/29/Leagues/1766'
        self.arg_url_logined = 'https://beta.pinnacle.com/en/Sports/29/Leagues/1740'
        self.eng_url_logined = 'https://beta.pinnacle.com/en/Sports/29/Leagues/1980'
        self.gem_url_logined = 'https://beta.pinnacle.com/en/Sports/29/Leagues/1842'
        self.ita_url_logined = 'https://beta.pinnacle.com/en/Sports/29/Leagues/2436'
        self.liga_url_logined = 'https://beta.pinnacle.com/en/Sports/29/Leagues/2196'
        self.uefa_url_logined = 'https://beta.pinnacle.com/en/Sports/29/Leagues/2627'

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
                m.urls = [self.get_href_link(get_logined=True)] * 3
                matches.append(m)


class Sportsbet(Website):
    def __init__(self, driver, wait):
        super(Sportsbet, self).__init__(driver, wait)
        self.name = 'sportsbet'
        self.a_url = 'https://www.sportsbet.com.au/betting/soccer/australia/australian-a-league'
        self.arg_url = 'https://www.sportsbet.com.au/betting/soccer/americas/argentinian-primera-division'  # noqa
        self.eng_url = 'https://www.sportsbet.com.au/betting/soccer/united-kingdom/english-premier-league'  # noqa
        self.gem_url = 'https://www.sportsbet.com.au/betting/soccer/germany/german-bundesliga'
        self.ita_url = 'https://www.sportsbet.com.au/betting/soccer/italy/italian-serie-a'
        self.liga_url = 'https://www.sportsbet.com.au/betting/soccer/spain/spanish-la-liga'
        self.uefa_url = 'https://www.sportsbet.com.au/betting/soccer/uefa-competitions/uefa-champions-league'  # noqa
        self.w_url = 'https://www.sportsbet.com.au/betting/soccer/australia/australian-w-league-ladies'  # noqa
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
                elif status is not None and status != 'wait draw':
                    log_and_print('WARNING: sportsbet has unexpected input')
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
        self.gem_url = 'https://www.tab.com.au/sports/betting/Soccer/competitions/German%20Bundesliga'  # noqa
        self.ita_url = 'https://www.tab.com.au/sports/betting/Soccer/competitions/Italian%20Serie%20A'  # noqa
        self.liga_url = 'https://www.tab.com.au/sports/betting/Soccer/competitions/Spanish%20Primera%20Division'  # noqa
        self.uefa_url = 'https://www.tab.com.au/sports/betting/Soccer/competitions/UEFA%20Champions%20League'  # noqa
        self.w_url = 'https://www.tab.com.au/sports/betting/Soccer/competitions/Australia%20W%20League'  # noqa

    def fetch(self, matches):
        blocks = self.get_blocks('div.template-item.ng-scope')
        for b in blocks:
            teams = b.find_element_by_css_selector(
                'span.match-name-text.ng-binding').text.split(' v ')
            if len(teams) != 2:
                log_and_print('Tab - unexpected teams in: ' + b.text)
                continue
            m = Match()
            m.home_team, m.away_team = teams[0], teams[1]
            odds = b.find_elements_by_css_selector('div.animate-odd.ng-binding.ng-scope')
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
        self.eng_url = self.gem_url = self.ita_url = self.liga_url = self.uefa_url = ' '
        self.eng_urls = [
            'https://www.topbetta.com.au/sports/football/england-premier-league-round-16-146767',
            'https://www.topbetta.com.au/sports/football/england-premier-league-round-17-146769',
            ]
        self.gem_urls = [
            'https://www.topbetta.com.au/sports/football/bundesliga-round-15-150651',
            'https://www.topbetta.com.au/sports/football/bundesliga-round-16-150653',
            ]
        self.ita_urls = [
            'https://www.topbetta.com.au/sports/football/serie-a-tim-round-16-153155',
            'https://www.topbetta.com.au/sports/football/serie-a-tim-round-17-153157',
            ]
        self.liga_urls = [
            'https://www.topbetta.com.au/sports/football/liga-de-futbol-profesional-round-16-151375',  # noqa
            ]
        self.uefa_urls = [
            'https://www.topbetta.com.au/sports/football/uefa-champions-league-group-a-155259',
            'https://www.topbetta.com.au/sports/football/uefa-champions-league-group-b-155261',
            'https://www.topbetta.com.au/sports/football/uefa-champions-league-group-c-155263',
            'https://www.topbetta.com.au/sports/football/uefa-champions-league-group-d-155265',
            'https://www.topbetta.com.au/sports/football/uefa-champions-league-group-e-155267',
            'https://www.topbetta.com.au/sports/football/uefa-champions-league-group-f-155269',
            'https://www.topbetta.com.au/sports/football/uefa-champions-league-group-g-155271',
            'https://www.topbetta.com.au/sports/football/uefa-champions-league-group-h-155273',
        ]

    def fetch(self, matches):
        blocks = self.get_blocks('div.head-to-head-event')
        for b in blocks:
            m = Match()
            try:
                teams = b.find_elements_by_css_selector('div.team-container')
                odds = b.find_elements_by_css_selector('button.js_price-button.price')
                m.home_team = teams[0].text
                m.away_team = teams[1].text
                m.odds[0] = odds[0].text
                m.odds[1] = odds[2].text
                m.odds[2] = odds[1].text
            except StaleElementReferenceException:
                log_and_print('topbetta - Selenium has StaleElementReferenceException: ' + b.text)
                continue
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
        self.gem_url = 'https://ubet.com/sports/soccer/germany-bundesliga'
        self.ita_url = 'https://ubet.com/sports/soccer/italy-serie-a'
        self.liga_url = 'https://ubet.com/sports/soccer/spain-la-liga'
        self.uefa_url = 'https://ubet.com/sports/soccer/uefa-champions-league'
        self.w_url = 'https://ubet.com/sports/soccer/australia-w-league'

    def fetch(self, matches):
        blocks = self.get_blocks('div.ubet-sub-events-summary')
        for b in blocks:
            try:
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
            except StaleElementReferenceException:
                continue


class Unibet(Website):
    def __init__(self, driver, wait):
        super(Unibet, self).__init__(driver, wait)
        self.name = 'unibet'
        self.a_url = 'https://www.unibet.com.au/betting#filter/football/australia/a-league'
        self.arg_url = 'https://www.unibet.com.au/betting#filter/football/argentina/primera_division'  # noqa
        self.eng_url = 'https://www.unibet.com.au/betting#filter/football/england/premier_league'
        self.gem_url = 'https://www.unibet.com.au/betting#filter/football/germany/bundesliga'
        self.ita_url = 'https://www.unibet.com.au/betting#filter/football/italy/serie_a'
        self.liga_url = 'https://www.unibet.com.au/betting#filter/football/spain/laliga'
        self.uefa_url = 'https://www.unibet.com.au/betting#filter/football/champions_league'
        self.w_url = 'https://www.unibet.com.au/betting#filter/football/australia/w-league__w_'

    def fetch(self, matches):
        blocks = self.get_blocks('div.KambiBC-event-item__event-wrapper')
        for b in blocks:
            teams = b.find_elements_by_css_selector('div.KambiBC-event-participants__name')
            odds = b.find_elements_by_css_selector('span.KambiBC-mod-outcome__odds')
            if len(teams) < 2 or len(odds) < 3:
                log_and_print('unibet - incorrect teams or odds: ' + b.text)
                continue
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
        self.gem_url = 'https://www.williamhill.com.au/sports/soccer/europe/german-bundesliga-matches'  # noqa
        self.ita_url = 'https://www.williamhill.com.au/sports/soccer/europe/italian-serie-a-matches'
        self.liga_url = 'https://www.williamhill.com.au/sports/soccer/europe/spanish-primera-division-matches'  # noqa
        self.uefa_url = 'https://www.williamhill.com.au/sports/soccer/european-cups/uefa-champions-league-matches'  # noqa
        self.w_url = 'https://www.williamhill.com.au/sports/soccer/australia/w-league-matches'

    def fetch(self, matches):
        if 'rimera' in self.driver.current_url:  # if is arg
            s = self.driver.find_elements_by_css_selector(
                'div.Collapse_root_3H1.FilterList_menu_3g7')
            if len(s) is 0 or 'rimera' not in s[0].text:
                return  # La Liga is removed
        blocks = self.driver.find_elements_by_css_selector('div.EventBlock_root_1Pn')
        for b in blocks:
            names = b.find_elements_by_css_selector('span.SoccerListing_name_2g4')
            odds = b.find_elements_by_css_selector('span.BetButton_display_3ty')
            if len(names) < 3 or \
               names[0].text == 'BOTH TEAMS TO SCORE' or \
               names[2].text == 'BOTH TEAMS TO SCORE':
                continue
            m = Match()
            m.home_team, m.away_team = names[0].text, names[2].text
            for i in range(3):
                m.odds[i] = odds[i].text
            m.agents = ['William'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class WebWorker:
    def __init__(self, is_get_data, keep_driver_alive, log_to_file_=False):
        self.driver, self.wait = False, False
        if is_get_data:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            self.driver = webdriver.Chrome(chrome_options=chrome_options)
            self.driver.implicitly_wait(10)
            self.wait = WebDriverWait(self.driver, 10)
        self.is_get_data = is_get_data
        self.keep_driver_alive = keep_driver_alive
        global log_to_file
        log_to_file = log_to_file_
        if log_to_file:
            log_init()

    @staticmethod
    def calc_bonus_profit(website='luxbet', stake=50):
        maxp, bmh, bma, bpb, bi, bj, bp1, bp2, ba1, ba2, bob, bo1, bo2\
            = 0, 0, 0, 0, 0, 0, 0, 0, '', '', 0, 0, 0
        for l in g_leagues:
            try:
                with open(os.path.join(gettempdir(), l + '_' + website + '.pkl'), 'rb') as b_pkl:
                    pickle_bonus_matches = pickle.load(b_pkl)
                    if len(pickle_bonus_matches) is 0:
                        continue
                    maxp = 0
                    for bm in pickle_bonus_matches:
                        for w1 in g_websites_str.split(','):
                            if w1 == website:
                                continue
                            try:
                                with open(os.path.join(gettempdir(),
                                                       l + '_' + w1 + '.pkl'), 'rb') as pkl1:
                                    matches1 = pickle.load(pkl1)
                                    if len(matches1) is 0:
                                        continue
                                    for m1 in matches1:
                                        if m1.home_team != bm.home_team or \
                                           m1.away_team != bm.away_team:
                                            continue
                                        for odd_idx in range(3):
                                            ob = odd_idx
                                            o1 = (odd_idx + 1) % 3
                                            o2 = (odd_idx + 2) % 3
                                            for w2 in g_websites_str.split(','):
                                                if w2 == website:
                                                    continue
                                                with open(os.path.join(gettempdir(),
                                                          l + '_' + w2 + '.pkl'), 'rb') as pkl2:
                                                    matches2 = pickle.load(pkl2)
                                                    if len(matches2) is 0:
                                                        continue
                                                    for m2 in matches2:
                                                        if m2.home_team != bm.home_team or \
                                                              m2.away_team != bm.away_team:
                                                            continue
                                                        for i in range(stake * 3):
                                                            for j in range(stake * 3):
                                                                p_bw = float(bm.odds[ob]) * stake - stake - i - j  # noqa
                                                                p_1w = float(m1.odds[o1]) * i - i - j  # noqa
                                                                p_2w = float(m2.odds[o2]) * j - j - i  # noqa
                                                                minp = min(p_bw, p_1w, p_2w)
                                                                if maxp < minp:
                                                                    maxp = minp
                                                                    bmh = bm.home_team
                                                                    bma = bm.away_team
                                                                    bpb = p_bw
                                                                    bp1 = p_1w
                                                                    bp2 = p_2w
                                                                    bi = i
                                                                    bj = j
                                                                    ba1 = m1.agents[0]
                                                                    ba2 = m2.agents[0]
                                                                    bob = float(bm.odds[ob])
                                                                    bo1 = float(m1.odds[o1])
                                                                    bo2 = float(m2.odds[o2])
                                                                elif maxp == minp:
                                                                    ba1 += ' ' + m1.agents[0]
                                                                    ba2 += ' ' + m2.agents[0]
                            except FileNotFoundError:
                                continue
                    log_and_print('Max {:.2f} - '
                                  '{:.2f} (odds {:.2f}) ({:.2f} on {})\t'
                                  '{:.2f} (odds {:.2f}) ({:.2f} on {})\t'
                                  '{:.2f} (odds {:.2f}) ({:.2f} on {}) - {} vs {}'.format(
                                    maxp,
                                    bpb, bob, stake, website,
                                    bp1, bo1, bi, ba1,
                                    bp2, bo2, bj, ba2, bmh, bma))
            except FileNotFoundError:
                continue

    @staticmethod
    def calc_best_shot(o1, o2, o3):
        def min_pay(w, d, l, wp, dp, lp):
            if w * wp <= d * dp and w * wp <= l * lp:
                return w * wp
            if d * dp <= w * wp and d * dp <= l * lp:
                return d * dp
            else:
                return l * lp

        max_profit = 0
        m = Match()
        for i in range(100):
            for j in range(100 - i):
                profit = min_pay(o1, o2, o3,
                                 i, j, 100 - i - j)
                if profit > max_profit:
                    max_profit = profit
                    m.perts[0] = i
                    m.perts[1] = j
                    m.perts[2] = 100 - i - j
                    m.earns[0] = round(i*o1 - 100, 2)
                    m.earns[1] = round(j*o2 - 100, 2)
                    m.earns[2] = round((100-i-j)*o3 - 100, 2)
                    m.odds = o1, o2, o3
                    m.profit = profit
        m.display()
                    
    def run(self,
            websites,
            is_get_a=False,
            is_get_arg=False,
            is_get_eng=False,
            is_get_gem=False,
            is_get_ita=False,
            is_get_liga=False,
            is_get_uefa=False,
            is_get_w=False,
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
                    log_and_print('WARNING: ' + filename + ' will be truncated.')
                else:
                    log_and_print(filename + ' saved.')

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
                            log_and_print('... will get next url after 10 secs...')
                            time.sleep(10)
                        website.current_league = league
                        website.fetch(matches)
                save_to(matches, pkl_name)
            except Exception as e:
                logging.exception(e)
                _, _, eb = sys.exc_info()
                traceback.print_tb(eb)
                save_to([], pkl_name)

        websites_str = websites if websites != 'all' else g_websites_str
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
        match_merger = MatchMerger(set_pickles('a') if is_get_a else [],
                                   set_pickles('arg') if is_get_arg else [],
                                   set_pickles('eng') if is_get_eng else [],
                                   set_pickles('gem') if is_get_gem else [],
                                   set_pickles('ita') if is_get_ita else [],
                                   set_pickles('liga') if is_get_liga else [],
                                   set_pickles('uefa') if is_get_uefa else [],
                                   set_pickles('w') if is_get_w else [])

        def send_email_when_found():
            with open('output_title.txt', 'r') as title_file:
                title = title_file.read()
                if title != 'None':
                    with open('output_title.old.txt', 'r+') as title_old_file:
                        if title != title_old_file.read():
                            send_email_by_api()
                            title_old_file.write(title)
                        else:
                            log_and_print('INFO: send_email_when_found - email already sent')

        html_file = WriteToHtmlFile()
        while True:
            whole_start_time = datetime.now()
            for l in g_leagues:
                if eval('is_get_' + l):
                    league_start_time = datetime.now()
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
                            send_email_when_found()
                    log_and_print('League [{}] scan time: {}'
                                  .format(l, datetime.now()-league_start_time))
            log_and_print('Whole scan time: {}'.format(datetime.now()-whole_start_time))

            if is_get_only or loop_minutes is 0:
                if self.driver and not self.keep_driver_alive:
                    self.driver.quit()
                break

            for m in range(loop_minutes):
                log_and_print('Will rescan in {} minute{} ...'.format(
                    loop_minutes-m, '' if loop_minutes-m == 1 else 's'))
                time.sleep(60)
