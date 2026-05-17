#!/bin/bash
set -e
# Create extra databases listed in POSTGRES_MULTIPLE_DATABASES.
if [ -n "$POSTGRES_MULTIPLE_DATABASES" ]; then
  IFS=',' read -ra DBS <<< "$POSTGRES_MULTIPLE_DATABASES"
  for db in "${DBS[@]}"; do
    db="$(echo "$db" | xargs)"
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" <<EOSQL
      SELECT 'CREATE DATABASE ${db}'
      WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${db}')\gexec
EOSQL
  done
fi
