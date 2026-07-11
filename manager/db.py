"""manager.db 连接与建表。管理程序自身状态，不碰各账号的配置/数据。"""
import sqlite3
from datetime import datetime

from config import DB_PATH


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    conn = get_conn()
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            nickname    TEXT NOT NULL UNIQUE,
            dir_path    TEXT NOT NULL,
            version     TEXT,
            exe_name    TEXT DEFAULT 'GUI-BilibiliDanmuRobot.exe',
            has_token   INTEGER DEFAULT 0,
            roomid      TEXT,
            robotname   TEXT,
            robotmode   TEXT,
            created_at  TEXT,
            updated_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS process_state (
            account_id  INTEGER PRIMARY KEY,
            pid         INTEGER,
            started_at  TEXT,
            last_status TEXT,
            FOREIGN KEY(account_id) REFERENCES accounts(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS op_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id  INTEGER,
            action      TEXT,
            detail      TEXT,
            created_at  TEXT
        );
        """
    )
    conn.commit()
    conn.close()


def log_op(account_id, action, detail=""):
    """记录操作审计日志。"""
    conn = get_conn()
    conn.execute(
        "INSERT INTO op_log(account_id, action, detail, created_at) VALUES(?,?,?,?)",
        (account_id, action, detail, datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    conn.close()
