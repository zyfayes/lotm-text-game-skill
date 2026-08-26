# 《诡秘之主》文字游戏规则索引

> 版本：跨平台 Skill 运行版 v1.7（2026-08-26）
>
> 原则：完整保留自由探索、反作弊、命运锚点、正典校准、持久化与快节奏结构；把游戏语义、状态存储、传输平台和视觉生成彻底分离，使同一战役可由不同 Agent 与 IM 平台连续运行。

本索引不复述具体规则。各模块中的条款共同构成唯一权威规则集；不得只读索引后凭常识补写规则，也不得把未加载模块的内容猜成规则。

## 模块与唯一职责

| 模块 | 唯一权威范围 |
|---|---|
| [core-rules.md](core-rules.md) | 世界运行铁则、反作弊、回合结构、自由目标、难度、角色创建、开局、叙事与结局 |
| [canon-and-world.md](canon-and-world.md) | 世界观、组织与正典人物、时间线、正典来源和置信度协议 |
| [pathways-and-powers.md](pathways-and-powers.md) | 二十二途径、低序列能力、灵性、扮演、魔药、封印物与仪式 |
| [adjudication-and-systems.md](adjudication-and-systems.md) | 属性技能、风险预告、d100、伤害污染、经济、关系、组织、承诺、章节与调查 |
| [causality-and-continuity.md](causality-and-continuity.md) | 因果锚点、权威状态、事件事务、恢复、迁移和一致性校验 |
| [presentation.md](presentation.md) | 公开面板、触发词、渲染、IM 编排、插图与表现层故障恢复 |
| [appendices.md](appendices.md) | 术语、物品、判例、开场模板、维护来源与版本修订说明 |

运行时与平台的物理映射分别由 [runtime-and-storage.md](runtime-and-storage.md)、[transport-adapters.md](transport-adapters.md) 和 [visual-media.md](visual-media.md) 定义。它们不得重新定义游戏语义。

## 按任务加载

任何游戏内行动裁决都必须先完整读取 [runtime-core.md](runtime-core.md)。它只提供常规回合安全不变量、最小上下文和升级路由，不新增或覆盖游戏语义。

新建战役、显式迁移、故障恢复、规则摘要变化、状态版本异常或一致性失败时，必须完整读取本索引以及下列三个基线模块：

1. [core-rules.md](core-rules.md)
2. [adjudication-and-systems.md](adjudication-and-systems.md)
3. [causality-and-continuity.md](causality-and-continuity.md)

其他常规回合按 [runtime-core.md](runtime-core.md) 的升级条件完整读取相关权威模块。匹配 `ruleset_digest` 的持续会话上下文或不可变提示缓存可以复用已经提供给当前模型的完整文本；仅有数据库标记或旧会话记忆时仍视为未加载。

再按当前任务完整读取相关模块：

- 新建角色、进入新地点、接触正典人物或处理原著锚点：读取 [canon-and-world.md](canon-and-world.md)。
- 使用、学习、晋升或对抗非凡能力：读取 [pathways-and-powers.md](pathways-and-powers.md)。
- 生成状态面板、提示、插图或 IM 消息：读取 [presentation.md](presentation.md)。
- 解释术语、核对维护来源或审计版本变化：读取 [appendices.md](appendices.md)。

纯存储恢复可以只读取本索引、[causality-and-continuity.md](causality-and-continuity.md) 与 [runtime-and-storage.md](runtime-and-storage.md)；恢复后若要继续裁决，必须读取 [runtime-core.md](runtime-core.md)，并按行动命中的升级条件加载权威模块。

## 单一权威定义

- 角色创建、回合结构与结局：只以 [core-rules.md](core-rules.md) 为准。
- 判定、风险、后果、经济、关系、组织、承诺与章节：只以 [adjudication-and-systems.md](adjudication-and-systems.md) 为准。
- 正典来源、未知项与游戏性补完：只以 [canon-and-world.md](canon-and-world.md) 为准。
- 状态字段、事件顺序、事务、恢复与迁移：只以 [causality-and-continuity.md](causality-and-continuity.md) 为准。
- 面板触发、公开字段与渲染回退：只以 [presentation.md](presentation.md) 为准。

其他文件只能链接这些定义或说明如何实现，发生冲突时回到上述权威模块。

## 契约版本

新战役使用 v1.7 规则及通用名称的 v1.7 Schema：

- [campaign-state.schema.json](campaign-state.schema.json)
- [campaign-event.schema.json](campaign-event.schema.json)
- [portable-anchor.schema.json](portable-anchor.schema.json)

v1.6 契约保留为兼容校验资源：

- [campaign-state.v1.6.schema.json](campaign-state.v1.6.schema.json)
- [campaign-event.v1.6.schema.json](campaign-event.v1.6.schema.json)
- [portable-anchor.v1.6.schema.json](portable-anchor.v1.6.schema.json)

安装或读取 v1.7 Skill 不授权自动迁移旧战役。只有玩家明确要求迁移时，才能追加 `ruleset_migrated` 事件并补齐新字段；迁移前后的历史继续共用同一只追加事件链。
