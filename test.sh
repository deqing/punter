sudo systemctl start tunnelbear@oz
sleep 10
python3 punter.py crownbet --a
sudo systemctl stop tunnelbear@oz
