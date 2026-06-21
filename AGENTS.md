# AGENTS.md — hermes-evolution-hub

> 本文档面向 AI 编码助手。阅读本文档前，假设你对本项目一无所知。以下内容全部基于仓库中实际存在的文件，不做推测。

---

## 项目概述

`hermes-evolution-hub`（中文名：进化中枢）是一个 **Hermes Dashboard 插件**，用于可视化 Hermes 系统架构图与 HY Memory 进化引擎的运行状态。

插件入口定义在 `dashboard/manifest.json` 中：

- `name`: `hermes-evolution-hub`
- `label`: `进化中枢`
- `entry`: `dist/index.js`（前端页面逻辑）
- `css`: `dist/style.css`（前端样式）
- `api`: `plugin_api.py`（FastAPI 后端路由）
- 挂载标签页路径：`/evolution-hub`

项目没有独立的 HTTP 服务，后端以 `APIRouter` 的形式被 Hermes Dashboard（端口 9119）挂载到 `/api/plugins/hermes-evolution-hub/`。

---

## 目录结构

```
evolution_hub/
├── dashboard/
│   ├── manifest.json          # 插件元数据与入口配置
│   ├── plugin_api.py          # FastAPI 后端 API
│   ├── dist/
│   │   ├── index.js           # 前端页面（React + Hermes Plugin SDK）
│   │   ├── index.js.bak       # index.js 的旧版本备份
│   │   └── style.css          # 前端样式（暗色主题 SVG 反色处理）
│   └── __pycache__/           # Python 编译缓存（Python 3.11 / 3.12）
└── AGENTS.md                  # 本文件
```

> 注意：仓库中不存在 `pyproject.toml`、`package.json`、`Cargo.toml`、`setup.py`、`Makefile`、`requirements.txt`、测试目录或 CI 配置文件。这是一个仅由单个清单文件、一个 Python 路由文件和一个前端 dist 目录组成的轻量插件。

---

## 技术栈

- **后端**：Python 3，FastAPI（`APIRouter`）
- **前端**：原生 JavaScript，使用 Hermes Dashboard 提供的插件 SDK（`window.__HERMES_PLUGIN_SDK__` 暴露的 `React` 与 `hooks`）
- **数据存储**：读取本地 SQLite 数据库 `~/.hy_memory/data/cache.db`
- **外部依赖**：
  - HY Memory 服务：`http://localhost:19527/api/v1/status`
  - Hermes 运行日志：`~/.hermes/logs/agent.log`
  - Hermes 配置：`~/.hermes/config.yaml`
  - Hermes 源码目录：`/home/cyf/.hermes/hermes-agent/`（前端硬编码路径）

---

## 运行时架构

1. Hermes Dashboard 加载 `dashboard/manifest.json`。
2. Dashboard 将 `plugin_api.py` 中的 `router` 挂载到 `/api/plugins/hermes-evolution-hub/`。
3. 前端 `dist/index.js` 注册一个名为 `hermes-evolution-hub` 的页面组件。
4. 页面加载时，前端并行请求：
   - `GET /api/plugins/hermes-evolution-hub/architecture.svg`（架构图 SVG）
   - `GET /api/plugins/hermes-evolution-hub/api/health`（服务健康状态）
   - `GET /api/plugins/hermes-evolution-hub/api/agent-loop`（最近的 API / 工具调用统计）
   - `GET /api/plugins/hermes-evolution-hub/api/memory-feed`（L0~L7 记忆操作动态）
   - `GET /api/plugins/hermes-evolution-hub/api/prefetch-feed`（最近记忆预取查询与命中）
   - `GET /api/plugins/hermes-evolution-hub/api/self-improvement`（本地记忆/技能/工具调用自改进信号）
5. SVG 渲染后，前端会为图中的节点绑定点击事件；点击节点时通过 `api/source?path=<absolute_path>` 读取对应源码文件。
6. 页面下方渲染三个信息面板：L0~L7 记忆动态、记忆预取情况、Self-Improvement 嗅探。

---

## API 端点

| 端点 | 说明 |
|------|------|
| `GET /api/health` | 检查 HY Memory 服务状态、最近 prefetch 统计、近 1 小时 pipeline 活动 |
| `GET /api/agent-loop` | 从 `agent.log` 解析最近 500 行，统计 API 调用与工具调用（带 5 秒 TTL 缓存） |
| `GET /api/stats` | 读取 config.yaml 中的模型配置、线程数、pipeline 总量与分布、memory 操作分布 |
| `GET /api/evolution` | System2 / EXTRACT / DIGEST_SUMMARY 等进化步骤的最近记录（带 15 秒 TTL 缓存） |
| `GET /api/timeline` | 最近 memory 写入、S2 队列、系统指标、近 5 分钟实时 pipeline |
| `GET /api/memory-feed` | 最近 `memory_operations` 记录，按 L0~L7 layer 分组（带 5 秒 TTL 缓存） |
| `GET /api/prefetch-feed` | 最近 `pipeline_logs` 中 `READ_%` 预取查询与命中统计（带 5 秒 TTL 缓存） |
| `GET /api/self-improvement` | 嗅探 `MEMORY.md` / `USER.md` / `~/.hermes/skills` / `agent.log` 的自改进信号（带 5 秒 TTL 缓存） |
| `GET /api/source?path=...` | 读取给定绝对路径的源码文件内容 |
| `GET /evolution_hub_style` | 返回 `evolution_hub/evolution_hub_style.html` 模板页面 |
| `GET /architecture.svg` | 返回 `evolution_hub/architecture.svg` 架构图 |

> 注意：`plugin_api.py` 中通过 `_HERE = Path(__file__).resolve().parent.parent` 定位插件根目录，`_EVOLUTION_DIR = _HERE / "evolution_hub"`，资源文件为 `evolution_hub/evolution_hub_style.html` 与 `evolution_hub/evolution_hub/architecture.svg`。

---

## 构建与测试

- **没有正式的构建流程**。`dist/index.js` 与 `dist/style.css` 是手写或离线打包后的产物，仓库中没有源码目录、构建脚本或打包配置。
- **没有测试套件**。修改后请手动在 Hermes Dashboard 中加载插件进行验证。
- 验证步骤建议：
  1. 将 `dashboard/` 目录整体复制到 Hermes 插件目录。
  2. 确保 `evolution_hub/evolution_hub_style.html` 与 `evolution_hub/architecture.svg` 存在。
  3. 重启 Hermes Dashboard，访问 `/evolution-hub` 标签页。
  4. 检查浏览器控制台是否有 SDK 或 `authFetch` 报错。
  5. 检查 `/api/plugins/hermes-evolution-hub/api/health` 是否能正确返回 JSON。

---

## 代码风格与约定

- Python 代码采用较宽松的函数式风格，大量使用 `_query_db`、`subprocess.run`、`urllib.request` 等直接调用。
- 缓存使用模块级字典 `_cache` 与装饰器 `@cached(ttl=...)` 实现，未使用 Redis 等外部缓存。
- 前端代码为兼容 Hermes SDK 的 ES5-ish 风格：使用 `var`、React 的 `createElement` 而非 JSX、匿名函数替代箭头函数。
- 字符串与注释以中文为主，UI 文案为中文。
- 多处存在硬编码路径与硬编码会话 ID（如 `session = "20260619_235729_74dfff"`），修改时需注意。

---

## 安全注意事项

- **`/api/source` 端点接收 `path` 查询参数并直接读取本地任意文件**。当前没有路径白名单或沙箱校验，部署时应确保该接口仅在受信任的本地 Dashboard 环境中可访问。
- 后端通过 `subprocess.run` 执行 `grep`、`tail`、`ps` 等 shell 命令，并拼接日志路径等外部输入。虽然当前路径来自模块常量，但未来扩展时应避免将用户输入传入 shell。
- 前端通过 `dangerouslySetInnerHTML` 注入 SVG 内容。SVG 来自本地文件系统，但若该文件可被外部篡改，则存在 XSS 风险。
- 插件读取 `~/.hermes/config.yaml`、`~/.hermes/logs/agent.log`、`~/.hy_memory/data/cache.db` 等敏感本地文件。运行环境必须具备这些文件的读取权限，同时应限制插件文件本身不被未授权修改。

---

## 给后续开发者的提示

- 如果你想修改前端，需要直接编辑 `dashboard/dist/index.js` 与 `dashboard/dist/style.css`；仓库中没有 TypeScript / JSX 源码或构建脚本。
- 如果你想新增数据源或端点，直接在 `dashboard/plugin_api.py` 的 `router` 上添加即可，并注意补充 TTL 缓存以避免频繁读取 SQLite 或日志。
- 如果需要让源码节点点击功能在 Windows 或其他非 `/home/cyf/.hermes/hermes-agent/` 路径下工作，必须同步修改 `index.js` 中的 `resolvePath` 与 `NODES` 映射。
