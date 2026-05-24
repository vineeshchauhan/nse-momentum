"""
Email sender — uses smtplib with Gmail app password.
Renders Jinja2 HTML templates.
"""
import smtplib
import logging
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from string import Template
import re
import pytz

from config import EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECEIVER

logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")
TEMPLATE_DIR = Path(__file__).parent


def _render(template_name: str, context: dict) -> str:
    """Minimal Jinja2-like renderer (no dependency on jinja2)."""
    try:
        from jinja2 import Environment, FileSystemLoader, select_autoescape
        env = Environment(
            loader=FileSystemLoader(str(TEMPLATE_DIR)),
            autoescape=select_autoescape(["html"]),
        )
        tmpl = env.get_template(template_name)
        return tmpl.render(**context)
    except ImportError:
        # Fallback: very simple {{var}} substitution for non-loop templates
        html = (TEMPLATE_DIR / template_name).read_text(encoding="utf-8")
        for k, v in context.items():
            html = html.replace("{{ " + k + " }}", str(v))
            html = html.replace("{{" + k + "}}", str(v))
        return html


def _send(subject: str, html_body: str) -> bool:
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = EMAIL_SENDER
        msg["To"]      = EMAIL_RECEIVER
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        import socket
        ipv4 = socket.getaddrinfo("smtp.gmail.com", 587, socket.AF_INET)[0][4][0]
        with smtplib.SMTP(ipv4, 587) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(EMAIL_SENDER, EMAIL_PASSWORD)
            smtp.sendmail(EMAIL_SENDER, EMAIL_RECEIVER, msg.as_string())
        logger.info(f"Email sent: {subject}")
        return True
    except Exception as e:
        logger.error(f"Email failed ({subject!r}): {e}", exc_info=True)
        return False


def send_btst_email(signals: list, nifty_change: float = 0.0):
    today = date.today().strftime("%d %b %Y")
    generated_at = datetime.now(IST).strftime("%I:%M %p IST")
    context = {
        "date":         today,
        "nifty_change": f"{nifty_change:+.2f}",
        "count":        len(signals),
        "generated_at": generated_at,
        "signals":      signals,
    }
    html = _render("btst_template.html", context)
    return _send(f"BTST Screener — {today} — {len(signals)} Signals", html)


def send_momentum_email(top30: list, changes: list, exits: list, week_start: date):
    entries = [c for c in changes if c["change_type"] == "NEW ENTRY"]

    # Annotate top30 rows with rendering helpers
    rows = []
    for s in top30:
        rp = s.get("rank_previous")
        rc = s.get("rank")
        row_class = (
            "entry" if s["change_type"] == "NEW ENTRY"
            else "exit" if s["change_type"] == "EXIT"
            else "cont"
        )
        rank_delta = (rp - rc) if (rp is not None and rc is not None) else None
        rows.append({**s, "row_class": row_class, "rank_delta": rank_delta})

    generated_at = datetime.now(IST).strftime("%I:%M %p IST")
    context = {
        "week_start":   week_start.strftime("%d %b %Y"),
        "generated_at": generated_at,
        "entries":      entries,
        "exits":        exits,
        "top30":        rows,
    }
    html = _render("momentum_template.html", context)
    week_str = week_start.strftime("%d %b %Y")
    return _send(f"Momentum Portfolio — Week of {week_str} — {len(entries)} new, {len(exits)} exits", html)
