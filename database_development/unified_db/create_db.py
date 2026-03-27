"""Initialize the unified metadata SQLite database from schema.sql."""

import sqlite3
import os
import sys

def create_database(db_path: str, schema_path: str, force: bool = False):
    """Create the unified database from schema.sql."""
    if os.path.exists(db_path):
        if force:
            os.remove(db_path)
            print(f"Removed existing database: {db_path}")
        else:
            print(f"Database already exists: {db_path}")
            print("Use --force to recreate.")
            return

    with open(schema_path, 'r') as f:
        schema_sql = f.read()

    conn = sqlite3.connect(db_path)
    conn.executescript(schema_sql)
    conn.close()

    size_mb = os.path.getsize(db_path) / (1024 * 1024)
    print(f"Database created: {db_path} ({size_mb:.2f} MB)")

    # Verify tables
    conn = sqlite3.connect(db_path)
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = [row[0] for row in cursor.fetchall()]
    conn.close()

    print(f"Tables created ({len(tables)}):")
    for t in tables:
        print(f"  - {t}")


if __name__ == '__main__':
    from config import DB_PATH, SCHEMA_PATH

    force = '--force' in sys.argv
    create_database(DB_PATH, SCHEMA_PATH, force=force)
