"""
TODO
    base_url = 'https://www.odds.com.au/'
    url_spain = base_url + 'soccer/spanish-la-liga/'
    url_italy = base_url + 'soccer/italian-serie-a/'
    url_germany = base_url + 'soccer/bundesliga/'
    url_aus = base_url + 'soccer/a-league/'
    url_eng = base_url + 'soccer/english-premier-league/'

"""

import re
import datetime
import pickle
from colorama import init, Fore, Back, Style
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import time
import requests
import sys, traceback


is_refetch = True
is_get_data = False


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

    def __lt__(self, other):
        return self.home_team < other.home_team

    def display(self):
        msg = '{}\t{}({})({})({})\t{}({})({})({})\t{}({})({})({})\t- {} vs {}\t{}'.format(
            round(self.profit, 2),
            self.odds[0], self.agents[0], self.perts[0], self.earns[0],
            self.odds[1], self.agents[1], self.perts[1], self.earns[1],
            self.odds[2], self.agents[2], self.perts[2], self.earns[2],
            self.home_team, self.away_team, self.time)
        if float(self.profit) > 99.5:
            color_print(msg, background='yellow')
        else:
            print(msg)

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


def color_print(msg, foreground="black", background="white"):
    fground = foreground.upper()
    bground = background.upper()
    style = getattr(Fore, fground) + getattr(Back, bground)
    print(style + msg + Style.RESET_ALL)


def main():
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

    pickles_a = []
    pickles_liga = []

    def merge_matches():
        def get_id(team_name, ids):
            converted_name = ''.join(team_name.lower().split())
            if 'tico' in converted_name:
                converted_name = 'atlmadrid'
            elif 'lacoru' in converted_name:
                converted_name = 'deportivo'

            for name in ids:
                if name in converted_name:
                    return name
            raise ValueError('{}[{}] is not found in the league map!'.format(team_name, converted_name))

        # Keyword --> Display Name
        # Keyword is a string that can be found in all websites after lowercase + whitespace removing
        # need to be 1:1 as it will be used by home+away as matches key
        a_league = {
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
        a_league_ids = list(a_league.keys())
        la_liga = {
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

        la_liga_ids = list(la_liga.keys())

        for pickles, ids, league_map in ((pickles_a, a_league_ids, a_league),
                                         (pickles_liga, la_liga_ids, la_liga)):
            matches = {}  # 用hometeam和awayteam加起来做索引的map
            for p_name in pickles:
                with open(p_name, 'rb') as pkl:
                    pickle_matches = pickle.load(pkl)
                    for pm in pickle_matches:
                        key = get_id(pm.home_team, ids) + get_id(pm.away_team, ids)
                        if key not in matches.keys():
                            m = Match()
                            m.__dict__.update(pm.__dict__)
                            m.odds = list(m.odds)
                            m.home_team = league_map[get_id(pm.home_team, ids)]
                            m.away_team = league_map[get_id(pm.away_team, ids)]
                            matches[key] = m
                        else:
                            m = matches[key]
                            for i in range(3):
                                if pm.odds[i] > m.odds[i]:
                                    m.odds[i] = pm.odds[i]
                                    m.agents[i] = pm.agents[i]

            print('--- From', len(pickles), 'pickles -----')
            for m in sorted(matches.values()):
                m.calculate_best_shot()
                m.display()

    def save_to(obj, filename):
        with open(filename, 'wb') as pkl:
            pickle.dump(obj, pkl)
            if len(obj) == 0:
                print('WARNING:', filename, 'will be truncated.')
            else:
                print(filename, 'saved.')

    def extract(line, regx):
        m = re.search(regx, line)
        return m.group(1) if m else ''

    def get_blocks(css_string):
        wait.until(EC.visibility_of_element_located((By.CSS_SELECTOR, css_string)))
        blocks = driver.find_elements_by_css_selector(css_string)
        return blocks  #TODO
        blocks = []
        for _ in range(10):
            blocks = driver.find_elements_by_css_selector(css_string)
            if len(blocks) is not 0:
                break
            time.sleep(1)
            print('... retrying to get blocks')
        return blocks

    def fetch(website):
        if is_get_data:
            for league in 'a', 'liga':
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
                        print('Exception:', e)
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
        blocks = driver.find_elements_by_css_selector(
            'table.bettype-group.listings.odds.sports.match.soccer')
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

    def fetch_centre(matches):
        blocks = get_blocks('td.brdSports')
        for b in blocks:
            m = Match()
            for _ in range(10):
                try:
                    teams = b.find_elements_by_css_selector('div.sport-event')
                    odds = b.find_elements_by_css_selector('div.clear')
                    m.home_team, m.away_team = teams[0].text, teams[2].text
                    for i in range(3):
                        m.odds[i] = odds[i].text
                        m.agents[i] = 'Centre'
                    break
                except Exception:
                    print('... retrying centrebet')
                    time.sleep(1)
            matches.append(m)

    def fetch_crown(matches):
        blocks = []
        for _ in range(10):
            blocks = driver.find_elements_by_css_selector('div.container-fluid')
            if blocks[0].tag_name == 'div':
                break
            time.sleep(1)

        for b in blocks:
            values = b.text.split('\n')
            if len(values) < 10:
                continue
            m = Match()
            m.home_team, m.away_team = values[4], values[8]
            m.odds = values[5], values[7], values[9]
            m.agents = ['Crown '] * 3
            matches.append(m)

    def fetch_ladbrokes(matches):
        blocks = driver.find_elements_by_css_selector(
            'table.bettype-group.listings.odds.sports.match.soccer')
        for b in blocks:
            m = Match()
            info = b.find_elements_by_css_selector('tr.row')
            m.home_team, m.odds[0] = info[0].text.split('\n')
            m.away_team, m.odds[2] = info[1].text.split('\n')
            m.odds[1] = info[2].text.split('\n')[1]
            m.agents = ['ladbrok'] * 3
            matches.append(m)

    def fetch_palmerbet(matches):
        names = driver.find_elements_by_css_selector('td.nam')
        odds = driver.find_elements_by_css_selector('a.sportproduct')
        names.pop(0)
        for n in names:
            m = Match()
            m.home_team, m.away_team = n.text.split('\n')
            m.odds = odds[0].text, odds[2].text, odds[1].text
            odds = odds[5:]
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
                status = 'in win span' if status == 'wait win' else 'in draw span' if status == 'wait draw' else 'in lose span'
                continue

    def fetch_tab(matches):
        blocks = driver.find_elements_by_css_selector('div.template-item.ng-scope')
        for block in blocks:
            m = Match()
            m.home_team, m.away_team = block.find_element_by_css_selector('span.match-name-text.ng-binding').text.split(' v ')
            odds = block.find_elements_by_css_selector('div.animate-odd.ng-binding.ng-scope')
            for i in range(3):
                m.odds[i] = odds[i].text
                m.agents[i] = 'TAB   '
            matches.append(m)

    def fetch_topbetta(matches):
        blocks = get_blocks('div.head-to-head-event')
        for b in range(len(blocks)):
            m = Match()
            for _ in range(10):
                try:
                    blocks = driver.find_elements_by_css_selector('div.head-to-head-event')
                    teams = blocks[b].find_elements_by_css_selector('div.team-container')
                    odds = blocks[b].find_elements_by_css_selector('button.js_price-button.price')
                    m.home_team = teams[0].text
                    m.away_team = teams[1].text
                    m.odds[0] = odds[0].text
                    m.odds[1] = odds[2].text
                    m.odds[2] = odds[1].text
                    break
                except Exception:
                    print('... retrying topbetta')
                    time.sleep(1)
            m.agents = ['Betta '] * 3
            matches.append(m)

    def fetch_ubet(matches):
        blocks = driver.find_elements_by_css_selector('div.ubet-sub-events-summary')
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
        'enable_a': is_refetch,
        'enable_liga': is_refetch,
        'a_url': 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-27119403-2-18-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=1;anim=1',
        'liga_url': 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-33977144-2-8-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=1;anim=1',
        'fetch': fetch_bet365,
        'use_request': False,
    }

    betstar = {  # bookmarker uses same odds
        'name': 'betstar',
        'enable_a': is_refetch,
        'enable_liga': is_refetch,
        'a_url': 'https://www.betstar.com.au/sports/soccer/39922191-football-australia-australian-a-league/',
        'liga_url': 'https://www.betstar.com.au/sports/soccer/40963090-football-spain-spanish-la-liga/',
        'fetch': fetch_betstar,
        'use_request': False,
    }

    centrebet = {
        'name': 'centrebet',
        'enable_a': is_refetch,
        'enable_liga': is_refetch,
        'a_url': 'http://centrebet.com/#Sports/67166422',
        'liga_url': 'http://centrebet.com/#Sports/15806291',
        'fetch': fetch_centre,
        'use_request': False,
    }

    crownbet = {
        'name': 'crownbet',
        'enable_a': is_refetch,
        'enable_liga': is_refetch,
        'a_url': 'https://crownbet.com.au/sports-betting/soccer/australia/a-league-matches',
        'liga_url': 'https://crownbet.com.au/sports-betting/soccer/spain/spanish-la-liga-matches/',
        'fetch': fetch_crown,
        'use_request': False,
    }

    ladbrokes = {
        'name': 'ladbrokes',
        'enable_a': is_refetch,
        'enable_liga': is_refetch,
        'a_url': 'https://www.ladbrokes.com.au/sports/soccer/39445848-football-australia-australian-a-league/?utm_source=%2Fsports%2Fsoccer%2F35326546-australian-a-league-2017-2018%2F35326546-australian-a-league-2017-2018%2F&utm_medium=sport+banner&utm_campaign=a+league+round+4',
        'liga_url': 'https://www.ladbrokes.com.au/sports/soccer/40962944-football-spain-spanish-la-liga/',
        'fetch': fetch_ladbrokes,
        'use_request': False,
    }

    palmerbet = {
        'name': 'palmerbet',
        'enable_a': is_refetch,
        'enable_liga': is_refetch,
        'a_url': 'https://www.palmerbet.com/sports/soccer/australia-a_league',
        'liga_url': 'https://www.palmerbet.com/sports/soccer/spain-primera-division',
        'fetch': fetch_palmerbet,
        'use_request': False,
    }

    sportsbet = {
        'name': 'sportsbet',
        'enable_a': is_refetch,
        'enable_liga': is_refetch,
        'a_url': 'https://www.sportsbet.com.au/betting/soccer/australia/australian-a-league/ev_type_markets.html',
        'liga_url': 'https://www.sportsbet.com.au/betting/soccer/spain/spanish-la-liga',
        'fetch': fetch_sports,
        'use_request': True,
    }

    tab = {
        'name': 'tab',
        'enable_a': is_refetch,
        'enable_liga': is_refetch,
        'a_url': 'https://www.tab.com.au/sports/betting/Soccer/competitions/A%20League',
        'liga_url': 'https://www.tab.com.au/sports/betting/Soccer/competitions/Spanish%20Primera%20Division',
        'fetch': fetch_tab,
        'use_request': False,
    }

    topbetta = {
        'name': 'topbetta',
        'enable_a': is_refetch,
        'enable_liga': is_refetch,
        'a_url': 'https://www.topbetta.com.au/sports/football/hyundai-a-league-regular-season-151825',
        'liga_url': 'https://www.topbetta.com.au/sports/football/liga-de-futbol-profesional-round-11-151365',
        'fetch': fetch_topbetta,
        'use_request': False,
    }

    ubet = {
        'name': 'ubet',
        'enable_a': is_refetch,
        'enable_liga': is_refetch,
        'a_url': 'https://ubet.com/sports/soccer/australia-a-league/a-league-matches',
        'liga_url': 'https://ubet.com/sports/soccer/spain-la-liga',
        'fetch': fetch_ubet,
        'use_request': False,
    }

    unibet = {
        'name': 'unibet',
        'enable_a': is_refetch,
        'enable_liga': is_refetch,
        'a_url': 'https://www.unibet.com.au/betting#filter/football/australia/a-league',
        'liga_url': 'https://www.unibet.com.au/betting#filter/football/spain/laliga',
        'fetch': fetch_unibet,
        'use_request': False,
    }

    williamhill = {
        'name': 'williamhill',
        'enable_a': is_refetch,
        'enable_liga': is_refetch,
        'a_url': 'https://www.williamhill.com.au/sports/soccer/australia/a-league-matches',
        'liga_url': 'https://www.williamhill.com.au/sports/soccer/europe/spanish-primera-division-matches',
        'fetch': fetch_william,
        'use_request': False,
    }

    websites = (
            bet365,
            betstar,
            centrebet,
            crownbet,
            ladbrokes,
            palmerbet,
            sportsbet,
            tab,
            topbetta,
            ubet,
            unibet,
            williamhill,
    )

    pickles_a = ['a_'+w['name']+'.pkl' for w in websites]
    pickles_liga = ['liga_'+w['name']+'.pkl' for w in websites]

    for w in websites: fetch(w)

    #print_matches()  TODO
    merge_matches()

    if driver is not None:
        driver.quit()


if __name__ == "__main__":
    main()
