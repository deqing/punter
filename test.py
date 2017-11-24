from pinnacle.apiclient import APIClient

with open('pinnacle.pwd', 'r') as pwd_file:
    pwd = pwd_file.read()
api = APIClient('DH1007923', pwd)
#api = APIClient('DH1007923', 'dhina9la!')
leagues = api.reference_data.get_leagues(29)  # 29 is soccer


fixtures = api.market_data.get_fixtures(29, [1766])  # 1766 is a-league
odds = api.market_data.get_odds(29, [1766])

odds_map = dict()
for event in odds['leagues'][0]['events']:
    odds_map[event['id']] = event

for event in fixtures['league'][0]['events']:
    if event['liveStatus'] == 2:
        print(event['home'], event['away'])
        if event['id'] in odds_map.keys():
            odd = odds_map[event['id']]
            for period in odd['periods']:
                if 'moneyline' in period:
                    print(period['moneyline']['home'])
                    print(period['moneyline']['draw'])
                    print(period['moneyline']['away'])
                    break
