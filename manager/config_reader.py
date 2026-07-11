"""只读解析账号的 etc/bilidanmaku-api.yaml。

红线：本模块绝不写配置文件，只有读函数。用于总览展示与刷新缓存。
兼容两种键大小写格式：v1.3.8 的 PascalCase(+中文注释) 与 v1.3.10+ 的小写无注释。
"""
import os

import yaml

from config import DEFAULT_EXE_NAME
import paths


def _ci_get(d, key):
    """大小写不敏感地从字典取值（兼容 RoomId/roomid 等）。"""
    if not isinstance(d, dict):
        return None
    if key in d:
        return d[key]
    lk = key.lower()
    for k, v in d.items():
        if isinstance(k, str) and k.lower() == lk:
            return v
    return None


def _config_path(account):
    """根据账号记录定位 yaml 路径（兼容嵌套目录）。"""
    return os.path.join(paths.workdir(account), "etc", "bilidanmaku-api.yaml")


def read_config(account):
    """返回完整解析后的配置字典（只读展示用）。失败返回 None。"""
    path = _config_path(account)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return yaml.safe_load(f)
    except Exception:
        return None


def get_summary(account):
    """提取总览/刷新所需的摘要字段。roomid/robotname/mode 在 yaml 改大小写间兼容。"""
    cfg = read_config(account)
    if not cfg:
        return {"roomid": None, "robotname": None, "robotmode": None, "has_token": account["has_token"]}
    return {
        "roomid": _ci_get(cfg, "roomid"),
        "robotname": _ci_get(cfg, "robotname"),
        "robotmode": _ci_get(cfg, "robotmode"),
        "has_token": account["has_token"],
    }
