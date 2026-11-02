"""Basit SQLite veritabanı katmanı (ayarlar, uyarılar, yasaklı kelimeler)."""
import os
import sqlite3
import time

DB_PATH = os.getenv("DB_PATH", "data.db")

_conn = sqlite3.connect(DB_PATH, check_same_thread=False)
_conn.row_factory = sqlite3.Row
_conn.executescript(
    """
    CREATE TABLE IF NOT EXISTS settings (
        guild_id INTEGER NOT NULL,
        key TEXT NOT NULL,
        value TEXT,
        PRIMARY KEY (guild_id, key)
    );
    CREATE TABLE IF NOT EXISTS warnings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        guild_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL,
        mod_id INTEGER NOT NULL,
        reason TEXT,
        created_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS badwords (
        guild_id INTEGER NOT NULL,
        word TEXT NOT NULL,
        PRIMARY KEY (guild_id, word)
    );
    """
)
_conn.commit()


# ---------- Ayarlar ----------
def get_setting(guild_id: int, key: str, default=None):
    row = _conn.execute(
        "SELECT value FROM settings WHERE guild_id=? AND key=?", (guild_id, key)
    ).fetchone()
    return row["value"] if row and row["value"] is not None else default


def set_setting(guild_id: int, key: str, value) -> None:
    """value=None verilirse ayar silinir."""
    if value is None:
        _conn.execute("DELETE FROM settings WHERE guild_id=? AND key=?", (guild_id, key))
    else:
        _conn.execute(
            "INSERT INTO settings (guild_id, key, value) VALUES (?, ?, ?) "
            "ON CONFLICT(guild_id, key) DO UPDATE SET value=excluded.value",
            (guild_id, key, str(value)),
        )
    _conn.commit()


def get_channel_id(guild_id: int, key: str):
    value = get_setting(guild_id, key)
    return int(value) if value else None


def flag(guild_id: int, key: str) -> bool:
    return get_setting(guild_id, key) == "1"


# ---------- Uyarılar ----------
def add_warning(guild_id: int, user_id: int, mod_id: int, reason: str) -> int:
    """Uyarıyı ekler ve kullanıcının toplam uyarı sayısını döndürür."""
    _conn.execute(
        "INSERT INTO warnings (guild_id, user_id, mod_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
        (guild_id, user_id, mod_id, reason, int(time.time())),
    )
    _conn.commit()
    return count_warnings(guild_id, user_id)


def count_warnings(guild_id: int, user_id: int) -> int:
    row = _conn.execute(
        "SELECT COUNT(*) AS c FROM warnings WHERE guild_id=? AND user_id=?", (guild_id, user_id)
    ).fetchone()
    return row["c"]


def list_warnings(guild_id: int, user_id: int):
    return _conn.execute(
        "SELECT id, mod_id, reason, created_at FROM warnings "
        "WHERE guild_id=? AND user_id=? ORDER BY id DESC LIMIT 25",
        (guild_id, user_id),
    ).fetchall()


def delete_warning(guild_id: int, warning_id: int) -> bool:
    cur = _conn.execute("DELETE FROM warnings WHERE guild_id=? AND id=?", (guild_id, warning_id))
    _conn.commit()
    return cur.rowcount > 0


def clear_warnings(guild_id: int, user_id: int) -> int:
    cur = _conn.execute("DELETE FROM warnings WHERE guild_id=? AND user_id=?", (guild_id, user_id))
    _conn.commit()
    return cur.rowcount


# ---------- Yasaklı kelimeler ----------
def add_badword(guild_id: int, word: str) -> None:
    _conn.execute("INSERT OR IGNORE INTO badwords (guild_id, word) VALUES (?, ?)", (guild_id, word))
    _conn.commit()


def remove_badword(guild_id: int, word: str) -> bool:
    cur = _conn.execute("DELETE FROM badwords WHERE guild_id=? AND word=?", (guild_id, word))
    _conn.commit()
    return cur.rowcount > 0


def list_badwords(guild_id: int):
    rows = _conn.execute("SELECT word FROM badwords WHERE guild_id=?", (guild_id,)).fetchall()
    return [r["word"] for r in rows]
