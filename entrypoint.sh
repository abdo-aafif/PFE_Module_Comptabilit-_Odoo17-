#!/bin/bash
# Script d'entrée du container staging.
# Attend que PostgreSQL soit prêt, puis lance Odoo en mettant à jour le module.
set -e

: "${HOST:=db}"
: "${PORT:=5432}"
: "${USER:=odoo}"
: "${PASSWORD:=odoo}"
: "${DB_NAME:=staging_db}"
: "${MODULE_NAME:=315_v3_gev2_claudeCopieCopie}"

echo "[entrypoint] Attente de PostgreSQL ${HOST}:${PORT}..."
until PGPASSWORD="${PASSWORD}" psql -h "${HOST}" -p "${PORT}" -U "${USER}" -d postgres -c '\q' 2>/dev/null; do
    sleep 1
done
echo "[entrypoint] PostgreSQL est prêt."

# Crée la base staging si elle n'existe pas
DB_EXISTS=$(PGPASSWORD="${PASSWORD}" psql -h "${HOST}" -p "${PORT}" -U "${USER}" -d postgres \
    -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'")

if [ "${DB_EXISTS}" != "1" ]; then
    echo "[entrypoint] Création de la base ${DB_NAME} + initialisation du module..."
    odoo --database="${DB_NAME}" \
         --db_host="${HOST}" \
         --db_port="${PORT}" \
         --db_user="${USER}" \
         --db_password="${PASSWORD}" \
         --init=l10n_ma,"${MODULE_NAME}" \
         --without-demo=all \
         --stop-after-init \
         --log-level=info
else
    echo "[entrypoint] Base ${DB_NAME} existe → mise à jour du module..."
    odoo --database="${DB_NAME}" \
         --db_host="${HOST}" \
         --db_port="${PORT}" \
         --db_user="${USER}" \
         --db_password="${PASSWORD}" \
         --update="${MODULE_NAME}" \
         --stop-after-init \
         --log-level=info
fi

echo "[entrypoint] Démarrage d'Odoo..."
exec "$@" \
    --db_host="${HOST}" \
    --db_port="${PORT}" \
    --db_user="${USER}" \
    --db_password="${PASSWORD}" \
    --database="${DB_NAME}"
