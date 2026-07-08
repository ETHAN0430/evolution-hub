# evolution-hub / hy-memory — 项目索引

> 定制版 hy-memory 1.2.19 + Hermes 插件源码，含所有自定义 patch。

---

## 目录

- [一、文件结构](#一文件结构)
- [二、定制 patch 清单](#二定制-patch-清单)
- [三、修改文件详表](#三修改文件详表)
- [四、涉及概念](#四涉及概念)
- [五、部署与升级](#五部署与升级)
- [六、与官方版本的 diff 路径](#六与官方版本的-diff-路径)

---

## 一、文件结构

```
hy-memory/
├── package/hy_memory/          # Python 包源码 (site-packages)
│   ├── client.py               # 客户端入口
│   ├── server.py                # HTTP server
│   ├── config.py                # 配置
│   ├── pipelines/
│   │   ├── system2_agent.py    # 🔧 S2 Agent LLM prompt + 操作执行
│   │   ├── system2_tools.py    # 🔧 S2 工具执行器 (add_edge/evidence等)
│   │   ├── system2_writer.py   # S2 写入编排
│   │   ├── reader_legacy.py    # 🔧 主召回管线 (含 traverse_related)
│   │   ├── writer.py           # S1 写入 + reconcile
│   │   ├── cross_domain_sweeper.py
│   │   ├── _retrieval/
│   │   │   └── evolution.py    # _trace_full_chain 演化链回溯
│   │   └── ...
│   ├── data/
│   │   ├── graph_store_kuzu.py # 🔧 Kuzu 图存储 (4种REL TABLE)
│   │   └── graph_store_base.py # 🔧 图存储基类 (traverse_related等)
│   ├── agent/
│   │   ├── extractor.py        # LlmExtractor
│   │   ├── reconciler.py       # Reconcile 逻辑
│   │   └── ...
│   └── models/
│       └── memory.py           # MemoryNode 定义 (含 supersedes 链)
│
├── plugin/                     # Hermes 插件
│   ├── provider.py             # 🔧 Hermes 集成 provider
│   ├── server_manager.py       # 🔧 server 生命周期管理
│   ├── cli.py                  # CLI 工具
│   └── ...
│
└── README.md                   # 改动说明
```

🔧 = 已修改

---

## 二、定制 patch 清单

按修改动机分组：

### 2.1 S2 Digest / LLM Prompt

| # | Patch | 文件 | 说明 | 状态 |
|---|-------|------|------|------|
| P1 | **四种语义边** | `system2_agent.py` | Prompt 引导 LLM 产出 RELATED_TO / CORRECTED / SHAPED_BY / BUILDS_ON | ✅ 已上线 |
| P2 | **edge_type 设为必填** | `system2_agent.py` | 加 ✅ 正确示例 / ❌ 错误示例 / 自检规则 | ✅ 已上线 |
| P3 | **add_edge 传 edge_type** | `system2_tools.py` | 从 args 读 edge_type，不再硬编码 RELATES_TO | ✅ 已上线 |
| P4 | **domain=concept 自动打标** | `system2_tools.py` | Type 2 (Concept Schema) 自动打 domain=concept 标签 | ✅ 已上线 |
| P5 | **BATCH_SIZE=300** | `server_manager.py` | 环境变量固化，每次 digest 处理更多 fresh facts | ✅ 已上线 |

### 2.2 Kuzu 图存储

| # | Patch | 文件 | 说明 | 状态 |
|---|-------|------|------|------|
| P6 | **四种 REL TABLE** | `graph_store_kuzu.py` | 新增 CORRECTED / SHAPED_BY / BUILDS_ON 三种关系表 | ✅ 已上线 |
| P7 | **traverse_related** | `graph_store_kuzu.py` | 从节点出发沿语义边遍历，跳过着 RELATED_TO | ✅ 已上线 |
| P8 | **手动修正旧边** | Kuzu 数据 | 4 条 RELATED_TO → SHAPED_BY / BUILDS_ON | ✅ 已执行 |

### 2.3 检索增强

| # | Patch | 文件 | 说明 | 状态 |
|---|-------|------|------|------|
| P9 | **概念 Schema 加分** | `reader_legacy.py` | domain=concept 标签的结果在搜索时加分 | ✅ 已上线 |
| P10 | **reader_legacy L6 core 附加** | `reader_legacy.py` | 命中 L6 basic → 找关联 L6 core + traverse_related 展开 | ✅ 已上线 |

### 2.4 服务器稳定性

| # | Patch | 文件 | 说明 | 状态 |
|---|-------|------|------|------|
| P11 | **JSON 截断容忍** | `system2_agent.py` | LLM 返回截断 JSON 时自动补 `]` | ✅ 官方未修，我们patch了 |
| P12 | **Kuzu checkpoint 修复** | (hy-memory-system2-fix skill) | 防止 WAL 不落盘 | ✅ patch |
| P13 | **server_manager 覆写修复** | `server_manager.py` | upgrade=True 时恢复本地 patch | ✅ patch |

---

## 三、修改文件详表

### package/hy_memory/pipelines/system2_agent.py

**修改内容：** S2 Agent LLM prompt

```
- schema_type_two_formats  → 中英文两种 Schema 格式 + 四种边类型说明
- add_edge format 加 ✅/❌ 正反示例 + edge_type 必填标记
- output contract 加规则6/7：缺失 edge_type 丢弃 + 输出前自检
- _parse_operations_json 加 JSON 截断容忍
```

**行号参考（当前版本）：** `_build_single_call_system_prompt()` 函数内，CN 约 L864-898，EN 约 L900-932。

### package/hy_memory/pipelines/system2_tools.py

**修改内容：** add_edge 工具 executor

```
_tool_add_edge():
  之前: edge_type 只写死了 RELATED_TO
  现在: args.get("edge_type", "RELATED_TO") + 校验 4 种合法类型

add_evidence() / create_graph_node():
  自动检测 Type 2 → 追加 domain=concept 标签
```

### package/hy_memory/data/graph_store_kuzu.py

**修改内容：** Kuzu schema + 遍历

```
_init_schema():
  新增: CORRECTED / SHAPED_BY / BUILDS_ON 三个 REL TABLE

traverse_related():
  默认搜 CORRECTED / SHAPED_BY / BUILDS_ON
  跳过 RELATED_TO（太泛不追）
```

### package/hy_memory/pipelines/reader_legacy.py

**修改内容：** 检索时图遍历接入

```
_lite_read() 内:
  find_cores_from_basics()  → 从 L6 basic 找 L6 core
  traverse_related()        → 沿边展开关联节点
  get_nodes_by_tag("domain=concept") → tag 兜底
```

### plugin/server_manager.py

**修改内容：** 环境变量配置

```
build_server_env():
  MEMORY_S2_BATCH_SIZE=300
  MEMORY_AGENT_MAX_TOKENS=16000
  MEMORY_MODE 从 HY_MEMORY_MODE 读取
```

---

## 四、涉及概念

| 概念 | 说明 | 代码位置 |
|------|------|---------|
| **System 1 (S1)** | 快路径写入：对话→L1→L2事实抽取→reconcile→落库 | `pipelines/writer.py` |
| **System 2 (S2)** | 慢路径认知加工：digest → DBSCAN聚类 → LLM Schema归纳 | `pipelines/system2_*.py` |
| **L0-L6** | 记忆分层：原始/对话/事实/摘要/画像/知识/Schema | `models/memory.py` |
| **Concept Schema** | Type 2 Schema：用户的框架/知识结构（非行为模式） | `system2_tools.py` auto-tag |
| **evolve_chain** | supersedes/superseded_by 指针构成的演化链 | `_retrieval/evolution.py` |
| **traverse_related** | 沿 Kuzu 边展开关联节点 | `graph_store_kuzu.py` L1328 |
| **dual-path retrieval** | Chroma 向量搜 + Kuzu Schema 双路召回 | `reader_legacy.py` |

---

## 五、部署与升级

### 安装路径

```
插件: %LOCALAPPDATA%/hermes/plugins/hy-memory/
包:   %LOCALAPPDATA%/hermes/hermes-agent/venv/Lib/site-packages/hy_memory/
```

### 升级 hy-memory 版本时的操作

```bash
# 1. 下载新版本
pip download hy-memory==<new_version> -d /tmp

# 2. 解压对比
unzip /tmp/hy_memory-<new_version>.whl -d /tmp/hy_new
diff -ruN /tmp/hy_new/hy_memory/ package/hy_memory/

# 3. 手动合并 P1-P13 的改动到新版对应文件
# 重点关注: system2_agent.py, system2_tools.py, graph_store_*.py, reader_legacy.py

# 4. 部署
pip install hy-memory==<new_version>
# 重新 patch
```

---

## 六、与官方版本的 diff 路径

要查看当前 patch 的全量 diff（需本地保存官方 1.2.19 源码）：

```bash
# 首次：下载官方版本存为基线
pip download hy-memory==1.2.19 -d /tmp
unzip /tmp/hy_memory-1.2.19-py3-none-any.whl -d /tmp/hy_official

# 对比定制版
diff -ruN /tmp/hy_official/hy_memory/ package/hy_memory/ > /tmp/hy_patches.diff
```

也可以直接在 GitHub 上对比：点击 repo 中的文件，与原始 1.2.19 的 diff 自行对照。
