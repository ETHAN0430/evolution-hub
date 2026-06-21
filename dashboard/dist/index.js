(function () {
  "use strict";
  var SDK = window.__HERMES_PLUGIN_SDK__;
  if (!SDK || !window.__HERMES_PLUGINS__) return;
  var React = SDK.React;
  var hooks = SDK.hooks;
  var h = React.createElement;

  var BASE = '/api/plugins/hermes-evolution-hub';
  var token = (typeof window.__HERMES_SESSION_TOKEN__ === 'string') ? window.__HERMES_SESSION_TOKEN__ : '';
  var authHeaders = token ? {'X-Hermes-Session-Token': token} : {};

  function authFetch(url) {
    return fetch(url, {headers: authHeaders});
  }

  // ── node data ────────────────────────────────────────────────────────────
  // Organic vertical-flow layout: Hermes pipeline runs down the center-left,
  // memory/HY branch to the right, storage forms the foundation.
  var NODES = {
    // ── External surfaces (fan in from left), ordered by target proximity ────
    'Hermes CLI': {file: 'hermes_cli/cli_agent_setup_mixin.py', loc: 'CLIAgentSetupMixin', x: 100, y: 150, group: 'external', desc: '命令行版本。在本地直接启动 AIAgent，在 cli_agent_setup_mixin.py 里显式设置 platform="cli"。'},
    'API Server': {file: 'gateway/platforms/api_server.py', loc: 'APIServerAdapter', x: 100, y: 220, group: 'external', desc: 'OpenAI-compatible API 服务。外部客户端通过 REST/SSE 调用，platform="api_server"。'},
    'Messaging Platforms': {file: 'gateway/platforms/telegram.py', loc: 'TelegramAdapter', x: 100, y: 420, group: 'external', desc: 'Telegram、Discord、Slack、WhatsApp 这类聊天软件接入，经过 Messaging Gateway 处理。'},
    'TUI': {file: 'tui_gateway/entry.py', loc: 'main', x: 100, y: 470, group: 'external', desc: '终端 UI 版本。`hermes --tui` 启动，通过 tui_gateway/entry.py 建立 stdio 传输，走 tui_gateway 后端。'},
    'Desktop': {file: 'apps/desktop/electron/main.cjs', x: 100, y: 520, group: 'external', desc: '电脑桌面上的 App 窗口。本地模式走 tui_gateway；远程模式会连到远程 TUI Gateway（即远程 dashboard 后端）。'},
    'Dashboard': {file: 'hermes_cli/web_server.py', loc: 'start_server', x: 100, y: 570, group: 'external', desc: '网页版后台。通过 tui_gateway 提供 JSON-RPC 会话服务，你现在看到的可视化页面由它承载。'},

    // ── Gateway ──────────────────────────────────────────────────────────────
    'Messaging Gateway': {file: 'gateway/run.py', loc: 'GatewayRunner', x: 320, y: 420, group: 'gateway', desc: '消息总入口（Hermes 里通常说的 "gateway" 就是指它）。负责聊天平台的适配与路由：处理 Telegram、Discord 等消息，知道回哪、发给谁。CLI 一对一单会话，直接连 AIAgent，不需要它。'},
    'TUI Gateway': {file: 'tui_gateway/server.py', loc: 'dispatch', x: 320, y: 520, group: 'gateway', desc: 'Terminal/UI 网关。给 Desktop、Dashboard、TUI 这些 UI 客户端提供统一的后端会话服务。'},

    // ── AI providers (foundation row, below turn engine) ─────────────────────
    'Provider APIs': {file: 'agent/anthropic_adapter.py', loc: 'build_anthropic_client', x: 560, y: 780, group: 'provider', desc: '连接各个外部 AI 大模型服务商，比如 Claude、OpenAI、Gemini 等。'},

    // ── Hermes Turn Engine / AIAgent runtime (single vertical spine) ─────────
    'Agent Init': {file: 'agent/agent_init.py', loc: 'init_agent', x: 510, y: 190, group: 'pipeline', desc: '初始化 AIAgent 的地方。只在新建会话时跑一次：\n1. 设置 platform（cli/tui/api_server/...）\n2. 构建并缓存 system prompt\n3. 组装可用工具列表（含 MCP）\n4. 初始化会话状态（session_id、source、model 等）'},
    '输入清洗': {file: 'agent/turn_context.py', loc: 'build_turn_context', x: 510, y: 260, group: 'pipeline', desc: '每轮 Turn 的入口。清洗用户输入（如去掉非法 surrogate 字符），并把用户消息追加到对话历史中。'},
    'MCP 刷新': {file: 'tools/mcp_tool.py', loc: 'refresh_agent_mcp_tools', x: 510, y: 330, group: 'pipeline', desc: '每轮开头刷新 MCP 工具列表：检查是否有新连上的 MCP server，把新工具加入当前可用工具快照。'},
    '消息构建': {file: 'agent/system_prompt.py', loc: 'build_system_prompt', x: 510, y: 400, group: 'pipeline', desc: '构建发给 LLM 的 system prompt，按三层拼成一段文本并缓存：\n1. stable：身份设定、工具使用指南、skills 提示、环境/平台提示等（每会话只构建一次）。\n2. context：AGENTS.md、.cursorrules 等上下文文件、调用方传入的 system_message。\n3. volatile：记忆快照、用户画像、外部 MemoryProvider 静态块、时间戳等每轮可能变化的部分。\n\n当前 Turn 的用户消息（历史对话、PreHook 注入、记忆预取结果）是在 system prompt 之外单独组装的。'},
    '记忆预取': {file: 'agent/memory_manager.py', loc: 'prefetch_all', x: 510, y: 470, group: 'pipeline', desc: 'MemoryManager.prefetch_all()：每次 LLM 调用前，把当前用户消息丢给所有已注册的 MemoryProvider，让它们各自 prefetch() 回相关记忆。autoRecall 不是独立功能，就是这条链路。\n\n工程语义上和 PreHook 一样（都是在 LLM 调用前注入上下文），只是走了专用通道，不走 plugins 的 Hook 系统。'},
    'PreHook': {file: 'hermes_cli/plugins.py', loc: 'invoke_hook', x: 510, y: 540, group: 'pipeline', desc: '通用插件 Hook 注入点（本节点是 pre_llm_call）。"pre" 型 Hook：\n- pre_llm_call\n- pre_tool_call\n- pre_api_request\n- pre_gateway_dispatch\n- pre_approval_request\n- on_session_start\n- subagent_start\n\npre_llm_call 返回的上下文会拼到当前用户消息里；记忆预取可以看成这类需求的专用实现，二者最终效果相同。'},
    'LLM API': {file: 'agent/conversation_loop.py', loc: 'run_conversation', x: 510, y: 680, group: 'pipeline', desc: '真正去调用 AI 模型的地方。把准备好的“信”发出去，等 AI 回信。'},
    '工具执行': {file: 'agent/tool_executor.py', loc: 'execute_tool_calls_concurrent', x: 660, y: 680, group: 'pipeline', desc: '让 AI 可以动手做事，比如查资料、读写文件、搜索网页等。'},
    '上下文压缩': {file: 'agent/context_compressor.py', loc: 'ContextCompressor', x: 510, y: 610, group: 'pipeline', desc: '进入 LLM 前或工具结果返回后，如果上下文超过阈值，先压缩再交给 LLM。'},
    'PostHook': {file: 'agent/turn_finalizer.py', loc: 'finalize_turn', x: 810, y: 680, group: 'pipeline', desc: '通用插件 Hook 注入点（本节点是 post_llm_call）。"post" / transform / error / lifecycle 型 Hook：\n- post_llm_call\n- post_tool_call\n- post_api_request\n- api_request_error\n- transform_terminal_output\n- transform_tool_result\n- transform_llm_output\n- on_session_end\n- on_session_finalize\n- on_session_reset\n- subagent_stop\n- post_approval_response\n\npost_llm_call 在工具循环结束后触发，插件可用来持久化对话数据或同步到外部记忆系统。'},
    '输出后处理': {file: 'agent/turn_finalizer.py', loc: 'finalize_turn', x: 810, y: 610, group: 'pipeline', desc: '工具循环结束后的输出处理：\n1. 插件 transform_llm_output Hook（可选，改写 LLM 输出文本）\n2. 文件修改校验 footer\n3. 异常结束解释\n4. 提取 reasoning\n5. 组装 result'},
    '会话持久化': {file: 'agent/turn_finalizer.py', loc: 'finalize_turn', x: 810, y: 540, group: 'pipeline', desc: '把这轮对话写回 SQLite / JSON log，清理 VM/browser 等临时资源，去掉空的脚手架消息。'},
    'Turn End': {file: 'agent/turn_finalizer.py', loc: 'finalize_turn', x: 810, y: 470, group: 'pipeline', desc: '最终收尾：统计 token/cost、返回 result 给调用方。'},
    // ── Turn support modules (branch right from spine / above the turn chain) ────
    '后台复盘': {file: 'agent/background_review.py', loc: 'spawn_background_review_thread', x: 810, y: 400, group: 'pipeline', desc: '在后台 fork 一个独立 agent 复盘本轮对话，发现值得记住的用户偏好或需要更新的 skill 时，直接写入记忆/技能存储，不会回流到当前主对话。'},
    'ContextCompressor': {file: 'agent/context_compressor.py', loc: 'ContextCompressor', x: 920, y: 470, group: 'memory', desc: '具体负责“压缩对话长度”的工人，会保留开头和最新内容，把中间部分做摘要。'},

    // ── Memory abstraction layer ────────────────────────────────────────────
    'MemoryManager': {file: 'agent/memory_manager.py', loc: 'MemoryManager', x: 920, y: 220, group: 'memory', desc: '记忆的调度中心。每次对话前查记忆，对话结束后把新东西存进记忆。'},
    'MemoryProvider': {file: 'agent/memory_provider.py', loc: 'MemoryProvider', x: 920, y: 320, group: 'memory', desc: '外部记忆服务的接口。所有外部记忆系统都按这个标准接口接入 Hermes：system_prompt_block()、prefetch()、sync_turn()、get_tool_schemas() 等。HY Memory 也是通过它接入的。'},
    'ContextEngine': {file: 'agent/context_engine.py', loc: 'ContextEngine', x: 920, y: 520, group: 'memory', desc: '控制对话上下文长度的引擎。决定什么时候该压缩、怎么压缩。'},
    '记忆文件': {file: 'tools/memory_tool.py', loc: 'MemoryStore', x: 920, y: 620, group: 'memory', desc: '本地保存的长期记忆。比如你的喜好、重要事实、个人资料等。'},

    // ── HY Memory evolution engine ──────────────────────────────────────────
    'HY Memory': {file: 'hy_memory/client.py', loc: 'HyMemoryClient', x: 1140, y: 220, group: 'hy', desc: '一个更聪明的记忆系统。作为 Hermes 的 MemoryProvider 接入，通过 prefetch() 在每次 LLM 调用前召回相关记忆；也能被模型通过记忆工具显式读写。\n注：HY 记忆内容会追加在本地 memory 块之后写入 system prompt，靠后的位置让模型更倾向采信它。'},
    'S1 Writer': {file: 'hy_memory/pipelines/writer.py', loc: 'MemoryWriter', x: 1140, y: 320, group: 'hy', desc: '第一层记忆写入。先把对话内容简单归档，准备后续加工。'},
    'MemAgent': {file: 'hy_memory/agent/mem_agent.py', loc: 'MemAgent', x: 1140, y: 420, group: 'hy', desc: '记忆提炼员。自动从对话里提取重要事实、身份信息和摘要。'},
    'Reconciler': {file: 'hy_memory/agent/reconciler.py', loc: 'MemoryReconciler', x: 1140, y: 520, group: 'hy', desc: '记忆冲突检查员。看看新信息和旧记忆有没有矛盾，决定是新增、替换还是更新。'},
    'System 2': {file: 'hy_memory/pipelines/system2_writer.py', loc: 'System2Writer', x: 1140, y: 620, group: 'hy', desc: '深度思考层。把零散事实组织成概念、意图和知识图谱。'},
    '记忆检索': {file: 'hy_memory/coding/curator/tools.py', loc: 'search_memory', x: 1280, y: 260, group: 'hy', desc: 'HY Memory 的语义搜索工具。根据 query 召回相关记忆（只返回 metadata，完整内容需要再 read）。'},
    '记忆写入': {file: 'hy_memory/coding/curator/tools.py', loc: 'create_memory', x: 1280, y: 460, group: 'hy', desc: 'HY Memory 的写入工具。支持 create / update / delete 记忆。'},

    // ── Persistent stores (foundation) ──────────────────────────────────────
    'Vector DB': {file: 'hy_memory/data/vector_store_chroma.py', loc: 'ChromaVectorStore', x: 720, y: 860, group: 'storage', desc: '向量数据库。用“意思相近”来搜索记忆，而不是只匹配关键词。'},
    'Graph DB': {file: 'hy_memory/data/graph_store_kuzu.py', loc: 'KuzuGraphStore', x: 960, y: 860, group: 'storage', desc: '图数据库。像知识图谱一样保存概念、主题和它们之间的关系。'},
    'cache.db': {file: 'hy_memory/data/cache_sqlite.py', loc: 'SqliteCache', x: 1200, y: 860, group: 'storage', desc: '本地小数据库。记录系统运行日志、任务队列和一些临时数据。'},
    'SQLite Session': {file: 'hermes_state.py', loc: 'SessionDB', x: 1440, y: 860, group: 'storage', desc: '本地会话数据库（SessionDB）。保存每次对话的历史记录、source、model 等元数据，方便下次继续聊。'}
  };

  // Real data flows derived from source analysis
  var CONNECTIONS = [
    // external surfaces -> appropriate gateway / direct agent init
    ['Hermes CLI', 'Agent Init'],
    ['TUI', 'TUI Gateway'],
    ['Desktop', 'TUI Gateway'],
    ['API Server', 'Agent Init'],
    ['Messaging Platforms', 'Messaging Gateway'],
    ['Dashboard', 'TUI Gateway'],

    // gateway/control plane -> agent init
    ['Messaging Gateway', 'Agent Init'],
    ['TUI Gateway', 'Agent Init'],
    ['Provider APIs', 'LLM API'],
    ['Agent Init', '输入清洗'],

    // Hermes turn pipeline (spine). The agent loop is the cycle between LLM and tools.
    ['输入清洗', 'MCP 刷新'], ['MCP 刷新', '消息构建'], ['消息构建', '记忆预取'], ['记忆预取', 'PreHook'], ['PreHook', '上下文压缩'],
    ['LLM API', '工具执行'],
    ['工具执行', '上下文压缩', 'dashed'],
    ['上下文压缩', 'LLM API'],
    ['LLM API', 'PostHook'],
    ['PostHook', '输出后处理'],
    ['输出后处理', '会话持久化'],
    ['会话持久化', 'Turn End'],
    
    ['Turn End', '后台复盘'],
    ['后台复盘', 'MemoryManager'],

    // turn engine <-> memory abstraction
    ['MemoryManager', 'MemoryProvider'],
    ['MemoryProvider', '记忆文件'],
    ['记忆文件', 'ContextEngine'], ['ContextEngine', 'ContextCompressor'],

    // Hermes <-> HY Memory (prefetch / sync_turn)
    ['MemoryProvider', 'HY Memory'],

    // HY Memory internal flow
    ['HY Memory', 'S1 Writer'],
    ['HY Memory', '记忆检索'],
    ['HY Memory', '记忆写入'],
    ['S1 Writer', 'Vector DB'],
    ['S1 Writer', 'MemAgent'], ['MemAgent', 'Reconciler'],
    ['Reconciler', 'Vector DB'],
    ['HY Memory', 'System 2'], ['System 2', 'Graph DB'],

    // logging & session persistence
    ['MemoryManager', 'cache.db'],
    ['HY Memory', 'cache.db'],
    ['输入清洗', 'SQLite Session'], ['Turn End', 'SQLite Session']
  ];

  // Warm, nature-harmonized palette for a dark-green dashboard background.
  // Fills are dark desaturated greens/greys; strokes provide the accent.
  var COLORS = {
    external: {fill: '#1c2621', stroke: '#d4c5a9'},
    gateway: {fill: '#242718', stroke: '#e6c875'},
    control: {fill: '#2a2518', stroke: '#c4b28a'},
    provider: {fill: '#1a2330', stroke: '#8ab4e6'},
    pipeline: {fill: '#33231e', stroke: '#f4a68e'},
    memory: {fill: '#142d21', stroke: '#8fc9a3'},
    hy: {fill: '#1f2330', stroke: '#a8b8e6'},
    storage: {fill: '#132728', stroke: '#7dd3d8'}
  };

  var SOURCE_BASE = (typeof window.__HERMES_SOURCE_BASE__ === 'string' && window.__HERMES_SOURCE_BASE__)
    ? window.__HERMES_SOURCE_BASE__
    : '/home/cyf/.hermes/hermes-agent/';
  if (!SOURCE_BASE.endsWith('/')) SOURCE_BASE += '/';

  function resolvePath(src) {
    var base = SOURCE_BASE;
    if (src.startsWith('/')) return src;
    if (src.startsWith('hy_memory/')) return base + 'venv/lib/python3.11/site-packages/' + src;
    if (src === 'run_agent.py' || src === 'hermes_state.py') return base + src;
    if (src.startsWith('hermes_cli/') || src.startsWith('gateway/') || src.startsWith('apps/') || src.startsWith('tui_gateway/')) return base + src;
    if (src.startsWith('tools/')) return base + src;
    if (src.startsWith('agent/')) return base + src;
    return base + 'agent/' + src;
  }

  // ── components ───────────────────────────────────────────────────────────
  function ArchitectureSvg(props) {
    var onNodeClick = props.onNodeClick;

    var CLUSTERS = [
      {name: 'User', x: 20, y: 90, w: 170, h: 640, color: '#d4c5a9'},
      {name: 'Gateway', x: 210, y: 90, w: 190, h: 640, color: '#e6c875'},
      {name: 'Agent', x: 420, y: 90, w: 460, h: 650, color: '#f4a68e'},
      {name: 'AI Providers', x: 500, y: 740, w: 160, h: 80, color: '#8ab4e6'},
      {name: 'Memory', x: 900, y: 90, w: 200, h: 640, color: '#8fc9a3'},
      {name: 'HY Memory', x: 1120, y: 90, w: 200, h: 640, color: '#a8b8e6'},
      {name: 'Storage', x: 620, y: 820, w: 920, h: 110, color: '#7dd3d8'}
    ];

    var clusters = CLUSTERS.map(function (c, i) {
      return h('g', {key: 'cluster-' + i},
        h('rect', {x: c.x, y: c.y, width: c.w, height: c.h, rx: 10,
          fill: c.color, opacity: 0.12, stroke: c.color, strokeOpacity: 0.35, strokeWidth: 1,
          strokeDasharray: '4,4'}),
        h('text', {x: c.x + 14, y: c.y + 22, fill: c.color, opacity: 0.85, fontSize: 11,
          fontFamily: "ui-monospace,'SF Mono',Menlo,monospace", fontWeight: 600, letterSpacing: '0.08em'},
          c.name)
      );
    });

    function makeOrthogonalLink(c, i) {
      var a = NODES[c[0]], b = NODES[c[1]];
      var dx = b.x - a.x, dy = b.y - a.y;
      var x1 = a.x, y1 = a.y, x2 = b.x, y2 = b.y;
      // exit/enter from the side facing the target
      if (Math.abs(dx) > Math.abs(dy)) {
        x1 += dx > 0 ? 65 : -65;
        x2 += dx > 0 ? -65 : 65;
      } else {
        y1 += dy > 0 ? 17 : -17;
        y2 += dy > 0 ? -17 : 17;
      }
      var d;
      var dashed = c[2] === 'dashed';
      // Gateway/API Server -> Agent Init: exit right, rise in the corridor, then right into Agent Init
      var isGatewayToAgent = (c[0] === 'Messaging Gateway' || c[0] === 'TUI Gateway' || c[0] === 'API Server') && c[1] === 'Agent Init';
      // Hermes CLI -> Agent Init: should also turn in the gateway corridor and enter from the left
      var isCLIToAgent = c[0] === 'Hermes CLI' && c[1] === 'Agent Init';
      // External surface -> Gateway: exit right, run in the corridor, then turn right
      var isExternalToGateway = a.group === 'external' && (c[1] === 'Messaging Gateway' || c[1] === 'TUI Gateway');
      if (isGatewayToAgent) {
        // right out of gateway, up to CLI/Agent-Init height, then right into Agent Init
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        var corridorX = 410;
        d = 'M' + x1 + ',' + y1 + ' L' + corridorX + ',' + y1 + ' L' + corridorX + ',' + y2 + ' L' + x2 + ',' + y2;
      } else if (isExternalToGateway) {
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        // same height as gateway: straight horizontal line, no corner
        if (y1 === y2) {
          d = 'M' + x1 + ',' + y1 + ' L' + x2 + ',' + y2;
        } else {
          var corridorX = 200;
          d = 'M' + x1 + ',' + y1 + ' L' + corridorX + ',' + y1 + ' L' + corridorX + ',' + y2 + ' L' + x2 + ',' + y2;
        }
      } else if (isCLIToAgent) {
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        var cliCorridorX = 410;
        d = 'M' + x1 + ',' + y1 + ' L' + cliCorridorX + ',' + y1 + ' L' + cliCorridorX + ',' + y2 + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'LLM API' && c[1] === 'PostHook') {
        // route above the tool-execution node so the line doesn't pass through it
        x1 = a.x;
        y1 = a.y - 17;
        x2 = b.x;
        y2 = b.y - 17;
        var corridorY = 650;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + corridorY + ' L' + x2 + ',' + corridorY + ' L' + x2 + ',' + y2;
      } else if (c[0] === '工具执行' && c[1] === '上下文压缩') {
        // Tool -> context compressor: straight up, then left (vertical-first L)
        x1 = a.x;
        y1 = a.y - 17;
        x2 = b.x + 65;
        y2 = b.y;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + y2 + ' L' + x2 + ',' + y2;
      } else if (x1 === x2 || y1 === y2) {
        d = 'M' + x1 + ',' + y1 + ' L' + x2 + ',' + y2;
      } else if (Math.abs(dx) > Math.abs(dy)) {
        // mainly horizontal: go horizontal first, then vertical
        d = 'M' + x1 + ',' + y1 + ' L' + x2 + ',' + y1 + ' L' + x2 + ',' + y2;
      } else {
        // mainly vertical: go vertical first, then horizontal
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + y2 + ' L' + x2 + ',' + y2;
      }
      return h('path', {
        key: 'link-' + i,
        d: d,
        fill: 'none',
        stroke: '#5a7169',
        strokeWidth: 1,
        opacity: 0.75,
        strokeDasharray: dashed ? '4,3' : undefined,
        markerEnd: 'url(#eh-arrow)'
      });
    }

    var links = CONNECTIONS.map(function (c, i) {
      return makeOrthogonalLink(c, i);
    });

    var nodes = Object.keys(NODES).map(function (name) {
      var n = NODES[name];
      var c = COLORS[n.group];
      return h('g', {
        key: name,
        transform: 'translate(' + n.x + ',' + n.y + ')',
        className: 'eh-node',
        tabIndex: 0,
        role: 'button',
        'aria-label': name + ' — 点击查看介绍',
        onClick: function () { onNodeClick(name, n.file, n.loc); },
        onKeyDown: function (e) {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onNodeClick(name, n.file, n.loc);
          }
        }
      },
        h('rect', {x: -65, y: -17, width: 130, height: 34, rx: 6, fill: c.fill, stroke: c.stroke, strokeWidth: 1.5}),
        h('text', {x: 0, y: 4, textAnchor: 'middle', fill: '#f8fafc', fontSize: 12, fontWeight: 500}, name)
      );
    });

    return h('svg', {className: 'eh-arch', viewBox: '0 0 1600 960', width: '1600', height: '960'},
      h('defs', null,
        h('pattern', {id: 'eh-grid', width: 40, height: 40, patternUnits: 'userSpaceOnUse'},
          h('path', {d: 'M 40 0 L 0 0 0 40', fill: 'none', stroke: '#163b33', strokeWidth: 0.5, opacity: 0.4})
        ),
        h('marker', {id: 'eh-arrow', markerWidth: 8, markerHeight: 8, refX: 7, refY: 3, orient: 'auto'},
          h('path', {d: 'M0,0 L8,3 L0,6 L2,3 z', fill: '#5a7169'})
        )
      ),
      h('rect', {width: '100%', height: '100%', fill: '#0a1f1a'}),
      h('rect', {width: '100%', height: '100%', fill: 'url(#eh-grid)'}),
      h('text', {x: 780, y: 25, textAnchor: 'middle', fill: '#8a9e94', fontSize: 13,
        fontFamily: "ui-monospace,'SF Mono',Menlo,monospace", letterSpacing: '0.16em'},
        'HERMES · HY MEMORY EVOLUTION ARCHITECTURE'),
      clusters,
      links,
      nodes
    );
  }

  function DetailPanel(props) {
    var detail = props.detail;
    var onClose = props.onClose;
    var onViewSource = props.onViewSource;
    if (!detail) return null;
    var isError = detail.showCode && !detail.loading && detail.code && (detail.code.startsWith('Error:') || detail.code.startsWith('Error：'));
    return h('div', {className: 'eh-detail', role: 'dialog', 'aria-label': detail.name + ' 详情'},
      h('div', {className: 'eh-detail-header'},
        h('div', null,
          h('div', {className: 'eh-detail-title'}, detail.name),
          h('div', {className: 'eh-detail-path'}, detail.path)
        ),
        h('button', {className: 'eh-detail-close', onClick: onClose, 'aria-label': '关闭详情'}, '×')
      ),
      h('div', {className: 'eh-detail-body'},
        !detail.showCode
          ? h('div', {className: 'eh-detail-intro'},
              h('div', {className: 'eh-detail-desc'}, (detail.desc || '暂无介绍').replace(/([。；])/g, '$1\n')),
              h('button', {className: 'eh-detail-action', onClick: onViewSource}, '查看源码')
            )
          : detail.loading
            ? h('div', {className: 'eh-detail-loading'}, '加载源码中...')
            : isError
              ? h('div', {className: 'eh-detail-error'},
                  h('div', {className: 'eh-detail-error-title'}, '无法读取源码'),
                  h('div', {className: 'eh-detail-error-hint'},
                    '尝试路径：' + detail.path,
                    h('br', null),
                    '如果源码不在默认位置，可在 Hermes Dashboard 启动前设置环境变量或全局变量覆盖基础路径。'
                  )
                )
              : h('div', null,
                  detail.line
                    ? h('div', {className: 'eh-detail-code-meta', style: {fontSize: 11, color: '#8a9e94', marginBottom: 6, fontFamily: "ui-monospace,'SF Mono',Menlo,monospace"}},
                        detail.path + ':' + detail.line + ' (lines ' + detail.start + '-' + detail.end + ')')
                    : null,
                  detail.locError
                    ? h('div', {className: 'eh-detail-code-warn', style: {fontSize: 11, color: '#f4a68e', marginBottom: 6}},
                        '未找到定位 "' + detail.loc + '"，显示完整文件')
                    : null,
                  h('pre', {className: 'eh-detail-code'}, detail.code || '(空文件)')
                )
      )
    );
  }

  function EvolutionHubPage() {
    var _a = hooks.useState(null), health = _a[0], setHealth = _a[1];
    var _b = hooks.useState(null), agentLoop = _b[0], setAgentLoop = _b[1];
    var _c = hooks.useState(null), detail = _c[0], setDetail = _c[1];
    var _d = hooks.useState(1), svgScale = _d[0], setSvgScale = _d[1];
    var _e = hooks.useState(0), posX = _e[0], setPosX = _e[1];
    var _f = hooks.useState(0), posY = _f[0], setPosY = _f[1];
    var svgRef = hooks.useRef(null);
    var canvasRef = hooks.useRef(null);
    var dragRef = hooks.useRef(false);
    var dragStartRef = hooks.useRef({x: 0, y: 0});
    var posRef = hooks.useRef({x: 0, y: 0});

    var SVG_W = 1600;
    var SVG_H = 960;

    function fitToScreen() {
      if (!canvasRef.current) return;
      var rect = canvasRef.current.getBoundingClientRect();
      var pad = 48;
      var availW = rect.width - pad;
      var availH = rect.height - pad;
      var scale = Math.min(availW / SVG_W, availH / SVG_H * 0.85, 1.2);
      scale = Math.max(0.35, scale);
      var x = (rect.width - SVG_W * scale) / 2;
      var y = 20;
      setSvgScale(scale);
      setPosX(x);
      setPosY(y);
      posRef.current = {x: x, y: y};
    }

    hooks.useEffect(function () {
      fitToScreen();
      Promise.all([
        authFetch(BASE + '/api/health').then(function (r) { return r.json(); }).catch(function () { return null; }),
        authFetch(BASE + '/api/agent-loop').then(function (r) { return r.json(); }).catch(function () { return null; })
      ]).then(function (results) {
        setHealth(results[0]);
        setAgentLoop(results[1]);
      });
      var onResize = function () { fitToScreen(); };
      window.addEventListener('resize', onResize);
      return function () { window.removeEventListener('resize', onResize); };
    }, []);

    function loadSource(name, src, path, loc) {
      setDetail(function (prev) {
        return prev && prev.name === name
          ? {name: prev.name, desc: prev.desc, src: prev.src, path: prev.path, loc: prev.loc, code: null, loading: true, showCode: true}
          : prev;
      });
      var url = BASE + '/api/source?path=' + encodeURIComponent(path);
      if (loc) url += '&loc=' + encodeURIComponent(loc);
      authFetch(url)
        .then(function (r) { return r.json(); })
        .then(function (d) {
          setDetail(function (prev) {
            return prev && prev.name === name
              ? {name: prev.name, desc: prev.desc, src: prev.src, path: prev.path, loc: prev.loc,
                 code: d.content || ('Error: ' + (d.detail || d.error || 'unknown')),
                 line: d.line || null, start: d.start || null, end: d.end || null,
                 locError: d.error || null, loading: false, showCode: true}
              : prev;
          });
        })
        .catch(function (e) {
          setDetail(function (prev) {
            return prev && prev.name === name
              ? {name: prev.name, desc: prev.desc, src: prev.src, path: prev.path, loc: prev.loc,
                 code: 'Error: ' + e.message, line: null, start: null, end: null,
                 locError: null, loading: false, showCode: true}
              : prev;
          });
        });
    }

    function onNodeClick(name, src, loc) {
      var n = NODES[name];
      var path = resolvePath(src);
      setDetail({name: name, desc: n.desc || '', src: src, path: path, loc: loc || n.loc || '', code: null, loading: false, showCode: false});
    }

    function onMouseDown(e) {
      if (e.button !== 0) return;
      dragRef.current = true;
      dragStartRef.current = {x: e.clientX - posRef.current.x, y: e.clientY - posRef.current.y};
      e.currentTarget.style.cursor = 'grabbing';
    }

    function onMouseMove(e) {
      if (!dragRef.current) return;
      var nx = e.clientX - dragStartRef.current.x;
      var ny = e.clientY - dragStartRef.current.y;
      posRef.current = {x: nx, y: ny};
      setPosX(nx);
      setPosY(ny);
    }

    function onMouseUp(e) {
      if (!dragRef.current) return;
      dragRef.current = false;
      e.currentTarget.style.cursor = 'grab';
    }

    function onMouseLeave(e) {
      if (!dragRef.current) return;
      dragRef.current = false;
      e.currentTarget.style.cursor = 'grab';
    }

    var srv = health && health.server || {};
    var isOk = srv.vdb === 'ok' || srv.llm === 'ok';
    var transformStyle = 'translate(' + posX + 'px,' + posY + 'px) scale(' + svgScale + ')';

    return h('div', {className: 'eh-page'},
      h('div', {className: 'eh-announcer', 'aria-live': 'polite', 'aria-atomic': 'true'}, health ? ('服务' + (isOk ? '正常' : '异常') + ' · VDB ' + (srv.vdb_points || '?')) : ''),
      // Header
      h('div', {className: 'eh-header'},
        h('div', {className: 'eh-kicker'}, 'Hermes Evolution Hub'),
        h('div', {className: 'eh-title'}, '进化中枢'),
        h('div', {className: 'eh-subtitle'},
          'Hermes 架构图、HY Memory 进化引擎与系统健康状态的可视化面板。点击模块查看源码路径与连接关系。')
      ),
      // Controls
      h('div', {className: 'eh-controls'},
        h('div', {className: 'eh-status'},
          h('span', {className: 'eh-pill'},
            h('span', {className: 'eh-dot', style: {background: isOk ? '#4ade80' : '#ef4444', boxShadow: isOk ? '0 0 8px #4ade80' : '0 0 8px #ef4444'}}),
            '服务: ', h('b', null, health ? (isOk ? '正常' : '异常') : '检测中')
          ),
          h('span', {className: 'eh-pill'}, 'VDB: ', h('b', null, srv.vdb_points || '?')),
          h('span', {className: 'eh-pill'}, 'API: ', h('b', null, agentLoop ? agentLoop.total_api : '?'))
        )
      ),
      // Canvas + detail
      h('div', {ref: canvasRef, className: 'eh-canvas', onMouseDown: onMouseDown, onMouseMove: onMouseMove, onMouseUp: onMouseUp, onMouseLeave: onMouseLeave},
        h('div', {ref: svgRef, className: 'eh-svg-wrap', style: {transform: transformStyle}},
          h(ArchitectureSvg, {onNodeClick: onNodeClick})
        ),
        h(DetailPanel, {
          detail: detail,
          onClose: function () { setDetail(null); },
          onViewSource: function () { if (detail) loadSource(detail.name, detail.src, detail.path, detail.loc); }
        })
      )
    );
  }

  window.__HERMES_PLUGINS__.register('hermes-evolution-hub', EvolutionHubPage);
})();
