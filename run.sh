US_SAFE="bet365,betstar,ladbrokes,madbookie,palmerbet,sportsbet,tab,topbetta,ubet,unibet,williamhill"
AU_ONLY="luxbet,crownbet"

python3 punter.py $US_SAFE --a
sudo systemctl start tunnelbear@oz
sleep 10
python3 punter.py $AU_ONLY --a
sudo systemctl stop tunnelbear@oz
python3 punter.py $US_SAFE,$AU_ONLY --a --print-only
