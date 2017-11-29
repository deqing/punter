from flask import Flask
app = Flask(__name__)


@app.route('/please_tell_me_what_is_the_odds_of_this_website')
def reply():
    return 'Hello again, World!'
