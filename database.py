"""
database.py
===========
SQLite database setup for Guard Pay demo app.
"""

import sqlite3
import os
import hashlib
import random
import string
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "guardpay.db")

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def generate_bvn():
    return "".join(random.choices(string.digits, k=11))

def generate_account_number():
    return "".join(random.choices(string.digits, k=10))

def hash_pin(pin: str) -> str:
    return hashlib.sha256(pin.encode()).hexdigest()

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name       TEXT NOT NULL,
            phone           TEXT UNIQUE NOT NULL,
            bvn             TEXT UNIQUE NOT NULL,
            account_number  TEXT UNIQUE NOT NULL,
            pin_hash        TEXT NOT NULL,
            balance         REAL DEFAULT 50000.0,
            bank            TEXT DEFAULT 'GuardPay',
            state           TEXT DEFAULT 'Lagos',
            created_at      TEXT DEFAULT CURRENT_TIMESTAMP,
            is_admin        INTEGER DEFAULT 0,
            is_blocked      INTEGER DEFAULT 0
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            transaction_ref     TEXT UNIQUE NOT NULL,
            sender_account      TEXT NOT NULL,
            beneficiary_account TEXT NOT NULL,
            amount              REAL NOT NULL,
            channel             TEXT DEFAULT 'mobile_app',
            narration           TEXT,
            status              TEXT DEFAULT 'pending',
            risk_score          REAL DEFAULT 0.0,
            risk_band           TEXT DEFAULT 'LOW',
            recommended_action  TEXT DEFAULT 'ALLOW',
            top_signals         TEXT DEFAULT '[]',
            shap_explanation    TEXT DEFAULT '{}',
            ndpa_note           TEXT DEFAULT '',
            velocity_1h         INTEGER DEFAULT 0,
            velocity_6h         INTEGER DEFAULT 0,
            velocity_24h        INTEGER DEFAULT 0,
            cumulative_24h      REAL DEFAULT 0.0,
            is_new_beneficiary  INTEGER DEFAULT 0,
            sim_age_days        INTEGER DEFAULT 365,
            reviewed_by         TEXT DEFAULT NULL,
            review_action       TEXT DEFAULT NULL,
            review_note         TEXT DEFAULT NULL,
            created_at          TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Create admin account if not exists
    admin_exists = c.execute(
        "SELECT id FROM users WHERE phone = '08000000000'"
    ).fetchone()

    if not admin_exists:
        c.execute("""
            INSERT INTO users
            (full_name, phone, bvn, account_number, pin_hash, balance, state, is_admin)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            "Guard Pay Admin",
            "08000000000",
            generate_bvn(),
            "0000000000",
            hash_pin("0000"),
            999999999.0,
            "Lagos",
            1
        ))

    conn.commit()
    conn.close()
    print("Database initialised.")

if __name__ == "__main__":
    init_db()
