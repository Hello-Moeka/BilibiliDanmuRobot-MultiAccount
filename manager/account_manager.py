"""账号注册、zip 导入、模板解压、新增账号（建目录+复制模板）、刷新缓存。

红线：新增账号只复制模板的默认 yaml 原样副本，绝不改写配置字段；
      除 zip 导入（解压已有目录）外，不修改任何账号的 bilidanmaku-api.yaml。
"""
import os
import re
import shutil
import threading
import zipfile
from datetime import datetime

import yaml

import config_reader
import paths
from config import ACCOUNTS_DIR, BASE_DIR, DEFAULT_EXE_NAME, DEFAULT_ZIP_PATH, TEMPLATE_DIR
from db import get_conn, init_db, log_op

# 导入进度（单用户本地应用，模块级字典即可）
_import_progress = {"running": False, "done": 0, "total": 0, "current": "",
                    "finished": False, "error": "", "failed": [], "template_error": ""}

# 路径非法字符（Windows）
_ILLEGAL = re.compile(r'[\\/:*?"<>|]')


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #
def _decode_name(info):
    """zip 内中文路径多为 GBK 编码，zipfile 默认按 cp437 解析会乱码，这里还原。"""
    try:
        return info.filename.encode("cp437").decode("gbk")
    except Exception:
        return info.filename


def _parse_topname(top):
    """从顶层目录名拆出昵称与版本。

    如 '白桃GUI-BilibiliDanmuRobot_Windows_amd64_v1.3.10' -> ('白桃', 'v1.3.10')
    如 '贝璐' -> ('贝璐', None)
    """
    marker = "GUI-BilibiliDanmuRobot_Windows_amd64_"
    if marker in top:
        idx = top.index(marker)
        nickname = top[:idx]
        version = top[idx + len(marker):] or None
    else:
        nickname, version = top, None
    return nickname.strip(), version


def _version_from_name(name):
    """从文件名提取 v1.3.x 版本字符串。"""
    m = re.search(r"v(\d+\.\d+\.\d+(?:_\d+)?)", name)
    return "v" + m.group(1) if m else None


def _template_version():
    """读取 data/template/.meta.json 中的模板版本。"""
    import json
    meta = os.path.join(TEMPLATE_DIR, ".meta.json")
    if os.path.exists(meta):
        try:
            with open(meta, "r", encoding="utf-8") as f:
                return json.load(f).get("version")
        except Exception:
            return None
    return None


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------- #
# 账号查询
# --------------------------------------------------------------------------- #
def list_accounts():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM accounts ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_account(account_id):
    conn = get_conn()
    row = conn.execute("SELECT * FROM accounts WHERE id=?", (account_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


# --------------------------------------------------------------------------- #
# zip 扫描（只读预览）
# --------------------------------------------------------------------------- #
def scan_zip(zip_path=DEFAULT_ZIP_PATH):
    """扫描 zip，返回 {accounts:[...], template_zip:bool, path}。不写任何文件。"""
    if not os.path.exists(zip_path):
        raise FileNotFoundError(f"zip 不存在：{zip_path}")

    zf = zipfile.ZipFile(zip_path)
    infos = [(_decode_name(i), i) for i in zf.infolist()]

    # 按顶层段分组
    groups = {}  # top -> list of (name, info)
    template_member = None
    for name, info in infos:
        if not name:
            continue
        top = name.split("/")[0]
        if top.endswith(".zip"):
            # 嵌套干净模板
            if "GUI-BilibiliDanmuRobot" in top:
                template_member = info
            continue
        groups.setdefault(top, []).append((name, info))

    detected = []
    for top, members in groups.items():
        # 判定是否为账号目录：含 etc/bilidanmaku-api.yaml
        yaml_member = None
        token_member = None
        for name, info in members:
            low = name.lower()
            if low.endswith("etc/bilidanmaku-api.yaml"):
                yaml_member = info
            elif low.endswith("token/bili_token.json"):
                token_member = info
        if yaml_member is None:
            continue  # 非账号目录

        nickname, version = _parse_topname(top)
        roomid = robotname = robotmode = None
        has_token = False
        try:
            data = zf.read(yaml_member).decode("utf-8", errors="replace")
            cfg = yaml.safe_load(data)
            if cfg:
                roomid = config_reader._ci_get(cfg, "roomid")
                robotname = config_reader._ci_get(cfg, "robotname")
                robotmode = config_reader._ci_get(cfg, "robotmode")
        except Exception:
            pass
        if token_member is not None:
            try:
                has_token = len(zf.read(token_member)) > 5
            except Exception:
                has_token = False

        detected.append({
            "nickname": nickname,
            "version": version,
            "top_name": top,
            "roomid": str(roomid) if roomid is not None else None,
            "robotname": robotname,
            "robotmode": robotmode,
            "has_token": has_token,
            "member_count": len(members),
        })

    zf.close()
    return {
        "path": zip_path,
        "template_zip": template_member is not None,
        "accounts": detected,
    }


# --------------------------------------------------------------------------- #
# 模板解压
# --------------------------------------------------------------------------- #
def _find_template_files():
    """在 data/template/ 下定位 exe / yaml / upgrader。返回 dict，可能为空。"""
    result = {"exe": None, "yaml": None, "upgrader": None}
    for root, _dirs, files in os.walk(TEMPLATE_DIR):
        for fn in files:
            full = os.path.join(root, fn)
            low = fn.lower()
            if low.endswith(".exe") and "guibilibilidanmurobot" in low.replace("-", ""):
                result["exe"] = full
            elif low == "bilidanmaku-api.yaml":
                result["yaml"] = full
            elif low == "upgrader.exe":
                result["upgrader"] = full
    return result


def load_template(zip_path=DEFAULT_ZIP_PATH, force=False):
    """从大 zip 内解出嵌套的干净模板 zip 到 data/template/。"""
    tfiles = _find_template_files()
    if tfiles["exe"] and tfiles["yaml"] and not force:
        return {"ok": True, "msg": "模板已就绪", "files": tfiles}

    if not os.path.exists(zip_path):
        return {"ok": False, "msg": f"zip 不存在：{zip_path}", "files": tfiles}

    zf = zipfile.ZipFile(zip_path)
    template_member = None
    template_version = None
    for info in zf.infolist():
        name = _decode_name(info)
        if name.endswith(".zip") and "GUI-BilibiliDanmuRobot" in name:
            template_member = info
            template_version = _version_from_name(name)
            break

    if template_member is None:
        zf.close()
        return {"ok": False, "msg": "未在 zip 中找到干净模板包", "files": tfiles}

    # 清空模板目录
    if os.path.exists(TEMPLATE_DIR):
        shutil.rmtree(TEMPLATE_DIR)
    os.makedirs(TEMPLATE_DIR, exist_ok=True)

    # 读取嵌套 zip 字节并解压到模板目录
    nested_bytes = zf.read(template_member)
    zf.close()

    import io
    nested = zipfile.ZipFile(io.BytesIO(nested_bytes))
    names = [(_decode_name(i), i) for i in nested.infolist()]
    # 若嵌套 zip 内有单一顶层目录，则下钻一层
    tops = set()
    for name, _info in names:
        if name and "/" in name:
            tops.add(name.split("/")[0])
        elif name:
            tops.add(name)
    flatten = len(tops) == 1 and not any(
        n == list(tops)[0] for n, _ in names if "/" not in n and n
    )

    for name, info in names:
        if not name or name.endswith("/"):
            continue
        parts = name.split("/")
        if flatten and len(parts) > 1:
            parts = parts[1:]
        dest = os.path.join(TEMPLATE_DIR, *parts)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as f:
            f.write(nested.read(info))
    nested.close()

    # 记录模板版本元数据，供新增账号引用
    if template_version:
        import json
        with open(os.path.join(TEMPLATE_DIR, ".meta.json"), "w", encoding="utf-8") as f:
            json.dump({"version": template_version}, f, ensure_ascii=False)

    tfiles = _find_template_files()
    return {"ok": bool(tfiles["exe"] and tfiles["yaml"]), "msg": "模板解压完成" if tfiles["exe"] else "解压后未找到 exe", "files": tfiles}


# --------------------------------------------------------------------------- #
# 导入（后台带进度）
# --------------------------------------------------------------------------- #
def import_progress():
    return dict(_import_progress)


def import_all(zip_path=DEFAULT_ZIP_PATH, skip_logs=True):
    """启动后台导入。返回立即，进度通过 import_progress() 查询。"""
    if _import_progress["running"]:
        return {"ok": False, "msg": "已有导入任务在运行"}
    t = threading.Thread(target=_import_all_worker, args=(zip_path, skip_logs), daemon=True)
    t.start()
    return {"ok": True, "msg": "导入已启动"}


def _import_all_worker(zip_path, skip_logs):
    _import_progress.update(running=True, done=0, total=0, current="初始化",
                            finished=False, error="", failed=[], template_error="")
    try:
        scan = scan_zip(zip_path)
        accounts = scan["accounts"]
        _import_progress["total"] = len(accounts)

        # 先解压模板；失败不致命（仅影响后续新增账号，不影响已导入账号运行）
        _import_progress["current"] = "解压模板"
        try:
            load_template(zip_path)
        except Exception as e:
            _import_progress["template_error"] = f"模板解压失败（不影响导入）：{type(e).__name__}: {e}"

        zf = zipfile.ZipFile(zip_path)
        infos = [(_decode_name(i), i) for i in zf.infolist()]

        # 建顶层->成员索引
        groups = {}
        for name, info in infos:
            if not name:
                continue
            top = name.split("/")[0]
            if top.endswith(".zip"):
                continue
            groups.setdefault(top, []).append((name, info))

        done = 0
        failed = []
        for acc in accounts:
            top = acc["top_name"]
            nick = acc["nickname"]
            _import_progress["current"] = f"导入 {nick}"
            members = groups.get(top, [])
            dest_root = os.path.join(ACCOUNTS_DIR, nick)
            try:
                # 若已存在则先清空（以 zip 为准）
                if os.path.exists(dest_root):
                    shutil.rmtree(dest_root)
                os.makedirs(dest_root, exist_ok=True)

                for name, info in members:
                    if name.endswith("/"):
                        continue
                    parts = name.split("/")
                    rest = parts[1:]
                    # 剥离嵌套层
                    if len(rest) > 1 and rest[0].startswith("GUI-BilibiliDanmuRobot_Windows_amd64_"):
                        rest = rest[1:]
                    if skip_logs and rest and rest[0] == "logs":
                        continue
                    dest = os.path.join(dest_root, *rest)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    with open(dest, "wb") as f:
                        f.write(zf.read(info))

                # 写注册表
                _upsert_account({
                    "nickname": nick,
                    "dir_path": dest_root,
                    "version": acc["version"],
                    "exe_name": DEFAULT_EXE_NAME,
                    "has_token": 1 if acc["has_token"] else 0,
                    "roomid": acc["roomid"],
                    "robotname": acc["robotname"],
                    "robotmode": acc["robotmode"],
                })
                log_op(None, "import", f"{nick} (roomid={acc['roomid']})")
                done += 1
                _import_progress["done"] = done
            except Exception as e:
                # 单账号失败不连累其余，继续导入下一个
                failed.append({"nickname": nick, "error": f"{type(e).__name__}: {e}"})
                _import_progress["failed"] = list(failed)

        zf.close()
        if failed:
            _import_progress["current"] = f"完成（{len(failed)} 个失败）"
        else:
            _import_progress["current"] = "完成"
    except Exception as e:
        _import_progress["error"] = f"{type(e).__name__}: {e}"
        _import_progress["current"] = "出错"
    finally:
        _import_progress["running"] = False
        _import_progress["finished"] = True


def _upsert_account(a):
    # 存相对项目根的路径，便于整体迁移
    rel_dir = os.path.relpath(a["dir_path"], BASE_DIR) if os.path.isabs(a["dir_path"]) else a["dir_path"]
    conn = get_conn()
    now = _now()
    existing = conn.execute("SELECT id FROM accounts WHERE nickname=?", (a["nickname"],)).fetchone()
    if existing:
        conn.execute(
            "UPDATE accounts SET dir_path=?,version=?,exe_name=?,has_token=?,roomid=?,robotname=?,robotmode=?,updated_at=? WHERE id=?",
            (rel_dir, a["version"], a["exe_name"], a["has_token"], a["roomid"], a["robotname"], a["robotmode"], now, existing["id"]),
        )
    else:
        conn.execute(
            "INSERT INTO accounts(nickname,dir_path,version,exe_name,has_token,roomid,robotname,robotmode,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (a["nickname"], rel_dir, a["version"], a["exe_name"], a["has_token"], a["roomid"], a["robotname"], a["robotmode"], now, now),
        )
    conn.commit()
    conn.close()


# --------------------------------------------------------------------------- #
# 新增账号（建目录 + 复制模板，不写配置/不写 token）
# --------------------------------------------------------------------------- #
def _validate_nickname(nickname):
    if not nickname or not nickname.strip():
        return "昵称不能为空"
    nick = nickname.strip()
    if _ILLEGAL.search(nick):
        return "昵称含非法字符 \\ / : * ? \" < > |"
    # 不能与已存在目录或注册表重名
    conn = get_conn()
    row = conn.execute("SELECT id FROM accounts WHERE nickname=?", (nick,)).fetchone()
    conn.close()
    if row:
        return f"昵称已存在：{nick}"
    if os.path.exists(os.path.join(ACCOUNTS_DIR, nick)):
        return f"目录已存在：{nick}"
    return None


def create_account(nickname, auto_start=False):
    """新增账号：自动建目录骨架 + 从模板复制 exe 与默认 yaml（原样不改）+ 注册。

    不写配置、不写 token；首次启动 GUI 由用户自行配置 roomid/扫码登录。
    """
    err = _validate_nickname(nickname)
    if err:
        return {"ok": False, "msg": err}
    nick = nickname.strip()

    # 确保模板就绪
    tfiles = _find_template_files()
    if not tfiles["exe"] or not tfiles["yaml"]:
        r = load_template()
        if not r["ok"]:
            return {"ok": False, "msg": "模板未就绪，请先从 zip 导入或解压模板：" + r["msg"]}
        tfiles = _find_template_files()

    dest_root = os.path.join(ACCOUNTS_DIR, nick)
    # 建目录骨架
    for sub in ("etc", "token", "db", os.path.join("logs", "applog")):
        os.makedirs(os.path.join(dest_root, sub), exist_ok=True)
    # 复制 exe（保留元数据）
    shutil.copy2(tfiles["exe"], os.path.join(dest_root, os.path.basename(tfiles["exe"])))
    # 复制默认 yaml 原样（不改字段）
    shutil.copy2(tfiles["yaml"], os.path.join(dest_root, "etc", "bilidanmaku-api.yaml"))
    # 复制 upgrader（若有）
    if tfiles.get("upgrader"):
        shutil.copy2(tfiles["upgrader"], os.path.join(dest_root, "upgrader.exe"))

    # 推断模板版本（从模板元数据读取）
    version = _template_version()

    now = _now()
    conn = get_conn()
    conn.execute(
        "INSERT INTO accounts(nickname,dir_path,version,exe_name,has_token,roomid,robotname,robotmode,created_at,updated_at) VALUES(?,?,?,?,0,NULL,NULL,NULL,?,?)",
        (nick, os.path.relpath(dest_root, BASE_DIR), version, DEFAULT_EXE_NAME, now, now),
    )
    conn.commit()
    aid = conn.execute("SELECT id FROM accounts WHERE nickname=?", (nick,)).fetchone()["id"]
    conn.close()
    log_op(aid, "create", f"新增账号目录 {dest_root}")

    result = {"ok": True, "id": aid, "nickname": nick, "dir_path": dest_root}
    if auto_start:
        # 延迟导入避免循环依赖
        import process_manager
        process_manager.start(get_account(aid))
    return result


def create_accounts_batch(nicknames):
    """批量新增。返回 {success:[...], failed:[{nickname, msg}]}。"""
    success, failed = [], []
    for nick in nicknames:
        nick = nick.strip()
        if not nick:
            continue
        r = create_account(nick)
        if r["ok"]:
            success.append(nick)
        else:
            failed.append({"nickname": nick, "msg": r["msg"]})
    return {"success": success, "failed": failed}


# --------------------------------------------------------------------------- #
# 刷新缓存（只读重读 yaml，不写文件）
# --------------------------------------------------------------------------- #
def refresh_account(account_id):
    acc = get_account(account_id)
    if not acc:
        return {"ok": False, "msg": "账号不存在"}
    s = config_reader.get_summary(acc)
    # 同时刷新 has_token
    import token_manager
    has_token = token_manager.has_token(acc)
    conn = get_conn()
    conn.execute(
        "UPDATE accounts SET roomid=?,robotname=?,robotmode=?,has_token=?,updated_at=? WHERE id=?",
        (str(s["roomid"]) if s["roomid"] is not None else None, s["robotname"], s["robotmode"], 1 if has_token else 0, _now(), account_id),
    )
    conn.commit()
    conn.close()
    return {"ok": True, **s, "has_token": has_token}


def refresh_all():
    conn = get_conn()
    rows = conn.execute("SELECT id FROM accounts").fetchall()
    conn.close()
    n = 0
    for r in rows:
        refresh_account(r["id"])
        n += 1
    return {"ok": True, "msg": f"已刷新 {n} 个账号"}


# --------------------------------------------------------------------------- #
# 删除账号
# --------------------------------------------------------------------------- #
def delete_account(account_id, purge_files=True):
    """删除账号。默认同步删除项目目录（含 exe/配置/Token/db/日志）。"""
    acc = get_account(account_id)
    if not acc:
        return {"ok": False, "msg": "账号不存在"}
    # 先停止进程
    import process_manager
    try:
        process_manager.stop(acc)
    except Exception:
        pass
    conn = get_conn()
    conn.execute("DELETE FROM accounts WHERE id=?", (account_id,))
    conn.commit()
    conn.close()
    abs_dir = paths.account_dir(acc)
    if purge_files and os.path.exists(abs_dir):
        shutil.rmtree(abs_dir)
    log_op(account_id, "delete", f"purge={purge_files} dir={abs_dir}")
    return {"ok": True, "msg": f"已删除 {acc['nickname']}（{ '并移除目录' if purge_files else '保留目录' }）"}


def migrate_to_relative_paths():
    """一次性迁移：把 accounts.dir_path 中的绝对路径转为相对 BASE_DIR 的相对路径。

    使已导入的旧数据也能随项目整体迁移到任意目录/盘符。
    """
    conn = get_conn()
    rows = conn.execute("SELECT id, dir_path FROM accounts").fetchall()
    changed = 0
    for r in rows:
        p = r["dir_path"]
        if p and os.path.isabs(p):
            try:
                rel = os.path.relpath(p, BASE_DIR)
                conn.execute("UPDATE accounts SET dir_path=? WHERE id=?", (rel, r["id"]))
                changed += 1
            except Exception:
                pass
    conn.commit()
    conn.close()
    return changed


# 初始化
init_db()
migrate_to_relative_paths()
