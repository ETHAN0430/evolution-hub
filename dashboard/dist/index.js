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
    'Hermes CLI': {file: 'hermes_cli/cli_agent_setup_mixin.py', x: 120, y: 150, group: 'external', desc: '命令行版本。在本地直接启动 AIAgent，在 cli_agent_setup_mixin.py 里显式设置 platform="cli"。'},
    'API Server': {file: 'gateway/platforms/api_server.py', x: 120, y: 220, group: 'external', desc: 'OpenAI-compatible API 服务。外部客户端通过 REST/SSE 调用，platform="api_server"。'},
    'Messaging Platforms': {file: 'gateway/platforms/telegram.py', x: 120, y: 420, group: 'external', desc: 'Telegram、Discord、Slack、WhatsApp 这类聊天软件接入，经过 Messaging Gateway 处理。'},
    'TUI': {file: 'tui_gateway/entry.py', x: 120, y: 470, group: 'external', desc: '终端 UI 版本。`hermes --tui` 启动，通过 tui_gateway/entry.py 建立 stdio 传输，走 tui_gateway 后端。'},
    'Desktop': {file: 'apps/desktop/electron/main.cjs', x: 120, y: 520, group: 'external', desc: '电脑桌面上的 App 窗口。本地模式走 tui_gateway；远程模式会连到远程 TUI Gateway（即远程 dashboard 后端）。'},
    'Dashboard': {file: 'hermes_cli/web_server.py', x: 120, y: 570, group: 'external', desc: '网页版后台。通过 tui_gateway 提供 JSON-RPC 会话服务，你现在看到的可视化页面由它承载。'},

    // ── Gateway ──────────────────────────────────────────────────────────────
    'Messaging Gateway': {file: 'gateway/run.py', x: 320, y: 420, group: 'gateway', desc: '消息总入口（Hermes 里通常说的 "gateway" 就是指它）。负责聊天平台的适配与路由：处理 Telegram、Discord 等消息，知道回哪、发给谁。CLI 一对一单会话，直接连 AIAgent，不需要它。'},
    'TUI Gateway': {file: 'tui_gateway/server.py', x: 320, y: 520, group: 'gateway', desc: 'Terminal/UI 网关。给 Desktop、Dashboard、TUI 这些 UI 客户端提供统一的后端会话服务。'},

    // ── AI providers (foundation row, below turn engine) ─────────────────────
    'Provider APIs': {file: 'agent/anthropic_adapter.py', x: 560, y: 780, group: 'provider', desc: '连接各个外部 AI 大模型服务商，比如 Claude、OpenAI、Gemini 等。'},

    // ── Hermes Turn Engine / AIAgent runtime (single vertical spine) ─────────
    'Agent Init': {file: 'agent/agent_init.py', x: 520, y: 150, group: 'pipeline', desc: '初始化 AIAgent 的地方。只在新建会话时跑一次：设置 platform、组装首次 system prompt。'},
    'Turn Start': {file: 'turn_context.py', x: 520, y: 270, group: 'pipeline', desc: '每轮 Turn 的入口。turn_context.py 的序幕从这里开始，接下来会串行做输入清洗、记忆预取、预压缩、插件上下文注入，最后交给消息构建。'},
    '输入清洗': {file: 'turn_context.py', x: 620, y: 270, group: 'pipeline', desc: '清洗用户输入（如去掉非法 surrogate 字符），并把用户消息追加到对话历史中。'},
    '记忆预取': {file: 'turn_context.py', x: 620, y: 330, group: 'pipeline', desc: '用当前用户消息向 MemoryManager 发起 prefetch，把相关记忆（MEMORY.md、USER.md、HY Memory 等）提前查出来，供后续 prompt 使用。'},
    '预压缩': {file: 'turn_context.py', x: 620, y: 390, group: 'pipeline', desc: '在真正调用 LLM 前，如果发现上下文太长，先做一次预压缩（preflight compression），防止请求超出模型窗口。'},
    '插件上下文': {file: 'turn_context.py', x: 620, y: 450, group: 'pipeline', desc: '调用 pre_llm_call 插件钩子，把插件返回的额外上下文注入到用户消息中。'},
    '系统提示': {file: 'system_prompt.py', x: 520, y: 210, group: 'pipeline', desc: '给 AI 的“身份卡”和基本规则。在 Agent Init 时构建并缓存，之后每一轮都会被复用。'},
    '消息构建': {file: 'prompt_builder.py', x: 520, y: 410, group: 'pipeline', desc: '把你的问题、之前的对话、以及查到的记忆，打包成一封发给 AI 的“信”。'},
    'LLM API': {file: 'conversation_loop.py', x: 520, y: 480, group: 'pipeline', desc: '真正去调用 AI 模型的地方。把准备好的“信”发出去，等 AI 回信。'},
    '工具执行': {file: 'tool_executor.py', x: 520, y: 550, group: 'pipeline', desc: '让 AI 可以动手做事，比如查资料、读写文件、搜索网页等。'},
    'Turn End': {file: 'turn_finalizer.py', x: 520, y: 620, group: 'pipeline', desc: '一轮对话结束后，保存结果、更新记忆、做一些后台整理工作。'},

    // ── Turn support modules (branch right from spine, aligned to their caller) ──
    '后台复盘': {file: 'background_review.py', x: 720, y: 300, group: 'pipeline', desc: '在后台 fork 一个独立 agent 复盘本轮对话，发现值得记住的用户偏好或需要更新的 skill 时，直接写入记忆/技能存储，不会回流到当前主对话。'},
    '上下文压缩': {file: 'context_compressor.py', x: 720, y: 480, group: 'pipeline', desc: '当对话太长时，自动删掉不重要的部分，让 AI 不会“记不过来”。'},
    'ContextCompressor': {file: 'context_compressor.py', x: 720, y: 550, group: 'memory', desc: '具体负责“压缩对话长度”的工人，会保留开头和最新内容，把中间部分做摘要。'},
    'memory tool': {file: 'tools/memory_tool.py', x: 720, y: 620, group: 'pipeline', desc: 'AI 用来读写记忆文件的工具。相当于一个笔记本管理器。'},

    // ── Memory abstraction layer ────────────────────────────────────────────
    'MemoryManager': {file: 'memory_manager.py', x: 920, y: 220, group: 'memory', desc: '记忆的调度中心。每次对话前查记忆，对话结束后把新东西存进记忆。'},
    'MemoryProvider': {file: 'memory_provider.py', x: 920, y: 320, group: 'memory', desc: '外部记忆服务的接口。让 Hermes 可以接不同的记忆系统，比如 HY Memory。'},
    'MemoryStore': {file: 'tools/memory_tool.py', x: 920, y: 420, group: 'memory', desc: '本地记忆的仓库。负责保管 MEMORY.md、USER.md 这些文件。'},
    'ContextEngine': {file: 'context_engine.py', x: 920, y: 520, group: 'memory', desc: '控制对话上下文长度的引擎。决定什么时候该压缩、怎么压缩。'},
    '记忆文件': {file: 'tools/memory_tool.py', x: 920, y: 620, group: 'memory', desc: '本地保存的长期记忆。比如你的喜好、重要事实、个人资料等。'},

    // ── HY Memory evolution engine ──────────────────────────────────────────
    'HY Memory': {file: 'hy_memory/client.py', x: 1140, y: 220, group: 'hy', desc: '一个更聪明的记忆系统。不仅能存东西，还会自动整理、提炼、进化记忆。'},
    'S1 Writer': {file: 'hy_memory/pipelines/writer.py', x: 1140, y: 320, group: 'hy', desc: '第一层记忆写入。先把对话内容简单归档，准备后续加工。'},
    'MemAgent': {file: 'hy_memory/agent/mem_agent.py', x: 1140, y: 420, group: 'hy', desc: '记忆提炼员。自动从对话里提取重要事实、身份信息和摘要。'},
    'Reconciler': {file: 'hy_memory/agent/reconciler.py', x: 1140, y: 520, group: 'hy', desc: '记忆冲突检查员。看看新信息和旧记忆有没有矛盾，决定是新增、替换还是更新。'},
    'System 2': {file: 'hy_memory/pipelines/system2_writer.py', x: 1140, y: 620, group: 'hy', desc: '深度思考层。把零散事实组织成概念、意图和知识图谱。'},

    // ── Persistent stores (foundation) ──────────────────────────────────────
    'Vector DB': {file: 'hy_memory/data/vector_store_chroma.py', x: 720, y: 860, group: 'storage', desc: '向量数据库。用“意思相近”来搜索记忆，而不是只匹配关键词。'},
    'Graph DB': {file: 'hy_memory/data/graph_store_kuzu.py', x: 960, y: 860, group: 'storage', desc: '图数据库。像知识图谱一样保存概念、主题和它们之间的关系。'},
    'cache.db': {file: 'hy_memory/data/cache_sqlite.py', x: 1200, y: 860, group: 'storage', desc: '本地小数据库。记录系统运行日志、任务队列和一些临时数据。'},
    'SQLite Session': {file: 'hermes_state.py', x: 1440, y: 860, group: 'storage', desc: '本地会话数据库（SessionDB）。保存每次对话的历史记录、source、model 等元数据，方便下次继续聊。'}
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
    ['Agent Init', 'Turn Start'],

    // Hermes turn pipeline (spine). The agent loop is the cycle between LLM and tools.
    ['Agent Init', '系统提示'], ['系统提示', '消息构建'], ['Turn Start', '输入清洗'], ['输入清洗', '记忆预取'], ['记忆预取', '预压缩'], ['预压缩', '插件上下文'], ['插件上下文', '消息构建'], ['消息构建', 'LLM API'],
    ['LLM API', '工具执行'],
    ['工具执行', 'memory tool'],
    ['工具执行', 'LLM API'],
    ['LLM API', 'Turn End'],
    ['消息构建', '上下文压缩', 'dashed'], ['上下文压缩', 'LLM API', 'dashed'], ['上下文压缩', 'ContextCompressor'],
    ['Turn End', '后台复盘'],
    ['后台复盘', 'MemoryManager'],

    // turn engine <-> memory abstraction
    ['memory tool', 'MemoryStore'],
    ['MemoryManager', 'MemoryProvider'],
    ['MemoryProvider', 'MemoryStore'],
    ['MemoryStore', 'ContextEngine'], ['ContextEngine', 'ContextCompressor'],
    ['记忆文件', 'MemoryStore'],

    // Hermes <-> HY Memory (prefetch / sync_turn)
    ['MemoryProvider', 'HY Memory'],

    // HY Memory internal flow
    ['HY Memory', 'S1 Writer'],
    ['S1 Writer', 'Vector DB'],
    ['S1 Writer', 'MemAgent'], ['MemAgent', 'Reconciler'],
    ['Reconciler', 'Vector DB'],
    ['HY Memory', 'System 2'], ['System 2', 'Graph DB'],

    // logging & session persistence
    ['MemoryManager', 'cache.db'],
    ['HY Memory', 'cache.db'],
    ['Turn Start', 'SQLite Session'], ['Turn End', 'SQLite Session']
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
      {name: 'Agent', x: 420, y: 90, w: 410, h: 640, color: '#f4a68e'},
      {name: 'AI Providers', x: 500, y: 740, w: 160, h: 80, color: '#8ab4e6'},
      {name: 'Memory', x: 860, y: 210, w: 200, h: 440, color: '#8fc9a3'},
      {name: 'HY Memory', x: 1080, y: 210, w: 200, h: 440, color: '#a8b8e6'},
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
        onClick: function () { onNodeClick(name, n.file); },
        onKeyDown: function (e) {
          if (e.key === 'Enter' || e.key === ' ') {
            e.preventDefault();
            onNodeClick(name, n.file);
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
      // Visual annotation: the agent loop is the cycle between LLM and tools
      h('path', {d: 'M 585,480 L 650,480 L 650,550 L 585,550', fill: 'none', stroke: '#f4a68e', strokeWidth: 2, strokeDasharray: '4,3', markerEnd: 'url(#eh-arrow)'}),
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
              : h('pre', {className: 'eh-detail-code'}, detail.code || '(空文件)')
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

    function loadSource(name, src, path) {
      setDetail(function (prev) {
        return prev && prev.name === name
          ? {name: prev.name, desc: prev.desc, src: prev.src, path: prev.path, code: null, loading: true, showCode: true}
          : prev;
      });
      authFetch(BASE + '/api/source?path=' + encodeURIComponent(path))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          setDetail(function (prev) {
            return prev && prev.name === name
              ? {name: prev.name, desc: prev.desc, src: prev.src, path: prev.path, code: d.content || ('Error: ' + (d.detail || d.error || 'unknown')), loading: false, showCode: true}
              : prev;
          });
        })
        .catch(function (e) {
          setDetail(function (prev) {
            return prev && prev.name === name
              ? {name: prev.name, desc: prev.desc, src: prev.src, path: prev.path, code: 'Error: ' + e.message, loading: false, showCode: true}
              : prev;
          });
        });
    }

    function onNodeClick(name, src) {
      var n = NODES[name];
      var path = resolvePath(src);
      setDetail({name: name, desc: n.desc || '', src: src, path: path, code: null, loading: false, showCode: false});
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
          onViewSource: function () { if (detail) loadSource(detail.name, detail.src, detail.path); }
        })
      )
    );
  }

  window.__HERMES_PLUGINS__.register('hermes-evolution-hub', EvolutionHubPage);
})();
