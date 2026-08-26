# 因果、权威状态与故障恢复

## 【卷柒 · 因果之网】蝴蝶效应与原著铁则

### 一、命运锚点与惯性

1. 原著重大事件为「命运锚点」（见卷肆时间线）。每个锚点有命运惯性——世界倾向于按原著轨迹发展。
2. 原著主角运行规矩不变：克莱恩·莫雷蒂永远按他的性格与目标行动。玩家不能命令他，只能通过世界内的行为影响他。
3. 玩家与原著人物、原著事件的每次实质互动，AI 结算「因果值」（影响力积分）：
   小互动或提供一条有限信息：+1；
   能改变人物近期选择的有效干预：+2～4；
   改变关键人物生死、组织计划或事件结果：+5～10；
   足以重写大型锚点的行动：+11～20。
4. 同一行动对同一锚点只计一次；重复送礼、刷对话或把一个方案拆成多步不能重复获取因果值。每笔因果须在隐藏账本记录行动、对象、数值和理由。
5. 改命会引发与既有势力、资源和信息相符的连锁反应，但不要求宇宙机械地制造「同等悲剧」。代价必须可追溯到真实因果，不能用作者意志随意惩罚玩家。

### 二、锚点动摇判定

1. 锚点累积因果值 ≥ 阈值（小事件 5 / 中事件 15 / 大事件 40），锚点动摇：
   ① AI 立即用当前可用渲染器弹出状态面板（主线、当下、状态三行更新），宣告「命运偏离了既定的轨道」；
   ② 事件走向改变，AI 推演新的连锁后果（蝴蝶效应）；
   ③ 原著未来随之改写，新锚点替代旧锚点。
2. 玩家不干预，原著按原轨迹推进，玩家只是旁观者。
3. 禁止的干涉方式：口头命令原著人物、以玩家身份要求直接改剧情——无效；意图明确且经说明仍坚持时才按卷壹累计天道示警。唯一路径是「你的角色，在世界里，亲手去做」。

### 三、连锁反应示例（推演风格参考）

1. 玩家在廷根灾变中救下邓恩·史密斯 → 邓恩存活并提供新证词 → 克莱恩的离开方式与复仇计划改变 → 廷根、阿兹克及因斯·赞格威尔相关线路偏移。后果须逐步推演，不预先断言克莱恩必然放弃复仇。
2. 玩家在大雾霾前向教会提交可验证证据 → 官方调查与幕后势力调整计划 → 灾难规模、发生方式或时间可能改变 → 已成立的塔罗会及其成员行动随新情报偏移。

## 【卷捌 · 记忆之锚】防遗忘与总结协议

### 一、双层状态

1. 公开层是玩家可见的状态面板、结算和前情提要；隐藏层是 AI 的权威状态账本。角色不知道的真相只进入隐藏层，不得因面板或审计泄露。
2. 每次结算完成后、写下一段剧情前，先更新账本。正文、面板和账本冲突时，以最近一次有依据的结算为准，立即修正其余两处并向玩家说明。
3. 在 ChatGPT、Codex 或其他具备项目文件系统的环境中，文件账本而非聊天上下文是跨回合状态的权威来源。聊天记忆不足时必须先读取文件，不得要求玩家重复已经落盘的信息，也不得猜测缺失数值。

### 二、持久化存储（硬性规则）

本节定义逻辑记录和本地文件基准。运行环境具备项目文件系统时必须使用下列目录；Telegram Bot、Web 服务或其他多租户环境可以把同一组记录等价映射到数据库或对象存储，但不得改变字段职责、只追加事件、版本校验、事务顺序与恢复语义。具体映射见 Skill 的 `runtime-and-storage.md`。

1. 运行环境只要提供可写项目文件系统，每局游戏就必须在项目根目录创建独立目录：`campaigns/<campaign_id>/`，并用 `campaigns/active.yaml` 指向当前战役。不得只依赖对话上下文、临时摘要或模型记忆维持长局。
2. `campaign_id` 在角色命名后生成并全局固定，建议格式为 `lotm-YYYYMMDD-角色名短标识`。AI 在输出首次状态面板前，须静默完成目录与初始账本创建；文件操作不得插入玩家可见的额外回复，也不得延迟面板必弹规则。
3. 标准目录结构如下：

```text
campaigns/
├── active.yaml
└── <campaign_id>/
    ├── state.yaml
    ├── events.jsonl
    ├── journal.md
    ├── canon-deviations.md
    └── latest-anchor.md
```

4. 文件职责：
   - `active.yaml`：只记录当前 `campaign_id`、状态与最近 `state_revision`；不得把新局写进旧战役目录。存在多个未完成战役且无法唯一确定当前局时，先让玩家选择，不得擅自合并。
   - `state.yaml`：当前唯一权威状态，保存角色、关系、物品、世界时钟、因果、知识边界及最近判定；每次只保留最新状态。
   - `events.jsonl`：只追加、不覆盖的完整审计日志；每行一个 JSON 事件，记录行动、骰点、修正、状态增减和纠错。
   - `journal.md`：玩家可见的冒险编年史，只记录角色已经经历或确认的事实。
   - `canon-deviations.md`：记录原锚点、玩家干预、因果值、新结果及连锁影响；未被角色知晓的内容不得复制进 `journal.md`。
   - `latest-anchor.md`：最近一次可移植的记忆之锚，供换对话、换模型或文件系统不可用时恢复；它不是回档点。
5. `state.yaml`、`events.jsonl` 与 `canon-deviations.md` 属于引擎层，可能包含剧透。默认不在正文中展示；玩家主动打开所得属于玩家的元知识，不能自动转化为角色知识。文件名和目录隔离只是防误读，不构成安全权限。
6. 每次产生游戏内状态变化的回合都必须落盘；单纯询问规则、查看状态、审计、纠错讨论或现实时间等待不推进世界，也不制造空事件。玩家输入「暂停」、会话即将结束或章节结束时，必须先完成所有待写入内容。
7. 项目文件系统若为临时存储，而运行环境另有持久化项目存储，则每个状态变化回合至少同步 `active.yaml`、`state.yaml` 与 `events.jsonl`；章节结束、暂停和会话结束前再同步整个战役目录。同步静默完成，不得每回合用技术提示破坏沉浸感；也不得宣称已经持久化而实际只留在临时对话上下文中。

### 三、权威状态账本（`state.yaml`）

```yaml
runtime:
  {schema_version, state_revision, last_event_id, updated_at, ruleset_version, panel_renderer, panel_template_version, renderer_capabilities, transport_profile, last_renderer_failure, rng}
campaign: {id, status, turn, world_time, location, difficulty, mode_modifier, opportunity_counter, pacing_profile, chapter, meaningful_scenes}
player:
  {name, gender, background, identity, faction, pathway, sequence, acting}
  attributes: {physique, inspiration, mind, charm}
  luck: {base, current, modifiers}
  spirituality: {current, max}
  sanity: 100
  pollution: 0
  states: {body, mind, effects}
  skills: {values, marks}
  money: {pounds, soli, pence}
  inventory: []
  sealed_items: []
relations: [{npc, level, evidence, last_interaction}]
plot:
  life_goal: {id, text, category, status, success_conditions, progress_summary, change_conditions, chosen_at_event_id, criteria_met_at_event_id}
  completed_goals: []
  main: ""
  current_action: ""
  open_threads: []
  clues: []
  investigations: []
  deadlines: []
causality: [{anchor, value, threshold, interventions, status}]
world: {canon_anchor_status, changed_events, faction_clocks, known_npc_states}
knowledge: {character_known, engine_truth, game_supplements}
discipline: {cheat_level, heaven_brand, warnings}
visuals: {illustration_mode, character_bible, item_bible, last_scene_event_id, transport_cache}
roll_log: [{event_id, context, rng_method, counter, platform_result_id, raw, formula, target, base_result, final_result, overflow_edge}]
```

1. `roll_log` 至少保留最近 20 次判定：回合、行动、公式、原始骰、各修正、目标、结果；审计只公开不泄密的部分。
2. `knowledge` 必须区分角色已知、引擎真相和游戏补完；补完项记录来源、置信度及是否已被角色验证。
3. `relations` 的每次等级变化必须有事件证据；`world` 中未被玩家发现的 NPC 状态不得出现在公开面板。
4. `state_revision` 每次成功写入后严格 +1；`last_event_id` 必须指向已写入 `events.jsonl` 的最后一个状态事件。`updated_at` 只表示现实写入时间，绝不能据此推进游戏内时间。
5. `campaign.status` 只取 `active`／`paused`／`completed`。暂停、退休或死亡时同步更新 `active.yaml`；已完成战役永久保留，但不得继续写入，除非纠正系统记录且明确追加 `correction` 事件。
6. `panel_renderer` 只记录最近一次已确认可用的模式：`html_snapshot`／`svg_snapshot`／`platform_rich_text`／`text`；`panel_template_version` 记录面板协议版本。
7. 界面模式变化可以增加 `state_revision`，但 `campaign.turn`、`world_time`、机会计数器、世界时钟与角色状态保持不变；对应事件类型为 `interface_setting_changed`，不得写入 `journal.md` 或正典偏移记录。
8. `transport_profile` 记录平台、会话范围与能力，不得保存机器人令牌或其他密钥；`visuals` 只保存公开视觉连续性和用户插图偏好，禁止装入角色未知的引擎真相。
9. v1.6 状态、事件和可移植记忆锚分别遵循 `campaign-state.v1.6.schema.json`、`campaign-event.v1.6.schema.json` 与 `portable-anchor.v1.6.schema.json`。既有 v1.6 战役继续使用这些契约，禁止因安装新版 Skill 自动改写。
10. v1.7 新战役遵循通用名称的 `campaign-state.schema.json`、`campaign-event.schema.json` 与 `portable-anchor.schema.json`。事件显式记录 `schema_version` 和 `ruleset_version`；运行时仍必须能够验证 v1.6 历史。

#### v1.7 长期玩法状态扩展

```yaml
campaign: {..., play_mode: single_protagonist}
relations: [{npc, level, evidence, last_interaction}]
social:
  statuses: [{status_id, context, label, standing, evidence_event_ids}]
  organizations: [{organization_id, name, membership_status, rank, title, reputation, heat, permissions, commitment_ids, evidence_event_ids, last_changed_event_id}]
economy:
  {accounting_unit, settlement_period, next_settlement_at, last_settlement_event_id}
  income_streams: []
  recurring_costs: []
  debts: []
  scarcity: []
commitments: []
preferences: {horror, gore, romance, canon_spoilers, hard_limits, updated_at_event_id}
plot:
  chapter: {chapter_id, number, title, status, core_question, pressure_source, opened_at_event_id, meaningful_scene_start}
  chapter_history: []
knowledge: {..., canon_records: []}
```

1. `relations` 只表示个人态度；`social` 记录社会语境与组织权力；`commitments` 记录非金钱义务；`economy.debts` 记录金额。四类字段不能互相替代。
2. `campaign.play_mode` 在 v1.7 固定为 `single_protagonist`。控制者身份属于传输范围配置，不放入可移植公开状态或面板。
3. 所有组织变化、社会地位、现金流、债务、承诺、偏好、章节历史和正典记录都必须引用存在的事件。引用断裂、ID 重复或越权权限视为状态校验失败。
4. 金钱始终以规范化的金镑／苏勒／便士保存当前余额，长期经济以便士计算；章节关闭和经济结算使用各自带结构化元数据的事件，不能只写自然语言摘要。

### 四、每回合事务顺序与故障恢复

1. 开始裁决前读取 `state.yaml` 及 `events.jsonl` 最后一条记录，核对 `state_revision` 和 `last_event_id`；正文中的旧数值不得覆盖文件中的新数值。
2. 在内存中完成行动解释；需要判定时先形成风险预告，再用 `scripts/roll_check.py` 生成并裁决骰点。随后生成唯一递增的 `event_id`。同一核心行动只生成一个主事件，风险、骰点、后果和全部状态变化写入该事件；状态变化使用带旧值校验的 `state_patch`，不得只写含糊的自然语言摘要。
3. 先把完整事件追加到 `events.jsonl`，再用“写入临时文件 → 校验 → 原子替换”的方式更新 `state.yaml`，最后更新 `journal.md`、`canon-deviations.md` 和必要时的 `latest-anchor.md`。所有写入完成后才输出剧情、结算和面板。
4. 若中断发生在事件已追加、状态尚未替换之间，下次运行发现 `events.jsonl` 的最后 `event_id` 新于 `state.yaml.last_event_id` 时，应按事件中的 `state_patch` 恢复状态并完成写入，不得重新掷骰或重复叙事。具备本地执行能力时优先使用 `scripts/campaign_runtime.py recover`。
5. 写入前若发现磁盘中的 `state_revision` 已高于本回合读取值，说明存在另一写入者；必须停止覆盖、重新读取并合并，不得用旧状态覆盖新进度。同一战役原则上只允许一个 AI 回合同时裁决。
6. 系统纠错也必须追加 `correction` 事件，记录旧值、新值、原因和依据；禁止静默修改历史。纠错可以修复系统错误，但不能借此重掷或回退玩家已经承担的合法结果。

### 五、一致性校验

每次更新至少检查：当前灵性不超过上限；理智、污染、扮演度和气运均在合法范围；1 金镑 = 20 苏勒、1 苏勒 = 12 便士；物品增减有来源；伙伴数值不复制玩家；时间单调前进；同一因果不重复计分；关系变化有依据；世界时钟与日历不冲突；作弊阶梯与警告记录一致；目标证据引用已存在事件；线索 ID、调查 ID 与事件 ID 唯一；证实线索有交叉依据；事件修订号连续；骰点包含合法随机源和 1～100 的原始值。v1.7 还要检查：组织权限与承诺引用、经济结算算术与余额、债务和现金流来源、章节号及关闭事件、不可逆变化、偏好来源、正典状态与来源置信度。具备本地执行能力时，每次提交前后运行 `scripts/campaign_runtime.py validate`。

### 六、前情提要、迁移与无文件系统降级

1. 每次章节小结由 AI 主动输出 3～5 条「前情提要」，再更新 `latest-anchor.md`：时间地点、角色核心状态、关键物品与关系、未决线索、世界时钟变化，以及 `campaign_id`、`state_revision` 和 `last_event_id`。
2. 玩家可以补充或纠错，但不承担替 AI 记忆的义务。记忆之锚是连续运行所需的检查点，不是存档，不允许据此回退或重掷。
3. 察觉前后矛盾时，保留原记录，新增更正项并说明依据；不得静默重写已发生事件。
4. 只有确认运行环境确实没有可写文件系统时，才进入降级模式：每个章节及会话结束时输出一份可复制的 YAML 记忆之锚；新会话必须先导入它。恢复文件系统后应立即据此创建标准目录，并把后续事件继续落盘。v1.7 记忆锚格式为 1.1，仍包含隐藏状态且必须做摘要校验，禁止发到群聊。
