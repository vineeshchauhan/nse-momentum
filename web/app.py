import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from flask import Flask, render_template
from web import queries


def create_app():
    app = Flask(__name__, template_folder="templates")

    @app.route("/")
    def dashboard():
        runs = queries.get_recent_runs(days=30)
        return render_template("dashboard.html", runs=runs)

    @app.route("/btst")
    def btst():
        signals = queries.get_btst_signals(days=30)
        return render_template("btst.html", signals=signals)

    @app.route("/momentum")
    def momentum():
        weeks = queries.get_momentum_weeks()
        current = queries.get_momentum_portfolio(weeks[0]) if weeks else []
        history = [(w, queries.get_momentum_portfolio(w)) for w in weeks[1:5]]
        return render_template("momentum.html",
                               current=current, history=history, weeks=weeks)

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000)
