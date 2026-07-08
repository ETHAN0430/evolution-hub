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

除 `RELATED_TO` 外，关系均保持方向。历史数据库中已经存在的双向认知边不会自动迁移；新写入遵循新语义。

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

## 历史边归一化

`HyMemoryClient.normalize_legacy_cognitive_edges()` 默认 `dry_run=True`。它只自动规划可由节点时间判定的双向 `CORRECTED`：保留“新节点 → 旧节点”，删除反向副本。

```python
plan = client.normalize_legacy_cognitive_edges("user-id")
result = client.normalize_legacy_cognitive_edges("user-id", dry_run=False)
```

`SHAPED_BY` 和 `BUILDS_ON` 的历史双向副本无法仅凭现存属性可靠恢复原始方向，因此不会自动删除，应根据内容或 LLM 审核后迁移。

## 后续验证

当前测试覆盖关系注册、方向写入、临时引用解析、散事实演化触发、历史 `CORRECTED` dry-run 归一化和非版本链节点的认知关系富化。真实 Kuzu 升级后还应执行一次集成测试，确认新关系表由初始化流程创建。
