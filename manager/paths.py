"""路径解析工具：让项目可整体迁移到任意目录/盘符。

核心思路：数据库里只存相对项目根（BASE_DIR）的相对路径，如 accounts/白桃；
运行时由 account_dir() 解析为绝对路径。兼容旧的绝对路径数据。
"""
import os

from config import BASE_DIR


def account_dir(account):
    """返回账号根目录的绝对路径。

    account: dict / sqlite.Row（含 dir_path 键）或目录字符串。
    DB 中若存相对路径则拼到 BASE_DIR 下；若存旧的绝对路径则原样返回。
    """
    if isinstance(account, str):
        p = account
    else:
        p = account["dir_path"]
    if not p:
        return p
    if os.path.isabs(p):
        return p  # 旧数据，绝对路径直接用
    return os.path.normpath(os.path.join(BASE_DIR, p))


def workdir(account):
    """返回账号真正的工作目录（兼容扁平与嵌套 GUI-... 子目录）。"""
    base = account_dir(account)
    if not base:
        return base
    # 扁平结构
    if os.path.exists(os.path.join(base, "etc", "bilidanmaku-api.yaml")):
        return base
    # 嵌套结构：在一级子目录里找含 etc/bilidanmaku-api.yaml 的
    try:
        for name in os.listdir(base):
            sub = os.path.join(base, name)
            if os.path.isdir(sub) and os.path.exists(os.path.join(sub, "etc", "bilidanmaku-api.yaml")):
                return sub
    except OSError:
        pass
    return base
