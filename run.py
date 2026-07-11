"""启动入口：python run.py  或双击 start.bat"""
import os
import sys
import threading
import webbrowser

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "manager"))

from app import app  # noqa: E402
import process_manager  # noqa: E402
from config import HOST, PORT  # noqa: E402


if __name__ == "__main__":
    print("=" * 56)
    print("  弹幕机器人多账号管理面板")
    print(f"  访问地址：http://{HOST}:{PORT}")
    print("  仅本地访问，保护 Token 不外泄；关闭本窗口即停止服务")
    print("=" * 56)
    # 延迟 1.5 秒后打开浏览器（等 Flask 起来）
    threading.Timer(1.5, lambda: webbrowser.open(f"http://{HOST}:{PORT}")).start()
    process_manager.start_watchdog()
    app.run(host=HOST, port=PORT, debug=False)
