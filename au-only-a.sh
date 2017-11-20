sudo systemctl start tunnelbear@oz
sleep 10
for param
do
  python3 punter.py $param --a
done
sudo systemctl stop tunnelbear@oz
