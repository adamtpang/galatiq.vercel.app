"""Create or refresh inventory.db from config/seed.sql. Idempotent.

Usage: python scripts/init_db.py [--path inventory.db]
"""
import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from invoice_agents.db import db_path, init_db  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--path", default=None)
    args = ap.parse_args()
    p = init_db(args.path or db_path())
    with sqlite3.connect(p) as conn:
        rows = conn.execute("SELECT item, stock, unit_price FROM inventory ORDER BY item").fetchall()
    print(f"Initialized {p}")
    for item, stock, price in rows:
        print(f"  {item:<10} stock={stock:<4} price={price}")
