sudo systemctl start tunnelbear@oz
sleep 10
for param
do
  python3 punter.py $param --a --get-only
done

for param
do
  python3 punter.py $param --eng --get-only
done

for param
do
  python3 punter.py $param --ita --get-only
done

for param
do
  python3 punter.py $param --liga --get-only
done
sudo systemctl stop tunnelbear@oz
