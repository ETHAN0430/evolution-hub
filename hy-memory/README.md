# HY Memory — Custom Patched Build

基于 hy-memory [1.2.19](https://pypi.org/project/hy-memory/1.2.19/) (PyPI)，为 Hermes Agent 所做的定制修改。

## 目录结构

```
hy-memory/
├── package/hy_memory/     # Python 包源码 (site-packages)
├── plugin/                 # Hermes 插件 (plugins/hy-memory)
└── README.md
```

## 定制修改

| 修改 | 涉及文件 | 说明 |
|------|---------|------|
| **S2 Prompt 四种边** | `package/pipelines/system2_agent.py` | 表头/类型/工作流引导LLM产出RELATED_TO/CORRECTED/SHAPED_BY/BUILDS_ON |
| **add_edge 传 edge_type** | `package/pipelines/system2_tools.py` | 之前硬编码RELATED_TO，现在从args读edge_type并校验 |
| **domain=concept 打标** | `package/pipelines/system2_tools.py` | 自动检测Concept Schema并追加domain=concept标签 |
| **Kuzu 四种边** | `package/data/graph_store_kuzu.py` | 新增CORRECTED/SHAPED_BY/BUILDS_ON三种REL TABLE |
| **traverse_related** | `package/data/graph_store_base.py` | 沿边展开搜索 |
| **BATCH_SIZE=300** | `plugin/server_manager.py` | 每次digest处理更多fresh facts |
| **reader_legacy domain boost** | `package/pipelines/reader_legacy.py` | Concept Schema搜索结果加分 |

## 部署

插件路径: `%LOCALAPPDATA%/hermes/plugins/hy-memory/`

```powershell
# 部署插件文件
copy-item -Path plugin\* -Destination "$env:LOCALAPPDATA\hermes\plugins\hy-memory\" -Recurse -Force

# 部署包文件 (需重装或手动复制到venv)
# site-packages 路径:
# %LOCALAPPDATA%/hermes/hermes-agent/venv/Lib/site-packages/hy_memory/
```

## 更新上游

```bash
pip download hy-memory==<version> -d /tmp
unzip /tmp/hy_memory-<version>.whl -d /tmp/hy_src
diff -ruN /tmp/hy_src/hy_memory package/hy_memory
# 手动合并变更
```
