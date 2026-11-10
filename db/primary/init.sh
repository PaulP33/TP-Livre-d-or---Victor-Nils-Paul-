#!/bin/sh
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<EOSQL
CREATE ROLE $REPLICATION_USER WITH REPLICATION LOGIN PASSWORD '$REPLICATION_PASSWORD';

CREATE TABLE messages (
    id SERIAL PRIMARY KEY,
    author VARCHAR(50) NOT NULL,
    content TEXT NOT NULL,
    likes INTEGER NOT NULL DEFAULT 0,
    photo VARCHAR(64),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
EOSQL

echo "host replication $REPLICATION_USER all scram-sha-256" >> "$PGDATA/pg_hba.conf"
