import pickle
import os
from tempfile import gettempdir
from flask import Flask
from flask import jsonify
from flask import request
from flask import render_template
from worker import WebWorker

app = Flask(__name__)
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


@app.route('/upload')
def upload_file():
    return render_template('upload.html')


@app.route('/uploader', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        f = request.files['file']
        f.save(f.filename)
        return 'file uploaded successfully'


if __name__ == '__main__':
    app.run(debug=False, host='0.0.0.0')
