"""
TODO
add germany
add france
HOME: do betstar

add every hour

check bluebet
add neds.com.au (not easy to get by css)

    base_url = 'https://www.odds.com.au/'
    url_spain = base_url + 'soccer/spanish-la-liga/'
    url_italy = base_url + 'soccer/italian-serie-a/'
    url_germany = base_url + 'soccer/bundesliga/'
    url_aus = base_url + 'soccer/a-league/'
    url_eng = base_url + 'soccer/english-premier-league/'

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
import sys
import traceback
import logging
from tempfile import gettempdir
import os
from docopt import docopt
import smtplib
from email.mime.text import MIMEText


class WriteToHtmlFile:
    def __init__(self):
        self.file = open('output.html', 'w')
        self.file.write('<html>\n')
        self.title = ''

    def write_line(self, line):
        self.file.write(line + '\n')

    def write_line_in_table(self, line):
        #self.file.write('<div style=\'font-family: "Courier New", Courier, monospace\'>' + line + '</div>\n')  # noqa
        self.file.write('<tr><td>' + line.replace('\t', '</td><td>') + '</td></tr>\n')  # noqa

    def write_highlight_line(self, line):
        #self.file.write('<div style=\'font-family: "Courier New", Courier, monospace; background-color:yellow;\'>' + line + '</div>\n')  # noqa
        self.file.write('<tr><td><div style=\'background-color:yellow;\'>' + line.replace('\t', '</td><td>') + '</div></td></tr>\n')  # noqa
        self.title += line.split()[0] + ' '

    def close(self):
        self.file.write('</html>')
        self.file.close()
        with open('output_title.txt', 'w') as title_file:
            if len(self.title) is 0:
                title_file.write('None')
            else:
                title_file.write('!'*self.title.count(' ') + ' - ' + self.title)


html_file = WriteToHtmlFile()


class Match:
    def __init__(self):
        self.profit = 0
        self.home_team = ''
        self.away_team = ''
        self.time = ''
        self.odds = ['', '', '']
        self.agents = ['', '', '']
        self.perts = ['', '', '']
        self.earns = ['', '', '']
        self.other_agents = [[], [], []]
        self.has_other_agents = False

    def __lt__(self, other):
        return self.home_team < other.home_team

    @staticmethod
    def color_print(msg, foreground="black", background="white"):
        fground = foreground.upper()
        bground = background.upper()
        style = getattr(Fore, fground) + getattr(Back, bground)
        print(style + msg + Style.RESET_ALL)

    def display(self):
        msg = '{}\t{}({})({})({})\t{}({})({})({})\t{}({})({})({})\t- {} vs {}'.format(
            round(self.profit, 2),
            self.odds[0], self.agents[0], self.perts[0], self.earns[0],
            self.odds[1], self.agents[1], self.perts[1], self.earns[1],
            self.odds[2], self.agents[2], self.perts[2], self.earns[2],
            self.home_team, self.away_team)  # , self.time)
        if self.has_other_agents:
            msg += '\t(' + '|'.join([','.join(x) for x in self.other_agents]) + ')'

        if float(self.profit) > 99.5:
            self.color_print(msg, background='yellow')
            html_file.write_highlight_line(msg)
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


class Matches:
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
            'tucuman': 'Atletico Tucuman',
            'banfield': 'Banfield',
            'belgrano': 'Belgrano',
            'boca': 'Boca Juniors',
            'independ': 'CA Independiente',
            'corodoba': 'CA Talleres de Cordoba',
            'tigre': 'CA Tigre',
            'chacarita': 'Chacarita Juniors',
            'colon': 'Colon',
            'justicia': 'Defensa Justicia',
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
            'sarsfield': 'Velez Sarsfield'
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
        if 'tico' in converted_name:
            converted_name = 'atlmadrid'
        elif 'lacoru' in converted_name:
            converted_name = 'deportivo'
        elif 'mancity' == converted_name:
            converted_name = 'manchestercity'
        elif 'manutd' == converted_name or 'manunited' == converted_name:
            converted_name = 'manchesterunited'
        elif 'cpalace' == converted_name:
            converted_name = 'crystal'

        for name in keys:
            if name in converted_name:
                return name
        raise ValueError('{}[{}] is not found in the map of {}!'.format(
            team_name, converted_name, league_name))

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

    def merge_and_print(self):
        empty_count = 0
        for pickles, keys, league_map, league_name in \
                ((self.pickles_a, self.a_league_keys, self.a_league_map, 'Australia League'),
                 (self.pickles_arg, self.arg_keys, self.arg_map, 'Argentina Superliga'),
                 (self.pickles_eng, self.eng_keys, self.eng_map, 'English Premier League'),
                 (self.pickles_ita, self.ita_keys, self.ita_map, 'Italian Serie A'),
                 (self.pickles_liga, self.la_liga_keys, self.la_liga_map, 'Spanish La Liga'),):
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
                            key = self.get_id(pm.home_team, keys, league_name) + \
                                  self.get_id(pm.away_team, keys, league_name)
                            if key not in matches.keys():
                                m = Match()
                                m.__dict__.update(pm.__dict__)
                                m.odds = list(m.odds)
                                m.home_team = league_map[self.get_id(pm.home_team, keys, league_name)]
                                m.away_team = league_map[self.get_id(pm.away_team, keys, league_name)]
                                matches[key] = m
                            else:
                                m = matches[key]
                                for i in range(3):
                                    if pm.odds[i] > m.odds[i]:
                                        m.odds[i] = pm.odds[i]
                                        m.agents[i] = pm.agents[i]
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
                    m.display()
                html_file.write_line('</table>')

        with open('output_empty_pickles.txt', 'w') as empty_count_file:
            empty_count_file.write('({} empty pickles)'.format(empty_count))


def main():
    """Punter command-line interface.

    Usage:
      punter.py <websites> [options]

    Options:
      --all               Get all leagues
      --a                 Get A-league
      --arg               Get Argentina league
      --eng               Get EPL
      --ita               Get Italy league
      --liga              Get La Liga
      --get-only          Don't merge and print matches
      --print-only        Don't get latest odds, just print out based on saved odds
      --recalculate       Don't get latest odds, just print out based on saved all odds
      --send-email-api    Send email by MailGun's restful api
      --send-email-smtp   Send email by SMTP (note: not working in GCE)

    Example:
      punter.py luxbet,crownbet --a
      punter.py all --eng
    """
    args = docopt(str(main.__doc__))
    is_get_data = not args['--print-only'] and not args['--recalculate']
    is_get_a = args['--a']
    is_get_arg = args['--arg']
    is_get_eng = args['--eng']
    is_get_ita = args['--ita']
    is_get_liga = args['--liga']

    driver = None
    use_chrome = True
    if is_get_data:
        if use_chrome:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            driver = webdriver.Chrome(chrome_options=chrome_options)
            driver.implicitly_wait(10)
            wait = WebDriverWait(driver, 10)
        else:
            driver = webdriver.PhantomJS()

    def save_to(obj, filename):
        file = os.path.join(gettempdir(), filename)
        with open(file, 'wb') as pkl:
            pickle.dump(obj, pkl)
            if len(obj) == 0:
                print('WARNING:', filename, 'will be truncated.')
            else:
                print(filename, 'saved.')

    def send_email_by_restful_api():
        with open('api.key', 'r') as apifile, \
                open('output.html', 'r') as file, \
                open('output_title.txt', 'r') as title_file, \
                open('output_empty_pickles.txt', 'r') as empty_pickles_file:
            api_key = apifile.read()
            requests.post(
                "https://api.mailgun.net/v3/sandbox2923860546b04b2cbbc985925f26535f.mailgun.org/messages",  # noqa
                auth=("api", api_key),
                data={
                    "from": "Mailgun Sandbox <postmaster@sandbox2923860546b04b2cbbc985925f26535f.mailgun.org>",  # noqa
                    "to": "Deqing Huang <khingblue@gmail.com>",
                    "subject": title_file.read() + ' ' + empty_pickles_file.read(),
                    'html': file.read()})

    def send_email_by_smtp():
        with open('login.name', 'r') as login_name_file, \
                open('login.pwd', 'r') as login_pwd_file, \
                open('output.html', 'r') as file:
            msg = MIMEText(file.read())
            msg['Subject'] = "GCE"
            msg['From'] = "Mailgun Sandbox <postmaster@sandbox2923860546b04b2cbbc985925f26535f.mailgun.org>"  # noqa
            msg['To'] = "Deqing Huang <khingblue@gmail.com>"

            login_name = login_name_file.read()
            login_pwd = login_pwd_file.read()
            s = smtplib.SMTP('smtp.mailgun.org', 2525)
            s.login(login_name, login_pwd)
            s.sendmail(msg['From'], msg['To'], msg.as_string())
            s.quit()

    def extract(line, regx):
        m = re.search(regx, line)
        return m.group(1) if m else ''

    def get_blocks(css_string):
        try:
            wait.until(expected_conditions.visibility_of_element_located((By.CSS_SELECTOR, css_string)))  # noqa
        except TimeoutException:
            print('[{}] not found'.format(css_string))
            return []
        blocks = driver.find_elements_by_css_selector(css_string)
        return blocks

    def fetch_and_save_to_pickle(website):
        for league in 'a', 'arg', 'eng', 'ita', 'liga':
            if website['enable_'+league]:
                pkl_name = league + '_' + website['name'] + '.pkl'
                matches = []
                try:
                    if website['use_request']:
                        website['fetch'](matches, website[league+'_url'])
                    else:
                        driver.get(website[league+'_url'])
                        time.sleep(2)
                        website['fetch'](matches)
                    save_to(matches, pkl_name)
                except Exception as e:
                    logging.exception(e)
                    _, _, eb = sys.exc_info()
                    traceback.print_tb(eb)
                    save_to([], pkl_name)

    def fetch_bet365(matches):
        blocks = get_blocks('div.podEventRow')
        for b in blocks:
            names = b.find_elements_by_css_selector('div.ippg-Market_CompetitorName')
            odds = b.find_elements_by_css_selector('span.ippg-Market_Odds')
            match = Match()
            match.home_team, match.away_team = names[0].text, names[1].text
            for i in range(3):
                match.odds[i] = odds[i].text
                match.agents[i] = 'Bet365'
            matches.append(match)

    def fetch_betstar(matches):
        blocks = get_blocks('table.bettype-group.listings.odds.sports.match.soccer')
        for b in blocks:
            info = b.find_elements_by_css_selector('tr.row')
            if len(info) < 3:
                continue
            m = Match()
            m.home_team, m.odds[0] = info[0].text.split('\n')
            m.away_team, m.odds[2] = info[1].text.split('\n')
            m.odds[1] = info[2].text.split('\n')[1]
            m.agents = ['Betstar'] * 3
            matches.append(m)

    def fetch_crown(matches):
        blocks = []
        for _ in range(10):
            blocks = get_blocks('div.container-fluid')
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
            m.agents = ['Crown '] * 3
            matches.append(m)

    def fetch_ladbrokes(matches):
        blocks = get_blocks('table.bettype-group.listings.odds.sports.match.soccer')
        for b in blocks:
            if 'Footy Freaks' in b.text:
                continue
            m = Match()
            info = b.find_elements_by_css_selector('tr.row')
            m.home_team, m.odds[0] = info[0].text.split('\n')
            m.away_team, m.odds[2] = info[1].text.split('\n')
            m.odds[1] = info[2].text.split('\n')[1]
            m.agents = ['ladbrok'] * 3
            matches.append(m)

    def fetch_luxbet(matches):
        blocks = get_blocks('tr.asian_display_row')
        for b in blocks:
            m = Match()
            teams = b.find_elements_by_css_selector('div.bcg_asian_selection_name')
            m.home_team, m.away_team = teams[0].text, teams[2].text
            odds = b.find_element_by_css_selector('td.asian_market_cell.market_type_template_12')
            m.odds[0], m.odds[1], m.odds[2] = odds.text.split('\n')
            for i in range(3):
                m.odds[i] = m.odds[i].strip()
            m.agents = ['luxbet'] * 3
            matches.append(m)

    def fetch_madbookie(matches):
        blocks = driver.find_elements_by_css_selector('table.MarketTable.MatchMarket')
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
            m.agents = ['madbook'] * 3
            matches.append(m)

    def fetch_palmerbet(matches):
        names = driver.find_elements_by_css_selector('td.nam')
        odds = driver.find_elements_by_css_selector('a.sportproduct')
        show_all = driver.find_elements_by_css_selector('td.show-all.last')
        if len(names) is 0:
            return
        names.pop(0)
        for n in names:
            m = Match()
            m.home_team, m.away_team = n.text.split('\n')
            m.odds = odds[0].text, odds[2].text, odds[1].text
            odds = odds[3:] if len(show_all[0].text) is 0 else odds[5:]
            show_all = show_all[1:]
            m.agents = ['Palmer '] * 3
            matches.append(m)

    def fetch_sports(matches, url):
        content = requests.get(url).text.split('\n')
        status = None
        team_name_r = '<span class="team-name.*>(.+)</span>'
        m = Match()
        for line in content:
            if status is None and '<div class="price-link ' in line:
                status = 'wait home team'
                continue

            if '<span class="team-name' in line:
                if status == 'wait home team':
                    m.home_team = extract(line, team_name_r)
                    status = 'wait win'
                elif status == 'wait away team':
                    m.away_team = extract(line, team_name_r)
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
                m.agents = ['Sports'] * 3
                matches.append(m)
                m = Match()
                continue

            if status is not None and '<span class="price-val' in line:
                status = 'in win span' if status == 'wait win' else 'in draw span' \
                    if status == 'wait draw' else 'in lose span'
                continue

    def fetch_tab(matches):
        blocks = get_blocks('div.template-item.ng-scope')
        for block in blocks:
            m = Match()
            m.home_team, m.away_team = block.find_element_by_css_selector(
                'span.match-name-text.ng-binding').text.split(' v ')
            odds = block.find_elements_by_css_selector('div.animate-odd.ng-binding.ng-scope')
            for i in range(3):
                m.odds[i] = odds[i].text
                m.agents[i] = 'TAB   '
            matches.append(m)

    def fetch_topbetta(matches):
        blocks = get_blocks('div.head-to-head-event')
        for b in range(len(blocks)):
            m = Match()
            teams = blocks[b].find_elements_by_css_selector('div.team-container')
            odds = blocks[b].find_elements_by_css_selector('button.js_price-button.price')
            m.home_team = teams[0].text
            m.away_team = teams[1].text
            m.odds[0] = odds[0].text
            m.odds[1] = odds[2].text
            m.odds[2] = odds[1].text
            m.agents = ['Betta '] * 3
            matches.append(m)

    def fetch_ubet(matches):
        blocks = get_blocks('div.ubet-sub-events-summary')
        for b in blocks:
            odds = b.find_elements_by_css_selector('div.ubet-offer-win-only')
            match = Match()
            m = []
            for i in range(3):
                m.append(odds[i].text.split('\n'))
                match.odds[i] = m[i][1].replace('LIVE ', '')
                match.agents[i] = 'UBET  '
            if 'SUSPENDED' in match.odds[0]:
                continue
            match.home_team = m[0][0]
            match.away_team = m[2][0]
            matches.append(match)

    def fetch_unibet(matches):
        blocks = get_blocks('div.KambiBC-event-item__event-wrapper')
        for b in blocks:
            teams = b.find_elements_by_css_selector('div.KambiBC-event-participants__name')
            odds = b.find_elements_by_css_selector('span.KambiBC-mod-outcome__odds')
            m = Match()
            m.home_team, m.away_team = teams[0].text, teams[1].text
            for i in range(3):
                m.odds[i] = odds[i].text
                m.agents[i] = 'Unibet'
            matches.append(m)

    def fetch_william(matches):
        if 'rimera' in driver.current_url and \
           'rimera' not in driver.find_elements_by_css_selector('div.Collapse_root_3H1.FilterList_menu_3g7')[0].text:  # noqa
            return  # La Liga is removed
        blocks = driver.find_elements_by_css_selector('div.EventBlock_root_1Pn')
        for b in blocks:
            names = b.find_elements_by_css_selector('span.SoccerListing_name_2g4')
            odds = b.find_elements_by_css_selector('span.BetButton_display_3ty')
            match = Match()
            match.home_team, match.away_team = names[0].text, names[2].text
            for i in range(3):
                match.odds[i] = odds[i].text
                match.agents[i] = 'Wiliam'
            matches.append(match)

    bet365 = {
        'name': 'bet365',
        'enable_a': is_get_a,
        'enable_arg': is_get_arg,
        'enable_eng': is_get_eng,
        'enable_ita': is_get_ita,
        'enable_liga': is_get_liga,
        'a_url': 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-27119403-2-18-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=1;anim=1',  # noqa
        'arg_url': 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-34240206-2-12-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=30;anim=1',  # noqa
        'eng_url': 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-33577327-2-1-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=30;anim=1',  # noqa
        'ita_url': 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-34031004-2-6-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=30;anim=1',  # noqa
        'liga_url': 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-33977144-2-8-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=1;anim=1',  # noqa
        'fetch': fetch_bet365,
        'use_request': False,
    }

    betstar = {  # bookmarker uses same odds
        'name': 'betstar',
        'enable_a': is_get_a,
        'enable_arg': False,  # is_get_arg,
        'enable_eng': is_get_eng,
        'enable_ita': False,  # not yet
        'enable_liga': is_get_liga,
        'a_url': 'https://www.betstar.com.au/sports/soccer/39922191-football-australia-australian-a-league/',  # noqa
        'eng_url': 'https://www.betstar.com.au/sports/soccer/41388947-football-england-premier-league/',  # noqa
        'liga_url': 'https://www.betstar.com.au/sports/soccer/40963090-football-spain-spanish-la-liga/',  # noqa
        'fetch': fetch_betstar,
        'use_request': False,
    }

    crownbet = {
        'name': 'crownbet',
        'enable_a': is_get_a,
        'enable_arg': is_get_arg,
        'enable_eng': is_get_eng,
        'enable_ita': is_get_ita,
        'enable_liga': is_get_liga,
        'a_url': 'https://crownbet.com.au/sports-betting/soccer/australia/a-league-matches',
        'arg_url': 'https://crownbet.com.au/sports-betting/soccer/americas/argentina-primera-division-matches',  # noqa
        'eng_url': 'https://crownbet.com.au/sports-betting/soccer/united-kingdom/english-premier-league-matches',  # noqa
        'ita_url': 'https://crownbet.com.au/sports-betting/soccer/italy/italian-serie-a-matches/',
        'liga_url': 'https://crownbet.com.au/sports-betting/soccer/spain/spanish-la-liga-matches/',
        'fetch': fetch_crown,
        'use_request': False,
    }

    ladbrokes = {
        'name': 'ladbrokes',
        'enable_a': is_get_a,
        'enable_arg': is_get_arg,
        'enable_eng': is_get_eng,
        'enable_ita': is_get_ita,
        'enable_liga': is_get_liga,
        'a_url': 'https://www.ladbrokes.com.au/sports/soccer/39445848-football-australia-australian-a-league/?utm_source=%2Fsports%2Fsoccer%2F35326546-australian-a-league-2017-2018%2F35326546-australian-a-league-2017-2018%2F&utm_medium=sport+banner&utm_campaign=a+league+round+4',  # noqa
        'arg_url': 'https://www.ladbrokes.com.au/sports/soccer/43008934-football-argentina-argentinian-primera-division/',  # noqa
        'eng_url': 'https://www.ladbrokes.com.au/sports/soccer/41388947-football-england-premier-league/',  # noqa
        'ita_url': 'https://www.ladbrokes.com.au/sports/soccer/42212441-football-italy-italian-serie-a/',   # noqa
        'liga_url': 'https://www.ladbrokes.com.au/sports/soccer/40962944-football-spain-spanish-la-liga/',  # noqa
        'fetch': fetch_ladbrokes,
        'use_request': False,
    }

    luxbet = {
        'name': 'luxbet',
        'enable_a': is_get_a,
        'enable_arg': is_get_arg,
        'enable_eng': is_get_eng,
        'enable_ita': is_get_ita,
        'enable_liga': is_get_liga,
        'a_url': 'https://www.luxbet.com/?cPath=596&event_id=ALL',
        'arg_url': 'https://www.luxbet.com/?cPath=6278&event_id=ALL',
        'eng_url': 'https://www.luxbet.com/?cPath=616&event_id=ALL',
        'ita_url': 'https://www.luxbet.com/?cPath=1172&event_id=ALL',
        'liga_url': 'https://www.luxbet.com/?cPath=931&event_id=ALL',
        'fetch': fetch_luxbet,
        'use_request': False
    }

    madbookie = {
        'name': 'madbookie',
        'enable_a': is_get_a,
        'enable_arg': is_get_arg,
        'enable_eng': is_get_eng,
        'enable_ita': is_get_ita,
        'enable_liga': is_get_liga,
        'a_url': 'https://www.madbookie.com.au/Sport/Soccer/Australian_A-League/Matches',
        'arg_url': 'https://www.madbookie.com.au/Sport/Soccer/Argentinian_Primera_Division/Matches',
        'eng_url': 'https://www.madbookie.com.au/Sport/Soccer/English_Premier_League/Matches',
        'ita_url': 'https://www.madbookie.com.au/Sport/Soccer/Italian_Serie_A/Matches',
        'liga_url': 'https://www.madbookie.com.au/Sport/Soccer/Spanish_La_Liga/Matches',
        'fetch': fetch_madbookie,
        'use_request': False,
    }

    palmerbet = {
        'name': 'palmerbet',
        'enable_a': is_get_a,
        'enable_arg': is_get_arg,
        'enable_eng': is_get_eng,
        'enable_ita': is_get_ita,
        'enable_liga': is_get_liga,
        'a_url': 'https://www.palmerbet.com/sports/soccer/australia-a_league',
        'arg_url': 'https://www.palmerbet.com/sports/soccer/argentina-primera-división',
        'eng_url': 'https://www.palmerbet.com/sports/soccer/england-premier-league',
        'ita_url': 'https://www.palmerbet.com/sports/soccer/italy-serie-a',
        'liga_url': 'https://www.palmerbet.com/sports/soccer/spain-primera-division',
        'fetch': fetch_palmerbet,
        'use_request': False,
    }

    sportsbet = {
        'name': 'sportsbet',
        'enable_a': is_get_a,
        'enable_arg': is_get_arg,
        'enable_eng': is_get_eng,
        'enable_ita': is_get_ita,
        'enable_liga': is_get_liga,
        'a_url': 'https://www.sportsbet.com.au/betting/soccer/australia/australian-a-league/ev_type_markets.html',  # noqa
        'arg_url': 'https://www.sportsbet.com.au/betting/soccer/americas/argentinian-primera-division',  # noqa
        'eng_url': 'https://www.sportsbet.com.au/betting/soccer/united-kingdom/english-premier-league',  # noqa
        'ita_url': 'https://www.sportsbet.com.au/betting/soccer/italy/italian-serie-a',
        'liga_url': 'https://www.sportsbet.com.au/betting/soccer/spain/spanish-la-liga',
        'fetch': fetch_sports,
        'use_request': True,
    }

    tab = {
        'name': 'tab',
        'enable_a': is_get_a,
        'enable_arg': False,  # none
        'enable_eng': is_get_eng,
        'enable_ita': is_get_ita,
        'enable_liga': is_get_liga,
        'a_url': 'https://www.tab.com.au/sports/betting/Soccer/competitions/A%20League',
        'eng_url': 'https://www.tab.com.au/sports/betting/Soccer/competitions/English%20Premier%20League',  # noqa
        'ita_url': 'https://www.tab.com.au/sports/betting/Soccer/competitions/Italian%20Serie%20A',
        'liga_url': 'https://www.tab.com.au/sports/betting/Soccer/competitions/Spanish%20Primera%20Division',  # noqa
        'fetch': fetch_tab,
        'use_request': False,
    }

    topbetta = {
        'name': 'topbetta',
        'enable_a': is_get_a,
        'enable_arg': False,  # none
        'enable_eng': is_get_eng,
        'enable_ita': is_get_ita,
        'enable_liga': is_get_liga,
        'a_url': 'https://www.topbetta.com.au/sports/football/hyundai-a-league-regular-season-151825',  # noqa
        'eng_url': 'https://www.topbetta.com.au/sports/football/england-premier-league-season-146759',  # noqa
        'ita_url': 'https://www.topbetta.com.au/sports/football/serie-a-tim-round-14-153149',
        'liga_url': 'https://www.topbetta.com.au/sports/football/liga-de-futbol-profesional-season-151365',  # noqa
        'fetch': fetch_topbetta,
        'use_request': False,
    }

    ubet = {
        'name': 'ubet',
        'enable_a': is_get_a,
        'enable_arg': is_get_arg,
        'enable_eng': is_get_eng,
        'enable_ita': is_get_ita,
        'enable_liga': is_get_liga,
        'a_url': 'https://ubet.com/sports/soccer/australia-a-league/a-league-matches',
        'arg_url': 'https://ubet.com/sports/soccer/argentina-primera-division/arg-primera-matches',
        'eng_url': 'https://ubet.com/sports/soccer/england-premier-league/premier-league-matches',
        'ita_url': 'https://ubet.com/sports/soccer/italy-serie-a',
        'liga_url': 'https://ubet.com/sports/soccer/spain-la-liga',
        'fetch': fetch_ubet,
        'use_request': False,
    }

    unibet = {
        'name': 'unibet',
        'enable_a': is_get_a,
        'enable_arg': False,  # none
        'enable_eng': is_get_eng,
        'enable_ita': False,  # none
        'enable_liga': is_get_liga,
        'a_url': 'https://www.unibet.com.au/betting#filter/football/australia/a-league',
        'eng_url': 'https://www.unibet.com.au/betting#filter/football/england/premier_league',
        'liga_url': 'https://www.unibet.com.au/betting#filter/football/spain/laliga',
        'fetch': fetch_unibet,
        'use_request': False,
    }

    williamhill = {
        'name': 'williamhill',
        'enable_a': is_get_a,
        'enable_arg': is_get_arg,
        'enable_eng': is_get_eng,
        'enable_ita': is_get_ita,
        'enable_liga': is_get_liga,
        'a_url': 'https://www.williamhill.com.au/sports/soccer/australia/a-league-matches',
        'arg_url': 'https://www.williamhill.com.au/sports/soccer/americas/argentine-primera-division-matches',  # noqa
        'eng_url': 'https://www.williamhill.com.au/sports/soccer/british-irish/english-premier-league-matches',  # noqa
        'ita_url': 'https://www.williamhill.com.au/sports/soccer/europe/italian-serie-a-matches',  # noqa
        'liga_url': 'https://www.williamhill.com.au/sports/soccer/europe/spanish-primera-division-matches',  # noqa
        'fetch': fetch_william,
        'use_request': False,
    }

    website_map = {
        'bet365': bet365,
        'betstar': betstar,
        'crownbet': crownbet,
        'ladbrokes': ladbrokes,
        'luxbet': luxbet,
        'madbookie': madbookie,
        'palmerbet': palmerbet,
        'sportsbet': sportsbet,
        'tab': tab,
        'topbetta': topbetta,
        'ubet': ubet,
        'unibet': unibet,
        'williamhill': williamhill,
    }

    websites = []
    if args['--recalculate'] or args['<websites>'] == 'all':
        websites = list(website_map.values())
    else:
        for site in args['<websites>'].split(','):
            websites.append(website_map[site])

    def set_pickles(league_prefix):
        return [league_prefix+'_' + w['name'] + '.pkl'
                for w in websites if w['enable_'+league_prefix]] \
            if args['--'+league_prefix] else []
    pickles_a = set_pickles('a')
    pickles_arg = set_pickles('arg')
    pickles_eng = set_pickles('eng')
    pickles_ita = set_pickles('ita')
    pickles_liga = set_pickles('liga')
    ms = Matches(pickles_a, pickles_arg, pickles_eng, pickles_ita, pickles_liga)

    if is_get_data:
        for w in websites:
            fetch_and_save_to_pickle(w)

    if not args['--get-only']:
        ms.merge_and_print()

    #ms.print_each_match()

    if driver is not None:
        driver.quit()

    html_file.close()
    if args['--send-email-api']:
        send_email_by_restful_api()
    if args['--send-email-smtp']:
        send_email_by_smtp()


if __name__ == "__main__":
    main()
