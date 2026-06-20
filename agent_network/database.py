"""
数据库初始化与连接管理
"""
import sqlite3
import os
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "agent_network.db"


def get_connection() -> sqlite3.Connection:
    """获取数据库连接"""
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row  # 返回字典式 Row 对象
    conn.execute("PRAGMA journal_mode=WAL")  # 并发读更好
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """初始化数据库表结构"""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS agents (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id        TEXT UNIQUE NOT NULL,
            agent_type      TEXT NOT NULL,
            display_name    TEXT,
            public_key      TEXT NOT NULL,
            endpoint        TEXT NOT NULL,
            is_active       INTEGER NOT NULL DEFAULT 1,
            registered_at   TEXT NOT NULL,
            updated_at      TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS capabilities (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id        TEXT NOT NULL REFERENCES agents(agent_id),
            skill           TEXT NOT NULL,
            description     TEXT,
            UNIQUE(agent_id, skill)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id              TEXT PRIMARY KEY,
            from_agent      TEXT NOT NULL,
            to_agent        TEXT NOT NULL,
            intent          TEXT NOT NULL,
            payload         TEXT NOT NULL,
            in_reply_to     TEXT,
            signature       TEXT NOT NULL,
            timestamp       TEXT NOT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_agents_agent_id ON agents(agent_id);
        CREATE INDEX IF NOT EXISTS idx_capabilities_skill ON capabilities(skill);
        CREATE INDEX IF NOT EXISTS idx_messages_to ON messages(to_agent);
    """)
    conn.commit()
    conn.close()
