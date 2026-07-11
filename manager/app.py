"""Flask 主程序：整合账号导入、新增、进程管理、Token、盲盒看板、日志。"""
import os
import sys

from flask import Flask, jsonify, render_template, request

# 确保 manager 目录在 sys.path（直接 python app.py 运行时）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import account_manager
import blindbox_stats
import config_reader
import log_viewer
import process_manager
import token_manager
from config import DEFAULT_ZIP_PATH, HOST, PORT, TEMPLATE_DIR
from db import init_db

app = Flask(__name__)
app.config["JSON_AS_ASCII"] = False
init_db()


# --------------------------------------------------------------------------- #
# 页面
# --------------------------------------------------------------------------- #
@app.route("/")
def dashboard():
    accounts = account_manager.list_accounts()
    status = process_manager.status_all()
    for a in accounts:
        a["running"] = status.get(a["id"], {}).get("running", False)
        a["pid"] = status.get(a["id"], {}).get("pid")
    return render_template("dashboard.html", accounts=accounts, zip_path=DEFAULT_ZIP_PATH)


@app.route("/deploy")
def deploy_page():
    tpl = account_manager._find_template_files()
    ready = bool(tpl.get("exe") and tpl.get("yaml"))
    return render_template("deploy.html", template_ready=ready, template_version=account_manager._template_version())


@app.route("/accounts/<int:account_id>")
def account_detail(account_id):
    acc = account_manager.get_account(account_id)
    if not acc:
        return ("账号不存在", 404)
    status = process_manager.status_all()
    acc["running"] = status.get(acc["id"], {}).get("running", False)
    return render_template("account_detail.html", account=acc)


@app.route("/blindbox")
def blindbox_page():
    return render_template("blindbox.html")


# --------------------------------------------------------------------------- #
# 账号 JSON / 导入 / 新增 / 刷新
# --------------------------------------------------------------------------- #
@app.route("/api/accounts")
def api_accounts():
    accounts = account_manager.list_accounts()
    status = process_manager.status_all()
    for a in accounts:
        a["running"] = status.get(a["id"], {}).get("running", False)
        a["pid"] = status.get(a["id"], {}).get("pid")
    return jsonify(accounts)


@app.route("/api/zip/preview")
def api_zip_preview():
    zip_path = (request.args.get("zip_path") or DEFAULT_ZIP_PATH).strip()
    try:
        result = account_manager.scan_zip(zip_path)
        return jsonify(result)
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)}), 400


@app.route("/api/accounts/import-zip", methods=["POST"])
def api_import_zip():
    zip_path = (request.form.get("zip_path") or DEFAULT_ZIP_PATH).strip()
    skip_logs = request.form.get("skip_logs", "1") == "1"
    if not os.path.exists(zip_path):
        return jsonify({"ok": False, "msg": f"zip 不存在：{zip_path}"}), 400
    r = account_manager.import_all(zip_path, skip_logs=skip_logs)
    return jsonify(r)


@app.route("/api/import/progress")
def api_import_progress():
    return jsonify(account_manager.import_progress())


@app.route("/api/accounts/create", methods=["POST"])
def api_create_account():
    data = request.get_json(silent=True) or {}
    nickname = data.get("nickname") or request.form.get("nickname")
    auto_start = data.get("auto_start", False) or request.form.get("auto_start") == "1"
    if not nickname:
        return jsonify({"ok": False, "msg": "昵称不能为空"}), 400
    r = account_manager.create_account(nickname, auto_start=auto_start)
    return jsonify(r)


@app.route("/api/accounts/create-batch", methods=["POST"])
def api_create_batch():
    data = request.get_json(silent=True) or {}
    text = data.get("nicknames", "")
    nicks = [n.strip() for n in text.replace(",", "\n").splitlines() if n.strip()]
    if not nicks:
        return jsonify({"ok": False, "msg": "未提供昵称"}), 400
    return jsonify(account_manager.create_accounts_batch(nicks))


@app.route("/api/accounts/refresh", methods=["POST"])
def api_refresh_all():
    return jsonify(account_manager.refresh_all())


@app.route("/api/accounts/<int:account_id>/refresh", methods=["POST"])
def api_refresh_one(account_id):
    return jsonify(account_manager.refresh_account(account_id))


@app.route("/api/accounts/<int:account_id>/delete", methods=["POST"])
def api_delete_account(account_id):
    # 默认同步删除项目目录；显式 purge=0 才保留（purge 走查询参数，避免 415）
    purge = request.args.get("purge", "1") != "0"
    return jsonify(account_manager.delete_account(account_id, purge_files=purge))


# --------------------------------------------------------------------------- #
# 进程控制
# --------------------------------------------------------------------------- #
@app.route("/api/accounts/<int:account_id>/start", methods=["POST"])
def api_start(account_id):
    acc = account_manager.get_account(account_id)
    if not acc:
        return jsonify({"ok": False, "msg": "账号不存在"}), 404
    return jsonify(process_manager.start(acc))


@app.route("/api/accounts/<int:account_id>/stop", methods=["POST"])
def api_stop(account_id):
    acc = account_manager.get_account(account_id)
    if not acc:
        return jsonify({"ok": False, "msg": "账号不存在"}), 404
    return jsonify(process_manager.stop(acc))


@app.route("/api/accounts/<int:account_id>/restart", methods=["POST"])
def api_restart(account_id):
    acc = account_manager.get_account(account_id)
    if not acc:
        return jsonify({"ok": False, "msg": "账号不存在"}), 404
    return jsonify(process_manager.restart(acc))


@app.route("/api/accounts/batch", methods=["POST"])
def api_batch_process():
    data = request.get_json(silent=True) or {}
    ids = data.get("ids", [])
    action = data.get("action")
    if action == "start":
        return jsonify(process_manager.start_selected(ids))
    if action == "stop":
        return jsonify(process_manager.stop_selected(ids))
    return jsonify({"ok": False, "msg": "未知动作"}), 400


@app.route("/api/accounts/status")
def api_status():
    return jsonify(process_manager.status_all())


# --------------------------------------------------------------------------- #
# 配置（只读）/ Token / 日志
# --------------------------------------------------------------------------- #
@app.route("/api/accounts/<int:account_id>/config")
def api_config(account_id):
    acc = account_manager.get_account(account_id)
    if not acc:
        return jsonify({"ok": False, "msg": "账号不存在"}), 404
    cfg = config_reader.read_config(acc)
    return jsonify({"ok": cfg is not None, "config": cfg})


@app.route("/api/accounts/<int:account_id>/token", methods=["GET", "POST"])
def api_token(account_id):
    acc = account_manager.get_account(account_id)
    if not acc:
        return jsonify({"ok": False, "msg": "账号不存在"}), 404
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        raw = data.get("raw") or request.form.get("raw", "")
        return jsonify(token_manager.import_token(acc, raw))
    data = token_manager.read_token(acc)
    # 本地单用户，直接返回（不外发）
    return jsonify({
        "ok": True, "has_token": data["has_token"],
        "json": data["json"], "txt": data["txt"],
    })


@app.route("/api/accounts/<int:account_id>/login-check")
def api_login_check(account_id):
    acc = account_manager.get_account(account_id)
    if not acc:
        return jsonify({"ok": False, "msg": "账号不存在"}), 404
    return jsonify(token_manager.validate_login(acc))


@app.route("/api/accounts/<int:account_id>/logs")
def api_logs(account_id):
    acc = account_manager.get_account(account_id)
    if not acc:
        return jsonify({"ok": False, "msg": "账号不存在"}), 404
    name = request.args.get("name")
    if name:
        return jsonify(log_viewer.read_log(acc, name, tail=int(request.args.get("tail", 300))))
    return jsonify({"ok": True, "files": log_viewer.list_logs(acc)})


# --------------------------------------------------------------------------- #
# 盲盒盈亏看板
# --------------------------------------------------------------------------- #
@app.route("/api/blindbox")
def api_blindbox():
    account_id = request.args.get("account_id", type=int)
    year = request.args.get("year", type=int)
    return jsonify(blindbox_stats.get_dashboard(account_id=account_id, year=year))


# --------------------------------------------------------------------------- #
# 模板
# --------------------------------------------------------------------------- #
if __name__ == "__main__":
    process_manager.start_watchdog()
    app.run(host=HOST, port=PORT, debug=False)
