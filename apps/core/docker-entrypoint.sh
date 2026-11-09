#!/bin/sh
set -eu

# Apply migrations automatically only for the LOCAL database. The cloud
# database is never migrated implicitly.
if [ "${ULTRON_RUN_MIGRATIONS_ON_START:-false}" = "true" ]; then
  if [ "${ULTRON_DB_MODE:-local}" = "local" ]; then
    ultron-core migrate
  else
    echo "ULTRON_DB_MODE=${ULTRON_DB_MODE}: skipping automatic migrations (run them explicitly)."
  fi
fi

exec "$@"
