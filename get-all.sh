US_SAFE="bet365,betstar,ladbrokes,madbookie,palmerbet,topbetta,ubet,unibet"
AU_ONLY="luxbet,crownbet,sportsbet,tab,williamhill"

python3 punter.py $US_SAFE --a --eng --ita --liga --get-only
bash au-only.sh tab williamhill crownbet luxbet sportsbet
python3 punter.py all --a --eng --ita --liga --print-only

bash sendemail.sh
