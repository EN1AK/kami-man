# Kami Man Bot

基于 NoneBot2 和 OneBot V11 的 QQ 机器人，主要提供游戏王查卡/裁定、MyCard 对战平台查询，以及 Riftbound 查卡功能。

## 功能

### 游戏王

- `ck 卡名` / `查卡 卡名`：查询单张游戏王卡片信息，包含卡图。
- `卡图 卡名`：只查询卡图。
- `卡价 卡名`：复用 `ck/pl` 的 YGOCDB 模糊搜索，只返回文字。命中多张时回复编号、卡密或完整卡名选卡，再回复罕贵或编号查价；每步 3 分钟内有效，回复 `取消` 退出。
- `卡价 原石 简中`：先从文字候选中选卡，再选罕贵。已指定罕贵时，选卡后直接返回价格。
- `卡价 原石之皇脉 日文 UTR` / `卡价 原石之皇脉 简中 SR`：按语种和罕贵查询各卡包版本，分别展示人民币最低价、集换价及日期。游戏王默认日文，也支持英文。
- `pl 卡名` / `批量查卡 卡名`：批量查询卡片，使用合并转发返回。
- `裁定 卡名`：查询卡片裁定，每页 10 条。
- `裁定 卡名 2` / `裁定 卡名 p2` / `裁定 卡名 第2页`：查看后续裁定分页。
- 群聊中 `@Bot 问题`：调用独立部署的 `ygo-rag` 统一 Agent，由 Agent 自动选择查卡、翻译或裁定工具，并用合并转发返回。私聊不会触发该功能。
- 群聊中 `@Bot 翻译 文本` / `@Bot translate 文本`：调用 `ygo-rag` agent 的 LLM 翻译接口，长回复会拆分为合并转发消息。私聊不会触发该功能。
- 群聊中 `@神人` + 一张日文游戏王卡图（也可 `@神人 翻译` + 卡图）：返回中文卡名、效果及独立的灵摆效果，标注为机器翻译。每次限一张清晰完整卡图；识别失败不扣每日额度。图片需附在同一条消息中。

数据来源：

- 卡片与裁定：`https://ygocdb.com/api/v0/`
- 卡图 CDN：见 `services/ygo_api.py`
- 集换社价格：本机 Windows 微信登录会话，经私有桥接服务查询；安装、自动恢复及服务器配置见 [部署说明](deploy/production.md#jihuanshe-price-lookup-on-windows)。
- RAG Agent：同机部署的 `ygo-rag` HTTP 服务，默认 `http://127.0.0.1:7860/api/agent`
- LLM 翻译：同机部署的 `ygo-rag` HTTP 服务，默认 `http://127.0.0.1:7860/api/translate`

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

- `符文卡价 OGN-119 简中` / `符文卡价 OGN-119 英文`：查询集换社价格；别名 `符文查价`、`rb价`、`rbprice`。默认简中，也支持繁中和韩文。
- `符文卡价 阿狸 天真绮梦 简中 异画`：按完整卡名、副标题及罕贵查价；同名不同卡要求补全名称或卡号。

- `rb 卡名` / `符文查卡 卡名`：查询卡片，支持中文名、英文名、副标题、编号和模糊搜索。同名卡返回候选，使用编号查询指定版本。
- `rbpl 卡名` / `符文批量 卡名`：批量查询 Riftbound 卡片。

数据来自 riftsim 的 `cards_bilingual.db`，默认读取相邻仓库，可通过 `RIFTBOUND_CARDS_DB` 配置快照路径。普通版本优先；重印和异画按卡名、效果及属性归组；错字匹配仅返回候选，不自动选牌。每次批量最多展示10种卡片。

图片优先中文，缺失时使用英文；服务器缓存目录由 `RIFTBOUND_IMAGE_CACHE` 指定，默认 `data/riftbound_images/`。在 Linux 服务器执行 `python assets/cache_riftbound_images.py` 可补全卡图，支持断点重跑。卡图失败仍返回文字，人工补译与勘误分别标注。

`符文规则 问题` / `符文裁定 问题` 继续使用独立的规则问答服务；不注册宽泛的 `符文` 查卡别名。

### 系统管理

- `帮助` / `help` / `菜单`：生成并发送帮助图。
- `重载插件` / `更新代码` / `更新插件` / `reload`：超级用户命令，从 Git 拉取最新代码并重启 systemd 服务。

## 项目结构

```text
.
├── bot.py                    # NoneBot 入口
├── plugins/
│   ├── card_price.py         # 游戏王/符文战场分语种查价及罕贵选择
│   ├── admin.py              # 帮助图、代码更新与服务重启
│   ├── mycard.py             # MyCard 查询和订阅
│   ├── riftbound_card.py     # Riftbound 查卡
│   ├── ygo_rag_qa.py         # 游戏王 RAG 群聊问答
│   ├── ygo_rag_translate.py  # ygo-rag LLM 群聊翻译
│   └── ygo_card.py           # 游戏王查卡和裁定
├── services/
│   ├── jihuanshe_api.py      # 私有查价桥接客户端
│   ├── mycard_api.py         # MyCard API 与本地 JSON 存储
│   ├── onebot_forward.py     # OneBot 合并转发发送 helper
│   ├── riftbound_api.py      # Riftbound 本地卡库查询
│   ├── ygo_rag_agent_api.py          # ygo-rag 统一 Agent API 客户端
│   ├── ygo_rag_agent_messages.py     # ygo-rag Agent 消息分段与格式化
│   ├── ygo_rag_api.py        # ygo-rag 旧版查卡 RAG API 客户端
│   ├── ygo_rag_messages.py   # ygo-rag 提及解析与旧版 RAG 消息格式化
│   ├── ygo_rag_translation_api.py       # ygo-rag 翻译 API 客户端
│   ├── ygo_rag_translation_messages.py  # ygo-rag 翻译命令解析与分段
│   └── ygo_api.py            # YGOCDB API、卡图下载、裁定解析
├── assets/
│   ├── help.md               # 帮助文案
│   ├── render_help.py        # 帮助图渲染脚本
│   ├── cache_riftbound_images.py # 服务器卡图补全
│   └── sync_riftbound_db.py  # 旧版 JSON 同步脚本（不再使用）
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

普通 `@Bot 问题` 默认调用统一 Agent：

```text
http://127.0.0.1:7860/api/agent
```

Bot 侧可选环境变量：

```bash
export YGO_RAG_AGENT_API_URL="http://127.0.0.1:7860/api/agent"
export YGO_RAG_AGENT_TIMEOUT_SECONDS="240"
export YGO_RAG_AGENT_MAX_STEPS="6"
export YGO_RAG_AGENT_STRUCTURED_MAX_BLOCK_CHARS="1800"
export YGO_RAG_API_URL="http://127.0.0.1:7860/api/query"
export YGO_RAG_TIMEOUT_SECONDS="120"
export YGO_RAG_TOP_K="5"
export YGO_RAG_RERANK_CANDIDATES="5"
export YGO_RAG_STRUCTURED_MAX_BLOCK_CHARS="1800"
export YGO_RAG_TRANSLATE_API_URL="http://127.0.0.1:7860/api/translate"
export YGO_RAG_TRANSLATE_TIMEOUT_SECONDS="120"
export YGO_RAG_TRANSLATE_SOURCE_LANG="auto"
export YGO_RAG_TRANSLATE_TARGET_LANG="zh-CN"
export YGO_RAG_TRANSLATE_STRUCTURED_MAX_BLOCK_CHARS="1800"
export YGO_RAG_TRANSLATE_COMMAND_ALIASES="翻译,translate"
```

普通 `@Bot 问题` 的 Agent 请求默认启用：

```json
{
  "semantic": true,
  "rerank": false,
  "llm_rerank": true,
  "max_steps": 6
}
```

触发方式：

```text
@Bot 有没有效果类似我身作盾的卡？
@Bot 双方场上都只有一只怪兽时，对方发动破坏效果，我方怪兽可以代替破坏吗？
```

翻译触发方式：

```text
@Bot 翻译 Once per turn: You can target 1 card on the field; destroy it.
@Bot translate 你好
```

RAG 问答和翻译功能只处理群聊消息。私聊不会触发，也不会返回 RAG 问答或翻译回复。

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


### Unified chat and game Agent

`@神人` now accepts ordinary chat, YGO and Riftbound card/ruling questions,
and translation. Follow-ups share history only within the same group/user.
`@神人 清空对话` resets it. The explicit translation and Rift aliases delegate
to the same backend at 7861. Deployment is documented in the sibling
`ygo-rag/docs/unified-agent.md`; the separate 7862 service is retired.

### 日文卡图翻译

卡图翻译使用同一 `ygo-rag` 服务的 `POST /api/card-translate`，地址由
`YGO_RAG_AGENT_API_URL` 的 `/agent` 替换为 `/card-translate`，无需给 Bot 配置模型密钥。
需同步更新 `ygo-rag` 后端，并在该服务环境中配置 `DEEPSEEK_API_KEY`；
图片模型由 `DEEPSEEK_VISION_MODEL` 指定，默认 `deepseek-flash`，沿用 `DEEPSEEK_BASE_URL`。
普通聊天的 `DEEPSEEK_MODEL` 不变。Bot 从 QQ 图片域名下载不超过 10 MB 的卡图，将图片内容传给 DeepSeek 读取；链接过期时请重新发送原图。
卡图翻译与普通 `@神人` 共用每日额度，但作为独立翻译，不写入聊天历史。


### 群聊采集与随机聊天试运行

仅群 `819151070` 开启，从启用后的普通文字消息积累风格示例；排除机器人自身、
@消息、命令、图片/转发、链接和明显凭证/长数字串，不回填历史消息。
本地 `data/group_chat.db` 保存最多 10000 条、30 天的样本，成员标识做散列，
给模型仅传匿名成员编号。每六小时清理过期样本。
随机接话概率 3%，至少间隔 5 分钟，每北京时间自然日最多 20 次模型调用；
需要近期至少 4 条消息，模型可返回空字符串不发言。该额度独立于主动 @ 的个人额度。
最近 10 分钟最多 15 条对话和最多 8 条较早风格示例交给 DeepSeek，
用上下文示例参考群体风格，不更新模型权重。后台失败静默，冷却与调用次数跨重启保留。

- `@神人 随机聊天 状态` / `开启` / `关闭`
- `@神人 群聊采集 状态` / `开启` / `关闭` / `清空`

修改开关限群主、群管理员或机器人管理员；状态可由群成员查看。
关闭采集同时关闭随机接话；清空同时停用采集和接话。重新开启采集后，
需单独开启随机聊天。关闭接话期间仍可保留文字采集。
不发送启用公告或通知。图片翻译、查卡和裁定继续由现有入口处理。


### 自动群聊风格描述与翻译原图

群 819151070 每小时检查样本；首次至少 200 条有效文字、3 位成员，之后新增
至少 100 条且跨北京时间自然日才更新，每天最多成功更新一次。每次只发送最多
8 条多成员代表样本及本地聚合统计、旧风格描述给 DeepSeek，不扩大原始消息外发条数。
新风格描述自动作为随机接话的语气参考；样本不足保留已有描述。失败至少间隔
一小时重试，每天最多尝试三次，不发群通知或错误消息。
`@神人 群聊风格` 查看当前描述与样本进度。关闭采集会停止总结；
`@神人 群聊采集 清空` 同时删除样本和风格描述、取消在途总结，防止清空后写回。
描述保留最多 30 天，过期重新积累。随机接话的 3% 概率、冷却和每日上限不变。

卡图翻译成功后，第一条回复同时包含用户上传的同一张原图与中文翻译。
复用已下载的图片字节，不另行下载；长翻译后续分段不重复附图。识别失败不附图。


## 场景表达学习与预算

仅群 819151070，沿用 3% 触发、5 分钟冷却和每日最多 20 次聊天尝试。
`@神人 群聊学习 状态` 查看表达数量、待学习消息数和模型用量/费用估算。
首次累计 100 条合格文字、至少 3 位成员后学习；后续每 50 条新消息可更新，
每小时检查，最多每日成功 2 批、尝试 3 次，失败至少间隔 1 小时。
每批最多发送 8 条匿名人类样本，表达必须引用本批样本原句；机器人回复不作为学习样本。
表达最多保存 300 条、保留 30 天；本地按当前话题检索最多 5 条，与历史示例合计最多 8 项。
单次模型调用同时决定是否接话和生成回复，明确关闭思考模式。
生成期间出现新合格消息或管理员关闭/清空时丢弃旧回复；相似近期回复不重复发送。
`@神人 群聊采集 关闭` 停采并停止接话，保留已有表达；`清空` 同时删除样本、风格和表达。

后端共享预算覆盖随机聊天、表达学习和风格总结，默认每日 ¥1、每月 ¥10（北京时间）。
先原子预留最大估算费用，再按返回 token 用量结算；失败或用量未知保留预留额，重启不重置。
采用 Flash 高峰、未缓存价格保守估算，不等同于平台实际账单；不含查卡、图片翻译等功能。
配置及接口详见服务器 ygo-rag 的 `docs/design.md`。预算耗尽静默停止群聊模型调用，采集继续。


## 原文人格与轻量表情包

随机群聊直接使用 shirachino/astrbot-persona-prompts 的“大肥鱼”人格原文与
shirachino/astrbot-deepseek-meme-pack 图片素材，不安装 AstrBot 或其插件。
人格原文保存在后端 personas/deepseek-group/persona.txt；source.docx 与 provenance.json
保存原始文档、固定版本与哈希，正文不替换占位符、不改写。运行协议独立规定 JSON、
隐私、工具与长度限制。现有群聊采集、风格总结和表达学习继续独立运行。
仅随机群聊使用该人格与表情，普通 @ Agent、查卡、裁定和卡图翻译路径保持原样。

图片位于 data/group_memes/deepseek-girl-pack（运行时素材，不进 Git）。
模型在原有一次调用中选择可选分类；本地只从对应分类选一张，经验证后以 Base64 发给 OneBot。
允许文字加图或纯表情；没有合适图片、图片不可用或额度不足时回退文字/不接话。
请求配图后默认 25% 概率放行，最多每日 5 次发图尝试、间隔 30 分钟，同一图片 7 天不重复。
单张超过 4MiB 的原图保留在素材库，但不进入可发送清单。发送失败或发送前上下文失效的
已预留尝试仍计数，防止重复发图。发图状态与现有群聊计数存入同一 SQLite，重启不重置。
`@神人 群聊学习 状态` 同时显示可用图片、分类和今日发图尝试。
机器人文字和图片均不作为人类学习样本；没有开启群友表情包自动收集。

重新安装/校验固定版本素材：
`python3 scripts/install_group_persona_assets.py --bot-root /home/ubuntu/qqbot/kami-man --rag-root /home/ubuntu/qqbot/ygo-rag`
安装器只下载固定版本文档和图片，核对 Git blob 哈希，不执行第三方仓库代码。
只在完整下载校验后发布目录；若已存在不同版本，拒绝覆盖。

## @ 闲聊与专业问答隔离

群聊 @神人/文字 @神人/回复机器人入口先做中立分流。明确查卡、裁定、规则、翻译等
专业请求直接走原有 Agent；其他文字由不加载人格或聊天历史的分类器判断，低把握度或失败
默认专业服务。图片继续走卡图翻译，不经过分类或人格模型。

闲聊使用原文“大肥鱼”人格、独立闲聊历史及可选表情。仅群 819151070 可读取本群风格和
表达库，其他群只用固定人格。闲聊与专业共用既有每人每天30次额度，一条请求只扣一次，
失败退回；分类和人格调用计入现有群聊模型预算。随机接话每日20次尝试仍独立。
表情限制按群与随机接话共用，不因多个用户 @ 而重置；没有新增群聊采集范围。

专业服务不接收人格、学习样本或闲聊历史，也不经人格模型润色。专业问答使用新的
`:professional` 会话空间，不再读取以前混合聊天的旧会话。只有已登记为专业输出的
同用户/同群机器人引用才传入专业服务；人格引用和未知来源旧引用默认省略。
普通专业追问仍可使用自己的专业历史。

`@神人 清空对话`（也支持 重置对话/忘记上下文）免费清空闲聊、专业和旧会话，
并清理引用来源元数据。一个用户在一个群的请求串行处理，避免清空后旧回复再次写回。
Bot新增 data/mention_routes.db 仅存会话范围、回复SHA256和分支标签，不存引用原文。
后端闲聊存储与专业存储完全分开，见后端 docs/design.md。


### 固定指令分流更新（2026-10-20）

此规则替代上述语义分类和自动升级：@消息以 ck、pl、rb、rbpl、translate、查卡、裁定、翻译、规则、查价、卡价、符文规则/裁定、符文战场规则、卡图翻译等指令开头时走专业Agent，其余文字全部走原人格。英文指令支持 / 前缀及空格、冒号或中文参数。数字卡号、链接、发动等词和前一次分支不会单独触发专业。无需模型分类，人格不能自动升级；接口错误退回额度并提示失败。专业追问也要带指令。卡图翻译、清空对话及用量控制保留，专业与人格历史继续隔离。


### 群聊状态指令入口修复（2026-10-20）

群聊风格、群聊学习 状态等控制指令在所有群优先匹配，不进入人格或专业Agent。已启用学习群返回本群状态；其他群提示本群未启用，不读取其他群的风格或学习数据。命令本身不消耗个人Agent额度。普通讨论句仍走聊天。机器人完整回归325项通过；未向QQ发送测试消息。备份：/home/ubuntu/qqbot/group-control-routing-fix-bfno9jmn。


### @ 人格长回复与分段发送（2026-10-20）

仅放宽明确@人格回复：按内容决定长短，最多2000字符、1800输出token；原人格文件不改。长于约240字符时优先按句子和段落拆成最多4条，首条生成完成后立即发送，其余间隔0.8至1.6秒，同群人格消息组不互相穿插，表情仅附最后一条。完整回复先校验，每段保存为人格引用来源；一次提问仍计一次额度。代码围栏内容整体发送。这是完整生成后的分段交付，不是流式生成。随机接话仍限100字符，专业链保持原发送方式。验证：335项机器人测试和499项后端测试通过；真实模型287字符经模拟发送拆为两条，没有发送QQ群测试消息。详见deploy/persona-segmented-replies-2026-10-20.md。


### 管理员私聊触发（2026-10-20）

机器人superusers管理员可直接私聊，无需@，普通聊天使用原人格及分段发送，专业指令和卡图翻译保持原链路。私聊会话使用独立private命名空间，不读取群聊风格或表达，不进入群聊采集；清空对话仅清除自己的私聊上下文。表情使用固定图库及独立私聊收件人计数库。群聊状态指令在私聊提示回到已启用群查询。新聊天入口不会放行普通私聊用户；原有高优先级命令保持原行为。验证847项通过。详见deploy/admin-private-chat-2026-10-20.md。


### 短多段回复拆分修复（2026-10-20）

@人格及管理员私聊回复中的换行优先拆成独立消息，不再受240字符阈值限制；最多4条，更多行会合并为最多4组。代码围栏保持整体发送。单行短回复仍发一条，长单行回复保留原句子拆分。验证39项针对性测试通过，覆盖内容完整、群聊/私聊独立发送、发送间隔和一次提问计一次额度。备份：/home/ubuntu/qqbot/persona-newline-split-vrv0ctwu。


### 私聊爱弥斯人格（2026-10-20）

管理员私聊改用独立的爱弥斯/小爱原文：ygo-rag/personas/wuwa-aemeath/persona.txt；旁边保存source.docx和provenance.json。原文来自shirachino/astrbot-persona-prompts固定版本869d6793b93a756a410f00da44852f8b774e48f1的wuwa-aemeath/小爱人格提示词.docx，提取3481字符。可通过PRIVATE_CHAT_PERSONA_FILE指定私聊文件。群聊保持用户定制的大肥鱼人格，专业Agent不使用人格。小爱使用新私聊历史后缀:persona:aemeath，不读旧:persona历史；清空对话同时清除新旧私聊历史。512项后端测试通过，真实API确认小爱称呼。详见kami-man/deploy/private-aemeath-persona-2026-10-20.md。
