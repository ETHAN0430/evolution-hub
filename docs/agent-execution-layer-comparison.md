# Codex 与 Hermes Agent 执行层对比

> 审计日期：2026-07-08
> 范围：只比较本地 Agent 执行层，不比较模型权重、桌面 UI 和云端私有编排。

## 1. 结论

Hermes 的执行层并不简陋。它已经具备完整的多轮工具循环、并发与串行工具执行、上下文压缩、错误分类与重试、迭代预算、文件安全、停止前验证和子 Agent。Codex 的优势主要来自更收敛的架构、模型与工具协议的共同设计、系统级沙箱，以及单一编辑原语带来的稳定性。

简化判断：

| 维度 | Codex | Hermes |
|---|---|---|
| 主循环 | 事件驱动，状态较收敛 | 功能完整，但多 Provider 分支复杂 |
| 工具执行 | Tokio 异步调度，取消语义统一 | 支持并发/串行及中断，兼容面更广 |
| 编辑 | 单一 `apply_patch` 协议 | `write_file` + replace/V4A patch |
| 上下文 | 本地/远程 compaction 与 turn 状态深度整合 | 可插拔 ContextEngine，多类异常恢复 |
| 验证 | 依赖模型指令、测试和产品工作流 | 有显式 verify-on-stop 守卫，但默认关闭 |
| 权限 | OS 沙箱与审批策略是一等概念 | 路径护栏、命令规则与审批为主 |
| 多模型 | 主要围绕 OpenAI 模型优化 | 多 Provider、多协议适配明显更强 |
| 长期记忆 | 工作上下文型记忆 | 文件记忆和外部 MemoryProvider 更强 |

因此，用户感知的代码能力差距不能直接归因于 Hermes 缺少 Agent Loop。更可能的来源是：所用模型、编码模式是否启用、工具集是否收敛、停止前验证是否启用，以及模型是否熟悉对应编辑协议。

## 2. 审计基线

### 2.1 Hermes

本机源码：`/home/cyf/.hermes/hermes-agent/`

重点入口：

- `agent/conversation_loop.py`
- `agent/tool_executor.py`
- `agent/context_engine.py`
- `agent/coding_context.py`
- `agent/verification_stop.py`
- `agent/iteration_budget.py`
- `agent/turn_retry_state.py`
- `agent/file_safety.py`
- `tools/file_tools.py`
- `tools/approval.py`

### 2.2 Codex

上游仓库：<https://github.com/openai/codex>

本次审计 commit：`6849549b49446fc3db89ecc13d6226ab971bec79`

重点入口：

- `codex-rs/core/src/session/turn.rs`
- `codex-rs/core/src/stream_events_utils.rs`
- `codex-rs/core/src/tools/parallel.rs`
- `codex-rs/core/src/compact.rs`
- `codex-rs/core/src/agents_md.rs`
- `codex-rs/apply-patch/src/lib.rs`
- `codex-rs/core/src/sandboxing/mod.rs`

## 3. 执行链路对比

### 3.1 主循环与完成判定

Hermes 在 `agent/conversation_loop.py:612` 进入受 `max_iterations` 和共享 `IterationBudget` 约束的循环。循环处理中断、模型调用、工具结果、压缩、Provider 回退和最终回答。默认最大迭代值定义在 `agent/agent_init.py:177`，当前源码默认值为 90。

Codex 在 `codex-rs/core/src/session/turn.rs:142` 进入 `run_turn()`，并在 `:225` 的循环中持续采样。工具调用或待处理输入令 `needs_follow_up` 保持为真；只有 `needs_follow_up` 为假时才在 `:372` 完成该轮。

判断：两者都有真正的持续执行循环。Codex 的完成状态更集中；Hermes 的循环承担更多 Provider 兼容与恢复职责，分支明显更多。

### 3.2 工具执行与并发

Hermes 的并发和串行入口分别是：

- `agent/tool_executor.py:284`：`execute_tool_calls_concurrent()`
- `agent/tool_executor.py:857`：`execute_tool_calls_sequential()`

Codex 在 `codex-rs/core/src/tools/parallel.rs:75` 接收工具调用，并使用 Tokio task 执行可并发调用；典型 spawn 位于 `:132`、`:454`、`:698` 和 `:771`。

判断：能力层面接近。Codex 受益于 Rust async、统一取消 token 和统一事件协议；Hermes 更重视跨工具、跨 Provider 与多前端兼容。

### 3.3 文件编辑

Codex 以 `apply_patch` 作为核心编辑协议，实现在 `codex-rs/apply-patch/src/lib.rs:276`。它解析补丁、校验路径、生成 delta，并与沙箱和审批流程组合。

Hermes 提供 `write_file`、字符串替换和 V4A patch。`agent/coding_context.py:154-184` 会根据模型家族选择建议格式：GPT/Codex 使用 V4A，Claude 等模型优先字符串替换。

判断：Hermes 更灵活，Codex 更收敛。对于经过 `apply_patch` 工作流训练的模型，Codex 的单一路径更容易稳定；Hermes 的多格式能力需要正确的模型路由和提示才能兑现。

### 3.4 上下文压缩

Hermes 抽象了 `ContextEngine`，在 `agent/context_engine.py:83` 提供 `should_compress()`，在 `:110` 提供预飞判断。主循环还处理 413、上下文超限、输出预算不足和 Provider 回退。

Codex 在 `codex-rs/core/src/session/turn.rs:156` 运行采样前压缩，在 `:346-365` 对需要继续的轮次执行自动压缩，并能选择本地或远程 compaction。

判断：两者都成熟。Codex 的压缩与 Responses/turn 状态耦合更紧；Hermes 的实现更通用，但维护面更大。

### 3.5 编码姿态与仓库约束

Hermes 在 `agent/coding_context.py:39-49` 定义 `auto/focus/on/off`。默认 `auto` 只注入编码 brief，不收窄用户工具集；`focus` 才将工具集压缩到 coding 工具和 MCP。完整编码指令从 `:215` 开始，已经要求先读代码、批量检索、直接编辑、遵循仓库约定和执行验证。

Codex 在 `codex-rs/core/src/agents_md.rs:77` 开始发现并加载 `AGENTS.md`，执行器则天然围绕仓库、shell、patch、Git 和审批构建。

判断：Hermes 已有相当接近 Codex 的编码提示，但默认仍是通用 Agent 上的“编码姿态”；Codex 整个产品默认就是编码 Agent。

### 3.6 验证闭环

Hermes 在 `agent/conversation_loop.py:4693-4733` 检查停止前验证。如果代码已修改但没有新鲜验证证据，会注入内部追问并继续循环。但 `agent/verification_stop.py:135-165` 明确规定该功能默认关闭。

Codex 没有完全相同的单一 stop guard；它通过编码指令、工具回执、任务循环、Review 与测试工作流形成验证闭环。

判断：Hermes 的机制并不弱，但默认关闭会直接影响体感。把“有能力”与“默认会执行”区分开非常重要。

### 3.7 沙箱与安全

Codex 的文件系统、网络和命令权限由统一 sandbox/approval policy 贯穿执行层；`codex-rs/core/src/sandboxing/mod.rs` 是核心入口。

Hermes 在 `agent/file_safety.py`、`tools/approval.py` 和终端工具中实现路径拒绝、跨 Profile 警告、危险命令识别与审批。

判断：Hermes 护栏覆盖广，但以应用层规则为主；Codex 的 OS 级沙箱边界更清晰，也更容易推导某次调用到底拥有什么权限。

## 4. 为什么当前体感仍有差距

1. Hermes 默认模型与 Codex 的编码后训练不同；同一个执行器不能抹平模型对工具协议的熟悉度差异。
2. Hermes `coding_context=auto` 主要改变 Prompt，不会自动收窄大量通用工具；工具 schema 越宽，模型选择成本越高。
3. verify-on-stop 默认关闭，模型可以在修改后没有运行验证就结束。
4. Hermes 多 Provider 和多前端兼容使错误恢复更强，但也使主循环更复杂。
5. Codex 的模型、Prompt、`apply_patch`、shell、沙箱和事件协议由同一团队共同演进，整体匹配度更高。

## 5. 最值得利用的现成路径

Hermes 已经有 Codex App Server 运行模式。`agent/conversation_loop.py:598-610` 显示：当 `api_mode == "codex_app_server"` 时，Hermes 会跳过默认执行路径，将整轮任务交给 Codex App Server，文件、终端和 patch 都在 Codex 内执行。

推荐方向不是复制一套 Codex，而是：

```text
Hermes：身份、长期记忆、入口、任务路由
    -> Codex App Server：代码任务执行
    -> Hermes：保存结果、决策和后续计划
```

若继续使用 Hermes 原生执行层，优先验证以下配置组合：

1. 编码工作区使用 `coding_context=focus`。
2. 交互式编码表面启用 `verify_on_stop=auto` 或 `true`。
3. GPT/Codex 模型使用 V4A patch 路径。
4. 用固定仓库任务集做 A/B 测试，而不是只比较一次主观回答。

## 6. 边界

- Codex 模型权重、服务端系统提示和云端私有编排不在开源仓库中，本报告不对其实现作推断。
- Hermes 是本机当前安装源码，不代表所有发行版本。
- 本报告证明两套执行层具备哪些机制，不等价于证明它们在真实任务上的成功率；成功率仍需统一模型或统一任务集评测。
