"""
TODO

restarting aws:
https://aws.amazon.com/premiumsupport/knowledge-center/start-stop-lambda-cloudwatch/
http://boto3.readthedocs.io/en/latest/reference/services/ec2.html?highlight=start_instances#EC2.Client.reboot_instances

cronjob (when python able to write to file)
https://www.taniarascia.com/setting-up-a-basic-cron-job-in-linux/

Don't do:
- live bet - live is Phone only
- add neds.com.au (not easy to get by css)
"""

import logging
import os
import pickle
import re
import requests
import smtplib
import sys
import threading
import time
import traceback
from colorama import Fore, Back, Style
from datetime import datetime
from email.mime.text import MIMEText
from logging.handlers import RotatingFileHandler
from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException
from selenium.common.exceptions import StaleElementReferenceException
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions
from selenium.webdriver.support.ui import WebDriverWait
from tempfile import gettempdir


HEAD = '<html lang="en">\n'
log_to_file = False
g_leagues = ('a', 'arg', 'eng', 'fra', 'gem', 'ita', 'liga', 'uefa', 'w')
g_websites_str = 'bet365,bluebet,crownbet,ladbrokes,madbookie,palmerbet,pinnacle,sportsbet,tab,ubet,unibet,williamhill'  # noqa


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


def log_and_print(s, highlight=None, same_line=False):
    def color_print(msg, foreground='black', background='white'):
        fground = foreground.upper()
        bground = background.upper()
        style = getattr(Fore, fground) + getattr(Back, bground)
        print(style + msg + Style.RESET_ALL)

    if highlight is not None:
        color_print(s, background=highlight)
    elif same_line:
        print('\r' + s, end='')
    else:
        print(s)
    if log_to_file:
        logging.getLogger().info(s)


# e.g. 'Both to Score' -> 'bothtoscore'
def squash_string(name):
    return ''.join(name.lower().split())


def real_back_odd(odd):
    return ((odd - 1) * 95 + 100) / 100


class MonitorMatch:
    def __init__(self):
        self.home, self.away, self.odd1, self.odd2, self.odd3 = None, None, None, None, None
        self.do = False

    def init(self, h_, a_, o1_=None, o2_=None, o3_=None):
        self.home, self.away, self.odd1, self.odd2, self.odd3 = h_, a_, o1_, o2_, o3_
        self.do = True

    def compare(self, h_, a_, o1_, o2_, o3_):
        if self.home != h_ or self.away != a_:
            return False
        else:
            return not (self.odd1 is not None and self.odd1 >= o1_ or
                        self.odd2 is not None and self.odd2 >= o2_ or
                        self.odd3 is not None and self.odd3 >= o3_)


g_monitor_match = MonitorMatch()


class TimeIt:
    def __init__(self, top=False, bottom=False):
        self.top_start_time, self.bottom_start_time = None, None
        self.top = top
        self.bottom = bottom

    def reset(self):
        if self.bottom:
            self.bottom_start_time = datetime.now()

    def reset_top(self):
        if self.top:
            self.top_start_time = datetime.now()

    def log(self, s):
        if self.bottom:
            log_and_print(s + ': {}'.format(datetime.now() - self.bottom_start_time))

    def top_log(self, s):
        if self.top:
            log_and_print(s + ': {}'.format(datetime.now() - self.top_start_time))


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
        self.odds = [0.0] * 3
        self.perts = [0.0] * 3
        self.earns = [0.0] * 3
        self.agents = [''] * 3
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
        def width(odd):
            return '{:0.2f}'.format(odd)

        msg = '{}\t{}({})({})({})\t{}({})({})({})\t{}({})({})({})\t' \
              '- {} vs {}'.format(
                width(self.profit),
                width(self.odds[0]), self.agents[0], width(self.perts[0]), width(self.earns[0]),
                width(self.odds[1]), self.agents[1], width(self.perts[1]), width(self.earns[1]),
                width(self.odds[2]), self.agents[2], width(self.perts[2]), width(self.earns[2]),
                self.home_team, self.away_team)
        if self.has_other_agents:
            msg += '\t(' + '|'.join([','.join(x) for x in self.other_agents]) + ')'

        global g_monitor_match
        if g_monitor_match.do and g_monitor_match.compare(self.home_team, self.away_team,
                                                          self.odds[0], self.odds[1], self.odds[2])\
                or self.profit > 99.9:
            log_and_print(msg, highlight='yellow')
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

        for i in range(1, 99):
            for j in range(1, 100 - i):
                profit = min_pay(self.odds[0],
                                 self.odds[1],
                                 self.odds[2],
                                 i, j, 100 - i - j)
                if profit > self.profit:
                    self.profit = profit
                    self.perts[0] = i
                    self.perts[1] = j
                    self.perts[2] = 100 - i - j
                    self.earns[0] = round(i*self.odds[0] - 100, 2)
                    self.earns[1] = round(j*self.odds[1] - 100, 2)
                    self.earns[2] = round((100-i-j)*self.odds[2] - 100, 2)


class BetfairMatch(Match):
    def __init__(self):
        Match.__init__(self)
        self.lays = [0, 0, 0]


class MarketNames:
    def __init__(self):
        self.desc = {
            'main': 'Main Market',
            'both score': 'Both teams to Score?',
            'correct score': 'Correct Score',
            '1st scorer': 'First Goal Scorer',
            'first 0.5': 'First Half Goals 0.5',
            'first 1.5': 'First Half Goals 1.5',
            'half full': 'Half Time / Full Time',
            '+- 0.5': 'Over/Under 0.5 Goals',
            '+- 1.5': 'Over/Under 1.5 Goals',
            '+- 2.5': 'Over/Under 2.5 Goals',
            '+- 3.5': 'Over/Under 3.5 Goals',
            '+- 4.5': 'Over/Under 4.5 Goals',
        }

    def desc(self, key):
        return self.desc[key]

    def key(self, market_str):
        if market_str == 'Half Time':
            return None
        if 'Over/Under Total Goals' in market_str:
            market_str = market_str.replace('Total Goals ', '')
        squashed_market_str = squash_string(market_str)
        for desc_key, desc_value in self.desc.items():
            if squashed_market_str in squash_string(desc_value):
                return desc_key
        return None


class LeagueInfo:
    def __init__(self):
        # Keyword --> Display Name
        # Keyword: a string with lowercase + whitespace removing
        # The map need to be 1:1 as it will be used by home+away as matches key !IMPORTANT!
        self.map = dict()
        self.map['a'] = {
            'adelaide': 'Adelaide Utd',
            'brisbane': 'Brisbane Roar',
            'central': 'Central Coast',
            'perth': 'Perth Glory',
            'melbournecity': 'Melbourne City',
            'victory': 'Melbourne Victory',
            'newcastle': 'Newcastle Jets',
            'sydneyfc': 'Sydney FC',
            'wellington': 'Wellington Phoenix',
            'westernsydney': 'Western Sydney',
        }
        self.map['arg'] = {
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
        self.map['bel'] = {
            'charleroi': 'Royal Charleroi',
            'antwerp': 'Royal Antwerp',
            'kortrijk': 'KV Kortrijk',
            'waasland': 'Waasland Beveren',
            'zulte': 'Zulte Waregem',
            'genk': 'Racing Genk',
            'truidense': 'Sint-Truidense',
            'gent': 'KAA Gent',
            'standard': 'Standard Liege',
            'oostende': 'KV Oostende',
            'lokeren': 'KSC Lokeren',
        }
        self.map['eng'] = {
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
        self.map['fra'] = {
            'amiens': 'Amiens',
            'angers': 'Angers SCO',
            'bordeaux': 'Bordeaux',
            'caen': 'Caen',
            'clermont': 'Clermont Foot',
            'dijon': 'Dijon',
            'tienne': 'St Etienne',
            'guingamp': 'Guingamp',
            'lille': 'Lille',
            'lyon': 'Lyon',
            'marseille': 'Marseille',
            'metz': 'Metz',
            'monaco': 'AS Monaco',
            'montpellier': 'Montpellier HSC',
            'nantes': 'Nantes',
            'nice': 'Nice',
            'paris': 'Paris Saint Germain',
            'renn': 'Stade Rennais',
            'strasbourg': 'Strasbourg',
            'toulouse': 'Toulouse FC',
            'troyes': 'Troyes AC',
        }
        self.map['gem'] = {
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
        self.map['ita'] = {
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
        self.map['liga'] = {
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
        self.map['uefa'] = {
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
        self.map['w'] = {
            'adelaide': 'Adelaide United Women',
            'brisbane': 'Brisbane Roar Women',
            'canberra': 'Canberra United Women',
            'melbournecity': 'Melbourne City Women',
            'newcastle': 'Newcastle Jets Women',
        }

        self.league_long_names = {
            'a': 'Australia League',
            'arg': 'Argentina Superliga',
            'bel': 'Belgium League',
            'eng': 'English Premier League',
            'fra': 'French Ligue 1',
            'ita': 'Italian Serie A',
            'gem': 'German Bundesliga',
            'liga': 'Spanish La Liga',
            'uefa': 'UEFA Champions League',
            'w': 'Australia W-League',
        }

    def get_id(self, team_name, league_name):
        converted_name = squash_string(team_name)
        if converted_name == 'draw' or league_name not in self.map:
            return team_name

        if league_name == 'liga':
            if 'tico' in converted_name:
                converted_name = 'atlmadrid'
            elif 'lacoru' in converted_name:
                converted_name = 'deportivo'
            elif 'sociedad' in converted_name:
                converted_name = 'realsoc'
        elif league_name == 'eng':
            if 'mancity' == converted_name:
                converted_name = 'manchestercity'
            elif 'manutd' == converted_name or 'manunited' == converted_name:
                converted_name = 'manchesterunited'
            elif 'cpalace' in converted_name:
                converted_name = 'crystal'
        elif league_name == 'arg':
            if 'olimpo' in converted_name:
                converted_name = 'blanca'
            elif 'velez' in converted_name:
                converted_name = 'rsfield'
            elif 'lanús' == converted_name:
                converted_name = 'lanus'
            elif 'colón' == converted_name:
                converted_name = 'colon'
        elif league_name == 'uefa':
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
            elif 'beşikta' in converted_name:
                converted_name = 'besiktas'
        elif league_name == 'gem':
            if 'fcköln' in converted_name or 'koeln' in converted_name or \
                    'cologne' == converted_name:
                converted_name = 'koln'
            elif 'mgladbach' == converted_name or 'bormonch' == converted_name or \
                    'gladbach' in converted_name:
                converted_name = 'nchengladbach'
        elif league_name == 'fra':
            if converted_name == 'psg':
                converted_name = 'paris'
        elif league_name == 'w':
            if 'melbcity' in converted_name:
                converted_name = 'melbournecity'
            elif 'newcstlejets' in converted_name:
                converted_name = 'newcastle'
        elif league_name == 'a':
            if converted_name == 'sydney':
                converted_name = 'sydneyfc'

        for name in self.map[league_name].keys():
            if name in converted_name:
                return name
        return team_name

    def get_full_name(self, match_id, league_name):
        # so we can support other leagues that doesn't have map yet
        if league_name not in self.map or match_id not in self.map[league_name]:
            return match_id
        return self.map[league_name][match_id]

    def uniform(self, team_name, league):
        return self.get_full_name(self.get_id(team_name, league), league)


class MatchMerger:
    def __init__(self,
                 pickles_a,
                 pickles_arg,
                 pickles_eng,
                 pickles_fra,
                 pickles_gem,
                 pickles_ita,
                 pickles_liga,
                 pickles_uefa,
                 pickles_w,
                 ):
        self.pickles = dict()
        self.pickles['a'] = pickles_a
        self.pickles['arg'] = pickles_arg
        self.pickles['eng'] = pickles_eng
        self.pickles['fra'] = pickles_fra
        self.pickles['gem'] = pickles_gem
        self.pickles['ita'] = pickles_ita
        self.pickles['liga'] = pickles_liga
        self.pickles['uefa'] = pickles_uefa
        self.pickles['w'] = pickles_w

        self.betfair_min = None
        self.betfair_max = None
        self.betfair_delta = None
        self.betfair_hide = None
        self.betfair_print_only = False

    def merge_and_print(self, leagues, html_file):
        empty_count = 0
        loop = []
        info = LeagueInfo()
        for l in g_leagues:
            if l in leagues:
                loop.append((self.pickles[l], info.map[l], l))

        for pickles, league_map, l in loop:
            empty_names = ''
            matches_map = {}  # hometeam and awayteam = map's key
            for p_name in pickles:
                with open(os.path.join(gettempdir(), p_name), 'rb') as pkl:
                    pickle_matches = pickle.load(pkl)
                    if len(pickle_matches) is 0:
                        empty_names += p_name.split('_')[1].split('.')[0] + ' '
                        empty_count += 1
                    else:
                        for pm in pickle_matches:
                            id1 = info.get_id(pm.home_team, l)
                            id2 = info.get_id(pm.away_team, l)
                            if id1 == 'Draw' or id2 == 'Draw':
                                continue

                            key = id1 + id2
                            if key not in matches_map.keys():
                                m = Match()
                                m.__dict__.update(pm.__dict__)
                                m.odds = list(m.odds)  # Sometimes it's an immutable tuple

                                def same(a, b):
                                    return str(float(a)) == str(float(b))
                                if same(m.odds[0], 0) or same(m.odds[1], 0) or same(m.odds[2], 0):
                                    continue

                                m.home_team = league_map[info.get_id(pm.home_team, l)]
                                m.away_team = league_map[info.get_id(pm.away_team, l)]
                                matches_map[key] = m
                            else:
                                m = matches_map[key]
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

            matches = sorted(matches_map.values())
            if len(matches) is not 0 and not self.betfair_print_only:
                output = '--- {} ---'.format(info.league_long_names[l])
                empty_str = '({} pickles, empty: [{}])'.format(
                    len(pickles), empty_names.rstrip())
                log_and_print(output + empty_str)

                html_file.write_line('<b>' + output + '</b>' + empty_str)
                html_file.write_line('<table>')
                for m in matches:
                    m.calculate_best_shot()
                    m.display(html_file)
                html_file.write_line('</table>')

            self.merge_and_print_betfair(matches_map, l, pickles[0])

        with open('output_empty_pickles.txt', 'w') as empty_count_file:
            empty_count_file.write('({} empty pickles)'.format(empty_count))

    @staticmethod
    def get_balanced_stake(back_odd, lay_odd, back_stake):
        min_target = back_stake
        ret = dict()
        for lay_aim_stake in range(1, back_stake*10):
            lay_earn = lay_aim_stake * 0.95
            back_earn = back_stake * (back_odd - 1)
            liability = lay_aim_stake * (lay_odd - 1)
            profit_if_lay_win = lay_earn - back_stake
            profit_if_back_win = back_earn - liability  # liability is the "stake" you paid in lay
            target = abs(profit_if_back_win - profit_if_lay_win)
            if target < min_target:
                min_target = target
                ret['profit_if_lay_win'] = profit_if_lay_win
                ret['profit_if_back_win'] = profit_if_back_win
                ret['lay_aim_stake'] = lay_aim_stake
                ret['liability'] = liability
        return ret

    def merge_and_print_betfair(self, matches_map, league_name, p_name):
        if self.betfair_min is None or self.betfair_max is None:
            return
        with open(os.path.join(gettempdir(), p_name.split('_')[0] + '_betfair.pkl'),
                  'rb') as pkl:
            betfair_matches = pickle.load(pkl)
            if len(betfair_matches) is not 0:
                info = LeagueInfo()
                for bm in betfair_matches:
                    id1 = info.get_id(bm.home_team, league_name)
                    id2 = info.get_id(bm.away_team, league_name)
                    if id1 == 'Draw' or id2 == 'Draw':
                        continue

                    key = id1 + id2
                    if key in matches_map.keys():
                        m = matches_map[key]
                        for i in range(3):
                            if m.odds[i] is not 0 and m.agents[i] != 'Betfair' \
                                    and bm.lays[i] is not 0 \
                                    and self.betfair_min < bm.lays[i] < self.betfair_max \
                                    and bm.lays[i] - m.odds[i] < self.betfair_delta:
                                color = None
                                ret = self.get_balanced_stake(
                                    back_odd=m.odds[i],
                                    lay_odd=bm.lays[i],
                                    back_stake=100
                                )
                                if ret['profit_if_back_win'] >= self.betfair_hide or \
                                   ret['profit_if_lay_win'] >= self.betfair_hide:
                                    if ret['profit_if_lay_win'] >= 0 and \
                                       ret['profit_if_back_win'] >= 0:
                                            color = 'cyan'
                                    log_and_print(
                                        '{} back {} - lay {} [{}] - '
                                        'lay aim stake [{}] liability [{}] '
                                        'lay profit [{}] back profit [{}] - {} vs {}'.format(
                                            m.agents[i].strip(),
                                            '{:0.2f}'.format(m.odds[i]),
                                            '{:0.2f}'.format(bm.lays[i]),
                                            '{:0.2f}'.format(bm.lays[i] - m.odds[i]),
                                            '{:0.2f}'.format(ret['lay_aim_stake']),
                                            '{:0.2f}'.format(ret['liability']),
                                            '{:0.2f}'.format(ret['profit_if_lay_win']),
                                            '{:0.2f}'.format(ret['profit_if_back_win']),
                                            m.home_team, m.away_team,
                                        ),
                                        highlight=color)


class Website:
    def __init__(self, driver, wait):
        self.driver = driver
        self.wait = wait
        self.use_request = False
        self.a_url = False
        self.arg_url = False
        self.eng_url = False
        self.fra_url = False
        self.gem_url = False
        self.ita_url = False
        self.liga_url = False
        self.uefa_url = False
        self.w_url = False
        self.name = ''
        self.current_league = ''
        self.ask_gce = False

    def to_float(self, text):
        try:
            return float(text)
        except ValueError:
            log_and_print('{}: error when converting [{}] to float'.format(self.name, text))
            return 0.0

    def odds_to_float(self, m):
        for i in range(3):
            m.odds[i] = self.to_float(m.odds[i])

    @staticmethod
    def wait(s, wait, type_='css'):
        if type_ == 'css':
            wait.until(expected_conditions.visibility_of_element_located((By.CSS_SELECTOR, s)))
        elif type_ == 'partial':
            wait.until(expected_conditions.visibility_of_element_located((By.PARTIAL_LINK_TEXT, s)))
        elif type_ == 'link':
            wait.until(expected_conditions.visibility_of_element_located((By.LINK_TEXT, s)))
        elif type_ == 'id':
            wait.until(expected_conditions.visibility_of_element_located((By.ID, s)))
        else:
            log_and_print('Unexpected type: ' + type_)

    @staticmethod
    def get_element_static(css_string, driver, wait, silent=False):
        try:
            Website.wait(css_string, wait)
        except TimeoutException:
            if not silent:
                log_and_print('[{}] not found'.format(css_string))
            return None
        return driver.find_element_by_css_selector(css_string)

    @staticmethod
    def get_blocks_static(css_string, driver, wait):
        try:
            Website.wait(css_string, wait)
        except TimeoutException:
            log_and_print('[{}] not found'.format(css_string))
            return []
        return driver.find_elements_by_css_selector(css_string)

    def get_blocks(self, css_string):
        return self.get_blocks_static(css_string, self.driver, self.wait)

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
        self.fra_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-33754893-2-15-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=30;anim=1'  # noqa
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
                m.odds[i] = self.to_float(odds[i].text)
            m.agents = ['Bet365 '] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Betfair(Website):
    def __init__(self, driver, wait):
        super(Betfair, self).__init__(driver, wait)
        self.name = 'betfair'
        self.a_url = 'https://www.betfair.com.au/exchange/plus/football/competition/11418298?group-by=matched_amount'  # noqa
        self.arg_url = 'https://www.betfair.com.au/exchange/plus/football/competition/67387?group-by=matched_amount'  # noqa
        self.eng_url = 'https://www.betfair.com.au/exchange/plus/football/competition/10932509?group-by=matched_amount'  # noqa
        self.fra_url = 'https://www.betfair.com.au/exchange/plus/football/competition/55?group-by=matched_amount'  # noqa
        self.gem_url = 'https://www.betfair.com.au/exchange/plus/football/competition/59?group-by=matched_amount'  # noqa
        self.ita_url = 'https://www.betfair.com.au/exchange/plus/football/competition/81?group-by=matched_amount'  # noqa
        self.liga_url = 'https://www.betfair.com.au/exchange/plus/football/competition/117?group-by=matched_amount'  # noqa
        self.need_login = True
        self.get_back_odd = False

    @staticmethod
    def login_static(driver, wait):
        def save_cookie(f):
            with open(f, 'wb') as cookies_file:
                pickle.dump(driver.get_cookies(), cookies_file)

        def load_cookie(f):
            with open(f, 'rb') as cookies_file:
                cookies = pickle.load(cookies_file)
                for cookie in cookies:
                    driver.add_cookie(cookie)

        path = os.path.join(gettempdir(), 'betfair_cookie.pkl')
        try:
            load_cookie(path)
        except FileNotFoundError:
            Website.wait('ssc-liu', wait, type_='id')
            account = driver.find_element_by_id('ssc-liu')
            password = driver.find_element_by_id('ssc-lipw')
            login = driver.find_element_by_id('ssc-lis')
            with open('betfair.username', 'r') as username_file, \
                    open('betfair.password', 'r') as password_file:
                account.send_keys(username_file.read().rstrip())
                password.send_keys(password_file.read().rstrip())
            login.click()
            Website.wait('form.ssc-lof', wait)
            save_cookie(path)

    def login(self):
        self.login_static(self.driver, self.wait)

    def fetch(self, matches):
        blocks = self.get_blocks('table.coupon-table')
        if len(blocks) is 0:
            log_and_print('Betfair - matches not found')
            return
        all_teams = blocks[0].find_elements_by_css_selector('ul.runners')
        all_odds = blocks[0].find_elements_by_css_selector('div.coupon-runner')
        for teams in all_teams:
            m = BetfairMatch()
            m.home_team, m.away_team = teams.text.split('\n')
            for i in range(3):
                odds = all_odds[i].text.split('\n')
                if len(odds) < 3:
                    continue
                if self.get_back_odd:
                    m.odds[i] = real_back_odd(self.to_float(odds[0]))
                m.lays[i] = self.to_float(odds[2])
            m.agents = ['Betfair'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)
            if len(all_odds) > 3:
                del all_odds[:3]
            else:
                break


class Bluebet(Website):
    def __init__(self, driver, wait):
        super(Bluebet, self).__init__(driver, wait)
        self.name = 'bluebet'
        self.a_url = 'https://www.bluebet.com.au/sports/Soccer/Australia/Hyundai-A-League/38925'
        self.arg_url = 'https://www.bluebet.com.au/sports/Soccer/Argentina/Primera-Divisi%C3%B3n/28907'  # noqa
        self.eng_url = 'https://www.bluebet.com.au/sports/Soccer/England/English-Premier-League/36715'  # noqa
        self.fra_url = 'https://www.bluebet.com.au/sports/Soccer/France/Ligue-1-Orange/27235'
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
                log_and_print('bluebet - unexpected info, len: {}'.format(len(info)))
                continue
            info0 = info[0].text.split('\n')
            info1 = info[1].text.split('\n')
            info2 = info[2].text.split('\n')
            m = Match()
            m.home_team, m.away_team = info0[0], info2[0]
            m.odds[0] = self.to_float(info0[1])
            m.odds[1] = self.to_float(info1[1])
            m.odds[2] = self.to_float(info2[1])
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
        self.fra_url = 'https://crownbet.com.au/sports-betting/soccer/france/french-ligue-1-matches'
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
            for i, j in zip(range(3), (5, 7, 9)):
                m.odds[i] = self.to_float(values[j])
            m.agents = ['Crown  '] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Ladbrokes(Website):  # BetStar (and Bookmarker?) are the same
    def __init__(self, driver, wait):
        super(Ladbrokes, self).__init__(driver, wait)
        self.name = 'ladbrokes'
        self.a_url = 'https://www.ladbrokes.com.au/sports/soccer/39445848-football-australia-australian-a-league/?utm_source=%2Fsports%2Fsoccer%2F35326546-australian-a-league-2017-2018%2F35326546-australian-a-league-2017-2018%2F&utm_medium=sport+banner&utm_campaign=a+league+round+4'  # noqa
        self.arg_url = 'https://www.ladbrokes.com.au/sports/soccer/43008934-football-argentina-argentinian-primera-division/'  # noqa
        self.eng_url = 'https://www.ladbrokes.com.au/sports/soccer/41388947-football-england-premier-league/'  # noqa
        self.fra_url = 'https://www.ladbrokes.com.au/sports/soccer/43547428-football-france-french-ligue-1/'  # noqa
        self.gem_url = 'https://www.ladbrokes.com.au/sports/soccer/42213482-football-germany-german-bundesliga/'  # noqa
        self.ita_url = 'https://www.ladbrokes.com.au/sports/soccer/42212441-football-italy-italian-serie-a/'   # noqa
        self.liga_url = 'https://www.ladbrokes.com.au/sports/soccer/40962944-football-spain-spanish-la-liga/'  # noqa
        self.uefa_url = 'https://www.ladbrokes.com.au/sports/soccer/43625772-football-uefa-club-competitions-uefa-champions-league/'  # noqa

    @staticmethod
    def login_static(driver, wait):
        def save_cookie(f):
            with open(f, 'wb') as cookies_file:
                pickle.dump(driver.get_cookies(), cookies_file)

        def load_cookie(f):
            with open(f, 'rb') as cookies_file:
                cookies = pickle.load(cookies_file)
                for cookie in cookies:
                    driver.add_cookie(cookie)

        path = os.path.join(gettempdir(), 'ladbrokes_cookie.pkl')
        try:
            load_cookie(path)
        except FileNotFoundError:
            account = driver.find_element_by_id('userauth_username')
            password = driver.find_element_by_id('userauth_password')
            login = driver.find_element_by_css_selector('input.logbut')
            with open('ladbrokes.username', 'r') as username_file, \
                    open('ladbrokes.password', 'r') as password_file:
                account.send_keys(username_file.read().rstrip())
                password.send_keys(password_file.read().rstrip())
            login.click()
            Website.wait('div.welcome', wait)
            save_cookie(path)

    def fetch(self, matches):
        blocks = self.get_blocks('table.bettype-group.listings.odds.sports.match.soccer')
        for b in blocks:
            if 'Footy Freaks' in b.text:
                continue
            m = Match()
            info = b.find_elements_by_css_selector('tr.row')
            if len(info) != 3:
                log_and_print('{}: unexpected info, len: {}'.format(self.name, len(info)))
                continue
            m.home_team, m.odds[0] = info[0].text.split('\n')
            m.away_team, m.odds[2] = info[1].text.split('\n')
            m.odds[1] = info[2].text.split('\n')[1]
            self.odds_to_float(m)
            m.agents = ['Ladbrok'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Luxbet(Website):
    def __init__(self, driver, wait):
        super(Luxbet, self).__init__(driver, wait)
        self.name = 'luxbet'
        self.a_url = 'https://www.luxbet.com/?cPath=596&event_id=ALL'
        self.arg_url = 'https://www.luxbet.com/?cPath=6278&event_id=ALL'
        self.eng_url = 'https://www.luxbet.com/?cPath=616&event_id=ALL'
        self.fra_url = 'https://www.luxbet.com/?cPath=635&event_id=ALL'
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
                self.odds_to_float(m)
                m.home_team = ' '.join(info3)
                m.away_team = ' '.join(info4)

                m.agents = ['Luxbet '] * 3
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
                    m.odds[i] = self.to_float(odds[i].strip())

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
        self.fra_url = 'https://www.madbookie.com.au/Sport/Soccer/French_Ligue_1/Matches'
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
            self.odds_to_float(m)
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
        self.fra_url = 'https://www.palmerbet.com/sports/soccer/france-ligue-1'
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
            if len(odds) < 3:
                log_and_print('{}: unexpected len of odds: {}'.format(self.name, len(odds)))
                continue
            for i, j in zip(range(3), (0, 2, 1)):
                m.odds[i] = self.to_float(odds[j].text)
            odds = odds[3:] if len(show_all[0].text) is 0 else odds[5:]
            show_all = show_all[1:]
            m.agents = ['Palmer '] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Pinnacle(Website):
    def __init__(self, driver, wait):
        super(Pinnacle, self).__init__(driver, wait)
        self.name = 'pinnacle'
        self.a_url = 'https://www.pinnacle.com/en/odds/match/soccer/australia/australia-a-league'
        self.arg_url = 'https://www.pinnacle.com/en/odds/match/soccer/argentina/argentina-primera-division'  # noqa
        self.eng_url = 'https://www.pinnacle.com/en/odds/match/soccer/england/england-premier-league'  # noqa
        self.fra_url = 'https://www.pinnacle.com/en/odds/match/soccer/france/ligue-1'
        self.gem_url = 'https://www.pinnacle.com/en/odds/match/soccer/germany/bundesliga'
        self.ita_url = 'https://www.pinnacle.com/en/odds/match/soccer/italy/italy-serie-a'
        self.liga_url = 'https://www.pinnacle.com/en/odds/match/soccer/spain/spain-la-liga'
        self.uefa_url = 'https://www.pinnacle.com/en/odds/match/soccer/uefa/uefa-champions-league'
        self.a_url_logined = 'https://beta.pinnacle.com/en/Sports/29/Leagues/1766'
        self.arg_url_logined = 'https://beta.pinnacle.com/en/Sports/29/Leagues/1740'
        self.eng_url_logined = 'https://beta.pinnacle.com/en/Sports/29/Leagues/1980'
        self.fra_url_logined = 'https://beta.pinnacle.com/en/Sports/29/Leagues/2036'
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
                self.odds_to_float(m)
                m.agents = ['Pinacle'] * 3
                m.urls = [self.get_href_link(get_logined=True)] * 3
                matches.append(m)


class Sportsbet(Website):
    def __init__(self, driver, wait):
        super(Sportsbet, self).__init__(driver, wait)
        self.name = 'sportsbet'
        self.a_url = 'https://www.sportsbet.com.au/betting/soccer/australia/australian-a-league'
        self.arg_url = 'https://www.sportsbet.com.au/betting/soccer/americas/argentinian-primera-division'  # noqa
        self.eng_url = 'https://www.sportsbet.com.au/betting/soccer/united-kingdom/english-premier-league'  # noqa
        self.fra_url = 'https://www.sportsbet.com.au/betting/soccer/france/french-ligue-1'
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
                self.odds_to_float(m)
                status = None
                m.agents = ['Sports '] * 3
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
        self.fra_url = 'https://www.tab.com.au/sports/betting/Soccer/competitions/French%20Ligue%201'  # noqa
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
                m.odds[i] = self.to_float(odds[i].text)
            m.agents = ['TAB    '] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Topbetta(Website):
    def __init__(self, driver, wait):
        super(Topbetta, self).__init__(driver, wait)
        self.name = 'topbetta'
        self.a_url = 'https://www.topbetta.com.au/sports/football/hyundai-a-league-regular-season-151825'  # noqa
        self.eng_url = self.fra_url = self.gem_url = self.ita_url = self.liga_url = self.uefa_url = ' '  # noqa
        self.eng_urls = [
            'https://www.topbetta.com.au/sports/football/england-premier-league-round-16-146767',
            'https://www.topbetta.com.au/sports/football/england-premier-league-round-17-146769',
            ]
        self.fra_urls = [
            'https://www.topbetta.com.au/sports/football/ligue-1-orange-round-17-166360',
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
            # 'https://www.topbetta.com.au/sports/football/uefa-champions-league-group-a-155259',
            # 'https://www.topbetta.com.au/sports/football/uefa-champions-league-group-b-155261',
            # 'https://www.topbetta.com.au/sports/football/uefa-champions-league-group-c-155263',
            # 'https://www.topbetta.com.au/sports/football/uefa-champions-league-group-d-155265',
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
                self.odds_to_float(m)
            except StaleElementReferenceException:
                log_and_print('topbetta - Selenium has StaleElementReferenceException: ' + b.text)
                continue
            m.agents = ['TopBeta'] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Ubet(Website):
    def __init__(self, driver, wait):
        super(Ubet, self).__init__(driver, wait)
        self.name = 'ubet'
        self.a_url = 'https://ubet.com/sports/soccer/australia-a-league/a-league-matches'
        self.arg_url = 'https://ubet.com/sports/soccer/argentina-primera-division/arg-primera-matches'  # noqa
        self.eng_url = 'https://ubet.com/sports/soccer/england-premier-league/premier-league-matches'  # noqa
        self.fra_url = 'https://ubet.com/sports/soccer/france-ligue-1'
        self.gem_url = 'https://ubet.com/sports/soccer/germany-bundesliga'
        self.ita_url = 'https://ubet.com/sports/soccer/italy-serie-a'
        self.liga_url = 'https://ubet.com/sports/soccer/spain-la-liga'
        self.uefa_url = 'https://ubet.com/sports/soccer/uefa-champions-league'
        self.w_url = 'https://ubet.com/sports/soccer/australia-w-league'

    def fetch(self, matches):
        blocks = self.get_blocks('div.ubet-sub-events-summary')
        for b in blocks:
            try:
                values = b.text.split('\n')
            except StaleElementReferenceException:
                log_and_print('Ubet skipping - Selenium has StaleElementReferenceException')
                continue
            if len(values) < 7:
                log_and_print('Ubet - wrong info: ' + b.text)
                continue
            if 'WINNER' == values[0]:
                continue
            m = Match()
            m.home_team = values[1]
            m.away_team = values[5]
            m.odds[0] = values[2]
            m.odds[1] = values[4]
            m.odds[2] = values[6]

            for i in range(3):
                m.agents[i] = 'UBET   '
                m.urls[i] = self.get_href_link()
            if 'SUSPENDED' in m.odds[0]:
                continue
            else:
                self.odds_to_float(m)
            matches.append(m)


class Unibet(Website):
    def __init__(self, driver, wait):
        super(Unibet, self).__init__(driver, wait)
        self.name = 'unibet'
        self.a_url = 'https://www.unibet.com.au/betting#filter/football/australia/a-league'
        self.arg_url = 'https://www.unibet.com.au/betting#filter/football/argentina/primera_division'  # noqa
        self.eng_url = 'https://www.unibet.com.au/betting#filter/football/england/premier_league'
        self.fra_url = 'https://www.unibet.com.au/betting#filter/football/france/ligue_1'
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
                m.odds[i] = self.to_float(odds[i].text)
            m.agents = ['Unibet '] * 3
            m.urls = [self.get_href_link()] * 3
            matches.append(m)


class Williamhill(Website):
    def __init__(self, driver, wait):
        super(Williamhill, self).__init__(driver, wait)
        self.name = 'williamhill'
        self.a_url = 'https://www.williamhill.com.au/sports/soccer/australia/a-league-matches'
        self.arg_url = 'https://www.williamhill.com.au/sports/soccer/americas/argentine-primera-division-matches'  # noqa
        self.eng_url = 'https://www.williamhill.com.au/sports/soccer/british-irish/english-premier-league-matches'  # noqa
        self.fra_url = 'https://www.williamhill.com.au/sports/soccer/europe/french-ligue-1-matches'
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
        blocks = self.driver.find_elements_by_css_selector('div.EventBlock_root_1gq')
        for b in blocks:
            names = b.find_elements_by_css_selector('span.SoccerListing_name_pzi')
            odds = b.find_elements_by_css_selector('span.BetButton_display_3ty')
            if len(names) < 3 or \
               names[0].text == 'BOTH TEAMS TO SCORE' or \
               names[2].text == 'BOTH TEAMS TO SCORE':
                continue
            m = Match()
            m.home_team, m.away_team = names[0].text, names[2].text
            for i in range(3):
                m.odds[i] = self.to_float(odds[i].text)
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
            self.driver.implicitly_wait(2)
            self.wait = WebDriverWait(self.driver, 10)
            self.wait2 = WebDriverWait(self.driver, 2)
        self.is_get_data = is_get_data
        self.keep_driver_alive = keep_driver_alive
        global log_to_file
        log_to_file = log_to_file_
        if log_to_file:
            log_init()

    @staticmethod
    def calc_bonus_profit(websites_str, website='pinnacle', stake=100, with_stake=True, min_odd=2.0):  # Do they only returns winning?  # noqa
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
                        websites_str = g_websites_str if websites_str == 'all' else websites_str
                        for w1 in websites_str.split(','):
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
                                            ob = odd_idx  # ob - odd of bonus website
                                            if bm.odds[ob] < min_odd:
                                                continue

                                            o1 = (odd_idx + 1) % 3
                                            o2 = (odd_idx + 2) % 3
                                            for w2 in websites_str.split(','):
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
                                                                if with_stake:
                                                                    p_bw = bm.odds[ob] * stake - i - j  # noqa
                                                                else:
                                                                    p_bw = bm.odds[ob] * stake - stake - i - j  # noqa
                                                                p_1w = m1.odds[o1] * i - i - j  # noqa
                                                                p_2w = m2.odds[o2] * j - j - i  # noqa
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
                                                                    bob = bm.odds[ob]
                                                                    bo1 = m1.odds[o1]
                                                                    bo2 = m2.odds[o2]
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
        for i in range(1, 99):
            for j in range(1, 100 - i):
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

    @staticmethod
    def prepare_map_with_target_markets_as_key(market_names, target_markets):
        if target_markets == 'all':
            keys = list(market_names.desc.keys())
        else:
            keys = target_markets.split(',')
        odds = dict()
        for key in keys:
            odds[key] = dict()
        return odds

    def get_ladbrokes_markets_odd(self, url_back, target_markets, lay_markets):
        market_names = MarketNames()
        odds_back = self.prepare_map_with_target_markets_as_key(market_names, target_markets)

        self.driver.get(url_back)
        if 'main' not in lay_markets:  # Very likely it is for boost, so login to get real odd
            Ladbrokes.login_static(self.driver, self.wait)
            self.driver.get(url_back)

        try:
            self.wait.until(expected_conditions.visibility_of_element_located((By.ID,
                                                                               'twirl_element_1')))
        except TimeoutException:
            log_and_print('ladbroke has no match info:\n' + url_back)
            return dict()

        if 'main' in lay_markets:
            home_text = self.driver.find_element_by_id('twirl_element_1').text
            away_text = self.driver.find_element_by_id('twirl_element_2').text
            draw_text = self.driver.find_element_by_id('twirl_element_3').text

            home_name, home_odd = home_text.split('\n')
            away_name, away_odd = away_text.split('\n')
            _, draw_odd = draw_text.split('\n')

            odds_back['main'][home_name] = home_odd
            odds_back['main'][away_name] = away_odd
            odds_back['main']['Draw'] = draw_odd

        markets = self.driver.find_elements_by_css_selector('div.additional-market')
        for market in markets:
            desc = market.find_element_by_css_selector('div.additional-market-description').text
            if 'Over/Under First Half' in desc:
                desc = desc.replace('Over/Under First Half', 'First Half Goals')
            key = market_names.key(desc)
            if key in lay_markets:
                market.click()
                self.driver.implicitly_wait(1)
                blocks = market.find_elements_by_css_selector('tr.row')
                for b in blocks:
                    name = b.get_attribute('data-teamname')
                    odd = b.get_attribute('data-winoddsboost')
                    if 'Over (' in name:
                        name = name.replace('Over (', 'Over ')
                        name = name.replace(')', ' Goals')
                    elif 'Under (' in name:
                        name = name.replace('Under (', 'Under ')
                        name = name.replace(')', ' Goals')
                    odds_back[key][squash_string(name)] = odd
        return odds_back

    def get_william_markets_odd(self, url_back, target_markets):
        market_names = MarketNames()
        odds_back = self.prepare_map_with_target_markets_as_key(market_names, target_markets)

        self.driver.get(url_back)
        blocks = Website.get_blocks_static('div.table.teams', self.driver, self.wait)
        if len(blocks) < 3:
            log_and_print('Looks like no info in:\n' + url_back)
            return odds_back

        home_name, home_odd = blocks[0].text.split('\n')
        away_name, away_odd = blocks[2].text.split('\n')
        _, draw_odd = blocks[1].text.split('\n')
        if 'main' in odds_back:
            odds_back['main'][home_name] = home_odd
            odds_back['main'][away_name] = away_odd
            odds_back['main']['Draw'] = draw_odd

        if 'correct score' in odds_back:
            try:
                Website.wait('Correct Score', self.wait, type_='link')
                has_correct_score = True
            except TimeoutException:
                has_correct_score = False

            if has_correct_score:
                win_set, draw_set, _ = self.get_correct_score_sets()
                correct_score_key = market_names.key('Correct Score')

                scores = []
                scores.extend(win_set)
                scores.extend(draw_set)

                self.driver.find_element_by_link_text('Correct Score').click()
                blocks = Website.get_blocks_static('div.table.teams', self.driver, self.wait)
                for b in blocks:
                    if b.text == '':
                        continue
                    title, odd = b.text.split('\n')
                    team = title.split(' ')
                    if team.pop() in scores:
                        team_name = ' '.join(team)
                        if team_name == home_name \
                                or team_name == away_name \
                                or team_name == 'Draw':
                            odds_back[correct_score_key][squash_string(title)] = odd
                        else:
                            log_and_print('unexpected team name: ' + team_name)
        return odds_back

    @staticmethod
    def full_name_to_id(str_contains_full_name, league_name):
        info = LeagueInfo()
        if '/' in str_contains_full_name:
            team1, team2 = str_contains_full_name.split('/')
            team1_id = info.get_id(team1, league_name)
            team2_id = info.get_id(team2, league_name)
            return '/'.join([team1_id, team2_id])
        return str_contains_full_name

    # Convert team name to id for further matching
    def odds_map_to_id(self, odds_map, league_name, agent_name):
        formatted = dict()
        info = LeagueInfo()
        for key, market_map in odds_map.items():
            formatted[key] = dict()
            for name, value in market_map.items():
                value += ' ' + agent_name
                if '/' in name:
                    formatted[key][self.full_name_to_id(name, league_name)] = value
                elif '-' in name:
                    idx = name.find('-')-1
                    team_id = info.get_id(name[:idx], league_name)
                    score = name[idx:]
                    formatted[key][team_id + score] = value
                else:
                    formatted[key][name] = value
        return formatted

    @staticmethod
    def key_expand_full_name(key, league_name):
        info = LeagueInfo()
        if '/' in key:
            team1, team2 = key.split('/')
            team1_ = 'Draw' if team1 == 'Draw' else info.get_full_name(team1, league_name)
            team2_ = 'Draw' if team2 == 'Draw' else info.get_full_name(team2, league_name)
            return '/'.join([team1_, team2_])
        elif ' ' in key:
            idx = key.rfind(' ')
            team = key[:idx].strip()
            team_ = 'Draw' if team == 'Draw' else info.get_full_name(team, league_name)
            score = key[idx:].strip()
            return ' '.join([team_, score])
        else:
            return key

    def id_map_to_full_name(self, odds_map, league_name):
        formatted = dict()
        for key, value in odds_map.items():
            formatted[self.key_expand_full_name(key, league_name)] = value
        return formatted

    def get_until_more_than(self, css_str, expect_count, max_try=10, element=None):
        element = self.driver if element is None else element
        count_ = 0
        while True:
            time.sleep(1)
            count_ += 1
            lines_ = element.find_elements_by_css_selector(css_str)
            if len(lines_) > expect_count or count_ > max_try:
                break
        return lines_

    @staticmethod
    def count_down(loop_minutes):
        for m in range(loop_minutes):
            log_and_print('Will rescan in {} minute{} ...'.format(
                loop_minutes - m, '' if loop_minutes - m == 1 else 's'),
                same_line=(loop_minutes-m != 1)
            )
            time.sleep(60)

    @staticmethod
    def init_league_info(**urls_):
        info = dict()
        for key in urls_.keys():
            info[key] = dict()
        return info

    @staticmethod
    def get_vs(home, away, league):
        io = LeagueInfo()
        home_full_name = io.uniform(home, league)
        away_full_name = io.uniform(away, league)
        return home_full_name + ' vs ' + away_full_name

    # return a dict: id by time and team -> url with seq
    def get_classicbet_match_info(self):
        urls = dict(
            arg='https://www.classicbet.com.au/Sport/Soccer/Argentinian_Primera_A/Matches',
            a='https://www.classicbet.com.au/Sport/Soccer/Australian_A-League/Matches',
            bel='https://www.classicbet.com.au/Sport/Soccer/Belgian_Jupiler_League/Matches',
            # eng='https://www.classicbet.com.au/Sport/Soccer/English_FA_Cup/Matches',
            eng='https://www.classicbet.com.au/Sport/Soccer/English_Premier_League/Matches',
            fra='https://www.classicbet.com.au/Sport/Soccer/French_Ligue_1/Matches',
            gem='https://www.classicbet.com.au/Sport/Soccer/German_Bundesliga/Matches',
            ita='https://www.classicbet.com.au/Sport/Soccer/Italian_Serie_A/Matches',
            liga='https://www.classicbet.com.au/Sport/Soccer/Spanish_La_Liga/Matches',
        )
        info = self.init_league_info(**urls)

        def get_match_times():
            return Website.get_blocks_static('div.matchTime', self.driver, self.wait)

        for l, url in urls.items():
            self.driver.get(url)
            count = len(get_match_times())
            if count is 0:
                log_and_print('Looks like there is no match in:\n' + url)
            for i in range(count):
                match_lines = Website.get_blocks_static('table.MatchTable',
                                                        self.driver,
                                                        self.wait)[i].text.split('\n')
                pop_count = 1
                if 'LINE' in match_lines[0]:
                    pop_count += 1
                if 'OVER' in match_lines[0]:
                    pop_count += 3
                home = match_lines[1].split(' ')
                away = match_lines[2].split(' ')
                for _ in range(pop_count):
                    home.pop()
                    away.pop()

                if len(home) is 0 or len(away) is 0:  # Sometimes the odds are not ready yet
                    continue
                home.pop()  # draw odd

                match_time = get_match_times()[i].text.replace('@ ', '').replace(' 2018', '')
                info[l][match_time + ' - ' + self.get_vs(' '.join(home), ' '.join(away), l)] = \
                    url + ' ' + str(i)

        return info

    def get_ladbrokes_match_info(self):
        urls = dict(
            arg='https://www.ladbrokes.com.au/sports/soccer/45568353-football-argentina-argentinian-primera-division/',  # noqa
            a='https://www.ladbrokes.com.au/sports/soccer/44649922-football-australia-australian-a-league/',  # noqa
            bel='https://www.ladbrokes.com.au/sports/soccer/45568434-football-belgium-belgian-first-division-a/',  # noqa
            # eng='https://www.ladbrokes.com.au/sports/soccer/46666149-football-england-fa-cup/',  # noqa
            eng='https://www.ladbrokes.com.au/sports/soccer/44936933-football-england-premier-league/',  # noqa
            fra='https://www.ladbrokes.com.au/sports/soccer/45472697-football-france-french-ligue-1/',  # noqa
            gem='https://www.ladbrokes.com.au/sports/soccer/44769778-football-germany-german-bundesliga/',  # noqa
            ita='https://www.ladbrokes.com.au/sports/soccer/45942404-football-italy-italian-serie-a/',  # noqa
            liga='https://www.ladbrokes.com.au/sports/soccer/45822932-football-spain-spanish-la-liga/',  # noqa
        )
        info = self.init_league_info(**urls)
        for league, url in urls.items():
            self.driver.get(url)
            titles = Website.get_blocks_static('div.fullbox-hdr', self.driver, self.wait)
            times = Website.get_blocks_static('tr.bettype-hdr', self.driver, self.wait)
            if len(times) < len(titles):
                log_and_print('maybe there is no match in:\n' + url)
            for i in range(len(times)):
                if titles[i].text == 'PROMOTIONAL MARKET':
                    continue
                try:
                    title = titles[i].find_element_by_tag_name('a')
                except NoSuchElementException:
                    continue
                match_url = title.get_attribute('href')
                home, away = title.get_attribute('title').split(' - ')[-1].split(' v ')

                t = times[i].find_elements_by_css_selector('div.startingtime')
                date_ = datetime.strptime(t[0].text, '%a %d/%m/%Y').strftime('%a %d %b ')
                time_ = datetime.strptime(t[1].text, '%I:%M %p').strftime('%H:%M')
                info[league][date_ + time_ + ' - ' + self.get_vs(home, away, league)] = match_url
        return info

    def get_betfair_match_info(self):
        urls = dict(
            arg='https://www.betfair.com.au/exchange/plus/football/competition/67387',
            a='https://www.betfair.com.au/exchange/plus/football/competition/11418298',
            bel='https://www.betfair.com.au/exchange/plus/football/competition/89979',
            # eng='https://www.betfair.com.au/exchange/plus/football/competition/30558',  # FA Cup
            eng='https://www.betfair.com.au/exchange/plus/football/competition/10932509',
            fra='https://www.betfair.com.au/exchange/plus/football/competition/55',
            gem='https://www.betfair.com.au/exchange/plus/football/competition/59',
            ita='https://www.betfair.com.au/exchange/plus/football/competition/81',
            liga='https://www.betfair.com.au/exchange/plus/football/competition/117',
        )
        info = self.init_league_info(**urls)

        for key in urls.keys():
            self.driver.set_window_size(width=1920, height=1080)
            self.driver.get(urls[key])
            Betfair.login_static(self.driver, self.wait)
            self.driver.get(urls[key])
            break

        def get_date(i_):
            return Website.get_blocks_static('span.card-header-title',
                                             self.driver,
                                             self.wait)[i_].text

        def get_tables():
            tables_ = Website.get_blocks_static('table.coupon-table', self.driver, self.wait)
            if tables_[0].text.split('\n')[0] == 'In-Play':
                tables_.pop(0)
            return tables_

        def get_rows(id_):
            count_ = 10
            while count_ > 0:
                rows_ = get_tables()[id_].find_elements_by_css_selector('tr')
                if len(rows_) <= 2:
                    time.sleep(1)
                else:
                    rows_.pop(0)
                    return rows_
            return None

        for league, url in urls.items():
            self.driver.get(url)
            for table_id in range(len(get_tables())):
                for row_id in range(len(get_rows(table_id))):
                    row = get_rows(table_id)[row_id]
                    if row.text == '':
                        continue
                    details = get_rows(table_id)[row_id].text.split('\n')
                    time_, home, away = details[0], details[1], details[2]
                    date_ = get_date(table_id) + ' ' + time_.split(' ').pop()
                    match_url = row.find_element_by_tag_name('a').get_attribute('href')
                    info[league][date_ + ' - ' + self.get_vs(home, away, league)] = match_url
        return info

    def generate_compare_urls_file(self):
        def write_file(s):
            urls_file.write(s + '\n')
        
        def write_url(info):
            if title in info[league]:
                write_file(info[league][title])
            else:
                write_file('.')

        file = os.path.join(gettempdir(), 'punter-test.pkl')
        is_write = True
        if is_write:
            try:
                info_classicbet = self.get_classicbet_match_info()
                info_ladbrokes = self.get_ladbrokes_match_info()
                info_betfair = self.get_betfair_match_info()
            finally:
                self.driver.quit()

            with open(file, 'wb') as pkl:
                pickle.dump((info_classicbet, info_ladbrokes, info_betfair), pkl)
        else:
            with open(file, 'rb') as pkl:
                info_classicbet, info_ladbrokes, info_betfair = pickle.load(pkl)

        with open('compare.txt', 'w') as urls_file:
            write_file('==bet_type== q')
            write_file('==markets===:all')
            for league, matches in info_betfair.items():
                for title, betfair_url in matches.items():
                    if title in info_ladbrokes[league] or title in info_classicbet[league]:
                        write_file('-- ' + league)
                        write_file(title)
                        write_url(info_classicbet)
                        write_url(info_ladbrokes)
                        write_file(betfair_url)

    @staticmethod
    def has_value(d, key):
        return key in d and len(d[key]) != 0

    def get_classicbet_markets_odd(self, with_url_back, target_markets, lay_markets):
        market_names = MarketNames()
        odds_back = self.prepare_map_with_target_markets_as_key(market_names, target_markets)

        url_back, url_number = with_url_back.split(' ')
        try:
            self.driver.get(url_back)
        except TimeoutException:
            return dict()
        url_number = int(url_number)

        # -------- Get general info
        tables = self.get_until_more_than('table.MatchTable', url_number+1)
        if len(tables) <= url_number:
            return dict()
        main_lines = tables[url_number].text.split('\n')

        try:
            Website.wait('additional markets', self.wait2, type_='partial')
            a_text = tables[url_number].find_element_by_tag_name('a').get_attribute('onclick')
            market_number = a_text.split('(')[1].split(')')[0].split(',')[2].replace('\'', '')
            if not market_number.isdigit():
                log_and_print('Looks like no additional markets in: ' + with_url_back)
                raise TimeoutException
            has_additional = True
        except TimeoutException:
            has_additional = False
            market_number = None

        # -------- Get main
        if 'main' in lay_markets:
            # e.g. 1. 'Swansea City 10.25 5.30 +0.5@3.45 Over 2.5 1.61'
            #   or 1. 'Swansea City 10.25 5.30 Over 2.5 1.61'
            #
            #      2. 'Chelsea 10.25 +0.5@3.45 Under 2.5 1.61'
            #   or 2. 'Chelsea 10.25 Under 2.5 1.61'
            pop_count = 0
            if 'LINE' in main_lines[0]:
                pop_count += 1
            if 'OVER' in main_lines[0]:
                pop_count += 3

            info = main_lines[1].split(' ')
            for _ in range(pop_count):
                info.pop()  # 'Over 2.5 1.61'

            draw_odd = info.pop()
            is_odd_ready, _ = self.to_number(draw_odd)
            if not is_odd_ready:
                return dict()

            home_odd = info.pop()
            home_name = ' '.join(info)

            info = main_lines[2].split(' ')
            for _ in range(pop_count):
                info.pop()  # 'Under 2.5 1.61'

            away_odd = info.pop()
            away_name = ' '.join(info)

            odds_back['main'][home_name] = home_odd
            odds_back['main'][away_name] = away_odd
            odds_back['main']['Draw'] = draw_odd

        if has_additional:
            def click_additional_market(market_number_):
                a_links = self.driver.find_elements_by_partial_link_text('additional markets')
                for a in a_links:
                    # Maybe some matches don't have additional markets
                    if market_number_ in a.get_attribute('onclick'):
                        a.click()
                        break
                else:
                    log_and_print('Looks like no additional markets in: ' + with_url_back)
                    return False
                try:
                    Website.wait('Correct Score', self.wait2, type_='partial')
                except TimeoutException:
                    log_and_print('Looks like no additional markets expanded: ' + with_url_back)
                    return False
                return True

            def get_key(market_str_):
                if market_str_ == 'HT/FT Double':
                    return 'Half Time/Full Time'
                elif 'First Half Over/Under' in market_str_:
                    key_ = market_str_.replace('Goals', '')
                    return key_.replace('First Half Over/Under', 'First Half Goals')
                else:
                    return market_str_

            def get_odds(market_str_, key_):
                self.driver.find_element_by_link_text(market_str_).click()
                active = Website.get_element_static('dd.active', self.driver, self.wait2)
                if active is None:
                    self.driver.get(url_back)
                    Website.wait('additional markets', self.wait2, type_='partial')
                    if not click_additional_market(market_number):
                        return
                    Website.wait(market_str_, self.wait, type_='link')
                    self.driver.find_element_by_link_text(market_str_).click()
                    active = Website.get_element_static('dd.active', self.driver, self.wait2)
                    if active is None:
                        log_and_print('failed to get ' + market_str_)
                        return
                lines = active.text.split('\n')
                self.driver.find_element_by_link_text(market_str_).click()
                for line in lines:
                    info_ = line.split(' ')
                    if 'Straight' not in line:
                        continue
                    odd = info_[-1]
                    info_.pop()
                    info_.pop()
                    odds_back[key_][squash_string(''.join(info_))] = odd

            if not click_additional_market(market_number):
                return odds_back

            full_text = self.driver.find_element_by_id('pageContent').text.split('\n')
            vs_str = ''
            for s in full_text:
                if ' vs ' in s:
                    vs_str = s.split(' - ')[1]
                    break

            markets = ['Correct Score', 'First Goalscorer', 'Both Teams To Score', 'HT/FT Double']
            for goals in '0.5', '1.5':
                markets.append('First Half Over/Under ' + goals + ' Goals')
            for goals in '0.5', '1.5', '2.5', '3.5', '4.5':
                markets.append('Over/Under ' + goals + ' Goals')

            for m in markets:
                market_str = m + ' - ' + vs_str
                key = market_names.key(get_key(m))
                if market_str in full_text and key in lay_markets:
                    get_odds(market_str, key)
        return odds_back

    @staticmethod
    def merge_back_odds(first_dict, *dicts):
        odds = first_dict
        for d in dicts:
            for item, map_ in d.items():
                for key, value in map_.items():
                    if key in odds[item]:
                        odd = float(value.split(' ')[0])
                        if float(odds[item][key].split(' ')[0]) < odd:
                            odds[item][key] = value
                    else:
                        odds[item][key] = value
        return odds

    def thread_get_ladbrokes(self, aws_ip, url, target_markets, lay_markets):
        odds = requests.get(
            'http://{}:5000/get_ladbrokes'.format(aws_ip),
            params={'url': url,
                    'target_markets': target_markets,
                    'lay_markets_str': ','.join(lay_markets).replace(' ', '_')
                    }).json()
        self.save_to(odds, 'ladbrokes_odds.pkl', silent=True)

    def compare_multiple_sites(self, loop_minutes):
        with open('compare.txt', 'r') as urls_file:
            lines = urls_file.read().splitlines()

        aws_ip = lines.pop(0).split(' ')[1]
        bet_type = lines.pop(0).split(' ')[1]
        target_markets = lines.pop(0).split(':')[1]

        self.driver.get('https://www.betfair.com.au/exchange/plus/')
        Betfair.login_static(self.driver, self.wait)

        time_it = TimeIt(top=True, bottom=False)
        while len(lines) > 0:
            log_and_print('_'*100 + ' bet type: ' + bet_type)
            try:
                for l, match_info, url_classic, url_ladbrokes, url_lay in \
                        zip(lines[::5], lines[1::5], lines[2::5], lines[3::5], lines[4::5]):
                    time_it.reset_top()
                    league = l.split(' ')[1]

                    time_it.reset()
                    odds_lay, home, away = self.get_lay(url_lay, league, target_markets)
                    time_it.log('betfair')

                    lay_markets = []
                    for key in odds_lay.keys():
                        if len(odds_lay[key]) != 0:
                            lay_markets.append(key)

                    odds_back = dict()
                    thread_lad, odds_lad = None, None
                    if url_ladbrokes != '.':
                        time_it.reset()
                        if aws_ip == 'none':
                            odds_lad = self.get_ladbrokes_markets_odd(url_ladbrokes,
                                                                      target_markets,
                                                                      lay_markets)
                        else:
                            thread_lad = threading.Thread(target=self.thread_get_ladbrokes,
                                                          args=(aws_ip,
                                                                url_ladbrokes,
                                                                target_markets,
                                                                lay_markets))
                            thread_lad.start()
                        time_it.log('ladbrokes')

                    if url_classic != '.':
                        time_it.reset()
                        odds_classic = self.get_classicbet_markets_odd(url_classic,
                                                                       target_markets,
                                                                       lay_markets)
                        time_it.log('classicbet')

                        if len(odds_classic) is not 0:
                            odds_classic = self.odds_map_to_id(odds_classic, league, 'classicbet')
                            odds_back = self.merge_back_odds(odds_classic, odds_back)

                    if url_ladbrokes != '.':
                        if aws_ip != 'none':
                            thread_lad.join()
                            with open(os.path.join(gettempdir(), 'ladbrokes_odds.pkl'),
                                      'rb') as pkl:
                                odds_lad = pickle.load(pkl)
                        if len(odds_lad) is not 0:
                            odds_lad = self.odds_map_to_id(odds_lad, league, 'ladbrokes')
                            odds_back = self.merge_back_odds(odds_lad, odds_back)

                    if len(odds_back) is not 0:
                        back_urls = url_classic + '\n' + url_ladbrokes
                        self.compare_with_lay(home, away, odds_back, back_urls, url_lay, league,
                                              match_info, bet_type, odds_lay)
                    time_it.top_log('match scan time')

            except Exception as e:
                log_and_print('Exception: [' + str(e) + ']')
                loop_minutes = 0
            finally:
                if loop_minutes is 0 and self.driver:
                    self.driver.quit()
                    break
                else:
                    self.count_down(loop_minutes)

    def compare_back_and_lay(self, back_site, loop_minutes):
        file_name = back_site + '.txt'
        if back_site == 'ladbrokes':
            get_func = self.get_ladbrokes_markets_odd
        elif back_site == 'classicbet':
            get_func = self.get_classicbet_markets_odd
        elif back_site == 'william':
            get_func = self.get_william_markets_odd
        else:
            log_and_print('unexpected bet site: ' + back_site)
            return

        with open(file_name, 'r') as urls_file:
            lines = urls_file.read().splitlines()
        bet_type = lines.pop(0).split(' ')[1]
        target_markets = lines.pop(0).split(':')[1]
        while len(lines) > 0:
            log_and_print('_'*120 + ' bet type: ' + bet_type)
            for l, match_info, url_back, url_lay in \
                    zip(lines[::4], lines[1::4], lines[2::4], lines[3::4]):
                league = l.split(' ')[1]
                odds_lay, home, away = self.get_lay(url_lay, league, target_markets)
                if home == '':
                    continue
                odds_back = get_func(url_back, target_markets, odds_lay)
                odds_back = self.odds_map_to_id(odds_back, league, back_site)
                self.compare_with_lay(home, away, odds_back, url_back, url_lay, league,
                                      match_info, bet_type, odds_lay)

            if loop_minutes is 0 and self.driver:
                self.driver.quit()
                break
            else:
                self.count_down(loop_minutes)

    @staticmethod
    def get_correct_score_sets():
        win_set = ('1-0', '2-0', '3-0', '2-1', '3-1', '3-2')
        draw_set = ('0-0', '1-1', '2-2', '3-3')
        lose_set = ('0-1', '0-2', '0-3', '1-2', '1-3', '2-3')
        return win_set, draw_set, lose_set

    @staticmethod
    def add_item_to_results(item_, key_, lay_odd_, results_, odds_back_, bet_type_, display_):
        if item_ in odds_back_[key_] and lay_odd_ != '':
            back_odd, agent = odds_back_[key_][item_].split(' ')
            if agent == 'classicbet':
                agent = '(C)'
            elif agent == 'ladbrokes':
                agent = '(L)'

            lay_odd_, lay_amount = lay_odd_.split('\n')

            back_odd = float(back_odd)
            lay_odd_ = float(lay_odd_)
            if bet_type_ == 'snr':  # SNR
                profit = (back_odd - 1) * 100 - (lay_odd_ - 1) * (
                    (back_odd - 1) / (lay_odd_ - 0.05) * 100)
            elif 'boost' in bet_type_ or 'q' in bet_type_:  # qualifying
                if back_odd < 1.95:
                    back_odd = 0.1
                profit = (back_odd / (lay_odd_ - 0.05) * 100) * 0.95 - 100
            else:
                log_and_print('unexpected bet type: ' + bet_type_)
                return
            results_.append([profit, back_odd, agent, lay_odd_, lay_amount, item_, display_])

    def get_lay(self, url_lay, league_name, target_markets):
        self.driver.set_window_size(width=1920, height=1080)
        self.driver.get(url_lay)

        market_names = MarketNames()
        odds_lay = self.prepare_map_with_target_markets_as_key(market_names, target_markets)

        # ------- get main market
        def get_text(b_, css):
            return b_.find_element_by_css_selector(css).text

        bs = Website.get_blocks_static('tr.runner-line', self.driver, self.wait)
        if len(bs) < 3:
            log_and_print('no match info in:\n' + url_lay)
            return odds_lay, '', ''

        home_name = get_text(bs[0], 'h3.runner-name')
        away_name = get_text(bs[1], 'h3.runner-name')
        if 'main' in odds_lay:
            odds_lay['main'][home_name] = get_text(bs[0], 'td.bet-buttons.lay-cell.first-lay-cell')
            odds_lay['main'][away_name] = get_text(bs[1], 'td.bet-buttons.lay-cell.first-lay-cell')
            odds_lay['main']['Draw'] = get_text(bs[2], 'td.bet-buttons.lay-cell.first-lay-cell')

        # ------- get popular markets
        Website.wait('section.mod-tabs', self.wait)
        blocks = Website.get_blocks_static('div.mini-mv', self.driver, self.wait)
        for b in blocks:
            key = market_names.key(b.find_element_by_css_selector('span.market-name-label').text)
            if key is not None and key in odds_lay:
                trs = b.find_elements_by_css_selector('tr.runner-line')
                for tr in trs:
                    div = tr.find_element_by_css_selector('h3.runner-name')
                    btn = tr.find_element_by_css_selector('button.lay-button')
                    if btn.text != '':
                        odds_lay[key][squash_string(self.full_name_to_id(div.text, league_name))] \
                            = btn.text
        return odds_lay, home_name, away_name

    def compare_with_lay(self, home_name, away_name, odds_back, url_back, url_lay,
                         league, match_info, bet_type, odds_lay):
        results = []
        market_names = MarketNames()
        info = LeagueInfo()
        home_id = info.get_id(home_name, league)
        away_id = info.get_id(away_name, league)

        if self.has_value(odds_lay, 'main'):
            self.add_item_to_results(home_name, 'main', odds_lay['main'][home_name], results,
                                     odds_back, bet_type, 'Main: ' + home_name + ' win')
            self.add_item_to_results(away_name, 'main', odds_lay['main'][away_name], results,
                                     odds_back, bet_type, 'Main: ' + away_name + ' win')
            self.add_item_to_results('Draw', 'main', odds_lay['main']['Draw'], results,
                                     odds_back, bet_type, 'Main: Draw')

        # get correct score from popular markets
        correct_score_key = market_names.key('Correct Score')
        if self.has_value(odds_lay, correct_score_key):
            win_set, draw_set, lose_set = self.get_correct_score_sets()
            for b_score, b_value in odds_lay[correct_score_key].items():
                # Convert score in lay --> score in back
                if b_score in win_set:
                    score = home_id + b_score
                    display = home_name + ' ' + b_score
                elif b_score in draw_set:
                    score = 'draw' + b_score
                    display = 'Draw ' + b_score
                elif b_score in lose_set:
                    reverse_score = '-'.join(b_score.split('-')[::-1])
                    score = away_id + reverse_score
                    display = away_name + ' ' + b_score
                else:
                    continue
                self.add_item_to_results(score, correct_score_key, b_value, results,
                                         odds_back, bet_type, display)

        # get half full from popular markets
        half_full_key = market_names.key('Half Time / Full Time')
        if self.has_value(odds_lay, half_full_key):
            for b_half_full, b_value in odds_lay[half_full_key].items():
                self.add_item_to_results(b_half_full, half_full_key, b_value,
                                         results, odds_back, bet_type,
                                         self.key_expand_full_name(b_half_full, league))

        # get both score from popular markets
        both_score_key = market_names.key('Both teams to Score')
        if self.has_value(odds_lay, both_score_key):
            for b_yes_no, b_value in odds_lay[both_score_key].items():
                self.add_item_to_results(b_yes_no, both_score_key, b_value, results,
                                         odds_back, bet_type, 'Both teams to Score: ' + b_yes_no)

        # get over under from popular markets
        titles = []
        for goals in '0.5', '1.5':
            titles.append('First Half Goals ' + goals)
        for goals in '0.5', '1.5', '2.5', '3.5', '4.5':
            titles.append('Over/Under ' + goals + ' Goals')
        for title in titles:
            over_under_key = market_names.key(title)
            if self.has_value(odds_lay, over_under_key):
                for b_over_under, b_value in odds_lay[over_under_key].items():
                    self.add_item_to_results(b_over_under, over_under_key, b_value,
                                             results, odds_back, bet_type,
                                             title + ': ' + b_over_under.split('.')[0][:-1])

        # get player
        first_scorer_key = market_names.key('First Goalscorer')
        if self.has_value(odds_lay, first_scorer_key):
            tabs = self.get_until_more_than('h4.tab-label', 5)
            for tab in tabs:
                if tab.text == 'Player':
                    tab.click()
                    blocks = self.get_until_more_than('div.mini-mv', 10)
                    for b in blocks:
                        label = b.find_element_by_css_selector('span.market-name-label')
                        if label.text == 'First Goalscorer':
                            lines = self.get_until_more_than('tr.runner-line', 100, element=b)
                            for line in lines:
                                lay_box = line.find_element_by_css_selector(
                                    'td.bet-buttons.lay-cell.first-lay-cell')
                                if lay_box.text == '':
                                    continue
                                name = line.find_element_by_css_selector('h3.runner-name')
                                lay_odd = lay_box.find_element_by_css_selector(
                                    'span.bet-button-price')
                                odds_lay[first_scorer_key][name.text] = lay_odd.text

            for b_player, b_value in odds_lay[first_scorer_key].items():
                self.add_item_to_results(squash_string(b_player), first_scorer_key,
                                         b_value, results, odds_back, bet_type, b_player)

        count = 0
        results.sort(reverse=True)
        log_and_print('----------- (' + str(len(results)) + ') ' + match_info + ' -------------')
        if len(results) is 0:
            return

        if bet_type == 'boost':
            yellow_profit = -5
            red_profit = 0
        elif bet_type == 'q':
            yellow_profit = -5
            red_profit = -1
        else:  # bonus
            yellow_profit = 76
            red_profit = 80

        biggest_back = 17.9  # if back odd is too big, we might not have enough money to lay it
        top_results = 3

        if results[0][0] >= yellow_profit and results[0][1] < biggest_back:
            log_and_print(url_back)
            log_and_print(url_lay)

        for res in results:
            if res[1] >= biggest_back:
                continue
            # 0 profit, 1 back, 2 agent, 3 lay, 4 lay amount, 5 original item text, 6 pretty display
            msg = '{:0.2f}\t{:0.2f} {}\t{:0.2f} ({})\t{}'.format(
                res[0], res[1], res[2], res[3], res[4],
                self.key_expand_full_name(res[6], league))
            if res[0] >= yellow_profit:
                if res[0] >= red_profit:
                    log_and_print(msg, highlight='red')
                else:
                    log_and_print(msg, highlight='yellow')
            else:
                log_and_print(msg)
            count += 1
            if count > top_results:
                break

    @staticmethod
    def to_number(text):
        try:
            return True, float(text)
        except ValueError:
            return False, 0

    def compare_with_race(self):
        # Unfortunately Betfair is not able to get latest odds
        with open('race.txt', 'r') as urls_file:
            lines = urls_file.read().splitlines()

        url_back = lines[0]
        self.driver.get(url_back)
        Website.get_element_static('td.competitorCell', self.driver, self.wait)

        def get_back_odds():
            odds_ = dict()
            try:
                lines_ = Website.get_element_static('table.racing',
                                                    self.driver, self.wait).text.split('\n')
            except StaleElementReferenceException:
                return odds_

            race_no = 1
            while len(lines_) is not 0:
                line = lines_.pop(0)
                if line.startswith(str(race_no) + '.'):
                    line = lines_.pop(0)
                    texts = line.split(' ')
                    first_number_found = False
                    while len(texts) is not 0:
                        text = texts.pop()
                        is_number, odd = self.to_number(text)
                        if is_number:
                            if not first_number_found:
                                first_number_found = True  # This is the place odd
                            else:
                                odds_[race_no] = odd
                                break
                    race_no += 1
            return odds_

        def get_style(foreground, background):
            fground = foreground.upper()
            bground = background.upper()
            style_ = getattr(Fore, fground) + getattr(Back, bground)
            return style_
        green = get_style(foreground='white', background='black')
        yellow = get_style(foreground='black', background='green')

        def color_it(text, style):
            return '{}{}{}'.format(style, text, Style.RESET_ALL)

        log_and_print('>>>>')
        back_odds = get_back_odds()
        count = 1
        while True:
            old_odds = back_odds.copy()
            back_odds = get_back_odds()
            if len(back_odds) is not 0:
                msg = ''
                same_line = True
                for key, back_odd in back_odds.items():
                    if back_odd == old_odds[key]:
                        msg += '[{} {}] '.format(key, back_odd)
                    elif back_odd > old_odds[key]:
                        msg += '[{} {}] '.format(color_it(key, green), color_it(back_odd, green))
                        same_line = False
                    else:
                        msg += '[{} {}] '.format(color_it(key, yellow), color_it(back_odd, yellow))
                        same_line = False
                if same_line:
                    log_and_print(msg + str(count), same_line=True)
                else:
                    log_and_print('\n' + msg + str(count), same_line=False)
            count += 1
            time.sleep(3)

    @staticmethod
    def calc_real_back_odd(s):
        print(real_back_odd(s))

    @staticmethod
    def save_to(obj, filename, silent=False):
        file = os.path.join(gettempdir(), filename)
        with open(file, 'wb') as pkl:
            pickle.dump(obj, pkl)
            if not silent:
                if len(obj) == 0:
                    log_and_print('WARNING: ' + filename + ' will be truncated.')
                else:
                    log_and_print(filename + ' saved.')

    def run(self,
            websites_str,
            leagues_str,
            is_get_only=False,
            is_send_email_api=False,
            is_send_email_smtp=False,
            is_send_email_when_found=False,
            loop_minutes=0,
            ask_gce=None,
            gce_ip=None,
            highlight=None,
            betfair_limits=None,
            is_betfair=False,
            exclude=None,
            print_betfair_only=False,
            ):
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
                            if hasattr(website, 'need_login'):
                                website.login()
                                self.driver.get(url)
                            time.sleep(2)
                        if hasattr(website, league + '_urls'):
                            setattr(website, league + '_url', url)
                            log_and_print('... will get next url after 10 secs...')
                            time.sleep(10)
                        website.current_league = league
                        website.fetch(matches)
                self.save_to(matches, pkl_name)
            except Exception as e:
                logging.exception(e)
                _, _, eb = sys.exc_info()
                traceback.print_tb(eb)
                self.save_to([], pkl_name)

        websites_str = websites_str if websites_str != 'all' else g_websites_str
        if betfair_limits is not None or is_betfair:
            websites_str += ',betfair'
        exclude_websites = [] if exclude is None else exclude.split(',')

        websites = []
        website_map = {}
        for w in websites_str.split(','):
            if w in exclude_websites:
                continue
            # e.g. when w is 'tab': o = Tab(driver, wait)
            o = globals()[w.title()](self.driver, self.wait)
            websites.append(o)
            website_map[w] = o

        if is_betfair:
            website_map['betfair'].get_back_odd = True

        if ask_gce is not None:
            for w in ask_gce.split(','):
                website_map[w].ask_gce = True

        if highlight is not None:
            hls = highlight.split(',')
            for i in range(2, 5):
                hls[i] = None if hls[i] == '' else float(hls[i])
            global g_monitor_match
            g_monitor_match.init(*hls)

        def set_pickles(l_name):
            return [l_name + '_' + w_.name + '.pkl'
                    for w_ in websites if getattr(w_, l_name + '_url') and l_name in league_names]
        league_names = leagues_str.split(',')
        match_merger = MatchMerger(set_pickles('a'),
                                   set_pickles('arg'),
                                   set_pickles('eng'),
                                   set_pickles('fra'),
                                   set_pickles('gem'),
                                   set_pickles('ita'),
                                   set_pickles('liga'),
                                   set_pickles('uefa'),
                                   set_pickles('w'))

        def send_email_when_found():
            with open('output_title.txt', 'r') as title_file:
                title = title_file.read()
                if title != 'None':
                    with open('output_title.old.txt', 'r+') as title_old_file:
                        old_title = title_old_file.read()
                        if title != old_title:
                            log_and_print(
                                'INFO: send_email_when_found - title [{}] and old title [{}],'
                                ' so I am sending the email out'.format(title, old_title))
                            send_email_by_api()
                            title_old_file.seek(0)
                            title_old_file.write(title)
                            title_old_file.truncate()
                        else:
                            log_and_print('INFO: send_email_when_found - email already sent')

        html_file = WriteToHtmlFile()
        while True:
            whole_start_time = datetime.now()
            for l in league_names:
                league_start_time = datetime.now()
                for w in websites:
                    if self.is_get_data and getattr(w, l+'_url'):
                        fetch_and_save_to_pickle(w, l)
                if not is_get_only:
                    if betfair_limits is not None:
                        limits = betfair_limits.split(',')
                        match_merger.betfair_min = float(0 if limits[0] == '' else limits[0])
                        match_merger.betfair_max = float(100 if limits[1] == '' else limits[1])
                        match_merger.betfair_delta = float(100 if limits[2] == '' else limits[2])
                        match_merger.betfair_hide = float(100 if limits[3] == '' else limits[3])  # noqa
                        match_merger.betfair_print_only = print_betfair_only
                    html_file.init()
                    match_merger.merge_and_print(leagues=[l], html_file=html_file)
                    html_file.close()
                    if is_send_email_smtp:
                        send_email_by_smtp()
                    if is_send_email_api:
                        send_email_by_api()
                    if is_send_email_when_found:
                        send_email_when_found()
                if self.is_get_data:
                    log_and_print('League [{}] scan time: {}'
                                  .format(l, datetime.now()-league_start_time))
            if self.is_get_data:
                log_and_print('Whole scan time: {}'.format(datetime.now()-whole_start_time))

            if is_get_only or loop_minutes is 0:
                if self.driver and not self.keep_driver_alive:
                    self.driver.quit()
                break
            else:
                self.count_down(loop_minutes)
