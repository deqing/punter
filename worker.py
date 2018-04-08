"""
TODO
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
g_get_all_markets = False  # TODO if do lay only: change to False
g_print_urls = True


def calc3(win_odd, draw_odd, lost_odd):
    def get_min_pay_back(w, d, l, wp, dp, lp):
        if w * wp <= d * dp and w * wp <= l * lp:
            return w * wp
        elif d * dp <= w * wp and d * dp <= l * lp:
            return d * dp
        else:
            return l * lp

    win_odd = float(win_odd)
    draw_odd = float(draw_odd)
    lost_odd = float(lost_odd)

    min_pay_back = 0
    win_percent = draw_percent = lost_precent = 0
    win_profit = draw_profit = lost_profit = 0
    for i in range(1, 99):
        for j in range(1, 100 - i):
            pay_back = get_min_pay_back(win_odd, draw_odd, lost_odd, i, j, 100 - i - j)
            if pay_back > min_pay_back:
                min_pay_back = pay_back
                win_percent = i
                draw_percent = j
                lost_precent = 100 - i - j
                win_profit = round(i * win_odd - 100, 2)
                draw_profit = round(j * draw_odd - 100, 2)
                lost_profit = round((100-i-j) * lost_odd - 100, 2)
    return min_pay_back, \
        win_percent, draw_percent, lost_precent, \
        win_profit, draw_profit, lost_profit


def calc2(a_odd, b_odd):
    def get_min_pay_back(ao, bo, ap, bp):
        if ao * ap <= bo * bp:
            return round(ao * ap, 2)
        else:
            return round(bo * bp, 2)

    a_odd = float(a_odd)
    b_odd = float(b_odd)

    min_pay_back = 0
    a_pay = b_pay = 0
    a_profit = b_profit = 0
    for i in range(1, 999):
        ipay = float(i/10)
        pay_back = get_min_pay_back(a_odd, b_odd, ipay, 100 - ipay)
        if pay_back > min_pay_back:
            min_pay_back = pay_back
            a_pay = round(ipay, 2)
            b_pay = round(100 - ipay, 2)
            a_profit = round(ipay * a_odd - 100, 2)
            b_profit = round((100 - ipay) * b_odd - 100, 2)
    return min_pay_back, a_pay, b_pay, a_profit, b_profit


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
    n = name.replace('\'', '').replace('.', '')
    return ''.join(n.lower().split())


def real_back_odd(odd):
    if '\n' in odd:
        odd = float(odd.split('\n')[0])
    else:
        odd = float(odd)
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
        self.desc = {  # TODO market names
            'main': (3, 'Main Market'),
            'both score': (2, 'Both teams to Score?'),
            'correct score': (0, 'Correct Score'),
            '1st scorer': (0, 'First Goal Scorer'),
            'anytime scorer': (0, 'Anytime Scorer'),
            'first 0.5': (2, 'First Half Over Under 0.5 Goals'),
            'first 1.5': (2, 'First Half Over Under 1.5 Goals'),
            'first 2.5': (2, 'First Half Over Under 2.5 Goals'),
            'first 3.5': (2, 'First Half Over Under 3.5 Goals'),
            'first home 0.5': (2, 'First Half Home Over Under 0.5 Goals'),
            'first home 1.5': (2, 'First Half Home Over Under 1.5 Goals'),
            'first home 2.5': (2, 'First Half Home Over Under 2.5 Goals'),
            'first home 3.5': (2, 'First Half Home Over Under 3.5 Goals'),
            'first away 0.5': (2, 'First Half Away Over Under 0.5 Goals'),
            'first away 1.5': (2, 'First Half Away Over Under 1.5 Goals'),
            'first away 2.5': (2, 'First Half Away Over Under 2.5 Goals'),
            'first away 3.5': (2, 'First Half Away Over Under 3.5 Goals'),
            'first half odd even goals': (2, 'First Half Odd Even Goals'),
            'first half both team to score': (2, 'First Half Both Team To Score'),
            'first half home team to score': (2, 'First Half Home Team To Score'),
            'first half away team to score': (2, 'First Half Away Team To Score'),
            'first half handicap home a1': (3, 'First Handicap Home a1'),
            'first half handicap home a2': (3, 'First Handicap Home a2'),
            'first half handicap home a3': (3, 'First Handicap Home a3'),
            'first half handicap away a1': (3, 'First Handicap Away a1'),
            'first half handicap away a2': (3, 'First Handicap Away a2'),
            'first half handicap away a3': (3, 'First Handicap Away a3'),
            'half time': (3, 'First Half Straight'),
            'half full': (0, 'Half Time / Full Time'),
            'half time score': (0, 'Half Time Score'),
            'ad 0.5': (2, 'Over/Under 0.5 Goals'),
            'ad 1.5': (2, 'Over/Under 1.5 Goals'),
            'ad 2.5': (2, 'Over/Under 2.5 Goals'),
            'ad 3.5': (2, 'Over/Under 3.5 Goals'),
            'ad 4.5': (2, 'Over/Under 4.5 Goals'),
            'ad 5.5': (2, 'Over/Under 5.5 Goals'),
            'ad 6.5': (2, 'Over/Under 6.5 Goals'),
            'ad 7.5': (2, 'Over/Under 7.5 Goals'),
            'ad 8.5': (2, 'Over/Under 8.5 Goals'),
            'handicap home a1': (3, 'Handicap Home a1'),
            'handicap home a2': (3, 'Handicap Home a2'),
            'handicap home a3': (3, 'Handicap Home a3'),
            'handicap home a4': (3, 'Handicap Home a4'),
            'handicap home a5': (3, 'Handicap Home a5'),
            'handicap away a1': (3, 'Handicap Away a1'),
            'handicap away a2': (3, 'Handicap Away a2'),
            'handicap away a3': (3, 'Handicap Away a3'),
            'handicap away a4': (3, 'Handicap Away a4'),
            'handicap away a5': (3, 'Handicap Away a5'),
            'home ad 0.5': (2, 'Home Over Under 0.5 Goals'),
            'home ad 1.5': (2, 'Home Over Under 1.5 Goals'),
            'home ad 2.5': (2, 'Home Over Under 2.5 Goals'),
            'home ad 3.5': (2, 'Home Over Under 3.5 Goals'),
            'away ad 0.5': (2, 'Away Over Under 0.5 Goals'),
            'away ad 1.5': (2, 'Away Over Under 1.5 Goals'),
            'away ad 2.5': (2, 'Away Over Under 2.5 Goals'),
            'away ad 3.5': (2, 'Away Over Under 3.5 Goals'),
        }

    def get_desc(self, key):
        return self.desc[key][1]

    def key(self, market_str):
        if 'Over/Under Total Goals' in market_str:
            market_str = market_str.replace('Total Goals ', '')
        squashed_market_str = squash_string(market_str)
        for desc_key, desc_values in self.desc.items():
            if squashed_market_str in squash_string(desc_values[1]):
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
            'banfield': 'Banfield',
            'belgrano': 'Belgrano',
            'boca': 'Boca Juniors',
            'independ': 'CA Independiente',
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
            'sarsfield': 'Velez Sarsfield',
            'santa': 'Union Santa',
            'sanmartin': 'San Martin de San Juan',
            'talleres': 'CA Talleres de Cordoba',
            'temperley': 'Temperley',
            'tigre': 'CA Tigre',
            'tucu': 'Atletico Tucuman',
        }
        self.map['bel'] = {
            'anderlecht': 'Anderlecht',
            'antwerp': 'Royal Antwerp',
            'brugge': 'Brugge',
            'charleroi': 'Royal Charleroi',
            'eupen': 'Eupen',
            'genk': 'Racing Genk',
            'gent': 'KAA Gent',
            'kortrijk': 'KV Kortrijk',
            'mechelen': 'KV Mechelen',
            'mouscron': 'Mouscron',
            'standard': 'Standard Liege',
            'truidense': 'Sint-Truidense',
            'oostende': 'KV Oostende',
            'liege': 'Standard Liege',
            'lokeren': 'KSC Lokeren',
            'waasland': 'Waasland Beveren',
            'zulte': 'Zulte Waregem',
        }
        self.map['eng'] = {
            'arsenal': 'Arsenal',
            'bournemouth': 'Bournemouth',
            'birmingham': 'Birmingham City',
            'brighton': 'Brighton',
            'burnley': 'Burnley',
            'chelsea': 'Chelsea',
            'coventry': 'Coventry',
            'crystal': 'Crystal Palace',
            'everton': 'Everton',
            'huddersfield': 'Huddersfield',
            'leicester': 'Leicester',
            'liverpool': 'Liverpool',
            'manchestercity': 'Man City',
            'manchesterunited': 'Man Utd',
            'newport': 'Newport County',
            'newcastle': 'Newcastle',
            'notts': 'Notts County',
            'rochdale': 'Rochdale',
            'sheffield': 'Sheffield United',
            'southampton': 'Southampton',
            'stoke': 'Stoke',
            'swansea': 'Swansea',
            'tottenham': 'Tottenham',
            'watford': 'Watford',
            'westbrom': 'West Brom',
            'westham': 'West Ham',
            'wigan': 'Wigan',
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
            'acmilan': 'AC Milan',
            'anderlecht': 'Anderlecht',
            'arsenal': 'Arsenal',
            'astana': 'FC Astana',
            'atalanta': 'Atalanta',
            'athens': 'AEK Athens',
            'apoel': 'APOEL Nicosia',
            'atleticomadrid': 'Atletico Madrid',
            'barcelona': 'Barcelona',
            'basel': 'FC Basel',
            'bayern': 'Bayern Munich',
            'belgrade': 'Partizan Belgrade',
            'benfica': 'Benfica',
            'besiktas': 'Besiktas JK',
            'bilbao': 'Athletic Bilbao',
            'braga': 'Braga',
            'celtic': 'Celtic',
            'chelsea': 'Chelsea',
            'cska': 'CSKA Moscow',
            'copenhagen': 'Copenhagen',
            'dortmund': 'Borussia Dortmund',
            'dynamo': 'Dynamo Kiev',
            'feyenoord': 'Feyenoord',
            'fcsb': 'FCSB',
            'juventus': 'Juventus',
            'lazio': 'Lazio',
            'leipzig': 'RB Leipzig',
            'liverpool': 'Liverpool',
            'lokomotiv': 'Lokomotiv Moscow',
            'ludogorets': 'Ludogorets Razgrad',
            'lyon': 'Lyon',
            'mancity': 'Manchester City',
            'manutd': 'Manchester United',
            'marseille': 'Marseille',
            'maribor': 'NK Maribor',
            'monaco': 'AS Monaco',
            'napoli': 'Napoli',
            'nice': 'Nice',
            'olympia': 'Olympiakos',
            'ostersund': 'Ostersunds FK',
            'paris': 'Paris Saint Germain',
            'plzen': 'Viktoria Plzen',
            'porto': 'FC Porto',
            'qarabag': 'FK Qarabag',
            'realmad': 'Real Madrid',
            'roma': 'AS Roma',
            'salzburg': 'FC Salzburg',
            'sociedad': 'Real Sociedad',
            'spartak': 'Spartak Moscow',
            'lisbon': 'Sporting Lisbon',
            'sportingcp': 'Sporting CP',
            'sevilla': 'Sevilla',
            'shakhtar': 'Shakhtar Donetsk',
            'tottenham': 'Tottenham Hotspur',
            'villarreal': 'Villarreal',
            'zenit': 'Zenit St Petersburg',
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
            elif 'sheffwed' in converted_name:
                converted_name = 'sheffield'
        elif league_name == 'arg':
            if 'olimpo' in converted_name:
                converted_name = 'blanca'
            elif 'velez' in converted_name:
                converted_name = 'sarsfield'
            elif 'lanús' == converted_name:
                converted_name = 'lanus'
            elif 'colón' == converted_name:
                converted_name = 'colon'
        elif league_name == 'uefa':
            if 'manchestercity' == converted_name:
                converted_name = 'mancity'
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
            elif 'bucharest' in converted_name:
                converted_name = 'fcsb'
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
    def get_blocks_static(css_string, driver, wait, check=True):
        def check_and_get():
            try:
                Website.wait(css_string, wait)
                return driver.find_elements_by_css_selector(css_string)
            except TimeoutException:
                log_and_print('[{}] not found'.format(css_string))
                return []

        if not check:
            blocks_ = driver.find_elements_by_css_selector(css_string)
            if len(blocks_) is 0:
                return check_and_get()
            else:
                return blocks_
        else:
            return check_and_get()

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
                    m.odds[i] = real_back_odd(odds[0])
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
            Website.wait('userauth_username', wait, type_='id')
            account = driver.find_element_by_id('userauth_username')
            password = driver.find_element_by_id('userauth_password')
            login = driver.find_element_by_css_selector('input.logbut')
            with open('ladbrokes.username', 'r') as username_file, \
                    open('ladbrokes.password', 'r') as password_file:
                account.send_keys(username_file.read().rstrip())
                password.send_keys(password_file.read().rstrip())
            login.click()
            time.sleep(2)
            Website.wait('div.welcome', wait)  # When this failed, set a breakpoint here, then it will work  # noqa
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
        self.home_name, self.away_name, self.league = '', '', ''
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

    def get_website(self, worker_id):
        log_and_print('Process {} starting...'.format(worker_id))
        self.compare_multiple_sites(worker_id=worker_id)

    @staticmethod
    def get_snr_profit(back_odd, lay_odd):
        return (back_odd - 1) * 100 - (lay_odd - 1) * ((back_odd - 1) / (lay_odd - 0.05) * 100)

    @staticmethod
    def test():
        min_pay_back, ip, jp, iget, jget = calc2(1.5, 2.88)
        log_and_print('{} ${}({}) ${}({})'.format(min_pay_back, ip, iget, jp, jget))

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
        if not g_get_all_markets and 'main' not in lay_markets:
            # Very likely it is for boost, so login to get real odd
            Ladbrokes.login_static(self.driver, self.wait)
            self.driver.get(url_back)

        try:
            self.wait.until(expected_conditions.visibility_of_element_located((By.ID,
                                                                               'twirl_element_1')))
        except TimeoutException:
            log_and_print('ladbroke has no match info:\n' + url_back)
            return dict()

        if g_get_all_markets or 'main' in lay_markets:
            home_text = self.driver.find_element_by_id('twirl_element_1').text
            away_text = self.driver.find_element_by_id('twirl_element_2').text
            draw_text = self.driver.find_element_by_id('twirl_element_3').text

            self.home_name, home_odd = home_text.split('\n')
            self.away_name, away_odd = away_text.split('\n')
            _, draw_odd = draw_text.split('\n')

            odds_back['main'][self.home_name] = home_odd
            odds_back['main'][self.away_name] = away_odd
            odds_back['main']['Draw'] = draw_odd

        markets = self.driver.find_elements_by_css_selector('div.additional-market')
        for market in markets:
            desc = market.find_element_by_css_selector('div.additional-market-description').text
            if desc == 'First Half Correct Score':
                desc = 'Half Time Score'
            elif 'Total Goals' in desc:
                # Over/Under Barcelona Total Goals 1.5 -> Away Over/Under 1.5 Goals
                for name, name_to in ((self.home_name, 'Home'),
                                      (self.away_name, 'Away')):
                    first_half = 'Over/Under First Half ' + name + ' Total Goals'
                    if desc.startswith(first_half):
                        desc = desc.replace(first_half, 'First Half ' + name_to + ' Over Under')
                        desc += ' Goals'
                    else:
                        total_goals = 'Over/Under ' + name + ' Total Goals'
                        if desc.startswith(total_goals):
                            desc = desc.replace(total_goals, name_to + ' Over/Under')
                            desc += ' Goals'
            key = market_names.key(desc)
            if key is not None and g_get_all_markets or key in lay_markets:
                market.click()
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

    def safe_click(self, text):
        link = self.driver.find_element_by_link_text(text)
        self.wait.until(
            expected_conditions.visibility_of_element_located((By.LINK_TEXT, text)))
        self.driver.execute_script("arguments[0].click();", link)
        time.sleep(0.5)

    def get_crown_markets_odd(self, url_back, target_markets, _):
        market_names = MarketNames()
        self.driver.get(url_back)
        odds_back = self.prepare_map_with_target_markets_as_key(market_names, target_markets)
        sections = Website.get_blocks_static('div.match-type.clearfix', self.driver, self.wait)
        for section in sections:
            title = section.find_element_by_css_selector('div.title').text
            odds = section.find_element_by_css_selector('div.single-event-table-wrapper').text.split('\n')  # noqa
            if title == 'Win-Draw-Win':
                self.home_name = odds[0]
                self.away_name = odds[4]
                odds_back['main'][self.home_name] = odds[1]
                odds_back['main']['Draw'] = odds[3]
                odds_back['main'][self.away_name] = odds[5]
            elif title == 'Total Goals Over/Under':
                if 'Under' not in odds[0] or 'Over' not in odds[2]:
                    log_and_print('DEBUG: unexpected ad ' + ','.join(odds))
                    continue
                goals = odds[0].split('(')[1][:-1]
                odds_back['ad ' + goals]['under'] = odds[1]
                odds_back['ad ' + goals]['over'] = odds[3]
            elif title == 'Both Teams To Score':
                odds_back['both score']['yes'] = odds[1]
                odds_back['both score']['no'] = odds[3]
            elif title == 'Half Time/Full Time':
                for t, odd in zip(odds[::2], odds[1::2]):
                    name1, name2 = t.split(' - ')
                    odds_back['half full'][name1 + '/' + name2] = odd
            elif title == 'Correct Score':
                for t, odd in zip(odds[::2], odds[1::2]):
                    if t == 'Any Other Score':
                        continue
                    odds_back['correct score'][''.join(t.split(' '))] = odd
        return odds_back

    def get_william_markets_odd(self, url_back, target_markets, _):
        market_names = MarketNames()
        odds_back = self.prepare_map_with_target_markets_as_key(market_names, target_markets)
        self.driver.get(url_back)
        sections = Website.get_blocks_static('div.Market_market_2m7', self.driver, self.wait)
        
        def loop_check():
            for goals in 0.5, 1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5:
                title_ = 'Over/Under {} Goals'.format(goals)
                if header == title_:
                    odds_back['ad {}'.format(goals)]['over'] = odds[1]
                    odds_back['ad {}'.format(goals)]['under'] = odds[3]
                    return

            for goals in 0.5, 1.5, 2.5, 3.5:
                if header == '{} Over/Under {} goals'.format(self.home_name, goals):
                    odds_back['home ad {}'.format(goals)]['over'] = odds[2]
                    odds_back['home ad {}'.format(goals)]['under'] = odds[5]
                elif header == '{} Over/Under {} goals'.format(self.away_name, goals):
                    odds_back['away ad {}'.format(goals)]['over'] = odds[2]
                    odds_back['away ad {}'.format(goals)]['under'] = odds[5]
                elif header == 'First Half Over/Under {} goals'.format(goals):
                    odds_back['first {}'.format(goals)]['over'] = odds[1]
                    odds_back['first {}'.format(goals)]['under'] = odds[3]
                elif header == 'First Half {} Over/Under {} goals'.format(self.home_name, goals):
                    odds_back['first home {}'.format(goals)]['over'] = odds[2]
                    odds_back['first home {}'.format(goals)]['under'] = odds[5]
                elif header == 'First Half {} Over/Under {} goals'.format(self.away_name, goals):
                    odds_back['first away {}'.format(goals)]['over'] = odds[2]
                    odds_back['first away {}'.format(goals)]['under'] = odds[5]
                else:
                    continue
                return
            
            for goals in 0.5, 1.5, 2.5, 3.5:
                try:
                    if len(odds) < 5:
                        o, u = 1, 3
                    else:
                        o, u = 2, 5
                        
                    if header == 'First Half Over/Under {} Goals'.format(goals):
                        odds_back['first {}'.format(goals)]['over'] = odds[o]
                        odds_back['first {}'.format(goals)]['under'] = odds[u]
                    elif header == '{} Over/Under {} Goals'.format(self.home_name, goals):
                        odds_back['home ad {}'.format(goals)]['over'] = odds[o]
                        odds_back['home ad {}'.format(goals)]['under'] = odds[u]
                    elif header == '{} Over/Under {} Goals'.format(self.away_name, goals):
                        odds_back['away ad {}'.format(goals)]['over'] = odds[o]
                        odds_back['away ad {}'.format(goals)]['under'] = odds[u]
                    elif header == 'First Half {} Over/Under {} Goals'.format(self.home_name, goals) or\
                            header == 'First Half {} {} Goals'.format(self.home_name, goals):
                        odds_back['first home {}'.format(goals)]['over'] = odds[o]
                        odds_back['first home {}'.format(goals)]['under'] = odds[u]
                    elif header == 'First Half {} Over/Under {} Goals'.format(self.away_name, goals) or\
                            header == 'First Half {} {} Goals'.format(self.away_name, goals):
                        odds_back['first away {}'.format(goals)]['over'] = odds[o]
                        odds_back['first away {}'.format(goals)]['under'] = odds[u]
                    else:
                        continue
                    return
                except:
                    raise

            for goals in 1, 2, 3, 4, 5:
                if header == 'Handicap {} +{}'.format(self.home_name, goals):
                    title = 'handicap home a{}'.format(goals)
                elif header == 'Handicap {} -{}'.format(self.home_name, goals):
                    title = 'handicap away a{}'.format(goals)
                elif header == 'First Half Handicap {} +{}'.format(self.home_name, goals):
                    title = 'first half handicap home a{}'.format(goals)
                elif header == 'First Half Handicap {} -{}'.format(self.home_name, goals):
                    title = 'first half handicap away a{}'.format(goals)
                else:
                    continue
                odds_back[title][self.home_name] = odds[1] if 'SUS' not in odds[1] else '0'
                odds_back[title]['draw'] = odds[3] if 'SUS' not in odds[3] else '0'
                odds_back[title][self.away_name] = odds[5] if 'SUS' not in odds[5] else '0'
                return
        
        for section in sections:
            header = section.find_element_by_css_selector('div.Market_header_2Wc').text
            odds = section.find_element_by_css_selector('div.Outcomes_outcomes_2uk').text.split('\n')  # noqa
            if header == 'Match Result':
                self.home_name = odds[0]
                self.away_name = odds[4]
                odds_back['main'][self.home_name] = odds[1]
                odds_back['main']['Draw'] = odds[3]
                odds_back['main'][self.away_name] = odds[5]
            elif header == 'Both Teams To Score':
                odds_back['both score']['yes'] = odds[1]
                odds_back['both score']['no'] = odds[3]
            elif header == 'First Half Odd / Even Goals':
                odds_back['first half odd even goals']['odd'] = odds[1]
                odds_back['first half odd even goals']['even'] = odds[3]
            elif header == 'First Half - Match Result':
                odds_back['half time']['odd'] = odds[1]
                odds_back['half time']['even'] = odds[3]
            elif header == 'HT/FT Double' or header == 'HT/NT Double':
                for t, odd in zip(odds[::2], odds[1::2]):
                    odds_back['half full'][t] = odd
            elif header == 'Correct Score':
                for t, odd in zip(odds[::2], odds[1::2]):
                    odds_back['correct score'][''.join(t.split(' '))] = odd
            elif header == 'First Half Correct Score':
                for t, odd in zip(odds[::2], odds[1::2]):
                    odds_back['half time score'][''.join(t.split(' '))] = odd
            elif header == 'First Goalscorer':
                for t, odd in zip(odds[::2], odds[1::2]):
                    odds_back['1st scorer'][t] = odd
            else:
                loop_check()
        return odds_back

    def get_william_markets_odd_old(self, url_back, target_markets, lay_markets):
        market_names = MarketNames()
        map_headers = {
            'Correct Score': 'correct score',
            'Both Teams To Score': 'both score',
            'HT/FT Double': 'half full',
            'First Half - Straight': 'half time',
            'First Half Odd / Even Goals': 'first half odd even goals',
            'First Half Correct Score': 'half time score',
            'First Half Over/Under 0.5 Goals': 'first 0.5',
            'First Half Over/Under 1.5 Goals': 'first 1.5',
            'First Half Over/Under 2.5 Goals': 'first 2.5',
            'First Half Over/Under 3.5 Goals': 'first 3.5',
            'First Half Both Teams To Score': 'first half both team to score',
            'First Goalscorer': '1st scorer',
            'Anytime Goalscorer': 'anytime scorer',
        }

        # -- get popular markets
        odds_back = self.prepare_map_with_target_markets_as_key(market_names, target_markets)
        self.driver.set_window_size(width=1920, height=1080)
        self.driver.get(url_back)
        sections = Website.get_blocks_static('section.block.flat', self.driver, self.wait)
        for section in sections:
            titles = section.text.split('\n')
            if titles[0] == 'Straight':
                self.home_name = titles[1]
                self.away_name = titles[5]
                home_odd = titles[2]
                draw_odd = titles[4]
                away_odd = titles[6]
                break
        else:
            log_and_print('Looks like no info in:\n' + url_back)
            return odds_back

        if g_get_all_markets or 'main' in lay_markets:
            odds_back['main'][self.home_name] = home_odd
            odds_back['main'][self.away_name] = away_odd
            odds_back['main']['Draw'] = draw_odd

        for name, s in (self.home_name, 'home'), (self.away_name, 'away'):
            map_headers[name + ' To Score First Half'] = 'first half ' + s + ' team to score'
            for goals in '0.5', '1.5':
                map_headers['First Half ' + name + ' Over/Under ' + goals + ' Goals'] = \
                    'first ' + s + ' ' + goals

        # WilliamHill is only using home for Handicap
        # handicap home a1 <- Birmingham +1 (a means add, b means minus)
        # handicap away a1 <- Birmingham -1
        hn, an = self.home_name, self.away_name
        m = map_headers
        for j in '1', '2', '3', '4', '5':
            m['Handicap {} +{}'.format(hn, j)] = 'handicap home a' + j
            m['Handicap {} -{}'.format(hn, j)] = 'handicap away a' + j
            m['First Half Handicap {} +{}'.format(hn, j)] = 'first half handicap home a' + j
            m['First Half Handicap {} -{}'.format(hn, j)] = 'first half handicap away a' + j

        for i in range(9):
            j = str(i) + '.5'
            m['Over/Under {} Goals'.format(j)] = 'ad ' + j

        for i in range(4):
            j = str(i) + '.5'
            m['{} Over/Under {} Goals'.format(hn, j)] = 'home ad ' + j
            m['{} Over/Under {} Goals'.format(an, j)] = 'away ad ' + j

        def read_sections(tab_):
            def try_multiple(func, arg):
                for _ in range(3):
                    try:
                        func(arg)
                        break
                    except NoSuchElementException:  # Sometimes we don't have additional market
                        break
                    except Exception as e:
                        log_and_print(
                            'DEBUG: will try again as having {}'.format(type(e).__name__))
                        time.sleep(1)

            def get_texts(_=None):
                sections_ = Website.get_blocks_static('section.block.flat', self.driver, self.wait)
                for section_ in sections_:
                    header = section_.find_elements_by_css_selector('header.drop-header')
                    if len(header) == 0:
                        continue
                    header = header[0].text.strip()
                    if header in headers:
                        if len(section_.find_elements_by_css_selector(
                                'h3.event-header.is-open')) is 0:
                            self.safe_click(header)
                        odd_blocks = section_.find_elements_by_css_selector('div.table.teams')
                        for odd_block in odd_blocks:
                            t = odd_block.text
                            if t != '':
                                first, second = t.split('\n')
                                odds_back[map_headers[header]][squash_string(first)] = second

            if tab_ != 'main':
                try_multiple(self.safe_click, tab_)

            headers = map_headers.keys()
            try_multiple(get_texts, arg=None)

        for tab in 'main', '1st Half', 'Goal Scorer', 'Handicaps', 'Totals':
            try:
                read_sections(tab)
            except NoSuchElementException:
                log_and_print('DEBUG - WilliamHill [{}] NoSuchElementException'.format(tab))
            except StaleElementReferenceException:
                log_and_print('DEBUG - WilliamHill [{}] StaleElementReferenceException'.format(tab))

        return odds_back

    def full_name_to_id(self, str_contains_full_name):
        info = LeagueInfo()
        if '/' in str_contains_full_name:
            team1, team2 = str_contains_full_name.split('/')
            team1_id = info.get_id(team1, self.league)
            team2_id = info.get_id(team2, self.league)
            return '/'.join([team1_id, team2_id])
        return str_contains_full_name

    # Convert team name to id for further matching
    def odds_map_to_id(self, odds_map, agent_name=None, is_betfair=False):
        formatted = dict()
        info = LeagueInfo()
        try:
            for key, market_map in odds_map.items():
                formatted[key] = dict()
                for name, odd in market_map.items():
                    if agent_name is not None:
                        odd = str(odd) + ' ' + agent_name
                    if '/' in name:
                        formatted[key][self.full_name_to_id(name)] = odd
                    elif key in ('correct score', 'half time score'):
                        win_set, draw_set, lose_set = self.get_correct_score_sets()
                        if is_betfair:
                            if name in win_set or name in draw_set or name in lose_set:
                                formatted[key][name] = odd
                        else:
                            idx = name.rfind('-') - 1
                            idx = idx - 1 if '10-0' in name else idx
                            team, score = name[:idx], name[idx:]
                            if score not in win_set and score not in draw_set:
                                continue
                            team_id = info.get_id(team, self.league)
                            home_id = info.get_id(self.home_name, self.league)
                            away_id = info.get_id(self.away_name, self.league)
                            if team_id == home_id or team == 'draw' or team == 'Draw':
                                formatted[key][score] = odd
                            elif team_id == away_id:
                                formatted[key][score[::-1]] = odd
                            else:
                                log_and_print('DEBUG - unexpected [{}] [{}] [{}] [{}] [{}]'.format(
                                              name, team, team_id, home_id, away_id))
                    else:
                        name = name.replace('tie', 'draw')
                        formatted[key][info.get_id(name, self.league)] = odd
        except AttributeError:
            log_and_print('DEBUG: len of odds is ' + str(len(odds_map)))
            raise
        return formatted

    def title_expand_full_name(self, title_):
        info = LeagueInfo()

        to_full = dict()
        if self.home_name != '':
            to_full[info.get_id(self.home_name, self.league)] = self.home_name
        if self.away_name != '':
            to_full[info.get_id(self.away_name, self.league)] = self.away_name
        to_full['draw'] = 'Draw'
        to_full['over'] = 'Over '
        to_full['under'] = 'Under '
        to_full['goals'] = ' Goals'

        for team, full_name in to_full.items():
            title_ = title_.replace(team, ' ' + full_name + ' ')

        return title_

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
            # uefa='https://www.classicbet.com.au/Sport/Soccer/UEFA_Europa_League/Matches',
            # uefa='https://www.classicbet.com.au/Sport/Soccer/UEFA_Champions_League/Matches',
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
                info[l][self.get_vs(' '.join(home), ' '.join(away), l)] = \
                    (match_time, '{} {}'.format(url, i))

        return info

    def get_crownbet_match_info(self):
        urls = dict(
            arg='https://crownbet.com.au/sports-betting/soccer/americas/argentina-primera-division-matches',  # noqa
            a='https://crownbet.com.au/sports-betting/soccer/australia/a-league-matches',
            # bel='',
            # eng='',
            eng='https://crownbet.com.au/sports-betting/soccer/united-kingdom/english-premier-league-matches',  # noqa
            fra='https://crownbet.com.au/sports-betting/soccer/france/french-ligue-1-matches',
            gem='https://crownbet.com.au/sports-betting/soccer/germany/german-bundesliga-matches',
            ita='https://crownbet.com.au/sports-betting/soccer/italy/italian-serie-a-matches/',
            liga='https://crownbet.com.au/sports-betting/soccer/spain/spanish-la-liga-matches/',
            uefa='https://crownbet.com.au/sports-betting/soccer/uefa-competitions/champions-league-matches/',  # noqa
        )
        info = self.init_league_info(**urls)

        for l, url in urls.items():
            self.driver.get(url)
            blocks = Website.get_blocks_static('td.content', self.driver, self.wait)
            for b in blocks:
                date_ = b.find_element_by_css_selector('span.tv').text
                date_ = '{dt:%a} {dt.day} {dt:%b} '.format(dt=datetime.strptime(date_, '%d/%m'))
                title = b.find_element_by_css_selector('span.match-name')
                match_url = title.find_element_by_tag_name('a').get_attribute('href')
                t = title.text
                if t == 'Outright Markets':
                    continue
                try:
                    home, away = t.split(' v ')
                except:
                    log_and_print('DEBUG: failed to split ' + t)
                    raise
                info[l][self.get_vs(home, away, l)] = (date_, match_url)
        return info

    def get_ladbrokes_match_info(self):
        urls = dict(
            arg='https://www.ladbrokes.com.au/sports/soccer/45568353-football-argentina-argentinian-primera-division/',  # noqa
            a='https://www.ladbrokes.com.au/sports/soccer/44649922-football-australia-australian-a-league/',  # noqa
            # bel='https://www.ladbrokes.com.au/sports/soccer/45568434-football-belgium-belgian-first-division-a/',  # noqa
            # eng='https://www.ladbrokes.com.au/sports/soccer/46666149-football-england-fa-cup/',  # noqa
            eng='https://www.ladbrokes.com.au/sports/soccer/44936933-football-england-premier-league/',  # noqa
            fra='https://www.ladbrokes.com.au/sports/soccer/45472697-football-france-french-ligue-1/',  # noqa
            gem='https://www.ladbrokes.com.au/sports/soccer/44769778-football-germany-german-bundesliga/',  # noqa
            ita='https://www.ladbrokes.com.au/sports/soccer/45942404-football-italy-italian-serie-a/',  # noqa
            liga='https://www.ladbrokes.com.au/sports/soccer/45822932-football-spain-spanish-la-liga/',  # noqa
            # uefa='https://www.ladbrokes.com.au/sports/soccer/47323146-football-uefa-club-competitions-uefa-europa-league/',  # noqa
            # uefa='https://www.ladbrokes.com.au/sports/soccer/48526915-football-uefa-club-competitions-uefa-champions-league/',  # noqa
        )
        info = self.init_league_info(**urls)
        for league, url in urls.items():
            self.driver.get(url)
            titles = Website.get_blocks_static('div.fullbox-hdr', self.driver, self.wait)
            times = Website.get_blocks_static('tr.bettype-hdr', self.driver, self.wait)
            if len(times) < len(titles):
                log_and_print('maybe there is no match in:\n' + url)
            for i in range(len(times)):
                if i >= len(titles) or titles[i].text == 'PROMOTIONAL MARKET':
                    continue
                try:
                    title = titles[i].find_element_by_tag_name('a')
                except NoSuchElementException:
                    continue
                match_url = title.get_attribute('href')
                home, away = title.get_attribute('title').split(' - ')[-1].split(' v ')

                t = times[i].find_elements_by_css_selector('div.startingtime')
                if len(t) is not 0:
                    date_ = '{dt:%a} {dt.day} {dt:%b} '.format(
                        dt=datetime.strptime(t[0].text, '%a %d/%m/%Y'))
                    time_ = datetime.strptime(t[1].text, '%I:%M %p').strftime('%H:%M')
                    info[league][self.get_vs(home, away, league)] = (date_ + time_, match_url)
        return info

    def get_william_match_info(self):
        urls = dict(
            a='https://www.williamhill.com.au/sports/soccer/australia/a-league-matches',
            arg='https://www.williamhill.com.au/sports/soccer/americas/argentine-primera-division-matches',  # noqa
            # bel='https://www.williamhill.com.au/sports/soccer/europe/belgian-first-division-a-matches',  # noqa
            eng='https://www.williamhill.com.au/sports/soccer/british-irish/english-premier-league-matches',  # noqa
            fra='https://www.williamhill.com.au/sports/soccer/europe/french-ligue-1-matches',
            gem='https://www.williamhill.com.au/sports/soccer/europe/german-bundesliga-matches',
            ita='https://www.williamhill.com.au/sports/soccer/europe/italian-serie-a-matches',
            liga='https://www.williamhill.com.au/sports/soccer/europe/spanish-primera-division-matches',  # noqa
            # uefa='https://www.williamhill.com.au/sports/soccer/european-cups/uefa-europa-league-matches',  # noqa
            # uefa='https://www.williamhill.com.au/sports/soccer/european-cups/uefa-champions-league-matches',  # noqa
        )
        info = self.init_league_info(**urls)
        for league, url in urls.items():
            self.driver.get(url)
            titles = Website.get_blocks_static('div.SportEvent_headerContent_3Be',
                                               self.driver, self.wait)
            for title in titles:
                try:
                    event = title.find_element_by_tag_name('a')
                    match_url = event.get_attribute('href')
                    vs = event.text
                    t = title.find_element_by_css_selector('span.SportEvent_startTime_359').text
                except NoSuchElementException:
                    continue

                home, away = vs.split(' VS ')
                home.replace('.', '')
                away.replace('.', '')

                date_, time_ = t.split(', ')
                date_ = '{dt:%a} {dt.day} {dt:%b} '.format(dt=datetime.strptime(date_, '%d %b'))
                time_ = time_.split(' ')[0]

                info[league][self.get_vs(home, away, league)] = (date_ + time_, match_url)
        return info

    def get_betfair_match_info(self):
        urls = dict(
            arg='https://www.betfair.com.au/exchange/plus/football/competition/67387',
            a='https://www.betfair.com.au/exchange/plus/football/competition/11418298',
            # bel='https://www.betfair.com.au/exchange/plus/football/competition/89979',
            # eng='https://www.betfair.com.au/exchange/plus/football/competition/30558',  # FA Cup
            eng='https://www.betfair.com.au/exchange/plus/football/competition/10932509',
            fra='https://www.betfair.com.au/exchange/plus/football/competition/55',
            gem='https://www.betfair.com.au/exchange/plus/football/competition/59',
            ita='https://www.betfair.com.au/exchange/plus/football/competition/81',
            liga='https://www.betfair.com.au/exchange/plus/football/competition/117',
            # uefa='https://www.betfair.com.au/exchange/plus/football/competition/2005',
            uefa='https://www.betfair.com.au/exchange/plus/football/competition/228',
        )
        info = self.init_league_info(**urls)

        for _ in range(3):
            try:
                url = list(urls.values())[0]
                self.driver.set_window_size(width=1920, height=1080)
                self.driver.get(url)
                Betfair.login_static(self.driver, self.wait)
                time.sleep(1)
                break
            except Exception as e:
                log_and_print('DEBUG {}'.format(str(e)))
                continue

        def get_date(i_):
            return Website.get_blocks_static('span.card-header-title',
                                             self.driver,
                                             self.wait)[i_].text

        def get_tables():
            tables_ = Website.get_blocks_static('table.coupon-table', self.driver, self.wait)
            if len(tables_) is not 0:
                matches = tables_[0].text.split('\n')
                if len(matches) is not 0 and matches[0] == 'In-Play':
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
                    info[league][self.get_vs(home, away, league)] = (date_, match_url)
        return info

    def generate_compare_urls_file(self):
        def is_in(info_):
            if league in info_:
                for v in info_[league]:
                    if vs == v:
                        return True
            return False

        def write_file(s):
            urls_file.write(s + '\n')
        
        def write_url(info_):
            if is_in(info_):
                write_file(info_[league][vs][1])
            else:
                write_file('.')

        def write_pkl(obj, file):
            with open(file, 'wb') as pkl:
                pickle.dump(obj, pkl)

        def read_pkl(file):
            with open(file, 'rb') as pkl:
                return pickle.load(pkl)

        file_c = os.path.join(gettempdir(), 'c_info.pkl')
        file_w = os.path.join(gettempdir(), 'w_info.pkl')
        file_b = os.path.join(gettempdir(), 'b_info.pkl')

        is_write = True  # False for debug
        if is_write:
            try:
                log_and_print('getting crownbet')
                info_crownbet = self.get_crownbet_match_info()
                write_pkl(info_crownbet, file_w)

                log_and_print('getting ladbrokes')
                info_ladbrokes = self.get_ladbrokes_match_info()

                log_and_print('getting william')
                info_william = self.get_william_match_info()
                # write_pkl(info_william, file_w)

                log_and_print('getting betfair')
                info_betfair = self.get_betfair_match_info()
                write_pkl(info_betfair, file_b)
            finally:
                self.driver.quit()
        else:
            info_crownbet = read_pkl(file_c)
            info_ladbrokes = dict()
            info_william = read_pkl(file_w)
            info_betfair = read_pkl(file_b)

        with open('compare.txt', 'w') as urls_file:
            write_file('==bet_type== q')
            write_file('==markets===:all')
            for league, matches in info_betfair.items():
                for vs, betfair_pair in matches.items():
                    if is_in(info_crownbet) or is_in(info_ladbrokes) or is_in(info_william):
                        time_, betfair_url = betfair_pair
                        write_file('-- ' + league)
                        write_file(time_ + ' - ' + vs)
                        write_url(info_crownbet)
                        write_url(info_ladbrokes)
                        write_url(info_william)
                        write_file(betfair_url)

    @staticmethod
    def has_value(d, key):
        return key in d and len(d[key]) != 0

    def get_classicbet_markets_odd(self, with_url_back, target_markets, lay_markets):
        s_home_name, s_away_name = self.home_name, self.away_name
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

        def get_over_under(info_):
            odd = info_.pop()
            goals_ = info_.pop()
            s_ = 'Over/Under ' + goals_ + ' Goals'
            odds_back[market_names.key(s_)][squash_string(info_.pop()+goals_)] = odd
            return info_

        # -------- Get main
        if g_get_all_markets or 'main' in lay_markets:
            # e.g. 1. 'Swansea City 10.25 5.30 +0.5@3.45 Over 2.5 1.61'
            #   or 1. 'Swansea City 10.25 5.30 Over 2.5 1.61'
            #
            #      2. 'Chelsea 10.25 +0.5@3.45 Under 2.5 1.61'
            #   or 2. 'Chelsea 10.25 Under 2.5 1.61'
            #
            #      3. 'Chelsea 10.25 +0.5@3.45 Under 2.5 1.61'
            #   or 3. 'Chelsea 10.25 -0.5@3.45 Over 2.5 1.61'
            has_line = 'LINE' in main_lines[0]  # pop_count += 1
            has_over = 'OVER' in main_lines[0]  # pop_count += 3

            home_info = main_lines[1].split(' ')
            if has_over:  # 'Over 2.5 1.61'
                home_info = get_over_under(home_info)

            if has_line:
                home_info.pop()

            draw_odd = home_info.pop()
            is_odd_ready, _ = self.to_number(draw_odd)
            if not is_odd_ready:
                return dict()

            home_odd = home_info.pop()
            self.home_name = ' '.join(home_info)

            away_info = main_lines[2].split(' ')
            if has_over:  # 'Under 2.5 1.61'
                away_info = get_over_under(away_info)

            away_odd = away_info.pop()
            if '@' in away_odd:
                away_odd = away_info.pop()

            self.away_name = ' '.join(away_info)
            s_home_name, s_away_name = self.home_name, self.away_name

            odds_back['main'][self.home_name] = home_odd
            odds_back['main'][self.away_name] = away_odd
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
                    # Looks like no additional markets in: ' + with_url_back)
                    return False
                try:
                    Website.wait('Correct Score', self.wait2, type_='partial')
                except TimeoutException:
                    log_and_print('Looks like no additional markets expanded: ' + with_url_back)
                    return False
                return True

            def get_odds(market_str_, key_):
                try:
                    self.driver.find_element_by_link_text(market_str_).click()
                    active = Website.get_element_static('dd.active', self.driver, self.wait2)
                except StaleElementReferenceException:
                    active = None
                if active is None:
                    self.driver.get(url_back)
                    Website.wait('additional markets', self.wait2, type_='partial')
                    if not click_additional_market(market_number):
                        return
                    Website.wait(market_str_, self.wait, type_='link')
                    self.driver.find_element_by_link_text(market_str_).click()
                    active = Website.get_element_static('dd.active', self.driver, self.wait2)
                    if active is None:
                        return
                lines = active.text.split('\n')
                self.driver.find_element_by_link_text(market_str_).click()
                try:
                    for line in lines:
                        if line == 'SELECTION WIN':
                            continue
                        info_ = line.split(' ')
                        odd = info_.pop(-1)
                        info_ = squash_string(''.join(info_))
                        if info_ == 'tie':
                            info_ = 'draw'
                        odds_back[key_][info_] = odd
                except Exception as e:
                    log_and_print('DEBUG: {}'.format(str(e)))
                    raise

            if not click_additional_market(market_number):
                return odds_back

            full_text = self.driver.find_element_by_id('pageContent').text.split('\n')
            vs_str = ''
            for s in full_text:
                if ' vs ' in s:
                    vs_str = s.split(' - ')[1]
                    s_home_name, s_away_name = vs_str.split(' vs ')
                    break

            hn, an = s_home_name, s_away_name
            m = {
                'Anytime Goalscorer': 'anytime scorer',
                'Both Teams To Score': 'both score',
                'Correct Score': 'correct score',
                'First Goalscorer': '1st scorer',
                'First Half': 'half time',
                'First Half Both Teams To Score': 'first half both team to score',
                'First Half Correct Score': 'half time score',
                'First Half Odd / Even Goals': 'first half odd even goals',
                hn + ' To Score First Half': 'first half home team to score',
                an + ' To Score First Half': 'first half away team to score',
                'HT/FT Double': 'half full',
            }
            for i in '1', '2', '3', '4', '5':
                m['Handicap {} +{}'.format(hn, i)] = 'handicap home a' + i
                m['Handicap {} -{}'.format(hn, i)] = 'handicap away a' + i
                m['First Half Handicap {} +{}'.format(hn, i)] = 'first half handicap home a' + i
                m['First Half Handicap {} -{}'.format(hn, i)] = 'first half handicap away a' + i
            for i in '0.5', '1.5', '2.5', '3.5', '4.5', '5.5':
                m['Over/Under {} Goals'.format(i)] = 'ad ' + i
            for i in '0.5', '1.5', '2.5', '3.5':
                m['First Half Over/Under {} Goals'.format(i)] = 'first ' + i
                m['First Half {} Over/Under {} Goals'.format(hn, i)] = 'first home ' + i
                m['First Half {} Over/Under {} Goals'.format(an, i)] = 'first away ' + i
                m['{} Over/Under {} Goals'.format(hn, i)] = 'home ad ' + i
                m['{} Over/Under {} Goals'.format(an, i)] = 'away ad ' + i

            for ms, mk in m.items():
                market_str = ms + ' - ' + vs_str
                if market_str in full_text and (g_get_all_markets or mk in lay_markets):
                    get_odds(market_str, mk)

        return odds_back

    @staticmethod
    def merge_back_odds(base_dict, to_merge_dict):
        odds = base_dict
        for item, map_ in to_merge_dict.items():
            for key, value in map_.items():
                if key in odds[item]:
                    odds[item][key] = odds[item][key] + '|' + str(value)
                else:
                    odds[item][key] = value
        return odds

    def thread_get_ladbrokes(self, aws_ip, url, target_markets, lay_markets):
        if len(lay_markets) is 0:
            odds = dict()
        else:
            odds = requests.get(
                'http://{}:5000/get_ladbrokes'.format(aws_ip),
                params={'url': url,
                        'target_markets': target_markets,
                        'lay_markets_str': ','.join(lay_markets).replace(' ', '_')
                        }).json()
        self.save_to(odds, 'ladbrokes_odds_from_thread.pkl', silent=True)

    def get_lay_markets(self, new=False):
        pkl_name = 'lay_markets.pkl'
        if new:
            match_to_markets = dict()
        else:
            with open(os.path.join(gettempdir(), pkl_name), 'rb') as pkl:
                match_to_markets = pickle.load(pkl)

        with open('compare.txt', 'r') as urls_file:
            lines = urls_file.read().splitlines()
        _ = lines.pop(0)  # bet type
        target_markets = lines.pop(0).split(':')[1]

        self.driver.get('https://www.betfair.com.au/exchange/plus/')
        Betfair.login_static(self.driver, self.wait)

        time_it = TimeIt(top=True, bottom=True)
        time_it.reset_top()
        while len(lines) > 0:
            count = 0
            try:
                for l, match_info, _, _, _, url_lay in zip(lines[::6], lines[1::6], lines[2::6],
                                                           lines[3::6], lines[4::6], lines[5::6]):
                    time_it.reset()
                    if new or (match_info not in match_to_markets) \
                            or len(match_to_markets[match_info]) is 0:
                        self.league = l.split(' ')[1]
                        odds_lay, _, = self.get_betfair_odd(url_lay, target_markets)

                        lay_markets = []
                        for key in odds_lay.keys():
                            if len(odds_lay[key]) != 0:
                                lay_markets.append(key)
                        if len(lay_markets) is not 0:
                            match_to_markets[match_info] = lay_markets
                    time_it.log('{} of {} ({})'.format(count, int(len(lines)/5), match_info))
                    count += 1

            except Exception as e:
                log_and_print('Exception: [' + str(e) + ']')
                _, _, eb = sys.exc_info()
                traceback.print_tb(eb)
            finally:
                if self.driver:
                    self.driver.quit()
                    break
        self.save_to(match_to_markets, pkl_name)
        time_it.top_log('get lay markets')

    def scan_match(self, get_ladbrokes, get_crown, get_william, get_betfair,
                   match_info, url_crown, url_lad, url_william, url_lay,
                   use_aws, bet_type, target_markets):
        def get(func, is_get_from_net, is_pickle_it, pickle_name):
            if is_get_from_net == 1:
                odds_ = func()
                if is_pickle_it == 1:
                    self.save_to(odds_, pickle_name)
            else:
                odds_ = self.get_from_pickle(pickle_name)
            return odds_

        def func_get_lad():
            return self.odds_map_to_id(
                self.get_ladbrokes_markets_odd(url_lad, target_markets, lay_markets), 'ladbrokes')

        def func_get_crown():
            return self.odds_map_to_id(
                self.get_crown_markets_odd(url_crown, target_markets, lay_markets), 'crown')

        def func_get_william():
            return self.odds_map_to_id(
                self.get_william_markets_odd(url_william, target_markets, lay_markets), 'william')

        # Production: 01
        # Debug: 11 (read from net and write pickle) then 00 (read from pickle)
        #
        # - Set net to 0 to read pickle
        # - Set pickle to 0 to avoid writing
        # TODO change when necessary
        is_pickle_lad = 0
        is_net_lad = 1

        is_pickle_crown = 0
        is_net_crown = 1

        is_pickle_william = 0
        is_net_william = 1

        is_pickle_betfair = 0
        is_net_betfair = 1

        # get betfair
        odds_lay, odds_betfair, lay_markets = dict(), dict(), []
        if get_betfair:
            if is_net_betfair:
                odds_lay, odds_betfair = self.get_betfair_odd(url_lay, target_markets)
                if is_pickle_betfair:
                    self.save_to(odds_lay, 'hdq_betfair_lay.pkl')
                    self.save_to(odds_betfair, 'hdq_betfair.pkl')
            else:
                odds_lay = self.get_from_pickle('hdq_betfair_lay.pkl')
                odds_betfair = self.get_from_pickle('hdq_betfair.pkl')

            odds_lay = self.odds_map_to_id(odds_lay, is_betfair=True)
            odds_betfair = self.odds_map_to_id(odds_betfair, agent_name='betfair', is_betfair=True)
            for key in odds_lay.keys():
                if len(odds_lay[key]) != 0:
                    lay_markets.append(key)

        # get ladbrokes
        thread_lad, odds_crown, odds_lad, odds_william = None, dict(), dict(), dict()
        if get_ladbrokes and url_lad != '.':
            if use_aws:
                thread_lad = threading.Thread(target=self.thread_get_ladbrokes,
                                              args=('deqing.cf', url_lad,
                                                    target_markets, lay_markets))
                thread_lad.start()
            else:
                odds_lad = get(func_get_lad, is_net_lad, is_pickle_lad, 'hdq_lad.pkl')

        # get william
        if get_william and url_william != '.':
            odds_william = get(func_get_william, is_net_william, is_pickle_william, 'hdq_w.pkl')

        # get crownbet
        if get_crown and url_crown != '.':
            odds_crown = get(func_get_crown, is_net_crown, is_pickle_crown, 'hdq_c.pkl')

        # wait ladbrokes from thread
        if url_lad != '.' and get_ladbrokes and use_aws:
            thread_lad.join()
            odds_lad = self.get_from_pickle('ladbrokes_odds_from_thread.pkl')

        # merge results
        odds_back = dict()
        for d in odds_betfair, odds_crown, odds_william, odds_lad:
            if len(d) is not 0:
                odds_back = self.merge_back_odds(d, odds_back)

        self.generate_max_back_odds(odds_back)
        if False:  # Compare back together?  TODO make it usable
            self.print_back_profits(odds_back, match_info)

        if get_betfair and len(odds_back) is not 0:
            back_urls = url_crown + '\n' + url_lad + '\n' + url_william
            self.compare_with_lay(odds_back, back_urls, url_lay, match_info, bet_type, odds_lay)

    @staticmethod
    def is_qualifying(agent):
        if '(' in agent:
            return agent in ('(C)', '(L)', '(W)')
        else:
            return agent in ('crown', 'ladbrokes', 'william')

    # 'both to score':            {'yes': '1.15 w|1.15 c|1.13 b', 'no': ...} ->
    #            {'yes': '1.13 b|1.15 c,w@|1.15 w|1.15 c|1.13 b', 'no': ...}
    #  first one is max to see if it's over 100, second is targeting at qualifying
    def generate_max_back_odds(self, odds_back):
        for market, d in odds_back.items():
            for key in d.keys():
                texts = d[key].split('|')
                max_odd, max_agent = maxq_odd, maxq_agent = 0, 'N/A'
                for t in texts:
                    odds = t.split(' ')
                    odd, agent = odds[-2], odds[-1]
                    try:
                        odd = float(odd)
                        if odd < 50:
                            if odd >= max_odd:
                                max_agent = agent if odd > max_odd else max_agent + ',' + agent
                                max_odd = odd
                            if odd >= maxq_odd and self.is_qualifying(agent):
                                maxq_agent = agent if odd > maxq_odd else maxq_agent + ',' + agent
                                maxq_odd = odd
                    except:
                        raise
                d[key] = '{} {}|{} {}@{}'.format(max_odd, max_agent, maxq_odd, maxq_agent, d[key])

    def print_back_profits(self, odds_back, match_info):
        def is_odds_valid(odd):
            return float(odd) > 1 and float(odd) > 1.4

        def all_not_qualifying_agents(agents_):
            for a in agents_:
                if self.is_qualifying(a):
                    return False
            return True

        market_names = MarketNames()
        results = []

        match_info += ''
        log_and_print('\n')  # ------- ' + match_info + ' --------')
        
        def set_profit_map(p_, o1, o2, agent1, agent2):
            if is_odds_valid(o1):
                p_['mp'], p_['apay'], p_['bpay'], p_['ap'], p_['bp'] = calc2(o1, o2)
                p_['odd0'], p_['odd1'] = o1, o2
                p_['agent0'], p_['agent1'] = agent1, agent2
            else:
                p_['mp'] = 0

        def set_profit_map3(p_, o1, o2, o3, agent1, agent2, agent3):
            if is_odds_valid(o1):
                p_['mp'], p_['apay'], p_['bpay'], p_['cpay'], p_['ap'], p_['bp'], p_['cp'] = \
                    calc3(o1, o2, o3)
                p_['odd0'], p_['odd1'], p_['odd2'] = o1, o2, o3
                p_['agent0'], p_['agent1'], p_['agent2'] = agent1, agent2, agent3
            else:
                p_['mp'] = 0

        def get_max(size_of_odds):
            m_ = p[0]
            for i_ in range(size_of_odds):
                if 'mp' in p[i_ + 1] and p[i_ + 1]['mp'] > m_['mp']:
                    m_ = p[i_ + 1]
            return m_

        for market, d in odds_back.items():
            keys, odds, agents, q_odds, q_agents = [], [], [], [], []
            if len(d) in (2, 3):
                for key, odd_text in d.items():
                    keys.append(key)

                    best, best_q = odd_text.split('@')[0].split('|')

                    best_odd, best_agent = best.split(' ')
                    odds.append(best_odd)
                    agents.append(self.shorten_agent(best_agent))

                    q_odd, q_agent = best_q.split(' ')
                    q_odds.append(q_odd)
                    q_agents.append(self.shorten_agent(q_agent))

                p = []
                for _ in range(4):
                    p.append(dict())
                
                if len(d) == 2 and market_names.desc[market][0] == 2:
                    set_profit_map(p[0], *odds, *agents)
                    if p[0]['mp'] < 100 and all_not_qualifying_agents(agents):
                        p[0]['mp'] = 0
                        set_profit_map(p[1], q_odds[0], odds[1], q_agents[0], agents[0])
                        set_profit_map(p[2], q_odds[1], odds[0], q_agents[1], agents[1])

                    m = get_max(2)
                    if m['mp'] != 0:
                        results.append([m['mp'], 2, market,
                                        keys[0], float(m['odd0']), m['apay'], m['ap'], m['agent0'],
                                        keys[1], float(m['odd1']), m['bpay'], m['bp'], m['agent1']])

                elif len(d) == 3:
                    set_profit_map3(p[0], *odds, *agents)
                    if p[0]['mp'] < 100 and all_not_qualifying_agents(agents):
                        p[0]['mp'] = 0
                        set_profit_map3(p[1], q_odds[0], odds[1], odds[2], q_agents[0], agents[1], agents[2])  # noqa
                        set_profit_map3(p[2], odds[0], q_odds[1], odds[2], agents[0], q_agents[1], agents[2])  # noqa
                        set_profit_map3(p[3], odds[0], odds[1], q_odds[2], agents[0], agents[1], q_agents[2])  # noqa

                    m = get_max(3)
                    if m['mp'] != 0:
                        results.append([m['mp'], 3, market,
                                        keys[0], float(m['odd0']), m['apay'], m['ap'], m['agent0'],
                                        keys[1], float(m['odd1']), m['bpay'], m['bp'], m['agent1'],
                                        keys[2], float(m['odd2']), m['cpay'], m['cp'], m['agent2']])

        def to100(profit_, spent):
            return (profit_ / spent) * 100

        count = 2
        results.sort(reverse=True)
        for r in results:
            profit = r[0]
            n = r.pop(1)
            if profit != 0:
                global g_print_urls
                if n == 2:
                    profit1 = to100(r[5], r[4])
                    profit2 = to100(r[10], r[9])
                    #if profit1 > -5 and r[3] > 1.5 or profit2 > -5 and r[8] > 1.5:
                    #    g_print_urls = True
                    log_and_print('{:0.2f} {:0.2f} >\t'
                                  '{:0.2f}\t[{}]\t'
                                  '{} {:0.2f} (${})({}){}\t'
                                  '{} {:0.2f} (${})({}){}'.format(profit1, profit2, *r))
                elif n == 3:
                    profit1 = to100(r[5], r[4])
                    profit2 = to100(r[10], r[9])
                    profit3 = to100(r[15], r[14])
                    #if profit1 > -5 and r[3] > 1.5 or profit2 > -5 and r[8] > 1.5 or profit3 > -5 and r[13] > 1.5:  # noqa
                    #    g_print_urls = True
                    log_and_print('{:0.2f} {:0.2f} {:0.2f} >\t'
                                  '{:0.2f}\t[{}]\t'
                                  '{} {:0.2f} (${})({}){}\t'
                                  '{} {:0.2f} (${})({}){}\t'
                                  '{} {:0.2f} (${})({}){}'.format(profit1, profit2, profit3, *r))
                else:
                    log_and_print('DEBUG: wrong result for odds_back')
            count = count - 1
            if count == 0:
                break

    def compare_multiple_sites(self, loop_minutes=0,
                               get_crown=False,  # TODO choose agents to get
                               get_ladbrokes=False,
                               get_william=True,
                               get_betfair=True,
                               worker_id=None):
        with open('compare.txt', 'r') as urls_file:
            lines = urls_file.read().splitlines()

        use_aws = False

        bet_type = lines.pop(0).split(' ')[1]
        target_markets = lines.pop(0).split(':')[1]

        if get_betfair:
            self.driver.get('https://www.betfair.com.au/exchange/plus/')
            Betfair.login_static(self.driver, self.wait)

        if worker_id is not None:
            num_of_processes, child_id = worker_id.split('-')
            num_of_processes, child_id = int(num_of_processes), int(child_id)
            chunk_size = len(lines) // (6 * num_of_processes) * 6
            lines_array = [lines[i:i+chunk_size] for i in list(range(len(lines))[::chunk_size])]
            if len(lines_array[-1]) < chunk_size:
                lines_array[-2] += lines_array[-1]
                lines_array.pop(-1)
            lines = lines_array[child_id]

        while len(lines) > 0:
            log_and_print('_'*100 + ' bet type: ' + bet_type)
            for l, match_info, url_crown, url_lad, url_william, url_lay in \
                    zip(lines[::6], lines[1::6], lines[2::6],
                        lines[3::6], lines[4::6], lines[5::6]):

                self.league = l.split(' ')[1]

                try:
                    self.scan_match(get_ladbrokes, get_crown, get_william, get_betfair,
                                    match_info, url_crown, url_lad, url_william,
                                    url_lay, use_aws, bet_type, target_markets)
                except Exception as e:
                    log_and_print('Exception: [' + str(e) + ']')
                    _, _, eb = sys.exc_info()
                    traceback.print_tb(eb)
            if loop_minutes is 0:
                if self.driver:
                    self.driver.quit()
                break
            else:
                self.count_down(loop_minutes)

    def compare_back_and_lay(self, back_site, loop_minutes):
        file_name = back_site + '.txt'
        if back_site == 'ladbrokes':
            get_func = self.get_ladbrokes_markets_odd
        elif back_site == 'crown':
            get_func = self.get_crown_markets_odd
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
                self.league = l.split(' ')[1]
                odds_lay = self.get_betfair_odd(url_lay, target_markets)
                odds_back = get_func(url_back, target_markets, odds_lay)
                odds_back = self.odds_map_to_id(odds_back, back_site)
                self.compare_with_lay(odds_back, url_back, url_lay, match_info, bet_type, odds_lay)

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
    def shorten_agent(agent):
        def shorten(a_):
            if a_ == 'classicbet':
                return 'C'
            elif a_ == 'ladbrokes':
                return 'L'
            elif a_ == 'william':
                return 'W'
            elif a == 'betfair':
                return 'B'
            else:
                return a_

        agents, res = [], []
        many = ',' in agent
        if many:
            agents = agent.split(',')
        else:
            agents.append(agent)

        for a in agents:
            res.append(shorten(a))

        if many:
            return '(' + ','.join(res) + ')'
        else:
            return '(' + res[0] + ')'

    def add_item_to_results(self, title_, market_, lay_odd_, results_, odds_back_, bet_type_,
                            display_):
        def get_profit(bo):
            if bet_type_ == 'snr':  # SNR
                return self.get_snr_profit(bo, lay_odd_)
            elif 'boost' in bet_type_ or 'q' in bet_type_:  # qualifying
                return (bo / (lay_odd_ - 0.05) * 100) * 0.95 - 100
            else:
                raise 'DEBUG unexpected bet type: ' + bet_type_

        if title_ in odds_back_[market_] and lay_odd_ != '':
            try:
                best, q_best = odds_back_[market_][title_].split('@')[0].split('|')
            except Exception:
                raise
            best_odd, agent = best.split(' ')
            q_odd, q_agent = q_best.split(' ')
            lay_odd_, lay_amount = lay_odd_.split('\n')

            agent = self.shorten_agent(agent)
            q_agent = self.shorten_agent(q_agent)
            back_odd = float(best_odd)
            q_odd = float(q_odd)
            lay_odd_ = float(lay_odd_)
            profit = get_profit(back_odd)
            if profit < 100:
                profit = get_profit(q_odd)
                results_.append([profit, q_odd, q_agent, lay_odd_, lay_amount, title_, display_])
            else:
                results_.append([profit, back_odd, agent, lay_odd_, lay_amount, title_, display_])

    def get_betfair_odd(self, url_lay, target_markets):
        self.driver.set_window_size(width=1920, height=1080)
        self.driver.get(url_lay)

        market_names = MarketNames()
        odds_lay = self.prepare_map_with_target_markets_as_key(market_names, target_markets)
        odds_back = self.prepare_map_with_target_markets_as_key(market_names, target_markets)

        # ------- get main market
        def get_text(b_, css='td.bet-buttons.lay-cell.first-lay-cell'):
            return b_.find_element_by_css_selector(css).text

        def get_back_odd(text):
            back_css = 'td.bet-buttons.back-cell.last-back-cell'
            return real_back_odd(get_text(text, back_css).split('\n')[0])

        bs = Website.get_blocks_static('tr.runner-line', self.driver, self.wait)
        if len(bs) < 3:
            log_and_print('no match info in:\n' + url_lay)
            return odds_lay, odds_back

        self.home_name = get_text(bs[0], 'h3.runner-name')
        self.away_name = get_text(bs[1], 'h3.runner-name')

        odds_back['main'][self.home_name] = get_back_odd(bs[0])
        odds_back['main'][self.away_name] = get_back_odd(bs[1])
        odds_back['main']['Draw'] = get_back_odd(bs[2])

        if 'main' in odds_lay:
            odds_lay['main'][self.home_name] = get_text(bs[0])
            odds_lay['main'][self.away_name] = get_text(bs[1])
            odds_lay['main']['Draw'] = get_text(bs[2])

        m = {
            'Correct Score': 'correct score',
            'Both teams to Score?': 'both score',
            'Half Time/Full Time': 'half full',
            'Half Time': 'half time',
            'First Half Odd / Even Goals': 'first half odd even goals',
            'First Half Correct Score': 'half time score',
            'First Half Both Teams To Score': 'first half both team to score',
            'First Goalscorer': '1st scorer',
            'Anytime Goalscorer': 'anytime scorer',
        }
        for i in '0.5', '1.5', '2.5', '3.5':
            m['First Half Goals ' + i] = 'first ' + i
            m['{} Over/Under {} Goals'.format(self.home_name, i)] = 'home ad ' + i
            m['{} Over/Under {} Goals'.format(self.away_name, i)] = 'away ad ' + i
        for i in range(9):
            j = str(i) + '.5'
            m['Over/Under {} Goals'.format(j)] = 'ad ' + j
        for i in range(6):
            m['{} +{}'.format(self.home_name, i)] = 'handicap home a' + str(i)
            m['{} +{}'.format(self.away_name, i)] = 'handicap away a' + str(i)
        
        def get_odds():
            def get_(css, is_lay, key):
                odds_ = odds_lay if is_lay else odds_back
                btn_ = tr.find_element_by_css_selector(css)
                t_ = btn_.text.strip()
                if t_ != '' and float(t_.split('\n')[0]) < 100:
                    title = squash_string(self.full_name_to_id(div.text))
                    title = title.replace('thedraw', 'draw').replace('draw(ht)', 'draw')
                    odds_[key][title] = t_ if is_lay else real_back_odd(t_)

            blocks = Website.get_blocks_static('div.mini-mv', self.driver, self.wait, check=False)
            for b in blocks:
                m_str = b.find_element_by_css_selector('span.market-name-label').text
                if m_str in m and m[m_str] is not 'main':
                    trs = b.find_elements_by_css_selector('tr.runner-line')
                    for tr in trs:
                        div = tr.find_element_by_css_selector('h3.runner-name')
                        get_('button.back-button', is_lay=False, key=m[m_str])
                        if m[m_str] in odds_lay:
                            get_('button.lay-button', is_lay=True, key=m[m_str])

        # ------- get popular markets
        Website.wait('section.mod-tabs', self.wait)
        get_odds()

        # ------- get other markets
        tabs = self.driver.find_elements_by_css_selector('h4.tab-label')
        for t in tabs:
            if t.text in ('Goals', 'Handicap', 'Half Time', 'Team', 'Player'):
                t.click()
                time.sleep(0.5)
                get_odds()

        return odds_lay, odds_back

    #      market    title
    # odds['main'  ]['tottenham'] = '3.0'
    # odds['ad 0.5']['over0.5goals'] = '1.6'
    def compare_with_lay(self, odds_back, url_back, url_lay, match_info, bet_type, odds_lay):
        results = []
        market_names = MarketNames()

        def pretty(market_short, t_):
            market_desc = market_names.get_desc(market_short)
            full_name = self.title_expand_full_name(t_)
            return '{}: {}'.format(market_desc, full_name)

        for m in odds_back.keys():
            if self.has_value(odds_back, m):
                for title_, b_odd in odds_back[m].items():
                    if title_ in odds_lay[m]:
                        self.add_item_to_results(title_, m, odds_lay[m][title_], results, odds_back,
                                                 bet_type, pretty(m, title_))

        count = 0
        results.sort(reverse=True)
        log_and_print('----------- (' + str(len(results)) + ') ' + match_info + ' -------------')
        if len(results) is 0:
            log_and_print('if this is boost, maybe there is no lay odds in correct score yet')
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
        top_results = 2

        global g_print_urls
        if g_print_urls or results[0][0] >= yellow_profit and results[0][1] < biggest_back:
            #log_and_print(url_back + '\n' + url_lay)
            g_print_urls = False

        for res in results:
            if res[1] >= biggest_back or res[0] < 0 and res[1] < 1.5:
                continue
            # 0 profit, 1 back, 2 agent, 3 lay, 4 lay amount, 5 original item text, 6 pretty display
            msg = '{:0.2f}\t{:0.2f} {}\t{:0.2f} ({})\t{}'.format(
                res[0], res[1], res[2], res[3], res[4], res[6])
            if res[0] >= yellow_profit and res[1] >= 1.95:
                if res[0] >= red_profit:
                    log_and_print(msg, highlight='red')
                else:
                    log_and_print(msg, highlight='yellow')
            else:
                log_and_print(msg)
            count += 1
            if count >= top_results:
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

        url_lay = lines[1]
        self.driver.set_window_size(width=1920, height=1080)
        self.driver.get(url_lay)
        Betfair.login_static(self.driver, self.wait)
        self.driver.get(url_lay)

        Website.get_blocks_static('span.bet-button-price', self.driver, self.wait, check=False)

    def compare_with_race_classicbet(self):
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
        with open(os.path.join(gettempdir(), filename), 'wb') as pkl:
            pickle.dump(obj, pkl)
            if not silent:
                if len(obj) == 0:
                    log_and_print('WARNING: ' + filename + ' will be truncated.')
                else:
                    log_and_print(filename + ' saved.')

    @staticmethod
    def get_from_pickle(filename):
        with open(os.path.join(gettempdir(), filename), 'rb') as pkl:
            return pickle.load(pkl)

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
