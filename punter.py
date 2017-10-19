"""
Will do following

https://www.punters.com.au/odds-comparison/soccer/spanish-la-liga/
https://www.punters.com.au/odds-comparison/soccer/a-league/
...

TODO:
https://www.tab.com.au/sports/betting/Soccer/competitions/A%20League
https://ubet.com/sports/soccer/australia-a-league/a-league-matches

https://www.tab.com.au/sports/betting/Soccer/competitions/UEFA%20Champions%20League

"""

import re
import datetime
import requests
import pickle
from colorama import init, Fore, Back, Style


def color_print(msg, foreground="black", background="white"):
    fground = foreground.upper()
    bground = background.upper()
    style = getattr(Fore, fground) + getattr(Back, bground)
    print(style + msg + Style.RESET_ALL)


def extract(line, regx):
    m = re.search(regx, line)
    return m.group(1) if m else ''


class Match:
    def __init__(self):
        self.profit = 0
        self.home_team = ''
        self.away_team = ''
        self.time = ''
        self.odds = ['', '', '']
        self.agents = ['', '', '']
        self.perts = ['', '', '']

    def display(self):
        msg = '{}\t{}({})({})  {}({})({})  {}({})({})\t- {} vs {}\t{}'.format(
            round(self.profit, 2),
            self.odds[0], self.agents[0], self.perts[0],
            self.odds[1], self.agents[1], self.perts[1],
            self.odds[2], self.agents[2], self.perts[2],
            self.home_team, self.away_team, self.time)
        if self.profit > 99.5:
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


def get_content(url, save_to='', mobile=False):
    """
    :param save_to: if it's not none, will save the content object to a local pickle file for easy debugging
                    if it's none, just return the content
    :param mobile: if is true, will pretend as a mobile to visit the url
    """
    if mobile:
        header = {'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 9_1 like Mac OS X) AppleWebKit/601.1.46 (KHTML, like Gecko) Version/9.0 Mobile/13B137 Safari/601.1'}
        punter = requests.get(url, headers=header)
        file_name = save_to + '_mobile.pkl'
    else:
        punter = requests.get(url)
        file_name = save_to + '.pkl'
    punter = punter.text.split('\n')

    if save_to != '':
        with open(file_name, 'wb') as pkl:
            pickle.dump(punter, pkl)
    else:
        return punter


def get_match_url_list(league_name='', content=None):
    menu_item_str = 'odds-menu__item'
    menu_item_r = 'href="(.+)"'
    if league_name != '':
        with open(league_name+'_mobile.pkl', 'rb') as pkl:
            content = pickle.load(pkl)
    else:
        content = content

    urls = []
    for line in content:
        if menu_item_str in line:
            urls.append(base_url + extract(line, menu_item_r))
    return urls

def crawl_odds_match_info(league_name=None, content=None):
    """ ------------- Text structure ---------------

    1) class="oc-table__event-name"        Spanish La Liga - Espanyol Vs Levante
    2) Win-Draw-Win  (could be others like "Correct Score" which has same structure below
                      so this is the only way to identify the section)
            <tr class...
              misc info
            </tr>
         <tbody ...
    3.1)    <tr class...
    3.2)       ppodds best                       1.95
    3.3)       ppodds best                       1.95
    3.x)    </tr>
    4.2)       ppodds best                       3.45
    4.x)    </tr>
    5.2)       ppodds best                       4.5
    6) </table>  # end
       ...
       class="oc-table__event-name"    {{eventFullName}} etc.
       ...
       class="oc-table__event-name"    Spanish La Liga - Bilbao vs xxx
       Win-Draw-Win

    # will do "draw no bet" later

    """
    match_info_str = 'event-name">'
    nums_str = 'ppodds best'
    match_info_r = match_info_str + '(.+?)<'
    nums_r = nums_str + '.*>([\d.]+?)</a>'

    if league_name is not None:
        with open(league_name+'.pkl', 'rb') as pkl:
            content = pickle.load(pkl).text.split('\n')
    else:
        content = content

    section = None
    matches = []
    match = Match()
    odd_idx = 0
    for line in content:
        if match_info_str in line:  # 1) Save match info
            match.match_info = extract(line, match_info_r)
            continue

        if section is None and 'Win-Draw-Win' in line:  # 2) Entering section
            section = 'wdw'
            continue

        if section == 'wdw':
            if '<tbody>' in line:
                odd_idx = 0
            elif '<tr class=' in line:  # 3.1)
                section = 'tr'
            elif '</table>' in line:  # 6) End of wdw
                section = None
                matches.append(match)
                match = Match()  # Next match
            continue

        if section == 'tr':
            if nums_str in line:
                match.odds[odd_idx] = extract(line, nums_r)
            if '</tr>' in line:
                section = 'wdw'
                odd_idx += 1
            continue

    for m in matches:
        m.calculate_best_shot()
        m.display()

    return


""" odds.com.au
    base_url = 'https://www.odds.com.au/'
    url_spain = base_url + 'soccer/spanish-la-liga/'
    url_italy = base_url + 'soccer/italian-serie-a/'
    url_germany = base_url + 'soccer/bundesliga/'
    url_aus = base_url + 'soccer/a-league/'
    url_eng = base_url + 'soccer/english-premier-league/'

    for url in url_aus, url_eng: #, url_spain, url_italy, url_germany, url_aus:
        menu_list = get_content(url, mobile=True)  # Need to visit by mobile here, it will return an expended menu, otherwise the menu is collapsed which is not able to read the matches
        urls = get_match_url_list(content=menu_list)
        for match_url in urls:
            page = get_content(match_url)
            crawl_match_info(content=page)

    #get_content(url_italy, 'italy')
    #get_content(url_germany, 'germany')
    #get_content(url_aus, 'aus')
    #get_content(url_eng, 'eng')

    #get_match_list('spain')

    #crawl_match_info('laliga')
    #crawl_match_info('spain')
    #crawl_match_info('italy')
    #crawl_match_info('germany')
    #crawl_match_info('aus')
"""


def get_match_info(league_name=None, content=None):
    if league_name is not None:
        with open(league_name+'.pkl', 'rb') as pkl:
            content = pickle.load(pkl)#.text.split('\n')
    for line in content:
        print(line)


from selenium.webdriver.chrome.options import Options
from selenium import webdriver

chrome_options = Options()
chrome_options.add_argument("--headless")

driver = webdriver.Chrome(chrome_options=chrome_options)


def main():
    matches = []

    # --- TAB
    if True:
        driver.get('https://www.tab.com.au/sports/betting/Soccer/competitions/A%20League')
        blocks = driver.find_elements_by_css_selector('div.template-item.ng-scope')
        for block in blocks:
            match = Match()
            match.home_team, match.away_team = block.find_element_by_css_selector('span.match-name-text.ng-binding').text.split(' v ')
            odds = block.find_elements_by_css_selector('div.animate-odd.ng-binding.ng-scope')
            for i in range(3):
                match.odds[i] = odds[i].text
                match.agents[i] = 'TAB'
            match.calculate_best_shot()
            matches.append(match)

    # --- UBET
    if True:
        driver.get('https://ubet.com/sports/soccer/australia-a-league/a-league-matches')
        blocks = driver.find_elements_by_css_selector('div.ubet-sub-events-summary')
        for b in blocks:
            odds = b.find_elements_by_css_selector('div.ubet-offer-win-only')
            match = Match()
            m = []
            for i in range(3):
                m.append(odds[i].text.split('\n'))
                match.odds[i] = m[i][1]
                match.agents[i] = 'UBET'  #TODO: write matches to pkl can compare them later
            match.home_team = m[0][0]
            match.away_team = m[2][0]
            match.calculate_best_shot()
            matches.append(match)

    for m in matches:
        m.display()




if __name__ == "__main__":
    main()
