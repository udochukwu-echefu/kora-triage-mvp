#!/bin/sh
set -e

if [ "$(id -u)" = "0" ]; then
  database_path="${KORA_DATABASE_PATH:-data/kora.db}"
  case "$database_path" in
    /*) ;;
    *) database_path="/app/backend/$database_path" ;;
  esac
  database_dir="$(dirname "$database_path")"
  # Mounted volumes (e.g. Railway's /data) are created root-owned.
  mkdir -p "$database_dir"
  chown -R kora:kora "$database_dir"
  exec setpriv --reuid=kora --regid=kora --init-groups "$0" "$@"
fi

exec uvicorn app.main:app --app-dir backend --host 0.0.0.0 --port "${PORT:-8000}"
