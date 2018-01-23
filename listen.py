import pickle
import os
from tempfile import gettempdir
from flask import Flask
from flask import jsonify
from flask import request, redirect, url_for
from flask import render_template
from worker import WebWorker
from werkzeug.utils import secure_filename


UPLOAD_FOLDER = gettempdir()

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


@app.route('/please_tell_me_if_you_are_up')
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


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0')
