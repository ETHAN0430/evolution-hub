# HY Memory 认知演化闭环

本次改造不新增数据库。VDB 继续保存事实与语义索引，Kuzu/Neo4j 继续保存 Schema 与关系，`DERIVED_FROM` 继续承担证据来源。

## 数据语义

认知节点使用 `MemoryNode.custom.cognitive_type` 标记角色：

- `experience`
- `evidence`
- `inference`
- `belief`
- `decision`
- `framework`
- `pattern`
- `intention`

Memory-to-Memory 关系统一定义在 `data/graph_relations.py`：

- `RELATED_TO`：无方向的主题关系
- `CORRECTED`：新版本修正旧版本
- `SHAPED_BY`：观点或框架受经历/特质塑造
- `BUILDS_ON`：认知结构建立在另一结构之上
- `SUPPORTED_BY`：观点受到证据支持
- `CONTRADICTED_BY`：观点被证据反驳
- `LED_TO`：经历、证据或推导导致观点/决策
- `RESULTED_IN`：观点或决策产生结果

除 `RELATED_TO` 外，关系均保持方向。历史数据库中已经存在的双向认知边默认不会自动改写；可通过 dry-run 工具先生成迁移计划。

## 来源、置信度与时间

- 边理由：`relation_type`
- 边置信度：`weight`
- 写入时间：`created_at`
- 支撑记忆：源节点到 VDB 影子节点的 `DERIVED_FROM`

这套映射复用现有字段，不要求数据库迁移。

## 检索输出

`expand_evolution_chains()` 现在接受可选 `graph_store`：

1. `supersedes` 继续生成版本主链；
2. `get_cognitive_relations()` 查询一跳原因/结果支路；
3. 搜索结果增加 `cognitive_relations`；
4. Hermes provider 将关系方向、关联内容和理由写入记忆上下文。

典型结果：

```text
旧观点 -> 当前观点
当前观点 -[SUPPORTED_BY]-> 新证据
当前观点 -[CONTRADICTED_BY]-> 反例
新经历 -[LED_TO]-> 当前决策
```

## Digest 触发与临时引用

Digest 仍以 DBSCAN cluster 作为高层 Schema 归纳的主要入口，但新增一条演化入口：当散事实没有形成 cluster、却向量命中已有 Schema 时，S2 Agent 仍会运行。这使单条关键反例或观点修正不必等待四条相似事实。

单次 JSON 规划支持 `create_schema.ref`。后续操作可用 `$ref` 引用执行阶段生成的真实 UUID：

```json
[
  {"op":"create_schema","ref":"belief_v2","content":"新观点","evidence_list":["fact-1"]},
  {"op":"add_edge","source_id":"$belief_v2","target_id":"old-schema-id","edge_type":"CORRECTED","reason":"新证据推翻旧假设"}
]
```

## Schema 防重复

`create_graph_node` 写入 L6 Schema 前会先用新 Schema 的内容向量搜索同用户同 agent 的现有 L6 Schema。若最高相似度达到 `MEMORY_S2_SCHEMA_DEDUPE_THRESHOLD`（默认 `0.95`），系统不会创建新节点，而是把新 evidence 追加到命中的旧 Schema，并返回旧 `node_id`。

这层检查位于工具执行层，因此可以覆盖跨 batch 的重复：即使 LLM 在不同 batch 中各自决定创建同一 Schema，最终写入时也会复用已有节点。

历史重复可用只读审计：

```python
audit = client.audit_duplicate_schema_nodes("user-id", threshold=0.95)
```

返回值包含高相似 pair 和合并后的候选 groups；该接口不删除、不改边，适合先人工看一眼。

也可以生成合并 dry-run 计划：

```python
plan = client.plan_duplicate_schema_merge("user-id", threshold=0.95)
```

计划会为每个重复 group 选择最早节点作为 `canonical`，其余节点作为 `duplicates`，并给出 `mark_duplicate` 建议动作。该接口仍然只读，不迁 evidence、不删节点、不改边。

## 历史边归一化

`HyMemoryClient.normalize_legacy_cognitive_edges()` 默认 `dry_run=True`。它只自动规划可由节点时间判定的双向 `CORRECTED`：保留“新节点 → 旧节点”，删除反向副本。

```python
plan = client.normalize_legacy_cognitive_edges("user-id")
result = client.normalize_legacy_cognitive_edges("user-id", dry_run=False)
```

`SHAPED_BY` 和 `BUILDS_ON` 的历史双向副本无法仅凭现存属性可靠恢复原始方向，因此不会自动删除，应根据内容或 LLM 审核后迁移。

历史 `RELATED_TO` 可用同一套 reason 关键词规则快速迁移。默认 dry-run：

```python
plan = client.migrate_legacy_related_edges("user-id", dry_run=True, max_edges=500)
result = client.migrate_legacy_related_edges("user-id", dry_run=False, max_edges=500)
```

迁移规则保守处理：

- `LED_TO` / `RESULTED_IN` / `CONTRADICTED_BY`：旧节点 → 新节点
- `CORRECTED` / `SHAPED_BY` / `BUILDS_ON`：新节点 → 旧节点
- `SUPPORTED_BY`：仅列为 `ambiguous`，不自动迁移
- 无明显 reason 信号：计入 `skipped`，继续保留 `RELATED_TO`

## 后续验证

当前测试覆盖关系注册、方向写入、临时引用解析、散事实演化触发、Schema 创建前去重、历史重复审计、历史 `CORRECTED` dry-run 归一化、历史 `RELATED_TO` 迁移计划和非版本链节点的认知关系富化。真实 Kuzu 升级后还应执行一次集成测试，确认新关系表由初始化流程创建。

## Digest 质量报告

`client.digest()` 返回中新增 `quality_report`：

```python
result = client.digest("user-id")
report = result["quality_report"]
```

核心字段：

- `schema_created`：本轮新建 Schema 数
- `schema_reused`：被动态去重拦截并复用的 Schema 数
- `evidence_added`：新增 evidence 连接数
- `edges_created`：新增 Schema 边数
- `edge_type_counts`：按边类型统计
- `related_to_ratio`：`RELATED_TO` 在新增边中的占比
- `warnings`：质量提示，如 `duplicate_schema_reused`、`high_related_to_ratio`、`no_graph_evolution`

这个报告用于判断一轮 digest 是真的产生认知演化，还是只是堆节点/堆弱相关边。

同一份报告也会写入 pipeline log，step 为 `SYSTEM2_QUALITY_REPORT`，供 Dashboard / Evolution Hub 直接展示。

## Graph 健康快照

当前认知图可用只读健康检查：

```python
health = client.graph_health_snapshot("user-id", duplicate_threshold=0.95)
```

核心字段：

- `schema_total`：活跃 L6 Schema 总数
- `duplicate_groups` / `duplicate_pairs`：高相似重复候选
- `edge_type_counts`：各类 Schema 边数量，`RELATED_TO` 会按无向 pair 去重
- `memory_edge_total` / `cognitive_edge_total`
- `related_to_ratio`：弱相关边占比
- `orphan_schema_count`：没有任何 Schema 边连接的 Schema
- `no_evidence_schema_count`：没有 `DERIVED_FROM` evidence 的 Schema

该接口只读，不做迁移、不改状态，适合在历史改写前判断图的污染程度。
