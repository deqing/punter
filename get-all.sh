US_SAFE="bet365,betstar,ladbrokes,madbookie,palmerbet,topbetta,ubet,unibet"
AU_ONLY="luxbet,crownbet,sportsbet,tab,williamhill"

python3 punter.py $US_SAFE --a --eng --ita --liga --get-only
sudo systemctl start tunnelbear@oz
sleep 10
python3 punter.py $AU_ONLY --a --eng --ita --liga --get-only
sudo systemctl stop tunnelbear@oz
python3 punter.py $US_SAFE,$AU_ONLY --a --eng --ita --liga --print-only

bash sendemail.sh
