import json
import os
import smtplib
from email.message import EmailMessage

import psycopg
import redis
from flask import Flask, Response, flash, redirect, render_template, request, url_for
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev")

DB_USER = os.environ["POSTGRES_USER"]
DB_PASSWORD = os.environ["POSTGRES_PASSWORD"]
DB_NAME = os.environ["POSTGRES_DB"]
PRIMARY_HOST = os.environ.get("DB_PRIMARY_HOST", "db-primary")
REPLICA_HOST = os.environ.get("DB_REPLICA_HOST", "db-replica")
SMTP_HOST = os.environ.get("SMTP_HOST", "mailpit")
SMTP_PORT = int(os.environ.get("SMTP_PORT", 1025))
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@livredor.local")

CACHE_PREFIX = "messages:"
CACHE_TTL = 30
PER_PAGE = 10
# temps minimum entre deux messages d'une meme IP
POST_DELAY = 30

cache = redis.Redis(host=os.environ.get("REDIS_HOST", "redis"), decode_responses=True)

requests_count = Counter("livredor_requests", "Requetes HTTP", ["page"])
messages_count = Counter("livredor_messages", "Messages postes")
cache_count = Counter("livredor_cache", "Acces au cache Redis", ["result"])
likes_count = Counter("livredor_likes", "Likes")
blocked_count = Counter("livredor_blocked", "Messages refuses", ["reason"])


def connect(host):
    return psycopg.connect(host=host, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME)


# pour les bases creees avant l'ajout des likes
with connect(PRIMARY_HOST) as conn:
    conn.execute("ALTER TABLE messages ADD COLUMN IF NOT EXISTS likes INTEGER NOT NULL DEFAULT 0")


@app.template_filter("hue")
def hue(name):
    # couleur de l'avatar, toujours la meme pour un meme nom
    return sum(map(ord, name)) % 360


def client_ip():
    # nginx met la vraie IP dans X-Real-IP
    return request.headers.get("X-Real-IP", request.remote_addr)


def clear_cache():
    try:
        for key in cache.scan_iter(CACHE_PREFIX + "*"):
            cache.delete(key)
    except redis.RedisError:
        app.logger.warning("Impossible de vider le cache")


def get_messages(page, search):
    key = f"{CACHE_PREFIX}{page}:{search}"

    # si redis est down on lit directement la replica au lieu de planter
    try:
        cached = cache.get(key)
    except redis.RedisError:
        cached = None
        app.logger.warning("Redis injoignable, lecture sur la replica")

    if cached is not None:
        cache_count.labels("hit").inc()
        return json.loads(cached), "cache Redis"

    cache_count.labels("miss").inc()
    pattern = f"%{search}%"
    with connect(REPLICA_HOST) as conn:
        rows = conn.execute(
            "SELECT id, author, content, likes, to_char(created_at, 'DD/MM/YYYY HH24:MI') "
            "FROM messages WHERE author ILIKE %s OR content ILIKE %s "
            "ORDER BY created_at DESC LIMIT %s OFFSET %s",
            (pattern, pattern, PER_PAGE, (page - 1) * PER_PAGE),
        ).fetchall()
        total, authors, today = conn.execute(
            "SELECT count(*), count(DISTINCT author), "
            "count(*) FILTER (WHERE created_at >= current_date) "
            "FROM messages WHERE author ILIKE %s OR content ILIKE %s",
            (pattern, pattern),
        ).fetchone()

    data = {
        "messages": [
            {"id": i, "author": a, "content": c, "likes": l, "date": d}
            for i, a, c, l, d in rows
        ],
        "total": total,
        "authors": authors,
        "today": today,
    }
    try:
        cache.set(key, json.dumps(data), ex=CACHE_TTL)
    except redis.RedisError:
        pass
    return data, "replica PostgreSQL"


def can_post(ip):
    # SET NX avec expiration : la cle existe tant que le delai n'est pas passe
    try:
        return cache.set(f"ratelimit:{ip}", 1, nx=True, ex=POST_DELAY)
    except redis.RedisError:
        return True


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
    page = max(request.args.get("page", 1, type=int), 1)
    search = request.args.get("q", "").strip()[:50]

    data, source = get_messages(page, search)
    pages = max((data["total"] + PER_PAGE - 1) // PER_PAGE, 1)

    try:
        liked = {int(i) for i in cache.smembers(f"liked:{client_ip()}")}
    except redis.RedisError:
        liked = set()

    return render_template(
        "index.html",
        source=source,
        page=page,
        pages=pages,
        search=search,
        liked=liked,
        **data,
    )


@app.post("/")
def new_message():
    requests_count.labels("post").inc()
    author = " ".join(request.form.get("author", "").split())[:50]
    content = request.form.get("content", "").strip()[:500]

    # champ cache dans le formulaire, seuls les bots le remplissent
    if request.form.get("website"):
        blocked_count.labels("bot").inc()
        return redirect(url_for("index"))

    if not author or not content:
        flash("Le nom et le message sont obligatoires.", "error")
        return redirect(url_for("index"))

    if not can_post(client_ip()):
        blocked_count.labels("ratelimit").inc()
        flash(f"Doucement ! Attends {POST_DELAY} secondes entre deux messages.", "error")
        return redirect(url_for("index"))

    with connect(PRIMARY_HOST) as conn:
        conn.execute(
            "INSERT INTO messages (author, content) VALUES (%s, %s)",
            (author, content),
        )
    clear_cache()
    messages_count.inc()
    send_notification(author, content)
    flash("Merci pour ton message !", "success")

    return redirect(url_for("index"))


@app.post("/like/<int:message_id>")
def like(message_id):
    requests_count.labels("like").inc()

    # un seul like par IP et par message
    try:
        if not cache.sadd(f"liked:{client_ip()}", message_id):
            return redirect(request.referrer or url_for("index"))
    except redis.RedisError:
        pass

    with connect(PRIMARY_HOST) as conn:
        conn.execute("UPDATE messages SET likes = likes + 1 WHERE id = %s", (message_id,))
    clear_cache()
    likes_count.inc()

    return redirect(request.referrer or url_for("index"))


@app.get("/health")
def health():
    status = {"db": "ok", "redis": "ok"}
    try:
        with connect(PRIMARY_HOST) as conn:
            conn.execute("SELECT 1")
    except psycopg.Error:
        status["db"] = "ko"
    try:
        cache.ping()
    except redis.RedisError:
        status["redis"] = "ko"

    # redis n'est pas bloquant, l'app marche sans
    code = 200 if status["db"] == "ok" else 503
    return status, code


@app.get("/metrics")
def metrics():
    return Response(generate_latest(), mimetype=CONTENT_TYPE_LATEST)
