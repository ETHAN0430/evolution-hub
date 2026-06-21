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

  function loadArchitecture() {
    return authFetch(BASE + '/api/architecture')
      .then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      });
  }

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
    storage: {fill: '#132728', stroke: '#7dd3d8'},
    hardware: {fill: '#2a1d18', stroke: '#e6a875'},
    infra: {fill: '#2a2218', stroke: '#c4b28a'}
  };

  var GLOSSARY = [
    {term: 'ReAct', def: 'Reasoning + Acting。翻译：先想想再动手。这也值得造个缩写？本质就是“模型调工具”循环，包装一下论文就好发了。Hermes 里就是 LLM API → 工具执行 → 上下文压缩 → LLM API 这个圈。'},
    {term: 'Function Calling', def: '模型输出 JSON，让外部程序去执行。说白了：模型就是个嘴炮指挥家，自己不动手。非要叫 Function Calling，显得比“调函数”高级。'},
    {term: 'Observation', def: '工具执行后返回的结果。一帮人非叫 Observation，听着像在做科学实验。其实就是“工具跑完告诉你啥情况”。'},
    {term: 'Reasoning / Thinking 模型', def: '会自己打草稿再回答的模型。DeepSeek-R1、o1 干的就是这事。非叫 Reasoning / Thinking Model，整得跟人类哲学家似的。'},
    {term: 'CoT（Chain-of-Thought）', def: 'prompt 里写“请逐步思考”。小学老师天天说“把过程写出来”，到 AI 圈就变成学术术语了，服了。'},
    {term: 'Post-Training / 后训练', def: '预训练之后继续训练。包括 SFT、RLHF、DPO。一帮人不敢叫“再训练”，非要叫 Post-Training，显得洋气。'},
    {term: 'PreHook / PostHook', def: 'LLM 调用前后插点代码。Pre=前，Post=后，Hook=钩子。三个字说明白的事非要整俩英文词，装逼指数拉满。'},
    {term: 'S1 / S2（System 1 / System 2）', def: '快思考 vs 慢思考。把“直觉反应”和“深思熟虑”说成 S1/S2，学术圈最爱的降维打击式命名。'},
    {term: 'Prompt Engineering', def: '调 prompt。说人话：跟模型说话的方式多试几遍，找最容易出好答案的说法。也被包装成一门学问，还出了各种“工程方法论”。'},
    {term: 'Loop', def: '循环。说人话：模型生成→调工具→再生成，反复直到任务完成。AI 圈啥都要叫 loop，agent loop、feedback loop、training loop，显得高级。'},
    {term: 'Context', def: '上下文。说人话：模型当前能看到的对话历史和背景。Context 长就是 token 贵，短就是模型忘事。搞不清时说“我 context 不够”就行了。'},
    {term: 'Harness', def: 'Harness（框架/脚手架）。说人话：把模型、工具、数据包在一起跑的一坨代码。非叫 Harness，跟骑马套鞍似的，也不知道在套谁。'},
    {term: 'Prompt vs Skill', def: '最好的 prompt 就是你的大脑：临场判断、上下文理解、随机应变。一旦某个流程固定下来、可以复用，它就变成了 skill。Prompt 是手动的，skill 是沉淀后的 prompt。'}
  ];

  var SOURCE_BASE = (typeof window.__HERMES_SOURCE_BASE__ === 'string' && window.__HERMES_SOURCE_BASE__)
    ? window.__HERMES_SOURCE_BASE__
    : '';
  if (SOURCE_BASE && !SOURCE_BASE.endsWith('/')) SOURCE_BASE += '/';

  function resolvePath(src) {
    if (!src) return '';
    if (src.startsWith('/')) return src;
    // Let the backend resolve relative paths; pass src through as-is when no base is configured.
    if (!SOURCE_BASE) return src;
    if (src === 'run_agent.py' || src === 'hermes_state.py') return SOURCE_BASE + src;
    if (src.startsWith('hermes_cli/') || src.startsWith('gateway/') || src.startsWith('apps/') || src.startsWith('tui_gateway/')) return SOURCE_BASE + src;
    if (src.startsWith('tools/')) return SOURCE_BASE + src;
    if (src.startsWith('agent/')) return SOURCE_BASE + src;
    if (src.startsWith('hy_memory/')) return src;
    return SOURCE_BASE + 'agent/' + src;
  }

  // ── components ───────────────────────────────────────────────────────────
  function ArchitectureSvg(props) {
    var onNodeClick = props.onNodeClick;
    var NODES = props.nodes;
    var CONNECTIONS = props.connections;

    var CLUSTERS = [
      {name: 'User', x: 20, y: 90, w: 170, h: 640, color: '#d4c5a9'},
      {name: 'Gateway', x: 210, y: 90, w: 190, h: 640, color: '#e6c875'},
      {name: 'Agent', x: 420, y: 90, w: 460, h: 650, color: '#f4a68e'},
      {name: 'Model / Reasoning', x: 20, y: 740, w: 1240, h: 80, color: '#8ab4e6'},
      {name: 'Model / Training', x: 20, y: 830, w: 1000, h: 220, color: '#8ab4e6'},
      {name: 'Memory', x: 900, y: 90, w: 420, h: 640, color: '#8fc9a3'},
      {name: 'Storage', x: 1340, y: 90, w: 200, h: 640, color: '#7dd3d8'},

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
      } else if (c[0] === 'LLM API' && c[1] === 'Tokenizer') {
        // LLM API -> Tokenizer: down out of the pipeline, then left above the inference cluster, then down into Tokenizer
        x1 = a.x;
        y1 = a.y + 17;
        x2 = b.x;
        y2 = b.y - 17;
        var tokenizerCorridorY = 750;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + tokenizerCorridorY + ' L' + x2 + ',' + tokenizerCorridorY + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'Output Head' && c[1] === 'LLM API') {
        // Output Head -> LLM API: up, then left to below LLM API, then up into its bottom
        x1 = a.x;
        y1 = a.y - 17;
        x2 = b.x;
        y2 = b.y + 17;
        var outputCorridorY = 720;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + outputCorridorY + ' L' + x2 + ',' + outputCorridorY + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'Turn Finalizer' && c[1] === '后台复盘') {
        // Turn Finalizer -> 后台复盘: go up to Agent Init height, then right into 后台复盘
        x1 = a.x;
        y1 = a.y - 17;
        x2 = b.x - 65;
        y2 = b.y;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + y2 + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'Turn Finalizer' && ['Hermes CLI', 'API Server', 'Messaging Gateway', 'TUI Gateway'].indexOf(c[1]) >= 0) {
        // Turn Finalizer -> gateways: exit upward, bend slightly above, go left to streaming-output x, then down
        x1 = a.x;
        y1 = a.y - 17;
        x2 = b.x;
        y2 = b.y;
        var replyCorridorY = 120;
        var replyCorridorX = 320;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + replyCorridorY + ' L' + replyCorridorX + ',' + replyCorridorY + ' L' + replyCorridorX + ',' + y2 + ' L' + x2 + ',' + y2;
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

    return h('svg', {className: 'eh-arch', viewBox: '0 0 1800 1180', width: '1800', height: '1180'},
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
              detail.src ? h('button', {className: 'eh-detail-action', onClick: onViewSource}, '查看源码') : null
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
    var _c = hooks.useState(null), arch = _c[0], setArch = _c[1];
    var _d = hooks.useState(null), detail = _d[0], setDetail = _d[1];
    var _glossary = hooks.useState(false), glossaryOpen = _glossary[0], setGlossaryOpen = _glossary[1];
    var _e = hooks.useState(1), svgScale = _e[0], setSvgScale = _e[1];
    var _f = hooks.useState(0), posX = _f[0], setPosX = _f[1];
    var _g = hooks.useState(0), posY = _g[0], setPosY = _g[1];
    var svgRef = hooks.useRef(null);
    var canvasRef = hooks.useRef(null);
    var dragRef = hooks.useRef(false);
    var dragStartRef = hooks.useRef({x: 0, y: 0});
    var posRef = hooks.useRef({x: 0, y: 0});

    var SVG_W = 1800;
    var SVG_H = 1180;

    function fitToScreen() {
      if (!canvasRef.current) return;
      var rect = canvasRef.current.getBoundingClientRect();
      var pad = 48;
      var availW = rect.width - pad;
      var availH = rect.height - pad;
      var scale = Math.min(availW / SVG_W, availH / SVG_H, 1.0);
      scale = Math.max(0.45, scale);
      var x = (rect.width - SVG_W * scale) / 2;
      var y = 32;
      setSvgScale(scale);
      setPosX(x);
      setPosY(y);
      posRef.current = {x: x, y: y};
    }

    hooks.useEffect(function () {
      fitToScreen();
      Promise.all([
        loadArchitecture().catch(function (e) { return {error: e.message || String(e)}; }),
        authFetch(BASE + '/api/health').then(function (r) { return r.json(); }).catch(function () { return null; }),
        authFetch(BASE + '/api/agent-loop').then(function (r) { return r.json(); }).catch(function () { return null; })
      ]).then(function (results) {
        setArch(results[0]);
        setHealth(results[1]);
        setAgentLoop(results[2]);
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
      var n = arch && arch.NODES && arch.NODES[name];
      if (!n) return;
      var safeSrc = src || '';
      var path = safeSrc ? resolvePath(safeSrc) : '';
      setDetail({name: name, desc: n.desc || '', src: safeSrc, path: path, loc: loc || n.loc || '', code: null, loading: false, showCode: false});
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

    var canvasChildren = [];
    if (!arch) {
      canvasChildren.push(h('div', {key: 'loading', className: 'eh-detail-loading', style: {padding: 24}}, '加载架构数据中…'));
    } else if (arch.error) {
      canvasChildren.push(h('div', {key: 'error', className: 'eh-detail-error', style: {padding: 24}},
        h('div', {className: 'eh-detail-error-title'}, '架构数据加载失败'),
        h('div', {className: 'eh-detail-error-hint'}, arch.error)
      ));
    } else {
      canvasChildren.push(
        h('div', {key: 'svg', ref: svgRef, className: 'eh-svg-wrap', style: {transform: transformStyle}},
          h(ArchitectureSvg, {onNodeClick: onNodeClick, nodes: arch.NODES, connections: arch.CONNECTIONS})
        )
      );
    }
    canvasChildren.push(
      h(DetailPanel, {
        key: 'detail',
        detail: detail,
        onClose: function () { setDetail(null); },
        onViewSource: function () { if (detail) loadSource(detail.name, detail.src, detail.path, detail.loc); }
      })
    );

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
      h('div', {ref: canvasRef, className: 'eh-canvas', onMouseDown: onMouseDown, onMouseMove: onMouseMove, onMouseUp: onMouseUp, onMouseLeave: onMouseLeave}, canvasChildren),
      // Glossary
      h('div', {className: 'eh-glossary' + (glossaryOpen ? ' eh-glossary-open' : ''), key: 'glossary'},
        h('button', {className: 'eh-glossary-toggle', onClick: function () { setGlossaryOpen(!glossaryOpen); }}, glossaryOpen ? '收起术语表 ▲' : '展开术语表 ▼'),
        h('div', {className: 'eh-glossary-content'},
          h('div', {className: 'eh-glossary-grid'},
            GLOSSARY.map(function (item, idx) {
              return h('div', {className: 'eh-glossary-item', key: idx},
                h('div', {className: 'eh-glossary-term'}, item.term),
                h('div', {className: 'eh-glossary-def'}, item.def)
              );
            })
          )
        )
      )
    );
  }

  window.__HERMES_PLUGINS__.register('hermes-evolution-hub', EvolutionHubPage);
})();
