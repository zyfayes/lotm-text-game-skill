# LOTM Text Game Skill

[English](README.md) · **简体中文**

一款受《诡秘之主》启发、能够长期保存进度并承担真实后果的文字冒险，也是一份可移植的 Agent Skill。

你将在纪元 1349 年 6 月 28 日的廷根醒来，与刚刚苏醒的克莱恩·莫雷蒂生活在同一座城市、同一段历史中。你可以选择任何合理的人生，追随不同途径与势力，干预熟悉的事件，也可以完全绕开它们。世界不会等待玩家，每一次有意义的行动都可能改变未来。

这是一套游戏引擎，而非预先写好的互动小说。它把自由角色扮演、明确判定、持久化战役、正典知识边界、确定性状态面板与 IM 平台适配组合在一起。

## 为什么好玩

| 系统 | 带来的游戏体验 |
|---|---|
| 自由行动 | 推荐选项不会把玩家锁进菜单，任何合理的世界内行为都可以尝试。 |
| 持续运转的世界 | 势力、威胁和重大事件会继续发展，不会停下来等待玩家。 |
| 真实后果 | 金钱、伤势、怀疑、关系、污染与错过的时机都会持续保留。 |
| 有边界的社会权力 | 个人好感、社会地位、组织职位、明确权限、声望与通缉热度分别记录；朋友的信赖不会自动变成组织授权。 |
| 承诺与生计 | 人情、承诺、契约、誓言、把柄、工资、生活成本、疗养、稀缺和财务债务都会延续，同时避免逐餐记账。 |
| 公平风险与失败 | 不可逆判定先说明角色可预见的风险；失败会改变局势，并留下新的行动方向。 |
| 可解的谜题 | 必需结论保留独立线索路径，证据记录来源、可信度和验证状态。 |
| 序列成长 | 魔药、扮演、灵性、仪式、材料与失控风险构成完整的晋升循环。 |
| 蝴蝶效应 | 玩家干预会积累因果值，可以改变重大命运锚点，却无法把正典角色变成傀儡。 |
| 不可读档重掷 | 骰点与后果只结算一次；故障恢复只修复中断写入，不会重掷历史。 |
| 可审计随机 | 判定使用系统安全随机源、已承诺的 HMAC 随机流或平台可验证随机源，并记录原始骰、上下文、计数器或平台凭证，以及最终裁决。 |
| 三种难度 | 可以体验命运眷顾、平凡求生，或者充满恶意的地狱旅程。 |
| 有推进力的章节 | 每章都有核心问题和压力源，只有产生不可逆变化后才能关闭。 |
| 可调内容强度 | 恐怖、血腥、恋爱、原著剧透与硬性避雷项采用安全默认值，并可随时调整。 |
| 可选沉浸插图 | 在核心信息输出完成并取得玩家同意后，可为关键人物、道具和场景生成插图。 |

## 胜负与游戏长度

第一场有意义的场景结束后，Agent 会根据角色背景和已公开的命运钩子提供四个「命运志向」，同时支持自由填写。常见方向包括获得自由、追索真相或复仇、掌握非凡力量、获得地位或归属，以及保护某个人或改变一场命运。锁定志向前，玩家会确认一至三条可观察的成功条件；完成条件必须引用已经提交的事件证据，终局门槛不会在后续被临时改变。

| 结果 | 含义 |
|---|---|
| 胜利 | 完成命运志向，并由玩家选择在此结束战役。 |
| 未竟 | 玩家在当前志向完成前主动退休。 |
| 败亡 | 角色不可逆死亡、完全失控或同化，或者永久失去自主行动能力且没有合理的世界内恢复路径。 |

完成志向只会开启终局选择，不会强制结束。玩家可以归档旧目标并选择新的志向。暂时失败、被捕、负债、受伤或关系破裂仍是游戏的一部分，不会自动判负。

每个结局还会获得独立的影响评级：凡尘、非凡、传奇或神话。它衡量因果影响，而非单纯比较序列。凡人可以胜利并留下传奇，高序列角色也可能败亡。

| 节奏档 | 预期长度 |
|---|---|
| 紧凑 | 约 12～20 个有意义场景，分为 3～4 章 |
| 标准 | 约 30～60 个有意义场景，分为 5～8 章；默认选项 |
| 长篇 | 80 个以上有意义场景，适合多城市、多势力或高序列生涯 |

这些数字是公开的体验预期，不是强制回合上限。有意义场景必须包含真实选择、发现、后果、关系变化或世界推进；如果连续两个场景都没有产生这些内容，Agent 必须压缩过场或进入下一个有效节点。玩家可以随时切换节奏，不会改变难度或推进世界时间。

一章通常包含四至八个有意义场景，场景数只作节奏参考。真正的章节契约是一项玩家能理解的核心问题、一个持续压力源和至少一项不可逆变化。章节关闭时会复核命运志向、关系、线索、世界时钟、组织、经济和承诺，只更新实际发生变化的领域。

## 核心架构

游戏事实与表现层完全分离。HTML 渲染失败、Telegram 重试或图片生成超时，都不能改变骰点、推进时间或重写战役状态。

```mermaid
flowchart TD
    U[玩家] --> T[本地 Agent 或 IM 适配器]
    T --> A[运行 SKILL.md 的 Agent]
    A --> Q[精简常规回合契约]
    Q --> R[当前领域的权威模块]
    R --> C[行动裁决与连续性]
    C --> D{需要判定？}
    D -->|是| G[可审计 d100 随机源]
    D -->|否| E[追加唯一且不可变的事件]
    G --> E
    E --> S[提交权威状态]
    S --> J[编年史与可移植记忆锚]
    S --> P[公开面板模型]
    S --> O[按平台能力生成投递计划]
    P --> H[HTML 或 SVG 渲染器]
    H --> I[PNG / JPEG / WebP]
    P --> F[富文本或纯文字降级]
    O --> F
```

| 层级 | 职责 | 主要文件 |
|---|---|---|
| Agent 契约 | 加载精简回合契约、按领域升级读取权威模块，并保证事务顺序 | `SKILL.md`、`references/runtime-core.md` |
| 游戏语义 | 一个权威索引，以及完整拆分的核心、正典、途径、裁决、因果、呈现和附录模块 | `references/ruleset.md` 及其链接的七个模块 |
| 持久化 | 战役隔离、只追加事件、原子状态、并发与恢复 | `references/runtime-and-storage.md` |
| 传输层 | Telegram 与通用 IM 投递、去重、按钮和 outbox | `references/transport-adapters.md` |
| 表现层 | 公开信息边界、移动端状态卡、语义色与插图授权 | `references/visual-media.md` |
| 确定性 UI | 校验公开模型并生成自包含 HTML 或 SVG | `scripts/render_panel.py` |
| 运行时完整性 | 生成可审计判定，并校验、提交或恢复状态补丁 | `scripts/roll_check.py`、`scripts/campaign_runtime.py` |
| 传输完整性 | 按平台能力调整同一个已提交回合，不重新裁决 | `scripts/transport_contract.py` |
| 可移植性检查 | 检测规则卷缺失、权威漂移、Markdown 删除线风险、原始 HTML 与移动端过宽表格 | `scripts/check_rules.py`、`scripts/check_markdown.py` |

## 运行时加载与速度

每次游戏内请求只固定加载 `turn-core-v1` 精简契约。新建、迁移、恢复、规则摘要变化、一致性失败时读取三份完整基线模块；普通回合只在触及对应规则领域时升级读取相关权威模块。完整规则仍是唯一权威，精简契约只保存安全不变量和保守升级路由。

`references/rules-manifest.json` 使用 SHA-256 摘要绑定精简契约与可缓存规则文件。只有当前模型确实能够访问摘要匹配的规则文本时，才算缓存命中；数据库标记或旧会话记忆不能代替内容。

IM 服务默认提交与状态修订绑定的最小工作集：本次行动相关状态、当前志向与章节、临近时钟与调查、相关社会或经济记录、最近 2～4 条事件，以及更早前置事件的引用。投影过期或字段不足时回退到权威状态，禁止猜测。

本地校验、随机、事务提交与传输规划均为轻量确定性操作。真实体感主要受模型推理、网络投递与媒体渲染影响。因此状态卡延迟时先发送同一修订的文字状态；可选 AI 插图只在核心回合和玩家授权完成后异步运行。

## 安装

将仓库直接克隆到 Codex Skill 目录：

```bash
git clone https://github.com/zyfayes/lotm-text-game-skill.git \
  ~/.codex/skills/lotm-text-game
```

重新启动或刷新 Agent，然后输入：

```text
使用 $lotm-text-game 开一局。
```

其他支持目录式 Skill 的 Agent 也可以加载根目录的 `SKILL.md`，但需要保留仓库内部的相对路径结构。

### 自动更新

通过 Git 安装的 Skill 会在每个 Agent 进程或会话首次加载时检查可信公开仓库的 `main` 分支。启动钩子每次都会调用；`.git` 内的五分钟检查缓存可以避免短生命周期 IM Worker 重复访问网络。远端检查会快速超时，任何失败都不会阻止使用当前已安装版本继续游戏。

只有工作区干净、origin 与本仓库一致、远端提交能够快进，并且候选版本在隔离 worktree 中通过规则、Markdown 和单元测试校验时，才会自动更新。更新器不会重置本地改动，也不会接触战役数据。复制安装仍可正常使用，但不具备自更新能力。设置 `LOTM_AUTO_UPDATE=0` 可以关闭自动更新。

## 一局游戏如何开始

1. 玩家选择难度。
2. 玩家选择性别。
3. Agent 当场生成四张新背景卡，并提供自定义选项。
4. 玩家亲自为主角命名。
5. 引擎建立持久化战役账本，并立即生成第一张状态面板。
6. 开局场景开始，同时提供推荐选项与自由行动。
7. 第一场有意义的场景结束后，玩家选择或填写命运志向，并确认战役节奏。

角色默认以普通人开局。平衡校验通过的自定义角色最高可以从序列 9 开始，但必须承担真实代价。

新战役使用 v1.7 状态和事件契约。引擎会直接写入默认内容设置：标准恐怖、克制血腥、恋爱内容先征求同意、只按角色知识处理原著剧透，以及尚未填写硬性避雷项；不会为此增加冗长的开局问卷，玩家可以随时修改。

正式规则只支持一名主角和一名权威控制者。群聊可以共同围观，但其他成员属于观众；多人投票、轮流控制、玩家对抗、并发秘密与多角色队伍不属于 v1.7。

原始 v1.6 Schema 作为兼容资源原样保留。安装 v1.7 不会自动改写 v1.6 战役；迁移需要玩家明确提出，并追加迁移事件。更早的 v1.2 至 v1.5 账本可以在只读模式下识别版本并校验事件连续性，在明确迁移前仍会拒绝写入、恢复和记忆锚导出。

## 战役持久化

创建战役前先解析数据落点：

```bash
python3 scripts/runtime_paths.py --mode local --workspace-root /absolute/project --create
```

本地模式默认使用显式传入的项目根。Telegram、Hermes、Web 等服务部署必须设置 `LOTM_DATA_ROOT` 或传入 `--data-root`；引擎不会从进程的临时工作目录推断持久化位置。解析器会拒绝文件系统根目录、用户主目录本身以及可复用 Skill 包。

解析后的数据根使用以下结构：

```text
<resolved-data-root>/campaigns/
├── active.yaml
└── <campaign_id>/
    ├── state.yaml
    ├── events.jsonl
    ├── journal.md
    ├── canon-deviations.md
    └── latest-anchor.md
```

`state.yaml` 保存最新权威状态，`events.jsonl` 是只追加的完整审计记录。编年史只记录角色亲历或已经确认的事实；隐藏世界状态与角色知识严格分离。

v1.7 运行时继续记录目标证据、线索与调查、公开风险、随机来源、后果及带旧值校验的状态补丁，同时校验组织权限、社会地位、承诺、财务循环、章节切换、内容偏好与正典来源置信度。本地 Agent 可以运行：

```bash
python3 scripts/campaign_runtime.py validate --campaign-dir /absolute/runtime-root/campaigns/example-campaign
python3 scripts/campaign_runtime.py recover --campaign-dir /absolute/runtime-root/campaigns/example-campaign
```

判定工具既可检查概率，也可生成真实骰点：

```bash
python3 scripts/roll_check.py odds --mode ordinary --target 100 --attribute 45 --skill 10
python3 scripts/roll_check.py roll --mode ordinary --target 100 --attribute 45 --skill 10 \
  --context evt-000042:inspect-door
```

服务端部署可以把这些记录映射到 SQLite、PostgreSQL 或对象存储，但必须保留版本校验、幂等、事务顺序和故障恢复语义。

## 跨平台行为

游戏会先提交事件，再处理表现层。同一个状态修订可以按照 Telegram 或其他 IM 平台的能力确定性降级。

| 平台限制 | 确定性行为 |
|---|---|
| 没有可写文件系统 | 在内存中构建带摘要校验的可移植记忆锚，标记持久化降级，并禁止把隐藏状态发到群聊。 |
| 不能发送图片 | 用同一修订的必需文字摘要替代状态卡。 |
| 没有按钮 | 发送编号完整的文字选项，同时保留自由行动提示。 |
| 消息长度很短 | 按语义边界拆分；无法保持编号与全文完整的选项会被拒绝发送。 |
| 不支持编辑消息 | 另发一条明确的纠错消息。 |
| webhook 或回调重复 | 返回该入口标识对应的既有结果，不再次调用游戏引擎。 |
| 媒体发送超时 | 保持待确认或可重试；事件、骰点、状态修订和世界时间不变。 |
| 多个聊天或话题 | 先解析完整范围键和控制者，再加载当前战役。 |

传输规划器只使用 Python 标准库；宿主提供内存对象时，它不需要读写文件。

## 渲染状态面板

渲染器只依赖 Python 标准库：

```bash
python3 scripts/render_panel.py \
  --input assets/panel-example.json \
  --format html \
  --output status.html

python3 scripts/render_panel.py \
  --input assets/panel-example.json \
  --format svg \
  --output status.svg
```

生成的 HTML 与 SVG 均为自包含文件。在 Telegram、Discord 等聊天平台中，应先将其光栅化为 PNG、JPEG 或 WebP。如果视觉渲染失败，引擎会依次降级到平台富文本和纯文字，同时保持战役状态不变。

界面没有 MMO 式的全局稀有度。封印物等级、事件危险度、序列层次、配方可信度与公开确认的物品类型分别表达；颜色只辅助已知语义，不会替玩家进行隐藏鉴定。

## 仓库结构

```text
.
├── SKILL.md
├── agents/
│   └── openai.yaml
├── assets/
│   ├── dossier-masthead-engraving.png
│   ├── icon.svg
│   ├── panel-example.json
│   └── panel-example.png
├── references/
│   ├── public-panel.schema.json
│   ├── campaign-state.schema.json
│   ├── campaign-event.schema.json
│   ├── portable-anchor.schema.json
│   ├── campaign-state.v1.6.schema.json
│   ├── campaign-event.v1.6.schema.json
│   ├── portable-anchor.v1.6.schema.json
│   ├── ruleset.md
│   ├── rules-manifest.json
│   ├── runtime-core.md
│   ├── core-rules.md
│   ├── canon-and-world.md
│   ├── pathways-and-powers.md
│   ├── adjudication-and-systems.md
│   ├── causality-and-continuity.md
│   ├── presentation.md
│   ├── appendices.md
│   ├── runtime-and-storage.md
│   ├── transport-adapters.md
│   └── visual-media.md
├── scripts/
│   ├── campaign_runtime.py
│   ├── transport_contract.py
│   ├── check_rules.py
│   ├── check_markdown.py
│   ├── runtime_paths.py
│   ├── self_update.py
│   ├── roll_check.py
│   └── render_panel.py
└── tests/
    ├── test_p0_runtime.py
    ├── test_p1_runtime.py
    ├── test_startup_runtime.py
    └── test_transport_contract.py
```

运行标准库回归测试：

```bash
python3 -m unittest discover -s tests -v
python3 scripts/check_rules.py
python3 scripts/check_markdown.py README.md README_CN.md SKILL.md references
```

## 安全与隐私

- 可复用 Skill 不应包含真实战役数据、玩家媒体、聊天标识、凭据或机器人令牌。
- 玩家可见面板与插图提示词只能使用已经公开的事实。
- 重复 webhook、按钮重试和上传失败不得重复结算同一个行动。
- 可选插图只负责表现，不能生成物品、泄露秘密、消耗资源或推进时间。

## 免责声明

这是一个非官方、非商业的同人项目，与阅文集团、起点中文网、作者爱潜水的乌贼及任何官方授权方不存在隶属、授权或背书关系。源自《诡秘之主》的名称、角色、世界观及其他元素，其权利归各自权利人所有。

本项目的世界观表达、游戏规则与呈现方式，也受到网络上小说读者、桌面角色扮演玩家和文字游戏爱好者分享内容的启发，仅供学习与交流使用。

MIT License 只适用于仓库作者有权授权的原创程序代码、运行协议与界面实现，不授予任何第三方知识产权许可。使用者有责任确保其部署、传播与生成内容符合适用法律和平台规则。
