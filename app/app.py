import json
import os
import smtplib
from email.message import EmailMessage

import psycopg
import redis
from flask import Flask, Response, redirect, render_template, request, url_for
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

app = Flask(__name__)

DB_USER = os.environ["POSTGRES_USER"]
DB_PASSWORD = os.environ["POSTGRES_PASSWORD"]
DB_NAME = os.environ["POSTGRES_DB"]
PRIMARY_HOST = os.environ.get("DB_PRIMARY_HOST", "db-primary")
REPLICA_HOST = os.environ.get("DB_REPLICA_HOST", "db-replica")
SMTP_HOST = os.environ.get("SMTP_HOST", "mailpit")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 1025))
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@livredor.local")

CACHE_KEY = "messages"
CACHE_TTL = 30

cache = redis.Redis(host=os.environ.get("REDIS_HOST", "redis"), decode_responses=True)

requests_count = Counter("livredor_requests", "Requetes HTTP", ["page"])
messages_count = Counter("livredor_messages", "Messages postes")
cache_count = Counter("livredor_cache", "Acces au cache Redis", ["result"])


def connect(host):
    return psycopg.connect(host=host, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME)


def get_messages():
    # si redis est down on lit directement la replica au lieu de planter
    try:
        cached = cache.get(CACHE_KEY)
    except redis.RedisError:
        cached = None
        app.logger.warning("Redis injoignable, lecture sur la replica")

    if cached is not None:
        cache_count.labels("hit").inc()
        return json.loads(cached), "cache Redis"

    cache_count.labels("miss").inc()
    with connect(REPLICA_HOST) as conn:
        rows = conn.execute(
            "SELECT author, content, to_char(created_at, 'DD/MM/YYYY HH24:MI') "
            "FROM messages ORDER BY created_at DESC LIMIT 50"
        ).fetchall()

    messages = [{"author": a, "content": c, "date": d} for a, c, d in rows]
    try:
        cache.set(CACHE_KEY, json.dumps(messages), ex=CACHE_TTL)
    except redis.RedisError:
        pass
    return messages, "replica PostgreSQL"


def send_notification(author, content):
    mail = EmailMessage()
    mail["Subject"] = f"Nouveau message de {author}"
    mail["From"] = "livredor@livredor.local"
    mail["To"] = ADMIN_EMAIL
    mail.set_content(f"{author} a ecrit :\n\n{content}")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=5) as smtp:
            smtp.send_message(mail)
    except OSError as e:
        app.logger.warning("Mail non envoye : %s", e)


@app.get("/")
def index():
    requests_count.labels("index").inc()
    messages, source = get_messages()
    return render_template("index.html", messages=messages, source=source)


@app.post("/")
def new_message():
    requests_count.labels("post").inc()
    author = " ".join(request.form.get("author", "").split())[:50]
    content = request.form.get("content", "").strip()[:500]

    if author and content:
        with connect(PRIMARY_HOST) as conn:
            conn.execute(
                "INSERT INTO messages (author, content) VALUES (%s, %s)",
                (author, content),
            )
        try:
            cache.delete(CACHE_KEY)
        except redis.RedisError:
            app.logger.warning("Impossible de vider le cache")
        messages_count.inc()
        send_notification(author, content)

    return redirect(url_for("index"))


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)
