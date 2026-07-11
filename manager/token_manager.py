"""Token / 登录凭证管理（针对 token/ 下的 bili_token 文件，非配置文件）。

bili_token.json: {"DedeUserID":...,"SESSDATA":...,"bili_jct":...,...}
bili_token.txt:  "DedeUserID=...;SESSDATA=...;bili_jct=...;..."
"""
import json
import os

import requests

from config import BILIBILI_NAV_API
from db import get_conn, log_op
import paths

# 用于登录态校验的关键 cookie 字段
_COOKIE_KEYS = ["SESSDATA", "bili_jct", "DedeUserID", "sid", "DedeUserID__ckMd5", "sec_ck"]


def _token_dir(account):
    return os.path.join(paths.workdir(account), "token")


def _json_path(account):
    return os.path.join(_token_dir(account), "bili_token.json")


def _txt_path(account):
    return os.path.join(_token_dir(account), "bili_token.txt")


def has_token(account):
    p = _json_path(account)
    if not os.path.exists(p):
        return False
    try:
        return os.path.getsize(p) > 5
    except OSError:
        return False


def read_token(account):
    """读取 token。返回 {"has_token":bool, "json":dict|None, "txt":str|None}。不回传敏感值到日志。"""
    jp, tp = _json_path(account), _txt_path(account)
    out = {"has_token": False, "json": None, "txt": None}
    if os.path.exists(jp):
        try:
            with open(jp, "r", encoding="utf-8", errors="replace") as f:
                out["json"] = json.load(f)
            out["has_token"] = bool(out["json"])
        except Exception:
            out["json"] = None
    if os.path.exists(tp):
        try:
            with open(tp, "r", encoding="utf-8", errors="replace") as f:
                out["txt"] = f.read().strip()
        except Exception:
            out["txt"] = None
    return out


def _parse_raw(raw):
    """把用户粘贴的内容统一解析成 dict。支持 JSON 或 k=v; 文本。"""
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("{"):
        try:
            d = json.loads(raw)
            return d if isinstance(d, dict) else None
        except Exception:
            return None
    # k=v; 形式
    d = {}
    for kv in raw.replace("\n", ";").split(";"):
        kv = kv.strip()
        if "=" in kv:
            k, v = kv.split("=", 1)
            d[k.strip()] = v.strip()
    return d or None


def _dict_to_txt(d):
    return "".join(f"{k}={v};" for k, v in d.items())


def import_token(account, raw):
    """导入 token：解析后同时写 json 与 txt 两份（兼容原项目）。"""
    d = _parse_raw(raw)
    if not d:
        return {"ok": False, "msg": "无法解析 token（需 JSON 或 k=v; 文本）"}
    os.makedirs(_token_dir(account), exist_ok=True)
    # 敏感数据只写文件，不记日志
    with open(_json_path(account), "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)
    with open(_txt_path(account), "w", encoding="utf-8") as f:
        f.write(_dict_to_txt(d))
    # 更新注册表 has_token
    conn = get_conn()
    conn.execute("UPDATE accounts SET has_token=1 WHERE id=?", (account["id"],))
    conn.commit()
    conn.close()
    log_op(account["id"], "token_import", "已写入 token 文件")
    return {"ok": True, "msg": "Token 已导入"}


def batch_import_tokens(mapping):
    """mapping: {account_id: raw_str}。返回 {success:[id], failed:[{id,msg}]}。"""
    from account_manager import get_account
    success, failed = [], []
    for aid, raw in mapping.items():
        acc = get_account(int(aid))
        if not acc:
            failed.append({"id": aid, "msg": "账号不存在"})
            continue
        r = import_token(acc, raw)
        (success if r["ok"] else failed).append(aid if r["ok"] else {"id": aid, "msg": r["msg"]})
    return {"success": success, "failed": failed}


def validate_login(account):
    """用 cookie 调 B站 nav 接口校验登录态。返回 {logged_in, uid, uname} 或 {expired}。"""
    data = read_token(account)
    if not data["has_token"] or not data["json"]:
        return {"logged_in": False, "reason": "无 token，请先导入或在 GUI 扫码登录"}
    d = data["json"]
    sessdata = d.get("SESSDATA")
    if not sessdata:
        return {"logged_in": False, "reason": "token 缺少 SESSDATA"}
    cookie = {k: d[k] for k in _COOKIE_KEYS if d.get(k)}
    try:
        resp = requests.get(BILIBILI_NAV_API, cookies=cookie, timeout=8,
                            headers={"User-Agent": "Mozilla/5.0"})
        body = resp.json()
    except Exception as e:
        return {"logged_in": False, "reason": f"请求失败：{e}"}
    code = body.get("code")
    if code == -101:
        return {"logged_in": False, "reason": "登录已过期，请重新登录"}
    if code == 0:
        info = body.get("data") or {}
        return {"logged_in": True, "uid": info.get("mid"), "uname": info.get("uname")}
    return {"logged_in": False, "reason": f"未知响应 code={code}: {body.get('message','')}"}
