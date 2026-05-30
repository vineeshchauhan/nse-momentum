import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
import time
from datetime import date, datetime

from flask import Flask, render_template, request, jsonify, g
from web import queries

logger = logging.getLogger(__name__)


def create_app():
    from logging_config import setup_logging
    setup_logging()

    app = Flask(__name__, template_folder="templates")

    @app.before_request
    def _log_request():
        g._req_start = time.monotonic()
        logger.info("--> %s %s [%s]", request.method, request.path, request.remote_addr)

    @app.after_request
    def _log_response(response):
        ms = (time.monotonic() - getattr(g, "_req_start", time.monotonic())) * 1000
        logger.info(
            "<-- %s %s %s (%.0fms)",
            request.method, request.path, response.status_code, ms,
        )
        return response

    @app.route("/")
    def dashboard():
        runs = queries.get_recent_runs(days=30)
        return render_template("dashboard.html", runs=runs, today=date.today().isoformat())

    @app.route("/btst")
    def btst():
        signals = queries.get_btst_signals(days=30)
        filter_stats = queries.get_btst_filter_stats(days=30)
        return render_template("btst.html", signals=signals,
                               filter_stats=filter_stats, today=date.today().isoformat())

    @app.route("/momentum")
    def momentum():
        weeks = queries.get_momentum_weeks()
        current = queries.get_momentum_portfolio(weeks[0]) if weeks else []
        history = [(w, queries.get_momentum_portfolio(w)) for w in weeks[1:5]]
        return render_template("momentum.html",
                               current=current, history=history, weeks=weeks,
                               today=date.today().isoformat())

    @app.route("/run/btst", methods=["POST"])
    def run_btst():
        payload = request.get_json(silent=True) or {}
        raw = payload.get("date", "")
        try:
            target = datetime.strptime(raw, "%Y-%m-%d").date() if raw else date.today()
        except ValueError:
            return jsonify({"ok": False, "error": f"Invalid date: {raw}"}), 400
        logger.info("Manual BTST trigger for %s", target.isoformat())
        try:
            from strategies.btst import run as btst_run
            from emailer.sender import send_btst_email
            signals, funnel = btst_run(target_date=target)
            email_sent = send_btst_email(signals) if signals else False
            logger.info(
                "Manual BTST complete: %d signal(s), email_sent=%s",
                len(signals), email_sent,
            )
            sig_data = [
                {
                    "symbol":           s["symbol"],
                    "name":             s.get("name") or s["symbol"],
                    "price_change_pct": s["price_change_pct"],
                    "volume_ratio":     s["volume_ratio"],
                    "close_price":      s["close_price"],
                    "suggested_strike": s["suggested_strike"],
                    "stop_loss":        s["stop_loss"],
                    "iv_current_month": s.get("iv_current_month"),
                    "iv_next_month":    s.get("iv_next_month"),
                }
                for s in signals
            ]
            return jsonify({
                "ok":        True,
                "signals":   sig_data,
                "funnel":    funnel,
                "email_sent": email_sent,
                "message":   f"{len(signals)} signal(s) found for {target.isoformat()}. "
                             + ("Email sent." if email_sent else "No email sent."),
            })
        except Exception as e:
            logger.exception("Manual BTST run failed for %s", target.isoformat())
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/run/momentum", methods=["POST"])
    def run_momentum():
        payload = request.get_json(silent=True) or {}
        raw = payload.get("date", "")
        try:
            target = datetime.strptime(raw, "%Y-%m-%d").date() if raw else date.today()
        except ValueError:
            return jsonify({"ok": False, "error": f"Invalid date: {raw}"}), 400
        logger.info("Manual Momentum trigger for %s", target.isoformat())
        try:
            from strategies.momentum import run as momentum_run
            from emailer.sender import send_momentum_email
            result = momentum_run(as_of_date=target)
            email_sent = send_momentum_email(
                result["top30"], result["changes"], result["exits"], result["week_start"]
            )
            logger.info(
                "Manual Momentum complete: %d stocks, week=%s, email_sent=%s",
                len(result["top30"]), result["week_start"], email_sent,
            )
            return jsonify({"ok": True,
                            "message": f"{len(result['top30'])} stocks in portfolio "
                                       f"for week of {result['week_start']}. Email sent."})
        except Exception as e:
            logger.exception("Manual Momentum run failed for %s", target.isoformat())
            return jsonify({"ok": False, "error": str(e)}), 500

    @app.route("/run/daily-batch", methods=["POST"])
    def run_daily_batch():
        payload = request.get_json(silent=True) or {}
        raw = payload.get("date", "")
        try:
            target = datetime.strptime(raw, "%Y-%m-%d").date() if raw else date.today()
        except ValueError:
            return jsonify({"ok": False, "error": f"Invalid date: {raw}"}), 400
        logger.info("Manual daily-batch trigger for %s", target.isoformat())
        try:
            from data_pipeline.daily_batch import run as batch_run
            batch_run(target_date=target)
            logger.info("Manual daily-batch complete for %s", target.isoformat())
            return jsonify({"ok": True,
                            "message": f"Daily batch completed for {target.isoformat()}."})
        except Exception as e:
            logger.exception("Manual daily-batch failed for %s", target.isoformat())
            return jsonify({"ok": False, "error": str(e)}), 500

    return app


if __name__ == "__main__":
    create_app().run(host="0.0.0.0", port=5000)
