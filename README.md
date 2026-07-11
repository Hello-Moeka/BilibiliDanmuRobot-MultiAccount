# BilibiliDanmuRobot 多账号管理面板

基于 [BilibiliDanmuRobot](https://github.com/xbclub/BilibiliDanmuRobot)（Go+Wails 的 B 站弹幕机器人）的**多账号本地 Web 管理辅助程序**，用 Python + Flask 实现，便于批量部署与运维。

> 原项目不原生支持多账号，每个账号需一份独立工作目录（exe + `etc/bilidanmaku-api.yaml` + `token/` + `db/` + `logs/`）+ 各自运行一个 exe。本面板在其之上做目录隔离与进程编排。

## 核心功能

1. **从 zip 批量导入** —— 扫描多账号备份包，自动解压到 `accounts/<昵称>/`，解出干净模板，并按账号建立注册表。支持**自定义 zip 路径**（迁移设备可指定）+ 导入前「检测」预览。
2. **新增账号** —— 自动建新目录 + 从模板复制项目文件（exe + 默认 yaml + 目录骨架），**不写配置、不写 Token**；创建后启动 GUI，由你在 GUI 内自行填写房间号、机器人名并扫码登录。支持单条与批量（粘贴昵称列表）。
3. **删除账号** —— 删注册表并**同步删除项目目录**（exe/配置/Token/数据库/日志），二次确认，不可恢复。
4. **进程启停监控** —— 单个/批量启动、停止、重启；状态徽章自动刷新；可选看门狗崩溃自重启。
5. **Token 管理** —— 查看/导入 B 站 cookie（`token/bili_token.json` + `.txt`），一键校验登录态是否过期。
6. **盲盒盈亏看板** —— **按主播划分、不跨主播整合**；提供主播下拉切换 + 年份过滤；月度盈亏趋势图（正绿负红）+ 盲盒名盈亏排行。只读 `db/sqliteDataBase.db` 的 `blind_<roomid>` 表，按自然月聚合。

## 红线约束
- **除从 zip 导入（解压已有目录）外，绝不修改任何账号的 `etc/bilidanmaku-api.yaml`**。配置仅只读查看（`config_reader.py` 无任何写函数）。
- 新增账号复制模板默认 yaml 原样副本（`RoomId:3`），零字段改写；房间号等由 GUI 写入。
- Token 文件属凭证而非"配置文件"，Token 管理允许读写。

## 可迁移性
- 数据库 `accounts.dir_path` 存**相对项目根的相对路径**（如 `accounts/白桃`），运行时由 `paths.account_dir()` 解析为绝对路径；模块加载时自动迁移旧绝对路径。
- 框架路径（`BASE_DIR`/`ACCOUNTS_DIR`/`TEMPLATE_DIR`/`DB_PATH`）基于 `__file__` 动态推导。
- 兼容扁平与嵌套两种导入后目录结构（`paths.workdir()` 自动定位真正工作目录）；导入时自动剥离嵌套层扁平化。
- 整个项目文件夹拷到任意目录/盘符即可运行；zip 不在默认路径时可在导入框指定。

## 目录结构
```
BilibiliDanmuRobot多账号管理/
├── manager/               # 管理面板源码
│   ├── app.py              # Flask 入口与路由
│   ├── account_manager.py  # 账号注册/zip导入/新增/删除/刷新
│   ├── process_manager.py  # 进程启停/监控/看门狗
│   ├── token_manager.py    # Token 读写/导入/登录态校验
│   ├── blindbox_stats.py   # 盲盒盈亏按自然月统计（按主播）
│   ├── config_reader.py    # 只读解析 yaml（绝不写）
│   ├── log_viewer.py       # 日志只读 tail
│   ├── paths.py            # workdir/account_dir 解析器（相对路径）
│   ├── db.py / config.py
│   ├── templates/  static/
│   └── requirements.txt
├── data/                   # 运行时数据（不提交，程序自建）
│   ├── manager.db          # 账号注册表/操作日志
│   └── template/           # 干净模板（供新增账号复制）
├── accounts/               # 各账号工作目录（含凭证，不提交）
├── run.py                  # 启动入口
├── start.bat               # Windows 一键启动
├── .gitignore
└── README.md
```

## 快速开始
1. 安装 **Python 3.10+** 并加入 PATH。
2. 双击 `start.bat`（首次自动 `pip install -r manager/requirements.txt`），或手动：
   ```
   pip install -r manager/requirements.txt
   python run.py
   ```
3. 浏览器打开 **http://127.0.0.1:8765**（启动后会自动打开）。

## 使用流程

### 导入现有账号
- 总览页「从 zip 导入」→ 在 zip 路径框填入实际位置 →「检测」确认 →「导入（跳过日志，推荐）」。
- 程序扫描 zip，把每个账号目录解压到 `accounts/<昵称>/`，自动解出干净模板到 `data/template/`，注册表记录房间号/机器人名/模式/版本/Token 状态。

### 新增账号
- 「新增账号」页：填昵称 → 创建（建目录+复制模板文件）。
- 回总览点「启动」打开 GUI → 在 GUI 内填房间号、机器人名 → 扫码登录。
- 回面板点「刷新配置缓存」即可在总览看到新配置。

### 删除账号
- 总览行内「删除」或详情页「删除账号」→ 确认 → 同步删除目录与注册表记录。

### 进程管理
- 勾选多个账号批量启停，或单行启停/重启。默认启动 GUI 版 exe（会弹窗，同手动双击）；可换 CLI 二进制无头运行。

### Token 管理
- 账号详情 → 「Token 管理」：粘贴 JSON 或 `k=v;` 文本导入；「校验登录态」调 B 站接口判断是否过期。

### 盲盒盈亏看板
- 「盲盒盈亏」页：顶部选主播 + 年份；显示该主播汇总卡片、月度盈亏柱状图、盲盒名盈亏排行。金额单位为元（原始千鸟/电池 ÷ 1000）。

## 安全提示
- 面板仅绑定 `127.0.0.1`，不对外暴露。`accounts/` 与 `花花Bot.zip` 含真实 B 站 `SESSDATA`/`bili_jct`，等同于账号凭证，**切勿外发**——已在 `.gitignore` 中排除，不会进入版本库。
- 默认启动 GUI exe 会弹窗（与手动双击一致）。

## 依赖
`Flask`、`PyYAML`、`psutil`、`requests`（见 `manager/requirements.txt`）。前端 Bootstrap 5 + Chart.js 走 CDN。
