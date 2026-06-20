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
    // ── External surfaces (fan in from left) ────────────────────────────────
    '用户': {file: 'run_agent.py', x: 120, y: 180, group: 'external'},
    'Hermes CLI': {file: 'hermes_cli/main.py', x: 120, y: 300, group: 'external'},
    'Desktop': {file: 'apps/desktop/electron/main.cjs', x: 120, y: 420, group: 'external'},
    'Messaging Platforms': {file: 'gateway/platforms/telegram.py', x: 120, y: 540, group: 'external'},
    'Dashboard': {file: 'hermes_cli/web_server.py', x: 120, y: 660, group: 'external'},

    // ── Gateway & control plane ─────────────────────────────────────────────
    'Gateway': {file: 'hermes_cli/gateway.py', x: 320, y: 420, group: 'gateway'},
    'Config & State': {file: 'hermes_cli/config.py', x: 320, y: 220, group: 'gateway'},
    'Provider APIs': {file: 'agent/anthropic_adapter.py', x: 320, y: 620, group: 'gateway'},

    // ── Hermes Turn Engine (main spine) ─────────────────────────────────────
    'Turn 前奏': {file: 'turn_context.py', x: 520, y: 120, group: 'pipeline'},
    '系统提示': {file: 'system_prompt.py', x: 520, y: 220, group: 'pipeline'},
    '消息构建': {file: 'prompt_builder.py', x: 520, y: 320, group: 'pipeline'},
    '主循环': {file: 'conversation_loop.py', x: 520, y: 420, group: 'pipeline'},
    'LLM API': {file: 'conversation_loop.py', x: 520, y: 520, group: 'pipeline'},
    '工具执行': {file: 'tool_executor.py', x: 520, y: 620, group: 'pipeline'},
    'Turn 收尾': {file: 'turn_finalizer.py', x: 520, y: 720, group: 'pipeline'},

    // ── Turn support modules (branch right from spine) ──────────────────────
    '背景 review': {file: 'background_review.py', x: 720, y: 220, group: 'pipeline'},
    '上下文压缩': {file: 'context_compressor.py', x: 720, y: 320, group: 'pipeline'},
    'ContextCompressor': {file: 'context_compressor.py', x: 720, y: 420, group: 'memory'},
    'memory tool': {file: 'tools/memory_tool.py', x: 720, y: 620, group: 'pipeline'},

    // ── Memory abstraction layer ────────────────────────────────────────────
    'MemoryManager': {file: 'memory_manager.py', x: 920, y: 320, group: 'memory'},
    'MemoryProvider': {file: 'memory_provider.py', x: 920, y: 420, group: 'memory'},
    'MemoryStore': {file: 'tools/memory_tool.py', x: 920, y: 520, group: 'memory'},
    'ContextEngine': {file: 'context_engine.py', x: 920, y: 620, group: 'memory'},
    '记忆文件': {file: 'tools/memory_tool.py', x: 920, y: 720, group: 'memory'},

    // ── HY Memory evolution engine ──────────────────────────────────────────
    'HY Memory': {file: 'hy_memory/client.py', x: 1140, y: 320, group: 'hy'},
    'S1 Writer': {file: 'hy_memory/pipelines/writer.py', x: 1140, y: 420, group: 'hy'},
    'MemAgent': {file: 'hy_memory/agent/mem_agent.py', x: 1140, y: 520, group: 'hy'},
    'Reconciler': {file: 'hy_memory/agent/reconciler.py', x: 1140, y: 620, group: 'hy'},
    'System 2': {file: 'hy_memory/pipelines/system2_writer.py', x: 1140, y: 720, group: 'hy'},

    // ── Persistent stores (foundation) ──────────────────────────────────────
    'Vector DB': {file: 'hy_memory/data/vector_store_chroma.py', x: 720, y: 840, group: 'storage'},
    'Graph DB': {file: 'hy_memory/data/graph_store_kuzu.py', x: 960, y: 840, group: 'storage'},
    'cache.db': {file: 'hy_memory/data/cache_sqlite.py', x: 1200, y: 840, group: 'storage'},
    'SQLite Session': {file: 'run_agent.py', x: 1440, y: 840, group: 'storage'}
  };

  // Real data flows derived from source analysis
  var CONNECTIONS = [
    // external surfaces -> gateway
    ['用户', 'Gateway'], ['Hermes CLI', 'Gateway'], ['Desktop', 'Gateway'],
    ['Messaging Platforms', 'Gateway'], ['Dashboard', 'Gateway'],

    // gateway/config -> turn engine
    ['Gateway', 'Turn 前奏'],
    ['Config & State', '系统提示'],
    ['Provider APIs', 'LLM API'],

    // Hermes turn pipeline (spine)
    ['Turn 前奏', '系统提示'], ['系统提示', '消息构建'], ['消息构建', '主循环'],
    ['主循环', 'LLM API'], ['LLM API', '主循环'],
    ['主循环', '工具执行'], ['工具执行', 'memory tool'],
    ['主循环', '上下文压缩'], ['上下文压缩', 'ContextCompressor'],
    ['背景 review', '主循环'], ['Turn 收尾', '主循环'],

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
    ['Turn 前奏', 'SQLite Session'], ['Turn 收尾', 'SQLite Session']
  ];

  // Warm, nature-harmonized palette for a dark-green dashboard background.
  // Fills are dark desaturated greens/greys; strokes provide the accent.
  var COLORS = {
    external: {fill: '#1c2621', stroke: '#d4c5a9'},
    gateway: {fill: '#242718', stroke: '#e6c875'},
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
    if (src === 'run_agent.py') return base + src;
    if (src.startsWith('hermes_cli/') || src.startsWith('gateway/') || src.startsWith('apps/')) return base + src;
    if (src.startsWith('tools/')) return base + src;
    if (src.startsWith('agent/')) return base + src;
    return base + 'agent/' + src;
  }

  // ── components ───────────────────────────────────────────────────────────
  function ArchitectureSvg(props) {
    var onNodeClick = props.onNodeClick;

    var CLUSTERS = [
      {name: 'External', x: 40, y: 130, w: 200, h: 590, color: '#94a3b8'},
      {name: 'Gateway', x: 240, y: 160, w: 200, h: 520, color: '#60a5fa'},
      {name: 'Turn Engine', x: 440, y: 60, w: 400, h: 710, color: '#fb923c'},
      {name: 'Memory', x: 860, y: 270, w: 200, h: 500, color: '#34d399'},
      {name: 'HY Memory', x: 1080, y: 270, w: 200, h: 500, color: '#c084fc'},
      {name: 'Storage', x: 620, y: 790, w: 920, h: 100, color: '#38bdf8'}
    ];

    var clusters = CLUSTERS.map(function (c, i) {
      return h('g', {key: 'cluster-' + i},
        h('rect', {x: c.x, y: c.y, width: c.w, height: c.h, rx: 10,
          fill: c.color, opacity: 0.05, stroke: c.color, strokeOpacity: 0.2, strokeWidth: 1,
          strokeDasharray: '4,4'}),
        h('text', {x: c.x + 14, y: c.y + 22, fill: c.color, opacity: 0.85, fontSize: 11,
          fontFamily: "ui-monospace,'SF Mono',Menlo,monospace", fontWeight: 600, letterSpacing: '0.08em'},
          c.name)
      );
    });

    function makeOrthogonalLink(a, b, i) {
      var dx = b.x - a.x, dy = b.y - a.y;
      var x1 = a.x, y1 = a.y, x2 = b.x, y2 = b.y;
      // edge offsets: horizontal if mainly horizontal, else vertical
      if (Math.abs(dx) > Math.abs(dy)) {
        x1 += dx > 0 ? 65 : -65;
        x2 += dx > 0 ? -65 : 65;
      } else {
        y1 += dy > 0 ? 17 : -17;
        y2 += dy > 0 ? -17 : 17;
      }
      // route through a midpoint: prefer horizontal-first L shape
      var mx = x2, my = y1;
      // for purely vertical/horizontal, use direct segment
      var d;
      if (x1 === x2 || y1 === y2) {
        d = 'M' + x1 + ',' + y1 + ' L' + x2 + ',' + y2;
      } else {
        d = 'M' + x1 + ',' + y1 + ' L' + mx + ',' + my + ' L' + x2 + ',' + y2;
      }
      return h('path', {
        key: 'link-' + i,
        d: d,
        fill: 'none',
        stroke: '#5a7169',
        strokeWidth: 1,
        opacity: 0.7,
        markerEnd: 'url(#eh-arrow)'
      });
    }

    var links = CONNECTIONS.map(function (c, i) {
      return makeOrthogonalLink(NODES[c[0]], NODES[c[1]], i);
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
        'aria-label': name + ' — 点击查看源码',
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

    var legendItems = [
      {label: 'External', color: COLORS.external.stroke},
      {label: 'Gateway', color: COLORS.gateway.stroke},
      {label: 'Turn Engine', color: COLORS.pipeline.stroke},
      {label: 'Memory', color: COLORS.memory.stroke},
      {label: 'HY Memory', color: COLORS.hy.stroke},
      {label: 'Storage', color: COLORS.storage.stroke}
    ];
    var legend = h('g', {transform: 'translate(1330, 880)'},
      h('rect', {x: -10, y: -14, width: 260, height: 44, rx: 6, fill: '#0f2922', stroke: '#2a4a40', strokeWidth: 1}),
      legendItems.map(function (item, i) {
        return h('g', {key: 'legend-' + i, transform: 'translate(' + (i % 3 * 85) + ',' + (Math.floor(i / 3) * 18) + ')'},
          h('rect', {x: 0, y: -4, width: 8, height: 8, rx: 2, fill: item.color}),
          h('text', {x: 12, y: 3, fill: '#a3b5ab', fontSize: 9, fontFamily: "ui-monospace,'SF Mono',Menlo,monospace"}, item.label)
        );
      })
    );

    return h('svg', {className: 'eh-arch', viewBox: '30 20 1510 870', width: '1510', height: '870'},
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
      h('text', {x: 780, y: 40, textAnchor: 'middle', fill: '#8a9e94', fontSize: 13,
        fontFamily: "ui-monospace,'SF Mono',Menlo,monospace", letterSpacing: '0.16em'},
        'HERMES · HY MEMORY EVOLUTION ARCHITECTURE'),
      clusters,
      links,
      nodes,
      legend
    );
  }

  function DetailPanel(props) {
    var detail = props.detail;
    var onClose = props.onClose;
    if (!detail) return null;
    var isError = !detail.loading && detail.code && (detail.code.startsWith('Error:') || detail.code.startsWith('Error：'));
    return h('div', {className: 'eh-detail', role: 'dialog', 'aria-label': detail.name + ' 源码'},
      h('div', {className: 'eh-detail-header'},
        h('div', null,
          h('div', {className: 'eh-detail-title'}, detail.name),
          h('div', {className: 'eh-detail-path'}, detail.path)
        ),
        h('button', {className: 'eh-detail-close', onClick: onClose, 'aria-label': '关闭详情'}, '×')
      ),
      h('div', {className: 'eh-detail-body'},
        detail.loading
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

    var SVG_W = 1510;
    var SVG_H = 870;

    function fitToScreen() {
      if (!canvasRef.current) return;
      var rect = canvasRef.current.getBoundingClientRect();
      var pad = 48;
      var availW = rect.width - pad;
      var availH = rect.height - pad;
      var scale = Math.min(availW / SVG_W, availH / SVG_H, 1.2);
      scale = Math.max(0.35, scale);
      var x = (rect.width - SVG_W * scale) / 2;
      var y = (rect.height - SVG_H * scale) / 2;
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

    function onNodeClick(name, src) {
      var path = resolvePath(src);
      setDetail({name: name, src: src, path: path, code: null, loading: true});
      authFetch(BASE + '/api/source?path=' + encodeURIComponent(path))
        .then(function (r) { return r.json(); })
        .then(function (d) {
          setDetail(function (prev) {
            return prev && prev.name === name
              ? {name: prev.name, src: prev.src, path: prev.path, code: d.content || ('Error: ' + (d.detail || d.error || 'unknown')), loading: false}
              : prev;
          });
        })
        .catch(function (e) {
          setDetail(function (prev) {
            return prev && prev.name === name
              ? {name: prev.name, src: prev.src, path: prev.path, code: 'Error: ' + e.message, loading: false}
              : prev;
          });
        });
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
        h(DetailPanel, {detail: detail, onClose: function () { setDetail(null); }})
      )
    );
  }

  window.__HERMES_PLUGINS__.register('hermes-evolution-hub', EvolutionHubPage);
})();
