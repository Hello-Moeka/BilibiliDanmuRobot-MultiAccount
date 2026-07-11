"""全局配置：路径、端口等。基于本文件位置自动推导，便于整体迁移。"""
import os

# manager/ 的上级目录即项目根
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
ACCOUNTS_DIR = os.path.join(BASE_DIR, "accounts")
TEMPLATE_DIR = os.path.join(DATA_DIR, "template")  # 干净模板（exe + 默认 yaml + 骨架）
DB_PATH = os.path.join(DATA_DIR, "manager.db")

# 默认的待导入 zip（用户手动部署的备份包）
DEFAULT_ZIP_PATH = os.path.join(BASE_DIR, "花花Bot.zip")

# 默认启动的程序名（GUI 版，会弹窗；可改 CLI 二进制实现无头运行）
DEFAULT_EXE_NAME = "GUI-BilibiliDanmuRobot.exe"

# Web 面板监听
HOST = "127.0.0.1"  # 仅本地访问，保护 token 不外泄
PORT = 8765

# B 站登录态校验接口
BILIBILI_NAV_API = "https://api.bilibili.com/x/web-interface/nav"

# 盲盒金额单位换算：1000 = 1 元
PRICE_UNIT = 1000

# 进程看门狗：崩溃自动重启（开关）
WATCHDOG_ENABLED = False
WATCHDOG_INTERVAL = 30  # 秒

for _d in (DATA_DIR, ACCOUNTS_DIR, TEMPLATE_DIR):
    os.makedirs(_d, exist_ok=True)
