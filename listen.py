import pickle
import os
from tempfile import gettempdir
from flask import Flask
from flask import jsonify
from flask import request, redirect, url_for
from worker import WebWorker
from werkzeug.utils import secure_filename

# python -u C:\Users\devin.huang\OneDrive\Documents\sty\punter\listen.py
#UPLOAD_FOLDER = 'C:\\hdq\\tmp'
UPLOAD_FOLDER = '/home/ubuntu/snj/'  # FIXME: should be an better path like: gettempdir()

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


@app.route("/upload", methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        file = request.files['file']
        if file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            return redirect(url_for('index'))
    return """
    <!doctype html>
    <title>Upload new File</title>
    <h1>Upload new File</h1>
    <form action="" method=post enctype=multipart/form-data>
      <p><input type=file name=file>
         <input type=submit value=Upload>
    </form>
    <p>%s</p>
    """ % "<br>".join(os.listdir(app.config['UPLOAD_FOLDER'],))


@app.route("/abc", methods=['GET', 'POST'])
def save_to_file():
    if request.method == 'POST':
        filename = request.form['filename']
        if filename:
            with open(os.path.join(app.config['UPLOAD_FOLDER'], filename), 'a') as f:
                f.write(request.form['content'])

    return """
    <!doctype html>
    <form action="" method=post>
        <textarea name="content" rows="10" cols="50" autofocus /></textarea><br>
        filename: <input type="text" name="filename"><br>
        <input type=submit value=Save>
    </form>
    <br>目前已有以下文件或目录：
    <ul><li>%s</li></ul>
    """ % "</li><li>".join(os.listdir(app.config['UPLOAD_FOLDER'],))


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0')
