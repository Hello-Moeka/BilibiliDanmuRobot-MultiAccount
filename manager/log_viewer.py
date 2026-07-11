"""日志只读查看（tail）。日志文件多为 GBK 编码，读取时容错。"""
import os

import paths


def _log_dir(account):
    return os.path.join(paths.workdir(account), "logs", "applog")


def list_logs(account):
    """返回日志目录下的文件列表 [{name, size}]，按名降序。"""
    d = _log_dir(account)
    if not os.path.isdir(d):
        return []
    files = []
    for name in os.listdir(d):
        full = os.path.join(d, name)
        if os.path.isfile(full):
            files.append({"name": name, "size": os.path.getsize(full)})
    files.sort(key=lambda x: x["name"], reverse=True)
    return files


def read_log(account, name, tail=300):
    """读取日志末尾若干行。自动尝试 gbk/utf-8 解码。"""
    d = _log_dir(account)
    # 防目录穿越：只取 basename
    safe = os.path.basename(name)
    full = os.path.join(d, safe)
    if not os.path.isfile(full):
        return {"ok": False, "msg": "日志文件不存在", "name": safe, "lines": []}
    try:
        size = os.path.getsize(full)
        # 只读末尾 256KB，避免大日志占用内存
        with open(full, "rb") as f:
            if size > 256 * 1024:
                f.seek(-256 * 1024, os.SEEK_END)
                f.readline()  # 跳过半行
            raw = f.read()
    except Exception as e:
        return {"ok": False, "msg": str(e), "name": safe, "lines": []}

    text = None
    for enc in ("utf-8", "gbk", "latin-1"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("utf-8", errors="replace")

    all_lines = text.splitlines()
    return {"ok": True, "name": safe, "lines": all_lines[-tail:]}
