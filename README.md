# Kami Man Bot

基于 NoneBot2 和 OneBot V11 的 QQ 机器人，主要提供游戏王查卡/裁定、MyCard 对战平台查询，以及 Riftbound 查卡功能。

## 功能

### 游戏王

- `ck 卡名` / `查卡 卡名`：查询单张游戏王卡片信息，包含卡图。
- `卡图 卡名`：只查询卡图。
- `pl 卡名` / `批量查卡 卡名`：批量查询卡片，使用合并转发返回。
- `裁定 卡名`：查询卡片裁定，每页 10 条。
- `裁定 卡名 2` / `裁定 卡名 p2` / `裁定 卡名 第2页`：查看后续裁定分页。
- 群聊中 `@Bot 问题`：调用独立部署的 `ygo-rag` 服务，使用 LLM rerank 和 LLM 回答生成，按卡片拆分为合并转发消息。私聊不会触发该功能。

数据来源：

- 卡片与裁定：`https://ygocdb.com/api/v0/`
- 卡图 CDN：见 `services/ygo_api.py`
- RAG 问答：同机部署的 `ygo-rag` HTTP 服务，默认 `http://127.0.0.1:7860/api/query`

### MyCard 对战平台

- `绑定 用户名`：绑定自己的 MyCard 用户名。
- `查询绑定` / `查询绑定 @用户`：查询绑定信息。
- `历史` / `5月历史` / `25年5月历史 用户名`：查询月度历史战绩。
- `胜率查询` / `胜率查询 用户名`：查询胜率统计。
- `首胜查询` / `首胜查询 用户名`：查询今日首胜。
- `订阅 用户名` / `订阅`：订阅用户新对局推送。
- `退订 用户名`：取消订阅。

数据会写入 `data/*.json`，这些运行时文件默认不提交到 Git。

### Riftbound

- `rb 卡名` / `符文查卡 卡名` / `符文 卡名`：查询单张 Riftbound 卡片。
- `rbpl 卡名` / `符文批量 卡名`：批量查询 Riftbound 卡片。

Riftbound 卡片数据文件为 `data/riftbound_cards.json`，可通过 `assets/sync_riftbound_db.py` 同步。

### 系统管理

- `帮助` / `help` / `菜单`：生成并发送帮助图。
- `重载插件` / `更新代码` / `更新插件` / `reload`：超级用户命令，从 Git 拉取最新代码并重启 systemd 服务。

## 项目结构

```text
.
├── bot.py                    # NoneBot 入口
├── plugins/
│   ├── admin.py              # 帮助图、代码更新与服务重启
│   ├── mycard.py             # MyCard 查询和订阅
│   ├── riftbound_card.py     # Riftbound 查卡
│   ├── ygo_rag_qa.py         # 游戏王 RAG 群聊问答
│   └── ygo_card.py           # 游戏王查卡和裁定
├── services/
│   ├── mycard_api.py         # MyCard API 与本地 JSON 存储
│   ├── riftbound_api.py      # Riftbound 本地卡库查询
│   ├── ygo_rag_api.py        # ygo-rag HTTP API 客户端
│   ├── ygo_rag_messages.py   # ygo-rag 消息分段与格式化
│   └── ygo_api.py            # YGOCDB API、卡图下载、裁定解析
├── assets/
│   ├── help.md               # 帮助文案
│   ├── render_help.py        # 帮助图渲染脚本
│   └── sync_riftbound_db.py  # Riftbound 数据同步脚本
└── data/                     # 运行时数据目录
```

## 环境要求

- Python 3.10+
- OneBot V11 兼容实现，例如 NapCat
- 可访问外部 API 和图片 CDN 的网络环境

主要 Python 依赖：

```bash
pip install nonebot2 nonebot-adapter-onebot nonebot-plugin-apscheduler
pip install httpx aiohttp beautifulsoup4 markdown pillow matplotlib pytz
```

建议后续补充 `requirements.txt` 固定版本。

## 本地运行

```bash
python -m venv venv
.\venv\Scripts\activate
pip install nonebot2 nonebot-adapter-onebot nonebot-plugin-apscheduler
pip install httpx aiohttp beautifulsoup4 markdown pillow matplotlib pytz
python bot.py
```

Linux：

```bash
python3 -m venv venv
source venv/bin/activate
pip install nonebot2 nonebot-adapter-onebot nonebot-plugin-apscheduler
pip install httpx aiohttp beautifulsoup4 markdown pillow matplotlib pytz
python bot.py
```

默认监听：

```text
0.0.0.0:18080
```

命令前缀：

```python
command_start={"/", ""}
```

因此既支持 `/help`，也支持 `help`。

## NapCat 连接

项目使用 OneBot V11 适配器。NapCat 需要配置反向 WebSocket 或 HTTP 上报到 Bot。

Bot 端地址：

```text
ws://<bot-host>:18080/onebot/v11/ws
```

如果 NapCat 和 Bot 在同一台 Docker 宿主机上，常见写法是：

```text
ws://host.docker.internal:18080/onebot/v11/ws
```

具体以 NapCat 的网络和 compose 配置为准。

## 游戏王 RAG 问答

RAG 问答功能不在 Bot 进程内加载模型。生产环境需要在同一台 Bot 服务器上独立部署 `ygo-rag` Web 服务，并确保该服务可以访问卡库、Chroma 索引和 DeepSeek。

`ygo-rag` 服务示例：

```bash
export DEEPSEEK_API_KEY="..."
export HF_HUB_OFFLINE="1"
python -m rag_agent web --host 127.0.0.1 --port 7860
```

Bot 默认调用：

```text
http://127.0.0.1:7860/api/query
```

Bot 侧可选环境变量：

```bash
export YGO_RAG_API_URL="http://127.0.0.1:7860/api/query"
export YGO_RAG_TIMEOUT_SECONDS="120"
export YGO_RAG_TOP_K="5"
export YGO_RAG_RERANK_CANDIDATES="5"
export YGO_RAG_STRUCTURED_MAX_BLOCK_CHARS="1800"
```

Bot 请求默认启用：

```json
{
  "semantic": true,
  "rerank": false,
  "llm_rerank": true,
  "llm": true
}
```

触发方式：

```text
@Bot 有没有效果类似我身作盾的卡？
```

该功能只处理群聊消息。私聊不会触发，也不会返回 RAG 问答回复。

## 帮助图

帮助图由 `assets/help.md` 渲染为 `assets/help.png`。发送时会读取图片并用 `base64://` 发送，避免 OneBot 端无法访问 Bot 服务器本地文件路径。

手动生成：

```bash
python assets/render_help.py
```

`assets/help.png` 是生成文件，不提交到 Git。

## 部署

生产环境建议使用 systemd 管理 `bot.py`，并使用虚拟环境中的 Python 启动：

```ini
[Unit]
Description=Kami Man Bot
After=network.target

[Service]
WorkingDirectory=/path/to/kami-man
ExecStart=/path/to/kami-man/venv/bin/python /path/to/kami-man/bot.py
Restart=always
User=ubuntu

[Install]
WantedBy=multi-user.target
```

重启：

```bash
sudo systemctl restart kami-man
```

查看状态：

```bash
systemctl status kami-man --no-pager -l
```

## 注意事项

- `data/*.json` 是运行时数据，包含绑定、订阅和缓存，不应随代码提交。
- `assets/help.png` 是生成文件，不应随代码提交。
- 合并转发可能被 NapCat 或 QQ 风控拒绝；游戏王查卡已在合并转发失败时回退为普通消息发送。
- 裁定文本可能很长，目前按每页 10 条分页展示。
