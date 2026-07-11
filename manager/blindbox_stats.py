"""盲盒盈亏按自然月统计（只读各账号 db/sqliteDataBase.db）。

按主播划分，不跨主播整合：每次只返回单个主播的统计。
表结构：blind_<roomid>(id, uid, blind_box_name, price, original_gift_price, cnt, year, month, day)
- price=开盒实际得到的礼物价值（随机）
- original_gift_price=盲盒固定原价
- cnt=该行聚合的开盒次数（总数必须用 SUM(cnt)）
- year/month/day=已拆分的整数日期，按自然月聚合直接 GROUP BY year, month
- 金额单位：1000 = 1 元
跳过 blind_3（空模板表）。
"""
import os
import re
import sqlite3
from collections import defaultdict

from config import PRICE_UNIT
from db import get_conn
import paths

_TABLE_RE = re.compile(r"^blind_\d+$")


def _ro_connect(path):
    """以只读方式打开 sqlite，绝不写入。"""
    try:
        uri = "file:" + path.replace("\\", "/") + "?mode=ro"
        return sqlite3.connect(uri, uri=True)
    except Exception:
        return sqlite3.connect(path)


def _list_blind_tables(conn):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'blind_%'")
    tables = [r[0] for r in cur.fetchall()]
    return [t for t in tables if _TABLE_RE.match(t) and t != "blind_3"]


def _safe_query(conn, sql):
    try:
        return conn.execute(sql).fetchall()
    except Exception:
        return []


def _zero():
    return {"opens": 0, "cost": 0, "income": 0, "profit": 0}


def _add(slot, opens, cost, income, profit):
    slot["opens"] += opens or 0
    slot["cost"] += cost or 0
    slot["income"] += income or 0
    slot["profit"] += profit or 0


def get_streamer_stats(account, year=None):
    """单主播统计（year 可选过滤，作用于月度与盲盒排行）。"""
    db_path = os.path.join(paths.workdir(account), "db", "sqliteDataBase.db")
    monthly = defaultdict(_zero)         # (y,m) -> slot
    boxes_cells = defaultdict(_zero)     # (name, y, m) -> slot
    if os.path.exists(db_path):
        try:
            conn = _ro_connect(db_path)
        except Exception:
            conn = None
        if conn:
            try:
                for tbl in _list_blind_tables(conn):
                    # 自然月聚合
                    for y, m, opens, cost, income, profit in _safe_query(conn, (
                        f'SELECT year, month, SUM(cnt), SUM(original_gift_price*cnt), '
                        f'SUM(price*cnt), SUM((price-original_gift_price)*cnt) '
                        f'FROM "{tbl}" GROUP BY year, month')):
                        if y is None:
                            continue
                        if year is not None and int(y) != int(year):
                            continue
                        _add(monthly[(int(y), int(m))], opens, cost, income, profit)
                    # 按盲盒名+年+月聚合（便于按年过滤盲盒排行）
                    for name, y, m, opens, cost, income, profit in _safe_query(conn, (
                        f'SELECT blind_box_name, year, month, SUM(cnt), SUM(original_gift_price*cnt), '
                        f'SUM(price*cnt), SUM((price-original_gift_price)*cnt) '
                        f'FROM "{tbl}" GROUP BY blind_box_name, year, month')):
                        if not name or y is None:
                            continue
                        if year is not None and int(y) != int(year):
                            continue
                        _add(boxes_cells[(name, int(y), int(m))], opens, cost, income, profit)
            finally:
                conn.close()

    # 组装
    monthly_list = [{"year": y, "month": m, **v} for (y, m), v in sorted(monthly.items())]
    total = _zero()
    for v in monthly.values():
        for k in total:
            total[k] += v[k]
    # 盲盒名汇总（聚合各月）
    box_agg = defaultdict(_zero)
    for (name, _y, _m), v in boxes_cells.items():
        _add(box_agg[name], v["opens"], v["cost"], v["income"], v["profit"])
    boxes_list = [{"name": n, **v} for n, v in sorted(box_agg.items(), key=lambda kv: kv[1]["profit"], reverse=True)]
    months = [{"year": y, "month": m} for (y, m) in sorted(monthly.keys())]
    return {"monthly": monthly_list, "total": total, "boxes": boxes_list, "months": months}


def get_dashboard(account_id=None, year=None):
    """返回 {streamers:[...], current:{...}|None, unit}。按主播，不整合。"""
    conn = get_conn()
    rows = conn.execute("SELECT id, nickname, roomid FROM accounts ORDER BY id").fetchall()
    conn.close()
    streamers = [{"id": r["id"], "nickname": r["nickname"], "roomid": r["roomid"]} for r in rows]

    current = None
    if account_id:
        conn = get_conn()
        acc = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
        conn.close()
        if acc:
            stats = get_streamer_stats(dict(acc), year)
            current = {"id": acc["id"], "nickname": acc["nickname"], "roomid": acc["roomid"], **stats}
    return {"streamers": streamers, "current": current, "unit": PRICE_UNIT}
