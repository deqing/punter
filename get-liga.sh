US_SAFE="bet365,betstar,ladbrokes,madbookie,palmerbet,topbetta,ubet,unibet"
AU_ONLY="crownbet,luxbet,sportsbet,tab,williamhill"

python3 punter.py $US_SAFE --liga
sudo systemctl start tunnelbear@oz
sleep 10
python3 punter.py $AU_ONLY --liga
sudo systemctl stop tunnelbear@oz
python3 punter.py $US_SAFE,$AU_ONLY --liga --print-only
