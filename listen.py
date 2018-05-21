import pickle
import os
from tempfile import gettempdir
from flask import Flask
from flask import jsonify
from flask import request, redirect, url_for
from worker import WebWorker
from werkzeug.utils import secure_filename

# python -u C:\Users\devin.huang\OneDrive\Documents\sty\punter\listen.py
UPLOAD_FOLDER = 'C:\\hdq\\tmp'
#UPLOAD_FOLDER = '/home/ubuntu/snj/'  # FIXME: should be an better path like: gettempdir()

app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
worker = WebWorker(is_get_data=True, keep_driver_alive=True)


@app.route('/please_tell_me_what_is_the_odds_of_this_website')
def reply():
    website = request.args.get('website')
    league = request.args.get('league')

    args = dict()
    args['websites_str'] = website
    args['leagues_str'] = league
    args['is_get_only'] = True
    worker.run(**args)

    pkl_name = league + '_' + website + '.pkl'
    with open(os.path.join(gettempdir(), pkl_name), 'rb') as pkl:
        matches = pickle.load(pkl)
        return jsonify(matches=[m.serialize() for m in matches])


@app.route('/get_ladbrokes')
def get_ladbrokes():
    url = request.args.get('url')
    target_markets = request.args.get('target_markets')  # usually it is 'all'
    lay_markets = request.args.get('lay_markets_str').replace('_', ' ').split(',')

    odds = worker.get_ladbrokes_markets_odd(url, target_markets, lay_markets)
    return jsonify(odds)


@app.route('/ping')
def ping():
    return 'yes'


@app.route("/ifttt", methods=['GET', 'POST'])
def ifttt():
    with open('ifttt.log', 'a') as f:
        f.write('I will post a url later')
    return 'ok'


def html_template(s):
    return """
    <!doctype html>
    <form action="" method=post enctype=multipart/form-data>
        {}
        <input type=submit value=Upload>
    </form>     
    <br>Current files:
    <ul><li>{}</li></ul>
    """.format(s, "</li><li>".join(os.listdir(app.config['UPLOAD_FOLDER'],)))


@app.route("/dqfile", methods=['GET', 'POST'])
def dqfile():
    if request.method == 'POST':
        for n in range(15):
            fn = 'f' + str(n)
            file = request.files[fn]
            if file:
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return redirect(url_for('dqfile'))

    s = ''
    for i in range(15):
        s += '<input type=file name="f{}"><br>'.format(i)
    return html_template(s)


@app.route("/dqtext", methods=['GET', 'POST'])
def dqtext():
    if request.method == 'POST':
        for n in range(15):
            fn = 'f' + str(n)
            cn = 'content' + str(n)
            filename = request.form[fn]
            if filename:
                with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), 'a') as f:
                    f.write(request.form[cn])
        return redirect(url_for('dqtext'))

    s = ''
    for i in range(15):
        s += '<textarea name="content{}" rows="10" cols="50" /></textarea><br>' \
            'filename: <input type="text" name="f{}"><br>'.format(i, i)
    return html_template(s)


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0')
