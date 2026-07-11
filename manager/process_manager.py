"""exe 进程启停与监控。

默认启动 GUI 版 exe（会弹窗，与手动双击一致）。通过 exe 全路径匹配进程，
因此即使用户手动双击启动也能被识别为"运行中"。停止则优先用记录的 pid，
找不到时按 exe 路径扫描后终止。
"""
import os
import sys
import subprocess
import threading
import time

import psutil

from config import WATCHDOG_ENABLED, WATCHDOG_INTERVAL
from db import get_conn, log_op
import paths

# Windows 进程创建标志：脱离父进程控制，Flask 退出后机器人继续运行
_CREATE_NEW_PROCESS_GROUP = 0x00000200
_DETACHED_PROCESS = 0x00000008


def _exe_full_path(account):
    # 兼容嵌套目录：exe 与 etc/token 同在 workdir 下
    return os.path.join(paths.workdir(account), account["exe_name"])


def _norm(p):
    return os.path.normpath(p).lower() if p else p


def _scan_running():
    """扫描一次所有进程，返回 {exe_path_norm: pid}。"""
    running = {}
    for p in psutil.process_iter(["pid", "exe"]):
        try:
            exe = p.info.get("exe")
            if exe:
                running[_norm(exe)] = p.info["pid"]
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return running


def _find_pid(account, running=None):
    """返回该账号当前运行的 pid（无则 None）。"""
    running = running if running is not None else _scan_running()
    exe = _norm(_exe_full_path(account))
    return running.get(exe)


# --------------------------------------------------------------------------- #
# 状态
# --------------------------------------------------------------------------- #
def is_alive(account, running=None):
    return _find_pid(account, running) is not None


def status_all():
    """返回 {account_id: {"running":bool, "pid":int|None}}。"""
    running = _scan_running()
    conn = get_conn()
    rows = conn.execute("SELECT id, dir_path, exe_name FROM accounts").fetchall()
    conn.close()
    out = {}
    for r in rows:
        acc = {"dir_path": r["dir_path"], "exe_name": r["exe_name"]}
        exe = _norm(os.path.join(paths.workdir(acc), r["exe_name"]))
        pid = running.get(exe)
        out[r["id"]] = {"running": pid is not None, "pid": pid}
    return out


def _persist_state(account_id, pid, status):
    conn = get_conn()
    conn.execute(
        "INSERT INTO process_state(account_id,pid,started_at,last_status) VALUES(?,?,?,?) "
        "ON CONFLICT(account_id) DO UPDATE SET pid=excluded.pid,last_status=excluded.last_status",
        (account_id, pid, time.strftime("%Y-%m-%d %H:%M:%S"), status),
    )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- #
# 启动
# --------------------------------------------------------------------------- #
def start(account):
    """启动账号 exe。已在运行则直接返回。"""
    running = _scan_running()
    if _find_pid(account, running) is not None:
        return {"ok": True, "msg": "已在运行", "pid": _find_pid(account, running)}

    exe = _exe_full_path(account)
    if not os.path.exists(exe):
        return {"ok": False, "msg": f"exe 不存在：{exe}"}

    flags = 0
    kwargs = {}
    if sys.platform == "win32":
        flags = _DETACHED_PROCESS | _CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(
            [exe],
            cwd=paths.workdir(account),  # 嵌套账号的工作目录在子文件夹里
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            **kwargs,
        )
    except Exception as e:
        return {"ok": False, "msg": f"启动失败：{e}"}

    _persist_state(account["id"], proc.pid, "running")
    log_op(account["id"], "start", f"pid={proc.pid}")
    return {"ok": True, "msg": "已启动", "pid": proc.pid}


def start_all():
    rows = _all_accounts()
    results = []
    for r in rows:
        results.append({"id": r["id"], "nickname": r["nickname"], **start(dict(r))})
    return results


def start_selected(ids):
    rows = _all_accounts(ids)
    return [{"id": r["id"], "nickname": r["nickname"], **start(dict(r))} for r in rows]


# --------------------------------------------------------------------------- #
# 停止
# --------------------------------------------------------------------------- #
def stop(account):
    running = _scan_running()
    pid = _find_pid(account, running)
    if pid is None:
        _persist_state(account["id"], None, "stopped")
        return {"ok": True, "msg": "未在运行"}
    try:
        p = psutil.Process(pid)
        p.terminate()  # Windows 等价 TerminateProcess
        try:
            p.wait(timeout=5)
        except Exception:
            p.kill()
    except psutil.NoSuchProcess:
        pass
    except Exception as e:
        return {"ok": False, "msg": f"停止失败：{e}"}
    _persist_state(account["id"], None, "stopped")
    log_op(account["id"], "stop", f"pid={pid}")
    return {"ok": True, "msg": "已停止", "pid": pid}


def stop_all():
    rows = _all_accounts()
    return [{"id": r["id"], "nickname": r["nickname"], **stop(dict(r))} for r in rows]


def stop_selected(ids):
    rows = _all_accounts(ids)
    return [{"id": r["id"], "nickname": r["nickname"], **stop(dict(r))} for r in rows]


# --------------------------------------------------------------------------- #
# 重启
# --------------------------------------------------------------------------- #
def restart(account):
    stop(account)
    time.sleep(1)
    return start(account)


# --------------------------------------------------------------------------- #
# 查询辅助
# --------------------------------------------------------------------------- #
def _all_accounts(ids=None):
    conn = get_conn()
    if ids:
        rows = conn.execute(
            "SELECT * FROM accounts WHERE id IN (%s) ORDER BY id" % ",".join("?" * len(ids)),
            ids,
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
    conn.close()
    return rows


# --------------------------------------------------------------------------- #
# 看门狗（可选）
# --------------------------------------------------------------------------- #
def _watchdog_loop():
    while True:
        try:
            if WATCHDOG_ENABLED:
                running = _scan_running()
                conn = get_conn()
                rows = conn.execute(
                    "SELECT a.* FROM accounts a JOIN process_state p ON a.id=p.account_id WHERE p.last_status='running'"
                ).fetchall()
                conn.close()
                for r in rows:
                    if _find_pid(dict(r), running) is None:
                        # 崩溃了，重启
                        _persist_state(r["id"], None, "crashed")
                        start(dict(r))
        except Exception:
            pass
        time.sleep(WATCHDOG_INTERVAL)


def start_watchdog():
    t = threading.Thread(target=_watchdog_loop, daemon=True)
    t.start()
