# -*- coding: utf-8 -*-
"""_apply-migration.py — apply a .sql file to the Supabase Postgres directly.

Needs a DB connection string (Supabase -> Settings -> Database -> Connection string,
URI form). Pass it via env LES_DB_URL or --db-url. The anon REST key cannot run DDL,
so this is the way to create the onboarding tables.

    set LES_DB_URL=postgresql://postgres:...@db.<ref>.supabase.co:5432/postgres
    py scripts/_apply-migration.py supabase/migration_005_onboarding.sql
"""
import sys, os, argparse
from pathlib import Path
import psycopg2

ap = argparse.ArgumentParser()
ap.add_argument("sql_file")
ap.add_argument("--db-url", default=os.environ.get("LES_DB_URL"))
args = ap.parse_args()

if not args.db_url:
    print("ERROR: set LES_DB_URL or pass --db-url (Supabase Settings -> Database -> Connection string)")
    sys.exit(2)

sql = Path(args.sql_file).read_text(encoding="utf-8")
conn = psycopg2.connect(args.db_url)
conn.autocommit = True
with conn.cursor() as cur:
    cur.execute(sql)
print(f"applied {args.sql_file}")
conn.close()
