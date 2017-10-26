"""
TODO
    base_url = 'https://www.odds.com.au/'
    url_spain = base_url + 'soccer/spanish-la-liga/'
    url_italy = base_url + 'soccer/italian-serie-a/'
    url_germany = base_url + 'soccer/bundesliga/'
    url_aus = base_url + 'soccer/a-league/'
    url_eng = base_url + 'soccer/english-premier-league/'

93.1	2.45(TAB)(38)  3.60(TAB)(26)  2.60(TAB)(36)	- Adelaide Utd vs MelbourneVictory
92.8	1.60(TAB)(58)  4.25(TAB)(22)  4.75(TAB)(20)	- Melbourne City vs Wellington
91.8	1.87(TAB)(50)  3.40(TAB)(27)  4.00(TAB)(23)	- Sydney FC vs Western Sydney
93.5	2.35(TAB)(40)  3.60(TAB)(26)  2.75(TAB)(34)	- Brisbane Roar vs Newcastle Jets
91.8	1.70(TAB)(54)  3.75(TAB)(25)  4.50(TAB)(21)	- Perth Glory vs Central Coast

93.6	2.60(UBET)(36)  3.40(UBET)(28)  2.60(UBET)(36)	- ADELAIDE UTD vs MELBOURNE VICTORY
93.0	1.50(UBET)(62)  4.55(UBET)(21)  5.75(UBET)(17)	- MELBOURNE CITY vs WELLINGTON PHOENIX
92.56	1.78(UBET)(52)  3.70(UBET)(26)  4.40(UBET)(22)	- SYDNEY FC vs WESTERN SYDNEY
92.8	2.25(UBET)(42)  3.65(UBET)(26)  2.90(UBET)(32)	- BRISBANE ROAR vs NEWCASTLE JETS
93.5	1.63(UBET)(58)  4.25(UBET)(22)  4.75(UBET)(20)	- PERTH GLORY vs CENTRAL COAST
"""

import re
import datetime
import pickle
from colorama import init, Fore, Back, Style
from selenium.webdriver.chrome.options import Options
from selenium import webdriver
import time
import requests

bet365_url = 'https://mobile.bet365.com.au/#type=Coupon;key=1-1-13-27119403-2-18-0-0-1-0-0-4100-0-0-1-0-0-0-0-0-0;ip=0;lng=1;anim=1'
betstar_url = 'https://www.betstar.com.au/sports/soccer/39922191-football-australia-australian-a-league/'
# bookmaker has same odds as above: 'https://www.bookmaker.com.au/sports/soccer/39922191-football-australia-australian-a-league/'
centre_url = 'http://centrebet.com/#Sports/67166422'
crown_url = 'https://crownbet.com.au/sports-betting/soccer/australia/a-league-matches'
ladbrokes_url = 'https://www.ladbrokes.com.au/sports/soccer/39445848-football-australia-australian-a-league/?utm_source=%2Fsports%2Fsoccer%2F35326546-australian-a-league-2017-2018%2F35326546-australian-a-league-2017-2018%2F&utm_medium=sport+banner&utm_campaign=a+league+round+4'
palmerbet_url = 'https://www.palmerbet.com/sports/soccer/australia-a_league'
sports_url = 'https://www.sportsbet.com.au/betting/soccer/australia/australian-a-league/ev_type_markets.html'
tab_url = 'https://www.tab.com.au/sports/betting/Soccer/competitions/A%20League'
topbetta_url = 'https://www.topbetta.com.au/sports/football/hyundai-a-league-regular-season-151825'
ubet_url = 'https://ubet.com/sports/soccer/australia-a-league/a-league-matches'
unibet_url = 'https://www.unibet.com.au/betting#filter/football/australia/a-league'
william_url = 'https://www.williamhill.com.au/sports/soccer/australia/a-league-matches'

pickles = ['a_league_betstar.pkl']
if True:
    pickles = ['a_league_tab.pkl',
               'a_league_ubet.pkl',
               'a_league_bet365.pkl',
               'a_league_william.pkl',
               'a_league_crown.pkl',
               'a_league_sports.pkl',
               'a_league_centre.pkl',
               'a_league_unibet.pkl',
               'a_league_topbetta.pkl',
               'a_league_ladbrokes.pkl',
               'a_league_palmerbet.pkl',
               'a_league_betstar.pkl',
               ]

fetch_a_league = True
fetch_tab = fetch_ubet = fetch_bet365 = fetch_william = fetch_crownbet = fetch_sportsbet = \
    fetch_centrebet = fetch_unibet = fetch_topbetta = fetch_ladbrokes = fetch_palmerbet = True
fetch_betstar = True
fetch_data = False


class Match:
    def __init__(self):
        self.profit = 0
        self.home_team = ''
        self.away_team = ''
        self.time = ''
        self.odds = ['', '', '']
        self.agents = ['', '', '']
        self.perts = ['', '', '']

    def __lt__(self, other):
        return self.home_team < other.home_team

    def display(self):
        msg = '{}\t{}({})({})  {}({})({})  {}({})({})\t- {} vs {}\t{}'.format(
            round(self.profit, 2),
            self.odds[0], self.agents[0], self.perts[0],
            self.odds[1], self.agents[1], self.perts[1],
            self.odds[2], self.agents[2], self.perts[2],
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


def color_print(msg, foreground="black", background="white"):
    fground = foreground.upper()
    bground = background.upper()
    style = getattr(Fore, fground) + getattr(Back, bground)
    print(style + msg + Style.RESET_ALL)


def merge_matches():
    def get_id(team_name):
        converted_name = ''.join(team_name.lower().split())
        for name in a_league_ids:
            if name in converted_name:
                return name
        raise ValueError(team_name + ' is not found in A league!')

    # Stores Keyword and Display Name
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

    a_matches = {}  # 用hometeam和awayteam加起来做索引的map

    for p_name in pickles:
        with open(p_name, 'rb') as pkl:
            matches = pickle.load(pkl)
            for m in matches:
                key = get_id(m.home_team) + get_id(m.away_team)
                if key not in a_matches.keys():
                    a_match = Match()
                    a_match.__dict__.update(m.__dict__)
                    a_match.home_team = a_league[get_id(m.home_team)]
                    a_match.away_team = a_league[get_id(m.away_team)]
                    a_matches[key] = a_match
                else:
                    a_match = a_matches[key]
                    for i in range(3):
                        if m.odds[i] > a_match.odds[i]:
                            a_match.odds[i] = m.odds[i]
                            a_match.agents[i] = m.agents[i]

    print('--- From', len(pickles), 'pickles -----')
    for m in sorted(a_matches.values()):
        m.calculate_best_shot()
        m.display()


def main():
    def save_to(obj, filename):
        if len(obj) == 0:
            print('WARNING: nothing will be saved to:', filename)
        else:
            with open(filename, 'wb') as pkl:
                pickle.dump(obj, pkl)
                print(filename, 'saved.')

    def extract(line, regx):
        m = re.search(regx, line)
        return m.group(1) if m else ''

    def fetch(if_fetch, driver, url, pkl_name, func):
        if fetch_data and if_fetch:
            try:
                matches = []
                driver.get(url)
                func(driver, matches)
                save_to(matches, pkl_name)
            except Exception as e:
                print(e)  # TODO: print it and ignore it

    driver = None
    use_chrome = True
    if fetch_data:
        if use_chrome:
            chrome_options = Options()
            chrome_options.add_argument("--headless")
            driver = webdriver.Chrome(chrome_options=chrome_options)
        else:
            driver = webdriver.PhantomJS()

    # -------------------------- A-League
    def fetch_tab(driver, matches):
        blocks = driver.find_elements_by_css_selector('div.template-item.ng-scope')
        for block in blocks:
            match = Match()
            match.home_team, match.away_team = block.find_element_by_css_selector('span.match-name-text.ng-binding').text.split(' v ')
            odds = block.find_elements_by_css_selector('div.animate-odd.ng-binding.ng-scope')
            for i in range(3):
                match.odds[i] = odds[i].text
                match.agents[i] = 'TAB   '
            matches.append(match)

    fetch(fetch_tab, driver, tab_url, 'a_league_tab.pkl', fetch_tab)
    if fetch_tab and fetch_data:
        matches = []
        driver.get(tab_url)
        blocks = driver.find_elements_by_css_selector('div.template-item.ng-scope')
        for block in blocks:
            match = Match()
            match.home_team, match.away_team = block.find_element_by_css_selector('span.match-name-text.ng-binding').text.split(' v ')
            odds = block.find_elements_by_css_selector('div.animate-odd.ng-binding.ng-scope')
            for i in range(3):
                match.odds[i] = odds[i].text
                match.agents[i] = 'TAB   '
            matches.append(match)
        save_to(matches, 'a_league_tab.pkl')

    # --- UBET
    if fetch_ubet and fetch_data:
        matches = []
        driver.get(ubet_url)
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
        save_to(matches, 'a_league_ubet.pkl')

    # --- Bet365
    if fetch_bet365 and fetch_data:
        matches = []
        blocks = []
        driver.get(bet365_url)
        for _ in range(10):
            time.sleep(1)
            blocks = driver.find_elements_by_css_selector('div.podEventRow')
            if len(blocks) is not 0:
                break

        for b in blocks:
            names = b.find_elements_by_css_selector('div.ippg-Market_CompetitorName')
            odds = b.find_elements_by_css_selector('span.ippg-Market_Odds')
            match = Match()
            match.home_team, match.away_team = names[0].text, names[1].text
            for i in range(3):
                match.odds[i] = odds[i].text
                match.agents[i] = 'Bet365'
            matches.append(match)
        save_to(matches, 'a_league_bet365.pkl')

    # --- WilliamHill
    if fetch_william and fetch_data:
        matches = []
        driver.get(william_url)
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
        save_to(matches, 'a_league_william.pkl')

    # --- Crownbet
    if fetch_crownbet and fetch_data:
        matches = []
        blocks = []
        driver.get(crown_url)
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
        save_to(matches, 'a_league_crown.pkl')

    # --- Sportsbet
    if fetch_sportsbet and fetch_data:
        content = requests.get(sports_url).text.split('\n')
        #with open('test.pkl', 'rb') as pkl: content = pickle.load(pkl)
        status = None
        team_name_r = '<span class="team-name.*>(.+)</span>'
        matches = []
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
        save_to(matches, 'a_league_sports.pkl')

    # --- CentreBet
    if fetch_centrebet and fetch_data:
        matches = []
        blocks = []
        driver.get(centre_url)
        for _ in range(10):
            blocks = driver.find_elements_by_css_selector('td.brdSports')
            if len(blocks) is not 0:
                break
            time.sleep(1)
        for b in blocks:
            teams = b.find_elements_by_css_selector('div.sport-event')
            odds = b.find_elements_by_css_selector('div.clear')
            m = Match()
            m.home_team, m.away_team = teams[0].text, teams[2].text
            for i in range(3):
                m.odds[i] = odds[i].text
                m.agents[i] = 'Centre'
            matches.append(m)
        save_to(matches, 'a_league_centre.pkl')

    # --- Unibet
    if fetch_unibet and fetch_data:
        matches = []
        driver.get(unibet_url)
        blocks = driver.find_elements_by_css_selector('div.KambiBC-event-item__event-wrapper')
        for b in blocks:
            teams = b.find_elements_by_css_selector('div.KambiBC-event-participants__name')
            odds = b.find_elements_by_css_selector('span.KambiBC-mod-outcome__odds')
            m = Match()
            m.home_team, m.away_team = teams[0].text, teams[1].text
            for i in range(3):
                m.odds[i] = odds[i].text
                m.agents[i] = 'Unibet'
            matches.append(m)
        save_to(matches, 'a_league_unibet.pkl')

    # --- Topbetta
    if fetch_topbetta and fetch_data:
        def get_blocks():
            return driver.find_elements_by_css_selector('div.head-to-head-event')
        matches = []
        blocks = []
        driver.get(topbetta_url)
        for _ in range(10):
            blocks = get_blocks()
            if len(blocks) is not 0:
                break
            time.sleep(1)
        for b in range(len(blocks)):
            m = Match()
            blocks = driver.find_elements_by_css_selector('div.head-to-head-event')
            teams = blocks[b].find_elements_by_css_selector('div.team-container')
            odds = blocks[b].find_elements_by_css_selector('button.js_price-button.price')
            m.home_team = teams[0].text
            m.away_team = teams[1].text
            m.odds[0] = odds[0].text
            m.odds[1] = odds[2].text
            m.odds[2] = odds[1].text
            m.agents = ['Tpbetta'] * 3
            matches.append(m)
        save_to(matches, 'a_league_topbetta.pkl')

    # --- ladbrokes
    if fetch_ladbrokes and fetch_data:
        matches = []
        driver.get(ladbrokes_url)
        blocks = driver.find_elements_by_css_selector('table.bettype-group.listings.odds.sports.match.soccer')
        for b in blocks:
            m = Match()
            info = b.find_elements_by_css_selector('tr.row')
            m.home_team, m.odds[0] = info[0].text.split('\n')
            m.away_team, m.odds[2] = info[1].text.split('\n')
            m.odds[1] = info[2].text.split('\n')[1]
            m.agents = ['ladbrok'] * 3
            matches.append(m)
        save_to(matches, 'a_league_ladbrokes.pkl')

    # --- palmerbet
    if fetch_palmerbet and fetch_data:
        matches = []
        driver.get(palmerbet_url)
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
        save_to(matches, 'a_league_palmerbet.pkl')

    # --- betstar
    if fetch_betstar and fetch_data:
        matches = []
        driver.get(betstar_url)
        blocks = driver.find_elements_by_css_selector('table.bettype-group.listings.odds.sports.match.soccer')
        for b in blocks:
            info = b.find_elements_by_css_selector('tr.row')
            m = Match()
            m.home_team, m.odds[0] = info[0].text.split('\n')
            m.away_team, m.odds[2] = info[1].text.split('\n')
            m.odds[1] = info[2].text.split('\n')[1]
            m.agents = ['Betstar'] * 3
            matches.append(m)
        save_to(matches, 'a_league_betstar.pkl')
        
    #==============
    merge_matches()


if __name__ == "__main__":
    main()


'''
<div class="price-link ...
<span class="team-name ...>Sydney FC</span>
<span class="price-val...
1.45
</span>
...
<div class="price-link ...
<span class="team-name ...>Draw</span>
<span class="price-val...
4.5
</span>
<div class="price-link ...
<span class="team-name ...>Perthxx</span>
<span class="price-val...
6
</span>

'''
