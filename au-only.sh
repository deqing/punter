sudo systemctl start tunnelbear@oz
sleep 10
for param
do
  python3 punter.py $param --a --eng --ita --liga --get-only
done
sudo systemctl stop tunnelbear@oz
