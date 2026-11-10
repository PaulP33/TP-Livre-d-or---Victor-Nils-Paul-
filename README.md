# Livre d'or

Projet Docker ESGI. Un livre d'or tout simple : on laisse un message, il est enregistré en base et un mail de notification est envoyé. Le but est surtout de faire tourner toute l'infra autour avec Docker Compose.

## Services

| Service | Image | Rôle |
|---|---|---|
| nginx | nginx:1.27-alpine | Reverse proxy, seul port exposé (80) |
| app | python:3.13-slim (Flask + Gunicorn) | Le site du livre d'or |
| db-primary | postgres:17-alpine | Base principale, les écritures vont ici |
| db-replica | postgres:17-alpine | Réplica en streaming replication, les lectures se font ici |
| redis | redis:7-alpine | Cache de la liste des messages (30 s) |
| mailpit | axllent/mailpit | Serveur SMTP de test avec interface web |
| prometheus | prom/prometheus | Récupère les métriques |
| grafana | grafana/grafana | Dashboard |
| node-exporter, redis-exporter, pg-exporter-primary, pg-exporter-replica | | Exporters pour Prometheus |

## Fonctionnement

1. L'utilisateur poste un message sur le site.
2. L'app l'écrit dans `db-primary`, vide le cache Redis et envoie un mail via Mailpit.
3. Pour afficher les messages, l'app regarde d'abord dans Redis. Si le cache est vide, elle lit dans `db-replica` puis remet le résultat en cache.

### Fonctionnalités du site

- Pagination (10 messages par page) et recherche par nom ou contenu
- Likes sur les messages, un seul par personne (les IPs qui ont liké sont stockées dans Redis)
- Anti-spam : un message toutes les 30 s par IP (clé Redis avec expiration) et un champ caché pour piéger les bots
- Statistiques en haut de page (messages, auteurs, messages du jour)
- Mode sombre automatique selon le système, avatars de couleur, compteur de caractères

Les likes et les messages refusés sont aussi comptés dans les métriques Prometheus (`livredor_likes`, `livredor_blocked`).

En bas de la page on voit d'où viennent les messages (cache Redis ou réplica), pratique pour vérifier que le cache marche.

## Lancer le projet

```bash
cp .env.example .env
docker compose up -d
```

Le premier lancement prend un peu de temps (téléchargement des images et build de l'app).

| Adresse | Quoi |
|---|---|
| http://localhost | Le livre d'or |
| http://localhost/mail/ | Les mails reçus (Mailpit) |
| http://localhost/grafana/ | Grafana (admin / admin) |
| http://localhost/prometheus/ | Prometheus |

Pour tout arrêter :

```bash
docker compose down
```

Et pour repartir de zéro en supprimant aussi les données :

```bash
docker compose down -v
```

## Vérifier la réplication

Sur la base principale, on doit voir la réplica connectée :

```bash
docker compose exec db-primary psql -U livredor -c "SELECT client_addr, state FROM pg_stat_replication;"
```

Sur la réplica, les messages postés sur le site doivent apparaître :

```bash
docker compose exec db-replica psql -U livredor -d livredor -c "SELECT * FROM messages;"
```

Et une écriture sur la réplica doit être refusée car elle est en lecture seule :

```bash
docker compose exec db-replica psql -U livredor -d livredor -c "INSERT INTO messages (author, content) VALUES ('test', 'test');"
```

## Healthcheck

L'app expose `/health` qui vérifie la connexion à la base principale et à Redis. Docker s'en sert pour savoir quand l'app est prête, et nginx ne démarre qu'une fois l'app en bonne santé.

```bash
docker compose ps
```

Si Redis tombe, le site continue de marcher : les messages sont lus directement sur la réplica.

```bash
docker compose stop redis
# le bas de la page doit afficher "replica PostgreSQL"
docker compose start redis
```

## Arborescence

```
.
├── docker-compose.yml
├── .env.example
├── app/
│   ├── Dockerfile
│   ├── app.py
│   ├── requirements.txt
│   ├── static/style.css
│   └── templates/index.html
├── db/
│   ├── primary/init.sh
│   └── replica/replica.sh
├── nginx/nginx.conf
└── monitoring/
    ├── prometheus.yml
    └── grafana/
        ├── dashboards/livre-dor.json
        └── provisioning/
```
