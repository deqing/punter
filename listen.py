import pickle
import os
from tempfile import gettempdir
from flask import Flask
from flask import jsonify
from flask import request
from worker import WebWorker

app = Flask(__name__)
worker = WebWorker(is_get_data=True)


@app.route('/please_tell_me_what_is_the_odds_of_this_website')
def reply():
    website = request.args.get('website')
    league = request.args.get('league')

    args = dict()
    args['websites'] = website
    args['is_get_only'] = True
    args['is_get_' + league] = True
    worker.run(**args)

    pkl_name = league + '_' + website + '.pkl'
    with open(os.path.join(gettempdir(), pkl_name), 'rb') as pkl:
        matches = pickle.load(pkl)
        return jsonify(matches)
