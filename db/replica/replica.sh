#!/bin/sh
set -e

if [ ! -s "$PGDATA/PG_VERSION" ]; then
    until pg_isready -h db-primary -p 5432; do
        echo "En attente de db-primary..."
        sleep 2
    done

    PGPASSWORD="$REPLICATION_PASSWORD" pg_basebackup -h db-primary -U "$REPLICATION_USER" -D "$PGDATA" -Fp -Xs -R
    chmod 700 "$PGDATA"
fi

exec postgres
