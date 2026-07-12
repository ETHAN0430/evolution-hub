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
    hy: {fill: '#142d21', stroke: '#8fc9a3'},
    storage: {fill: '#132728', stroke: '#7dd3d8'},
    hardware: {fill: '#2a1d18', stroke: '#e6a875'},
    infra: {fill: '#2a2218', stroke: '#c4b28a'}
  };

  var GLOSSARY = [
    {term: 'ReAct', def: 'Reasoning + Acting。翻译：先想想再动手。这也值得造个缩写？本质就是“模型调工具”循环，包装一下论文就好发了。Hermes 里就是 LLM API → 工具执行 → 上下文压缩 → LLM API 这个圈。'},
    {term: 'Function Calling', def: '模型输出 JSON，让外部程序去执行。说白了：模型就是个嘴炮指挥家，自己不动手。非要叫 Function Calling，显得比“调函数”高级。'},
    {term: 'Observation', def: '工具执行后返回的结果。一帮人非叫 Observation，听着像在做科学实验。其实就是“工具跑完告诉你啥情况”。'},
    {term: 'Reasoning / Thinking 模型', def: '会自己打草稿再回答的模型。DeepSeek-R1、o1 干的就是这事。非叫 Reasoning / Thinking Model，整得跟人类哲学家似的。'},
    {term: 'Thinking / Reasoning 模式', def: '模型“思考”的三种真相：Level 1 是纯 prompt 注入，system prompt 里加一句“请逐步思考”；Level 2 是训练出来的思考标记，模型通过 RL/SFT 自己学会吐 <think> 块，关掉只是过滤输出；Level 3 才是真正的推理时计算，比如 o1 的 reasoning_effort，会多花算力做搜索、验证、反思。99% 的 thinking 开关都是 Level 1 或 2。'},
    {term: 'CoT（Chain-of-Thought）', def: 'prompt 里写“请逐步思考”。小学老师天天说“把过程写出来”，到 AI 圈就变成学术术语了，服了。'},
    {term: 'Post-Training / 后训练', def: '预训练之后继续训练。包括 SFT、RLHF、DPO。一帮人不敢叫“再训练”，非要叫 Post-Training，显得洋气。'},
    {term: '训练 / Training', def: '这词很宽泛，不要只从技术视角理解。模型训练是更新神经网络权重；Agent 训练是让模型学会用工具或遵循流程；Skill 训练是把好用的 prompt 沉淀下来；人还能军训、健身。本架构图的 Model / Training 专指模型权重训练。'},
    {term: 'PreHook / PostHook', def: 'LLM 调用前后插点代码。Pre=前，Post=后，Hook=钩子。三个字说明白的事非要整俩英文词，装逼指数拉满。'},
    {term: 'S1 / S2（System 1 / System 2）', def: '快思考 vs 慢思考。把“直觉反应”和“深思熟虑”说成 S1/S2，学术圈最爱的降维打击式命名。'},
    {term: 'Prompt Engineering', def: '调 prompt。说人话：跟模型说话的方式多试几遍，找最容易出好答案的说法。也被包装成一门学问，还出了各种“工程方法论”。'},
    {term: 'Loop', def: '循环。说人话：模型生成→调工具→再生成，反复直到任务完成。AI 圈啥都要叫 loop，agent loop、feedback loop、training loop，显得高级。'},
    {term: 'Context', def: '上下文。说人话：模型当前能看到的对话历史和背景。Context 长就是 token 贵，短就是模型忘事。搞不清时说“我 context 不够”就行了。'},
    {term: 'Harness', def: 'Harness（框架/脚手架）。说人话：把模型、工具、数据包在一起跑的一坨代码。非叫 Harness，跟骑马套鞍似的，也不知道在套谁。'},
    {term: 'Prompt vs Skill', def: '最好的 prompt 就是你的大脑：临场判断、上下文理解、随机应变。一旦某个流程固定下来、可以复用，它就变成了 skill。Prompt 是手动的，skill 是沉淀后的 prompt。'},
    {term: 'Greedy Decoding', def: '永远选概率最大的 token。简单、稳定，但回答千篇一律，复杂问题容易车轱辘话。很多模型默认推理就用它，因为便宜可控。'},
    {term: 'Temperature', def: '控制采样随机性的温度参数。T=0 退化成 greedy，T=1 是原始分布，T>1 更随机。说人话：让模型老实点还是放飞自我。'},
    {term: 'Top-k Sampling', def: '只在概率最高的 k 个 token 里采样。k=1 就是 greedy，k 越大越多样。问题是 k 固定，可能把明显很差的词也塞进候选集。'},
    {term: 'Top-p / Nucleus Sampling', def: '从累计概率达到 p 的最小 token 集合里采样。比 top-k 灵活，能自动根据分布调整候选集大小。名字起得跟核物理似的，其实就这么点事。'},
    {term: 'Beam Search', def: '同时保留多条候选序列，按整体概率选最好的。翻译、搜索类任务常用。开放式对话里容易生成无聊的安全答案，因为候选越往后越趋同。'},
    {term: 'Repetition Penalty', def: '重复惩罚。模型老说同一句话？给已经出现过的 token logits 打个折，逼它换词。调太高了会胡言乱语。'},
    {term: 'Logits', def: '模型输出层给的原始分数，还没经过 softmax。说人话：每个候选 token 的“得分”，分越高越可能是答案，但不是概率。softmax 之后才变成概率。'},
    {term: 'Detokenization', def: '把模型生成的 token ID 序列反向查表，变回人类能看的文本。说人话：Tokenizer 把字切成数字，Detokenization 把数字拼回字。流式输出时每生成一个 token 就增量解码一个 chunk。'},
    {term: 'Plan Mode', def: '计划模式。每轮 Turn 里，遇到复杂任务时让模型列步骤（Todo List），给用户确认后再执行。说人话：先打草稿再动工，避免模型一上来就把你代码库改崩。不是只在会话开头跑一次，而是按需触发。'},
    {term: 'Distillation / 蒸馏', def: '知识蒸馏：让一个模型（Student）学另一个模型（Teacher）的输出分布，把能力从 Teacher 迁移到 Student。Student 通常更小，但不一定。Student 只感知到损失函数变了，它并不知道软目标来自更大的模型、更贵的模型还是人类标注；对它来说这就是一种特殊的训练目标。所以你问它“你是不是蒸馏了 Claude”，它也不知道。'},
    {term: 'Ask Mode', def: '询问模式。模型发现信息不够或需要选择时，停下来问用户。Hermes 里通常通过 approval / ask_user 工具实现：模型调用工具 → 前端阻塞等输入 → 回答写回上下文继续。'},
    {term: 'Tool Permissions', def: '工具权限。不同工具危险等级不同（只读 / 写 / 执行 / 危险）。Agent Init 按配置过滤可用工具，pre_tool_call 拦截越权，approval 处理危险操作。'},
    {term: 'Q / K / V', def: 'Attention 里的三个角色。Q（Query）是当前 token 的查询意图；K（Key）是每个 token 的索引标签，用来被匹配；V（Value）是每个 token 的实际内容，用来被加权组合。注意力权重 = softmax(Q × K^T)，输出 = 权重 × V。'},
    {term: 'RoPE（Rotary Positional Embedding）', def: '旋转位置编码。现代大模型常用的位置编码方式，不再作为独立层，而是把位置信息融进 自注意力 的 Q/K 向量里做旋转。说人话：给每个 token 的查询/键向量“拧”一下角度，让模型既能知道位置，又不破坏 attention 的结构。'},
    {term: '参数量 vs 推理成本', def: '参数量越大，每 token 推理越贵。因为每 forward 都要做更多矩阵乘法和内存读写。7B 便宜，70B 贵 10 倍左右，400B+ 更贵。上下文长度、batch size、量化、KV Cache 也会影响最终成本。'},
    {term: 'Input / Output Token 定价', def: 'Input token 便宜是因为 prompt 可以并行处理，GPU 利用率高。Output token 贵是因为自回归生成必须串行，每生成一个 token 都要重新加载权重前向传播一次。所以 API 里 output 通常比 input 贵 2~5 倍。另外 API 定价一般还会覆盖硬件折旧、电费、运维和利润；早期毛利可能到成本的 5~10 倍，价格战激烈时可能只有 1~2 倍甚至亏本。'},
    {term: 'Tensor / Vector / Matrix', def: '张量是最 general 的概念，向量是 1 维张量，矩阵是 2 维张量。标量是 0 维。深度学习里一个 token 的 embedding 是向量，一句话所有 token 拼起来是矩阵，一个 batch 的多句话就是 3 维张量 [batch, seq_len, hidden_dim]。'},
    {term: 'Fine-tuning / 微调', def: '在预训练好的模型基础上，用你自己的小批量高质量数据继续训练。让模型“内化”你的领域知识、输出格式或说话风格。SFT、RLHF、DPO 都属于后训练（Post-Training）范畴。说人话：让通用模型变成你的专属模型。'},
    {term: 'RAG / 检索增强生成', def: '模型回答前先去外部知识库检索相关资料，把检索结果拼进 prompt 再生成答案。知识存在数据库里，换文档就生效，模型权重不用改。说人话：开卷考试，模型边翻书边答。'}
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
    if (src.startsWith('cognitive_os/')) return src;
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
      {name: 'Model / Reasoning', x: 420, y: 760, w: 1380, h: 110, color: '#8ab4e6'},
      {name: 'Model / Training', x: 420, y: 890, w: 1380, h: 220, color: '#8ab4e6'},
      {name: 'Memory', x: 890, y: 90, w: 710, h: 650, color: '#8fc9a3'},
      {name: 'Tools', x: 900, y: 150, w: 220, h: 590, color: '#8fc9a3'},

      {name: 'Storage', x: 1600, y: 90, w: 200, h: 640, color: '#7dd3d8'},

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
        var tokenizerCorridorY = 745;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + tokenizerCorridorY + ' L' + x2 + ',' + tokenizerCorridorY + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'Sampling' && c[1] === 'LLM API') {
        // Sampling -> LLM API: up, then left to below LLM API, then up into its bottom
        x1 = a.x;
        y1 = a.y - 17;
        x2 = b.x;
        y2 = b.y + 17;
        var outputCorridorY = 745;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + outputCorridorY + ' L' + x2 + ',' + outputCorridorY + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'Sampling' && c[1] === 'Embedding') {
        // Sampling -> Embedding: autoregressive feedback loop for next-token generation
        x1 = a.x;
        y1 = a.y - 17;
        x2 = b.x;
        y2 = b.y - 17;
        var loopCorridorY = 860;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + loopCorridorY + ' L' + x2 + ',' + loopCorridorY + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'Model Weights' && ['Embedding', '自注意力', '前馈网络', 'Output Head'].indexOf(c[1]) >= 0) {
        // Model Weights -> inference layers: fan out below the node into the reasoning cluster
        x1 = a.x;
        y1 = a.y + 17;
        x2 = b.x;
        y2 = b.y - 17;
        var weightsCorridorY = 880;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + weightsCorridorY + ' L' + x2 + ',' + weightsCorridorY + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'Student' && c[1] === 'Model Weights') {
        // Student -> Model Weights: vertical-first to avoid crossing Post-Training / 微调
        x1 = a.x;
        y1 = a.y - 17;
        x2 = a.x > b.x ? b.x + 65 : b.x - 65;
        y2 = b.y;
        var studentCorridorY = 900;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + studentCorridorY + ' L' + x2 + ',' + studentCorridorY + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'Post-Training' && c[1] === 'Model Weights') {
        // Post-Training -> Model Weights: up, then right into Model Weights, avoiding 微调
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
      } else if (c[0] === '后台复盘' && c[1] === 'memory_tool') {
        // Background review -> memory_tool: horizontal into the tool surface
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + y2 + ' L' + x2 + ',' + y2;
      } else if (c[0] === '后台复盘' && c[1] === 'skill_manage') {
        // Background review -> skill_manage: drop down into the skill tool node
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + y2 + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'Agent Init' && c[1] === '记忆/技能') {
        // Agent Init -> 记忆/技能: up to top corridor, across to Storage, then down
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        var initMemCorridorY = 120;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + initMemCorridorY + ' L' + x2 + ',' + initMemCorridorY + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'Turn Finalizer' && c[1] === 'SQLite Session') {
        // Turn Finalizer -> SQLite Session: top corridor to avoid crossing System 2 Writer
        x1 = a.x;
        y1 = a.y - 17;
        x2 = b.x - 65;
        y2 = b.y;
        var sqliteCorridorY = 120;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + sqliteCorridorY + ' L' + x2 + ',' + sqliteCorridorY + ' L' + x2 + ',' + y2;
      } else if (c[0] === '记忆检索' && c[1] === 'Embedding') {
        // 记忆检索 -> Embedding: up to Embedding height, then right into retrieval cluster
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + y2 + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'ANN 检索' && c[1] === 'Vector DB') {
        // ANN 检索 -> Vector DB: right then up
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        d = 'M' + x1 + ',' + y1 + ' L' + x2 + ',' + y1 + ' L' + x2 + ',' + y2;
      } else if (c[0] === '记忆写入' && c[1] === 'System 1 Writer') {
        // 记忆写入 -> S1: explicit write tool feeds the write pipeline
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + y2 + ' L' + x2 + ',' + y2;
      } else if (c[0] === '记忆预取' && c[1] === 'Embedding') {
        // 记忆预取 -> Embedding: auto recall goes through the retrieval path
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        var prefetchEmbedCorridorX = 1100;
        d = 'M' + x1 + ',' + y1 + ' L' + prefetchEmbedCorridorX + ',' + y1 + ' L' + prefetchEmbedCorridorX + ',' + y2 + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'Vector DB' && c[1] === 'System 2 Writer') {
        // Vector DB -> System 2 Writer: exit left, travel left a segment, then up, then left into System 2 Writer right
        x1 = a.x - 65;
        y1 = a.y;
        x2 = b.x + 65;
        y2 = b.y;
        var vdbS2CorridorX = a.x - 130;
        var vdbS2CorridorY = 260;
        d = 'M' + x1 + ',' + y1 + ' L' + vdbS2CorridorX + ',' + y1 + ' L' + vdbS2CorridorX + ',' + vdbS2CorridorY + ' L' + x2 + ',' + vdbS2CorridorY + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'Reconciler' && c[1] === 'Vector DB') {
        // Reconciler -> Vector DB: exit right, go up to corridor, then left into Vector DB
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        var reconcilerVdbCorridorX = b.x + 80;
        d = 'M' + x1 + ',' + y1 + ' L' + reconcilerVdbCorridorX + ',' + y1 + ' L' + reconcilerVdbCorridorX + ',' + y2 + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'skill_manage' && c[1] === '记忆/技能') {
        // skill_manage -> 记忆/技能: right, then up to memory_tool's y, then right together into storage
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        var skillMergeX = 1200;
        d = 'M' + x1 + ',' + y1 + ' L' + skillMergeX + ',' + y1 + ' L' + skillMergeX + ',' + y2 + ' L' + x2 + ',' + y2;
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
      var label = n.label || name;
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
        h('text', {x: 0, y: 4, textAnchor: 'middle', fill: '#f8fafc', fontSize: 12, fontWeight: 500}, label)
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

  function formatDesc(text) {
    var lines = text.split('\n');
    var out = [];
    var bullets = [];
    function flushBullets() {
      if (bullets.length) {
        var items = bullets.map(function (b, i) { return h('li', {className: 'eh-detail-li', key: i}, b); });
        out.push(h('ul', {className: 'eh-detail-ul', key: 'ul-' + out.length}, items));
        bullets = [];
      }
    }
    lines.forEach(function (raw) {
      var line = raw.replace(/^[\s\u3000]+|[\s\u3000]+$/g, '');
      if (!line) { flushBullets(); return; }
      if (/^[-–—•]/.test(line)) {
        bullets.push(line.replace(/^[-–—•]\s*/, ''));
        return;
      }
      flushBullets();
      if (/[：:?？!！]$/.test(line)) {
        out.push(h('h4', {className: 'eh-detail-h4', key: 'h-' + out.length}, line));
      } else {
        out.push(h('p', {className: 'eh-detail-p', key: 'p-' + out.length}, line));
      }
    });
    flushBullets();
    return h('div', {className: 'eh-detail-desc'}, out);
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
              formatDesc(detail.desc || '暂无介绍'),
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

  function formatRelativeTime(iso) {
    if (!iso) return '';
    var then = new Date(iso).getTime();
    if (isNaN(then)) return iso;
    var now = Date.now();
    var diff = Math.floor((now - then) / 1000);
    if (diff < 60) return '刚刚';
    if (diff < 3600) return Math.floor(diff / 60) + '分钟前';
    if (diff < 86400) return Math.floor(diff / 3600) + '小时前';
    return Math.floor(diff / 86400) + '天前';
  }

  function Collapsible(props) {
    var title = props.title;
    var count = props.count;
    var children = props.children;
    var _s = hooks.useState(props.defaultOpen !== false), open = _s[0], setOpen = _s[1];
    return h('div', {className: 'eh-collapsible'},
      h('button', {
        className: 'eh-collapsible-header',
        onClick: function () { setOpen(!open); },
        'aria-expanded': open
      },
        h('span', {className: 'eh-collapsible-title'}, title),
        count != null ? h('span', {className: 'eh-collapsible-count'}, count) : null,
        h('span', {className: 'eh-collapsible-caret'}, open ? '▲' : '▼')
      ),
      open ? h('div', {className: 'eh-collapsible-body'}, children) : null
    );
  }

  function MemoryFeedPanel(props) {
    var data = props.data;
    if (!data) return h('div', {className: 'eh-feed-loading'}, '加载中…');
    if (data.error) return h('div', {className: 'eh-feed-error'}, '加载失败');
    var layers = data.layers || [];
    var recent = data.recent || [];
    var byLayer = {};
    layers.forEach(function (l) { byLayer[l] = []; });
    recent.forEach(function (item) {
      var l = item.layer || 'unknown';
      if (!byLayer[l]) byLayer[l] = [];
      byLayer[l].push(item);
    });
    var opLabel = function (op) {
      var map = {ADD: '新增', UPDATE: '更新', DELETE: '删除', SUPERSEDE: '替代'};
      return map[op] || op;
    };
    var layerLabel = function (l) { return l; };
    return h('div', {className: 'eh-feed-panel'},
      h('div', {className: 'eh-feed-header'}, '认知对象活动'),
      layers.map(function (layer) {
        var items = byLayer[layer] || [];
        return h(Collapsible, {key: layer, title: layerLabel(layer), count: items.length},
          items.length === 0
            ? h('div', {className: 'eh-feed-empty'}, '暂无记录')
            : h('ul', {className: 'eh-feed-list'},
                items.map(function (item, i) {
                  return h('li', {key: i, className: 'eh-feed-item'},
                    h('div', {className: 'eh-feed-meta'},
                      h('span', {className: 'eh-feed-time'}, formatRelativeTime(item.time)),
                      h('span', {className: 'eh-feed-badge'}, opLabel(item.op))
                    ),
                    h('div', {className: 'eh-feed-summary'}, item.summary)
                  );
                })
              )
        );
      })
    );
  }

  function PrefetchFeedPanel(props) {
    var data = props.data;
    if (!data) return h('div', {className: 'eh-feed-loading'}, '加载中…');
    if (data.error) return h('div', {className: 'eh-feed-error'}, '加载失败');
    var recent = data.recent || [];
    var stats = data.stats || {};
    return h('div', {className: 'eh-feed-panel'},
      h('div', {className: 'eh-graph-caption'}, '召回观测：自动召回是系统在每轮前主动取回；memory_search 是模型显式发起的查询。这里记录真实查询、命中和耗时。'),
      h('div', {className: 'eh-feed-header'}, '记忆预取情况'),
      h('div', {className: 'eh-feed-stats'},
        h('span', {className: 'eh-feed-stat'}, '1小时: ', h('b', null, stats.total_1h || 0)),
        h('span', {className: 'eh-feed-stat'}, '今日: ', h('b', null, stats.total_today || 0))
      ),
      h('div', {className: 'eh-feed-stats'}, '自动召回 ' + (stats.auto_recall || 0) + ' · memory_search ' + (stats.memory_search || 0) + ' · 失败 ' + (stats.errors || 0)),
      recent.slice(0, 12).map(function (item, i) {
        return h('div', {key: i, className: 'eh-prefetch-item'},
          h('div', {className: 'eh-feed-meta'},
            h('span', {className: 'eh-feed-time'}, formatRelativeTime(item.time)),
            h('span', {className: 'eh-feed-badge ' + (item.hits > 0 ? 'eh-feed-badge-hit' : 'eh-feed-badge-miss')},
              (item.hits || 0) + ' 命中')
          ),
          h('div', {className: 'eh-feed-query'}, item.query),
          h('div', {className: 'eh-feed-reader'}, 'reader: ' + (item.reader || 'legacy'))
        );
      })
    );
  }

  function MetricTile(props) {
    return h('div', {className: 'eh-metric-tile'},
      h('div', {className: 'eh-metric-label'}, props.label),
      h('div', {className: 'eh-metric-value'}, props.value == null ? '—' : props.value),
      props.hint ? h('div', {className: 'eh-metric-hint'}, props.hint) : null
    );
  }

  function CognitiveQualityPanel(props) {
    var data = props.data;
    if (!data) return h('div', {className: 'eh-feed-loading'}, '加载中…');
    if (data.error) return h('div', {className: 'eh-feed-error'}, '加载失败');
    var latest = data.latest || {};
    var edgeCounts = latest.edge_type_counts || {};
    var warnings = latest.warnings || [];
    var reports = data.reports || [];
    return h('div', {className: 'eh-feed-panel'},
      h('div', {className: 'eh-feed-header'}, 'Digest 质量报告'),
      h('div', {className: 'eh-metric-grid'},
        h(MetricTile, {label: '新 Schema', value: latest.schema_created || 0}),
        h(MetricTile, {label: '复用 Schema', value: latest.schema_reused || 0}),
        h(MetricTile, {label: '新增证据', value: latest.evidence_added || 0}),
        h(MetricTile, {label: '新增边', value: latest.edges_created || 0}),
        h(MetricTile, {label: 'RELATED_TO', value: Math.round((latest.related_to_ratio || 0) * 100) + '%'}),
        h(MetricTile, {label: '警告', value: warnings.length})
      ),
      h('div', {className: 'eh-edge-strip'},
        Object.keys(edgeCounts).length === 0
          ? h('span', {className: 'eh-feed-empty'}, '暂无边类型记录')
          : Object.keys(edgeCounts).sort().map(function (k) {
              return h('span', {key: k, className: 'eh-edge-chip'}, k + ' ' + edgeCounts[k]);
            })
      ),
      warnings.length
        ? h('div', {className: 'eh-warning-row'}, warnings.join(' · '))
        : h('div', {className: 'eh-ok-row'}, '本轮未发现质量告警'),
      reports.slice(0, 3).map(function (item, i) {
        var d = item.detail || {};
        return h('div', {key: i, className: 'eh-mini-report'},
          h('span', {className: 'eh-feed-time'}, formatRelativeTime(item.time)),
          h('span', null, 'Schema ' + (d.schema_created || 0) + ' / Evidence ' + (d.evidence_added || 0) + ' / Edge ' + (d.edges_created || 0))
        );
      })
    );
  }

  function CognitiveHealthPanel(props) {
    var data = props.data;
    if (!data) return h('div', {className: 'eh-feed-loading'}, '加载中…');
    if (data.error) return h('div', {className: 'eh-feed-error'}, '加载失败');
    var health = data.health || {};
    var graphOps = health.graph_ops || {};
    var edgeCounts = health.edge_type_counts || {};
    var recentOps = data.recent_ops || [];
    return h('div', {className: 'eh-feed-panel'},
      h('div', {className: 'eh-feed-header'}, '认知图健康'),
      h('div', {className: 'eh-metric-grid'},
        h(MetricTile, {label: 'Schema 总数', value: health.schema_total == null ? (health.schema_creates || 0) : health.schema_total}),
        h(MetricTile, {label: '图边总数', value: health.memory_edge_total || 0}),
        h(MetricTile, {label: '认知边', value: health.cognitive_edge_total || 0}),
        h(MetricTile, {label: '弱相关占比', value: Math.round((health.related_to_ratio || 0) * 100) + '%'}),
        h(MetricTile, {label: '孤立 Schema', value: health.orphan_schema_count || 0}),
        h(MetricTile, {label: '无证据 Schema', value: health.no_evidence_schema_count || 0})
      ),
      h('div', {className: 'eh-edge-strip'},
        Object.keys(edgeCounts).length === 0
          ? h('span', {className: 'eh-feed-empty'}, '暂无历史边记录')
          : Object.keys(edgeCounts).sort().map(function (k) {
              return h('span', {key: k, className: 'eh-edge-chip'}, k + ' ' + edgeCounts[k]);
            })
      ),
      recentOps.slice(0, 4).map(function (op, i) {
        return h('div', {key: i, className: 'eh-mini-report'},
          h('span', {className: 'eh-feed-time'}, formatRelativeTime(op.time)),
          h('span', {className: 'eh-feed-badge'}, op.op || 'GRAPH_OP'),
          op.edge_type ? h('span', {className: 'eh-edge-chip'}, op.edge_type) : null
        );
      })
    );
  }

  function WorkspaceObjectPanel(props) {
    var title = props.title;
    var source = props.source;
    var empty = props.empty;
    var items = props.items || [];
    return h('div', {className: 'eh-feed-panel'},
      h('div', {className: 'eh-feed-header'}, title),
      h('div', {className: 'eh-feed-stats'}, source || '数据源未知'),
      items.length === 0
        ? h('div', {className: 'eh-feed-empty'}, empty || '暂无记录')
        : items.slice(0, 6).map(function (item) {
            return h('div', {key: item.id, className: 'eh-prefetch-item'},
              h('div', {className: 'eh-feed-meta'},
                h('span', {className: 'eh-feed-time'}, formatRelativeTime(item.time)),
                h('span', {className: 'eh-feed-badge'}, item.status || 'active')
              ),
              h('div', {className: 'eh-feed-summary'}, item.content || '(无内容)'),
              item.tags && item.tags.length
                ? h('div', {className: 'eh-edge-strip'}, item.tags.slice(0, 4).map(function (tag) {
                    return h('span', {key: tag, className: 'eh-edge-chip'}, tag);
                  }))
                : null
            );
          })
    );
  }

  function DecisionWorkspacePanel(props) {
    var data = props.data;
    if (!data) return h('div', {className: 'eh-feed-loading'}, '加载真实认知资产中…');
    if (data.error) return h('div', {className: 'eh-feed-error'}, '工作台加载失败：' + data.error);
    var source = data.source || {};
    var health = data.graph_health || {};
    var decisions = data.decisions || {};
    var intents = data.intents || {};
    return h('div', {className: 'eh-feeds'},
      h('div', {className: 'eh-feed-panel eh-feed-panel-wide'},
        h('div', {className: 'eh-feed-header'}, '证据驱动的决策工作台'),
        h('div', {className: 'eh-feed-stats'},
          '当前记录：证据 ' + (source.vdb_total || 0) + ' 条 · 主张 ' + (source.graph_total || 0) + ' 条'
        ),
        h('div', {className: 'eh-metric-grid'},
          h(MetricTile, {label: 'Schema', value: health.schema_total == null ? '—' : health.schema_total}),
          h(MetricTile, {label: '孤立 Schema', value: health.orphan_schema_count == null ? '—' : health.orphan_schema_count}),
          h(MetricTile, {label: '图边', value: health.memory_edge_total == null ? '—' : health.memory_edge_total}),
          h(MetricTile, {label: '认知边', value: health.cognitive_edge_total == null ? '—' : health.cognitive_edge_total})
        )
      ),
      h('div', {className: 'eh-feeds-grid'},
        h('div', {className: 'eh-feeds-col'}, h(WorkspaceObjectPanel, {
          title: '当前主张 Claim', source: data.claims && data.claims.source,
          items: data.claims && data.claims.items, empty: '暂无可展示的主张'
        })),
        h('div', {className: 'eh-feeds-col'}, h(WorkspaceObjectPanel, {
          title: '协作与决策契约', source: data.contracts && data.contracts.source,
          items: data.contracts && data.contracts.items, empty: '暂无可展示的决策'
        }))
      ),
      h('div', {className: 'eh-feeds-grid'},
        h('div', {className: 'eh-feeds-col'}, h(WorkspaceObjectPanel, {
          title: '可迁移模型 Model', source: data.models && data.models.source,
          items: data.models && data.models.items, empty: '暂无可展示的模型'
        })),
        h('div', {className: 'eh-feeds-col'}, h(WorkspaceObjectPanel, {
          title: '待执行承诺 Intent', source: intents.source,
          items: intents.items,
          empty: '暂无有效行动承诺。'
        }))
      ),
      h('div', {className: 'eh-feed-panel eh-feed-panel-wide'},
        h('div', {className: 'eh-feed-header'}, '决策账本 Decision Ledger'),
        h('div', {className: 'eh-warning-row'}, decisions.message || '未接入')
      )
    );
  }

  function GlossaryPanel(props) {
    return h('div', {className: 'eh-glossary' + (props.open ? ' eh-glossary-open' : '')},
      h('button', {className: 'eh-glossary-toggle', onClick: props.onToggle}, props.open ? '收起术语表 ▲' : '展开术语表 ▼'),
      h('div', {className: 'eh-glossary-content'},
        h('div', {className: 'eh-glossary-grid'}, GLOSSARY.map(function (item, idx) {
          return h('div', {className: 'eh-glossary-item', key: idx},
            h('div', {className: 'eh-glossary-term'}, item.term),
            h('div', {className: 'eh-glossary-def'}, item.def)
          );
        }))
      )
    );
  }

  function OverallStatusPanel(props) {
    var health = props.health || {};
    var review = props.review || {};
    var map = props.map || {};
    var server = health.server || {};
    var ledger = health.ledger || {};
    var summary = review.summary || {};
    var attention = (summary.contradictions || 0) + (summary.overdue_decisions || 0) + (summary.pending_issues || 0) + (summary.pending_proposals || 0);
    var state = server.vdb === 'ok' ? '正常' : '需要检查';
    state = ledger.status === 'ready' ? '正常' : '需要检查';
    return h('div', {className: 'eh-overall-status'},
      h('div', {className: 'eh-feed-header'}, '整体状态'),
      h('div', {className: 'eh-metric-grid'},
        h(MetricTile, {label: 'Ledger 对象', value: ledger.object_count || 0, hint: 'Cognitive OS 的 canonical 对象数'}),
        h(MetricTile, {label: '认知系统', value: state, hint: '账本与检索是否可用'}),
        h(MetricTile, {label: '关系网络', value: (map.edges || []).length, hint: '当前显式关系数'}),
        h(MetricTile, {label: '待关注', value: attention, hint: '复盘、矛盾与待审事项'})
      )
    );
  }

  function TimelinePanel(props) {
    var events = props.events || [];
    var labels = {evidence_recorded: '记录了来源', claim_created: '形成了判断', claim_revised: '修订了判断', decision_created: '做出决定', intent_created: '设定行动', outcome_recorded: '收到了反馈', evidence_state_changed: '修订了来源', user_correction: '用户修订'};
    if (!events.length) return h('div', {className: 'eh-action-later'}, '时间链会从现在开始累计：历史记录保留原始时间，不伪造“刚刚”。');
    return h('div', {className: 'eh-action-later'},
      h('div', {className: 'eh-action-eyebrow'}, '最近发生了什么'),
      events.slice(0, 6).map(function (event, index) { return h('div', {key: index, className: 'eh-edge-chip'}, (event.occurred_at || '').replace('T', ' ').slice(0, 16) + ' · ' + (labels[event.event_type] || event.event_type) + (event.reason ? '：' + event.reason : '')); })
    );
  }

  function GraphHubPanel(props) {
    var _lens = hooks.useState('global'), lens = _lens[0], setLens = _lens[1];
    var _topic = hooks.useState(null), selectedTopicId = _topic[0], setSelectedTopicId = _topic[1];
    var selectedData = lens === 'global' ? props.globalData : props.detailData;
    if (lens === 'conflict' && selectedData && selectedData.nodes) {
      var keep = {};
      selectedData.nodes.forEach(function (node) { if (node.kind === 'outcome' && node.status === 'contradicts') keep[node.id] = true; });
      var changed = true;
      while (changed) {
        changed = false;
        (selectedData.edges || []).forEach(function (edge) {
          if (keep[edge.to] && !keep[edge.from]) { keep[edge.from] = true; changed = true; }
          if (keep[edge.from] && !keep[edge.to]) { keep[edge.to] = true; changed = true; }
        });
      }
      selectedData = {nodes: selectedData.nodes.filter(function (node) { return keep[node.id]; }), edges: (selectedData.edges || []).filter(function (edge) { return keep[edge.from] && keep[edge.to]; })};
    }
    var caption = lens === 'global' ? '全局：你保存了哪些认知对象，它们之间有多少明确关系。' : lens === 'conflict' ? '冲突：只看当前被现实结果挑战的决策链。' : '焦点：查看最近一项决策所依赖的证据、主张、模型与结果。';
    if (props.topicData) {
      var topics = props.topicData.topics || [];
      var semanticNodes = topics.map(function (topic, index) {
        var angle = index * 2.399963229728653;
        var radius = 0.12 + 0.34 * Math.sqrt((index + 0.5) / Math.max(topics.length, 1));
        var kind = String(topic.id).indexOf('decision:') === 0 ? 'decision_topic' : topic.status === 'suggested' ? 'suggested_topic' : 'topic';
        return {id: topic.id, kind: kind, label: topic.label, count: topic.member_count, status: topic.attention ? 'attention' : topic.status, detail: topic.detail, summary: topic.summary, position: [0.5 + Math.cos(angle) * radius, 0.5 + Math.sin(angle) * radius * 0.82]};
      });
      var inbox = props.topicData.unclassified || {};
      var inboxCount = (inbox.active || 0) + (inbox.unreviewed || 0);
      if (inboxCount) semanticNodes.push({id: 'unclassified', kind: 'inbox', label: '待归类 / 待确认', count: inboxCount, status: 'unreviewed', summary: '这些记录没有被硬凑成主题；争议和撤回记录不进入这个数字。'});
      var selectedTopic = topics.filter(function (topic) { return topic.id === selectedTopicId; })[0] || topics[0];
      if (lens === 'focus') selectedData = selectedTopic ? selectedTopic.detail : {nodes: [], edges: []};
      else if (lens === 'conflict') selectedData = {nodes: semanticNodes.filter(function (node) { return node.status === 'attention'; }), edges: []};
      else selectedData = {nodes: semanticNodes, edges: []};
    }
    return h('div', {className: 'eh-graph-hub'},
      props.topicData ? h('div', {className: 'eh-topic-legend'},
        h('div', {className: 'eh-topic-definition'}, h('b', null, '主题候选是什么？'), ' 它只是把相近记忆放进同一个浏览抽屉；不等于事实、主张或因果关系。'),
        h('div', {className: 'eh-topic-legend-items'},
          h('span', {className: 'eh-legend-item eh-legend-decision'}, '● 决策闭环：有显式 Decision 链'),
          h('span', {className: 'eh-legend-item eh-legend-suggested'}, '◌ 待确认分组：算法建议，需你确认'),
          h('span', {className: 'eh-legend-item eh-legend-active'}, '● 已确认主题：人工确认'),
          h('span', {className: 'eh-legend-item eh-legend-inbox'}, '□ 待归类：不硬凑主题')
        )
      ) : null,
      h('div', {className: 'eh-graph-lenses'},
        [['global', '全局'], ['focus', '焦点'], ['conflict', '冲突']].map(function (item) {
          return h('button', {key: item[0], className: 'eh-graph-lens' + (lens === item[0] ? ' eh-graph-lens-active' : ''), onClick: function () { setLens(item[0]); }}, item[1]);
        })
      ),
      h('div', {className: 'eh-graph-caption'}, caption),
      props.topicData ? h('div', {className: 'eh-graph-caption'}, lens === 'global' ? '主题总览：位置仅用于浏览，不代表因果、时间或语义距离；虚线星为待确认建议。' : lens === 'focus' ? '这是所选主题的显式关系与上下文。' : '这里只显示已有 Decision 反馈冲突的主题，不推断语义主题冲突。') : null,
      h(StarMapPanel, {data: selectedData, lens: lens, onReview: props.onReview, onSelect: function (node) { if (node && (node.kind === 'topic' || node.kind === 'suggested_topic' || node.kind === 'decision_topic')) { setSelectedTopicId(node.id); setLens('focus'); } else if (props.onObjectSelect) { props.onObjectSelect(node); } }}),
      lens === 'focus' && selectedTopic && String(selectedTopic.id).indexOf('decision:') === 0 ? h(RelationshipMapPanel, {data: props.detailData}) : null
    );
  }

  function StarMapPanel(props) {
    var data = props.data;
    var canvasRef = hooks.useRef(null);
    var _selected = hooks.useState(null), selected = _selected[0], setSelected = _selected[1];
    if (!data) return h('div', {className: 'eh-feed-loading'}, '正在绘制认知星图…');
    if (data.error) return h('div', {className: 'eh-feed-error'}, '星图加载失败：' + data.error);
    var nodes = data.nodes || [];
    var edges = data.edges || [];
    var layout = {
      evidence: [0.20, 0.55], claim: [0.39, 0.55], model: [0.43, 0.23], proposal: [0.44, 0.82],
      decision: [0.61, 0.55], intent: [0.83, 0.30], outcome: [0.83, 0.76]
    };
    var color = {evidence: [0.54, 0.71, 0.9, 1], claim: [0.56, 0.79, 0.64, 1], model: [0.9, 0.78, 0.46, 1], proposal: [0.72, 0.59, 0.88, 1], decision: [0.96, 0.65, 0.56, 1], intent: [0.49, 0.83, 0.85, 1], outcome: [0.49, 0.83, 0.85, 1]};
    hooks.useEffect(function () {
      var canvas = canvasRef.current;
      if (!canvas) return undefined;
      var gl = canvas.getContext('webgl', {antialias: true, alpha: true});
      if (!gl) return undefined;
      var dpr = window.devicePixelRatio || 1;
      var width = canvas.clientWidth || 900, height = 420;
      canvas.width = width * dpr; canvas.height = height * dpr;
      gl.viewport(0, 0, canvas.width, canvas.height);
      var vertex = 'attribute vec2 p; attribute float s; attribute vec4 c; varying vec4 v; void main(){gl_Position=vec4(p,0.,1.);gl_PointSize=s;v=c;}';
      var fragment = 'precision mediump float; varying vec4 v; void main(){vec2 d=gl_PointCoord-vec2(.5);if(dot(d,d)>.25)discard;gl_FragColor=v;}';
      var lineVertex = 'attribute vec2 p; void main(){gl_Position=vec4(p,0.,1.);}';
      var lineFragment = 'precision mediump float; uniform vec4 c; void main(){gl_FragColor=c;}';
      function program(v, f) { var vs=gl.createShader(gl.VERTEX_SHADER), fs=gl.createShader(gl.FRAGMENT_SHADER), p=gl.createProgram(); gl.shaderSource(vs,v);gl.compileShader(vs);gl.shaderSource(fs,f);gl.compileShader(fs);gl.attachShader(p,vs);gl.attachShader(p,fs);gl.linkProgram(p);return p; }
      var pointProgram = program(vertex, fragment), lineProgram = program(lineVertex, lineFragment);
      var positions = {};
      nodes.forEach(function (node, index) { positions[node.id] = node.position || layout[node.kind] || [0.5 + ((index % 3) - 1) * 0.26, 0.5 + (Math.floor(index / 3) - 0.5) * 0.34]; });
      function clip(pos) { return [pos[0] * 2 - 1, 1 - pos[1] * 2]; }
      gl.clearColor(0.04, 0.12, 0.10, 1); gl.clear(gl.COLOR_BUFFER_BIT);
      var starData=[];
      for (var starIndex=0; starIndex<84; starIndex++) { var sx=((starIndex*47)%101)/50-1, sy=((starIndex*71)%97)/48-1, ss=1+(starIndex%3)*0.55; starData=starData.concat([sx,sy,ss,0.20,0.47,0.42,0.7]); }
      gl.useProgram(pointProgram); var starBuffer=gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER,starBuffer); gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(starData),gl.STATIC_DRAW); var starStride=7*4, starPA=gl.getAttribLocation(pointProgram,'p'), starSA=gl.getAttribLocation(pointProgram,'s'), starCA=gl.getAttribLocation(pointProgram,'c'); gl.enableVertexAttribArray(starPA);gl.vertexAttribPointer(starPA,2,gl.FLOAT,false,starStride,0);gl.enableVertexAttribArray(starSA);gl.vertexAttribPointer(starSA,1,gl.FLOAT,false,starStride,8);gl.enableVertexAttribArray(starCA);gl.vertexAttribPointer(starCA,4,gl.FLOAT,false,starStride,12);gl.drawArrays(gl.POINTS,0,starData.length/7);
      var edgeData = [];
      edges.forEach(function (edge) { if (positions[edge.from] && positions[edge.to]) { edgeData = edgeData.concat(clip(positions[edge.from]), clip(positions[edge.to])); } });
      gl.useProgram(lineProgram); gl.uniform4f(gl.getUniformLocation(lineProgram, 'c'), 0.36, 0.53, 0.47, 0.72);
      var lineBuffer=gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER,lineBuffer); gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(edgeData),gl.STATIC_DRAW); var lineAttr=gl.getAttribLocation(lineProgram,'p'); gl.enableVertexAttribArray(lineAttr); gl.vertexAttribPointer(lineAttr,2,gl.FLOAT,false,0,0); gl.drawArrays(gl.LINES,0,edgeData.length/2);
      var nodeData=[];
      nodes.forEach(function (node) { var p=clip(positions[node.id]), c=node.kind === 'decision_topic' ? [0.96,0.65,0.56,1] : node.kind === 'suggested_topic' ? [0.48,0.70,0.68,0.72] : node.kind === 'topic' ? [0.94,0.68,0.38,1] : node.kind === 'inbox' ? [0.47,0.56,0.67,1] : color[node.kind]||[0.4,0.8,0.9,1], size=24+Math.min(34,Math.log((node.count||0)+1)*5); nodeData=nodeData.concat(p,size,c); });
      gl.useProgram(pointProgram); var buffer=gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER,buffer); gl.bufferData(gl.ARRAY_BUFFER,new Float32Array(nodeData),gl.STATIC_DRAW); var stride=7*4, pa=gl.getAttribLocation(pointProgram,'p'), sa=gl.getAttribLocation(pointProgram,'s'), ca=gl.getAttribLocation(pointProgram,'c'); gl.enableVertexAttribArray(pa);gl.vertexAttribPointer(pa,2,gl.FLOAT,false,stride,0);gl.enableVertexAttribArray(sa);gl.vertexAttribPointer(sa,1,gl.FLOAT,false,stride,8);gl.enableVertexAttribArray(ca);gl.vertexAttribPointer(ca,4,gl.FLOAT,false,stride,12);gl.drawArrays(gl.POINTS,0,nodes.length);
      canvas.onclick = function (event) { var r=canvas.getBoundingClientRect(), x=(event.clientX-r.left)/r.width, y=(event.clientY-r.top)/r.height, nearest=null, distance=Infinity; nodes.forEach(function(node){var q=positions[node.id], d=Math.pow(q[0]-x,2)+Math.pow(q[1]-y,2);if(d<distance){distance=d;nearest=node;}}); if(nearest && distance<0.015) { setSelected(nearest); if (props.onSelect) props.onSelect(nearest); } };
      return function () { canvas.onclick=null; gl.deleteProgram(pointProgram); gl.deleteProgram(lineProgram); };
    }, [data]);
    var isConflict = props.lens === 'conflict';
    return h('div', {className: 'eh-star-panel'},
      h('div', {className: 'eh-feed-header'}, '认知星图'),
      h('div', {className: 'eh-relation-caption'}, '每颗星代表一类已保存内容；星的大小代表数量，线只代表明确记录的关系。点击星团查看分类。'),
      h('div', {className: 'eh-star-wrap'}, h('canvas', {ref: canvasRef, className: 'eh-star-canvas', 'aria-label': '认知分类关系星图'}),
        h('div', {className: 'eh-star-labels'}, nodes.map(function(node,index){var p=node.position||layout[node.kind]||[.5+((index%3)-1)*.26,.5+(Math.floor(index/3)-.5)*.34];return h('button',{key:node.id,title:node.label,className:'eh-star-label eh-star-label-'+node.kind,style:{left:(p[0]*100)+'%',top:(p[1]*100)+'%'},onClick:function(){setSelected(node);if(props.onSelect)props.onSelect(node);}},h('span',{className:'eh-star-label-text'},node.label),node.count != null ? h('span',{className:'eh-star-count'},node.count) : null);}))
      ),
      h('div', {className: 'eh-relation-summary'}, edges.map(function(edge,i){return h('span',{key:i,className:'eh-edge-chip'},edge.label); })),
      selected ? h('div', {className: 'eh-relation-selected'},
        h('b', null, selected.label), selected.count != null ? '：当前保存 ' + selected.count + ' 条。' : '：' + (selected.status === 'contradicts' ? '这条结果与原判断冲突。' : '点击关系可追溯它和其他对象的联系。'),
        selected.status === 'contradicts' ? h('button', {className: 'eh-action-button', onClick: props.onReview}, '去处理这个冲突') : null
      ) : isConflict ? h('div', {className: 'eh-relation-selected'}, '点击右侧的“结果”节点，查看它正在挑战哪项判断。') : null
    );
  }

  function RelationshipMapPanel(props) {
    var data = props.data;
    var _sel = hooks.useState(null), selected = _sel[0], setSelected = _sel[1];
    if (!data) return h('div', {className: 'eh-feed-loading'}, '正在读取认知关系…');
    if (data.error) return h('div', {className: 'eh-feed-error'}, '关系视图加载失败：' + data.error);
    var nodes = data.nodes || [];
    var edges = data.edges || [];
    if (!nodes.length) return h('div', {className: 'eh-feed-empty'}, '还没有可展示的关系。先记录证据，再建立主张或决策。');
    var lanes = {evidence: 110, claim: 330, model: 550, proposal: 720, decision: 880, intent: 1080, outcome: 1080};
    var laneTitles = {evidence: '证据', claim: '主张', model: '模型', proposal: '待审提案', decision: '决策', intent: '行动', outcome: '结果'};
    var counts = {};
    nodes.forEach(function (node) { counts[node.kind] = (counts[node.kind] || 0) + 1; });
    var counters = {};
    var positions = {};
    nodes.forEach(function (node) {
      var kind = node.kind || 'claim';
      var index = counters[kind] || 0;
      counters[kind] = index + 1;
      positions[node.id] = {x: lanes[kind] || 350, y: 120 + index * 104};
    });
    var height = Math.max(360, Math.max.apply(null, Object.keys(positions).map(function (id) { return positions[id].y + 80; })));
    function short(text) { return String(text || '').length > 22 ? String(text).slice(0, 21) + '…' : String(text || ''); }
    function edgeElement(edge, index) {
      var from = positions[edge.from], to = positions[edge.to];
      if (!from || !to) return null;
      var mx = (from.x + to.x) / 2;
      return h('g', {key: 'edge-' + index},
        h('path', {d: 'M' + (from.x + 70) + ',' + from.y + ' C' + mx + ',' + from.y + ' ' + mx + ',' + to.y + ' ' + (to.x - 70) + ',' + to.y, className: 'eh-rel-edge', markerEnd: 'url(#eh-rel-arrow)'}),
        h('text', {x: mx, y: (from.y + to.y) / 2 - 7, className: 'eh-rel-edge-label'}, edge.label)
      );
    }
    function nodeElement(node) {
      var p = positions[node.id], chosen = selected && selected.id === node.id;
      return h('g', {key: node.id, className: 'eh-rel-node' + (chosen ? ' eh-rel-node-selected' : ''), onClick: function () { setSelected(node); }},
        h('title', null, node.label),
        h('rect', {x: p.x - 70, y: p.y - 27, width: 140, height: 54, rx: 8, className: 'eh-rel-node-box eh-rel-' + node.kind}),
        h('text', {x: p.x, y: p.y - 5, textAnchor: 'middle', className: 'eh-rel-node-kind'}, laneTitles[node.kind] || node.kind),
        h('text', {x: p.x, y: p.y + 14, textAnchor: 'middle', className: 'eh-rel-node-label'}, short(node.label + (node.count != null ? ' · ' + node.count : '')))
      );
    }
    return h('div', {className: 'eh-relation-panel'},
      h('div', {className: 'eh-feed-header'}, '你现在存了什么，彼此怎样关联'),
      h('div', {className: 'eh-relation-caption'}, '数字代表已保存的数量；连线只代表账本中明确记录的关系，不显示系统猜测出来的关联。'),
      h('div', {className: 'eh-relation-summary'}, nodes.map(function (node) { return h('span', {key: node.id, className: 'eh-edge-chip'}, node.label + ' ' + (node.count || 0)); }), h('span', {className: 'eh-edge-chip'}, '关系 ' + edges.length)),
      h(Collapsible, {title: '分类关系图', count: edges.length, defaultOpen: true},
        h('div', {className: 'eh-relation-canvas'},
          h('svg', {viewBox: '0 0 1200 ' + height, role: 'img', 'aria-label': '认知关系图'},
            h('defs', null, h('marker', {id: 'eh-rel-arrow', markerWidth: 7, markerHeight: 7, refX: 6, refY: 3, orient: 'auto'}, h('path', {d: 'M0,0 L7,3 L0,6 z', className: 'eh-rel-arrow'}))),
            Object.keys(lanes).filter(function (kind) { return counters[kind]; }).map(function (kind) { return h('text', {key: kind, x: lanes[kind], y: 42, textAnchor: 'middle', className: 'eh-rel-lane-title'}, laneTitles[kind]); }),
            edges.map(edgeElement), nodes.map(nodeElement)
          )
        ),
        selected ? h('div', {className: 'eh-relation-selected'}, h('b', null, laneTitles[selected.kind] || selected.kind), '：' + selected.label, selected.status ? h('span', null, ' · ' + selected.status) : null) : null
      )
    );
  }

  function ReviewQueuePanel(props) {
    var title = props.title;
    var items = props.items || [];
    var render = props.render;
    return h('div', {className: 'eh-review-queue'},
      h('div', {className: 'eh-review-queue-title'}, title, h('span', {className: 'eh-collapsible-count'}, items.length)),
      items.length === 0 ? h('div', {className: 'eh-feed-empty'}, '暂无待审查项') : items.slice(0, 8).map(function (item) { return render(item); })
    );
  }

  function CorrectionDesk(props) {
    var _reason = hooks.useState(''), reason = _reason[0], setReason = _reason[1];
    var _notice = hooks.useState(''), notice = _notice[0], setNotice = _notice[1];
    var items = props.selectedObject && (props.selectedObject.kind === 'claim' || props.selectedObject.kind === 'evidence') ? [props.selectedObject] : [];
    function correct(node, action) {
      if (!reason.trim()) { setNotice('先写一句为什么要这样改；这会保留在时间链里。'); return; }
      authFetch(BASE + '/api/corrections', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({object_type: node.kind, object_id: node.id, action: action, reason: reason})})
        .then(function (r) { return r.json().then(function (data) { if (!r.ok) throw new Error(data.detail || '保存失败'); return data; }); })
        .then(function () { setNotice('已保存，正在刷新关系图与审查状态…'); setReason(''); window.setTimeout(function () { window.location.reload(); }, 450); })
        .catch(function (error) { setNotice(error.message || '保存失败'); });
    }
    return h('div', {className: 'eh-action-primary'},
      h('div', {className: 'eh-action-eyebrow'}, '发现问题时，直接在这里修'),
      h('div', {className: 'eh-action-next'}, items.length ? '正在修订你刚才选中的对象。说明原因后标为错误、过期或已核实；旧记录会保留。' : '先在主题详情中点选一条判断或来源，再在这里修订；不会删除旧记录。'),
      items.length ? h('textarea', {className: 'eh-correction-reason', value: reason, placeholder: '修订原因，例如：这条消息后来被官方公告否定', onChange: function (e) { setReason(e.target.value); }}) : null,
      h('div', {className: 'eh-correction-list'}, items.slice(0, 8).map(function (node) { return h('div', {key: node.id, className: 'eh-review-card'},
        h('div', {className: 'eh-review-card-text'}, node.label),
        h('div', {className: 'eh-review-actions'},
          h('button', {className: 'eh-action-button', onClick: function () { correct(node, 'wrong'); }}, '标为错误'),
          h('button', {className: 'eh-action-button', onClick: function () { correct(node, 'outdated'); }}, '标为过期'),
          h('button', {className: 'eh-action-button', onClick: function () { correct(node, 'verify'); }}, '确认有效')
        )
      ); })),
      notice ? h('div', {className: 'eh-action-next'}, notice) : null
    );
  }

  function ActionReviewPanel(props) {
    var data = props.data;
    var _choice = hooks.useState(null), choice = _choice[0], setChoice = _choice[1];
    if (!data) return h('div', {className: 'eh-feed-loading'}, '正在整理下一步…');
    if (data.error) return h('div', {className: 'eh-feed-error'}, '审查数据加载失败：' + data.error);
    var q = data.queues || {}, s = data.summary || {};
    var contradiction = (q.outcomes || []).filter(function (item) { return item.implication === 'contradicts'; })[0];
    var overdue = (q.decisions || []).filter(function (item) { return item.review_state === 'overdue'; })[0];
    var primary = contradiction ? {kind: '结果与原判断冲突', title: '复盘这条现实反馈', detail: contradiction.observation, next: '判断它只是暂时噪音，还是足以修订支撑这项决策的主张或模型。'} : overdue ? {kind: '决策该复盘了', title: '复盘这项决策', detail: overdue.question, next: '记录发生了什么，再决定保留、修订或关闭原来的判断。'} : null;
    return h('div', {className: 'eh-action-review'},
      h('div', {className: 'eh-action-kicker'}, '审查队列'),
      primary
        ? h('div', {className: 'eh-action-primary'},
            h('div', {className: 'eh-action-eyebrow'}, '现在先做这一件事'),
            h('div', {className: 'eh-action-title'}, primary.title),
            h('div', {className: 'eh-action-detail'}, primary.detail),
            h('div', {className: 'eh-action-next'}, '你要做的选择：' + primary.next),
            h('button', {className: 'eh-action-button', onClick: function () { setChoice(choice ? null : primary); }}, choice ? '收起原因' : '为什么需要处理？')
          )
        : h('div', {className: 'eh-action-clear'},
            h('div', {className: 'eh-action-eyebrow'}, '当前没有紧急复盘'),
            h('div', {className: 'eh-action-title'}, '今天不用修订任何判断'),
            h('div', {className: 'eh-action-detail'}, '证据、反证条件和决策复盘目前没有直接阻塞项。')
          ),
      choice ? h('div', {className: 'eh-action-reason'}, '它被标记为“结果与原判断冲突”。先确认这条结果对应的条件是否仍然成立，再决定是否改写主张或模型。') : null,
      h(CorrectionDesk, {topicMap: props.topicMap, selectedObject: props.selectedObject}),
      h('div', {className: 'eh-action-later'},
        h('span', null, '稍后处理：待审提案 ' + (s.pending_proposals || 0) + ' · 健康检查 ' + (s.pending_issues || 0) + ' · 过期行动 ' + (s.expired_intents || 0))
      ),
      h(Collapsible, {title: '我不确定时，再查看证据与历史', defaultOpen: false}, h(ReviewPanel, {data: data}))
    );
  }

  function ReviewPanel(props) {
    var data = props.data;
    if (!data) return h('div', {className: 'eh-feed-loading'}, '正在读取 Cognitive OS 审查队列…');
    if (data.error) return h('div', {className: 'eh-feed-error'}, '审查数据加载失败：' + data.error);
    var s = data.summary || {}, q = data.queues || {};
    var concerns = (s.unbacked_claims || 0) + (s.unfalsifiable_claims || 0) + (s.overdue_decisions || 0) + (s.expired_intents || 0) + (s.contradictions || 0) + (s.weak_models || 0) + (s.pending_issues || 0);
    return h('div', {className: 'eh-review'},
      h('div', {className: 'eh-review-hero'}, h('div', null, h('div', {className: 'eh-feed-header'}, 'Cognitive OS 审查台'), h('div', {className: 'eh-review-caption'}, '只读审查：证据不等于真相；每条主张、决策与结果都应可追溯、可证伪、可复盘。')), h('div', {className: concerns ? 'eh-review-status eh-review-status-warn' : 'eh-review-status eh-review-status-ok'}, concerns ? concerns + ' 个待关注项' : '账本当前无待关注项')),
      h('div', {className: 'eh-metric-grid eh-review-metrics'}, h(MetricTile, {label: 'Evidence', value: s.evidence || 0}), h(MetricTile, {label: 'Claims', value: s.claims || 0}), h(MetricTile, {label: 'Decisions', value: s.decisions || 0}), h(MetricTile, {label: 'Outcomes', value: s.outcomes || 0}), h(MetricTile, {label: '无证据主张', value: s.unbacked_claims || 0}), h(MetricTile, {label: '缺失证伪条件', value: s.unfalsifiable_claims || 0}), h(MetricTile, {label: '逾期决策复盘', value: s.overdue_decisions || 0}), h(MetricTile, {label: '矛盾结果', value: s.contradictions || 0}), h(MetricTile, {label: '支持不足模型', value: s.weak_models || 0}), h(MetricTile, {label: '待处理提案', value: s.pending_proposals || 0})),
      h('div', {className: 'eh-review-grid'},
        h(ReviewQueuePanel, {title: '决策复盘队列', items: q.decisions, render: function (item) { return h('div', {key: item.id, className: 'eh-review-item'}, h('div', {className: 'eh-feed-meta'}, h('span', {className: 'eh-feed-badge ' + (item.review_state === 'overdue' ? 'eh-review-badge-warn' : '')}, item.review_state === 'overdue' ? '逾期复盘' : '已排期'), h('span', {className: 'eh-feed-time'}, item.review_at || '未设置复盘时间')), h('div', {className: 'eh-feed-summary'}, item.question), h('div', {className: 'eh-review-meta'}, '选择：' + (item.selected_option || '—') + ' · 关联主张 ' + (item.claim_count || 0) + ' · 结果 ' + (item.outcome_count || 0) + ' · 矛盾 ' + (item.contradiction_count || 0)), item.core_bet ? h('div', {className: 'eh-review-detail'}, '核心押注：' + item.core_bet) : null); }}),
        h(ReviewQueuePanel, {title: '主张证据链', items: q.claims, render: function (item) { var weak = !item.evidence_count || !item.falsifier; return h('div', {key: item.id, className: 'eh-review-item'}, h('div', {className: 'eh-feed-meta'}, h('span', {className: 'eh-feed-badge ' + (weak ? 'eh-review-badge-warn' : '')}, item.status || 'proposed'), h('span', {className: 'eh-feed-badge'}, item.kind || 'claim')), h('div', {className: 'eh-feed-summary'}, item.statement), h('div', {className: 'eh-review-meta'}, '证据 ' + (item.evidence_count || 0) + ' · 独立来源 ' + (item.source_count || 0)), h('div', {className: 'eh-review-detail'}, '证伪条件：' + (item.falsifier || '缺失')), item.source_refs ? h('div', {className: 'eh-review-detail'}, '来源：' + item.source_refs) : null); }})
      ),
      h('div', {className: 'eh-review-grid'},
        h(ReviewQueuePanel, {title: '模型准入检查', items: q.models, render: function (item) { var weak = item.admission_state !== 'ready'; return h('div', {key: item.id, className: 'eh-review-item'}, h('div', {className: 'eh-feed-meta'}, h('span', {className: 'eh-feed-badge ' + (weak ? 'eh-review-badge-warn' : '')}, weak ? '支持不足' : '可准入')), h('div', {className: 'eh-feed-summary'}, item.proposition), h('div', {className: 'eh-review-meta'}, '支持主张 ' + (item.support_claim_count || 0) + ' · 独立证据来源 ' + (item.support_source_count || 0))); }}),
        h(ReviewQueuePanel, {title: '维护队列', items: (q.issues || []).concat(q.proposals || []), render: function (item) { var detail = item.detail_json || item.rationale || item.suggested_action || ''; return h('div', {key: item.id, className: 'eh-review-item'}, h('div', {className: 'eh-feed-meta'}, h('span', {className: 'eh-feed-badge eh-review-badge-warn'}, item.severity || item.kind || 'pending')), h('div', {className: 'eh-feed-summary'}, item.suggested_action || item.kind || '维护项'), h('div', {className: 'eh-review-detail'}, String(detail).slice(0, 220))); }})
      ),
      h('div', {className: 'eh-review-grid'},
        h(ReviewQueuePanel, {title: '现实反馈 / Outcome', items: q.outcomes, render: function (item) { var contradicted = item.implication === 'contradicts'; return h('div', {key: item.id, className: 'eh-review-item'}, h('div', {className: 'eh-feed-meta'}, h('span', {className: 'eh-feed-badge ' + (contradicted ? 'eh-review-badge-warn' : '')}, item.implication || 'inconclusive'), h('span', {className: 'eh-feed-time'}, item.observed_at || '')), h('div', {className: 'eh-feed-summary'}, item.observation), h('div', {className: 'eh-review-detail'}, '关联决策：' + (item.decision_id || '—'))); }}),
        h(ReviewQueuePanel, {title: '执行承诺 / Intent', items: q.intents, render: function (item) { var expired = item.expiry_state === 'expired'; return h('div', {key: item.id, className: 'eh-review-item'}, h('div', {className: 'eh-feed-meta'}, h('span', {className: 'eh-feed-badge ' + (expired ? 'eh-review-badge-warn' : '')}, expired ? '已过期' : (item.status || 'active')), h('span', {className: 'eh-feed-time'}, item.valid_until || '')), h('div', {className: 'eh-feed-summary'}, item.action), h('div', {className: 'eh-review-detail'}, '触发：' + (item.trigger_kind || '—') + ' / ' + (item.trigger_value || '—'))); }})
      ),
      h('div', {className: 'eh-review-footer'}, '数据源：' + (data.source || 'Cognitive OS Ledger') + ' · 截止 ' + (data.as_of || '—') + ' · 本页面不写入、不接受提案、不自动修正账本。')
    );
  }

  function SelfImprovementPanel(props) {
    var data = props.data;
    if (!data) return h('div', {className: 'eh-feed-loading'}, '加载中…');
    if (data.error) return h('div', {className: 'eh-feed-error'}, '加载失败');
    var memoryUpdates = data.memory_updates || {};
    var recentSkills = data.recent_skills || [];
    var recentToolCalls = data.recent_tool_calls || [];
    var memNames = Object.keys(memoryUpdates);
    return h('div', {className: 'eh-feed-panel eh-feed-panel-wide'},
      h('div', {className: 'eh-feed-header'}, 'Self-Improvement 嗅探'),
      h('div', {className: 'eh-si-grid'},
        h('div', {className: 'eh-si-section'},
          h('div', {className: 'eh-si-title'}, '本地记忆文件'),
          memNames.length === 0
            ? h('div', {className: 'eh-feed-empty'}, '暂无更新')
            : memNames.map(function (name) {
                return h('div', {key: name, className: 'eh-si-row'},
                  h('span', null, name),
                  h('span', {className: 'eh-feed-time'}, formatRelativeTime(memoryUpdates[name]))
                );
              })
        ),
        h('div', {className: 'eh-si-section'},
          h('div', {className: 'eh-si-title'}, '最近技能'),
          recentSkills.length === 0
            ? h('div', {className: 'eh-feed-empty'}, '暂无新建/修改')
            : recentSkills.map(function (s, i) {
                return h('div', {key: i, className: 'eh-si-row'},
                  h('span', null, s.name),
                  h('span', {className: 'eh-feed-time'}, formatRelativeTime(s.modified))
                );
              })
        ),
        h('div', {className: 'eh-si-section eh-si-section-wide'},
          h('div', {className: 'eh-si-title'}, '最近记忆/技能工具调用'),
          recentToolCalls.length === 0
            ? h('div', {className: 'eh-feed-empty'}, '暂无记录')
            : recentToolCalls.map(function (t, i) {
                return h('div', {key: i, className: 'eh-si-row'},
                  h('span', {className: 'eh-si-row-text'},
                    h('span', {className: 'eh-feed-badge'}, t.tool + '.' + t.action),
                    ' ',
                    t.summary
                  ),
                  h('span', {className: 'eh-feed-time'}, formatRelativeTime(t.time))
                );
              })
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
    var _mem = hooks.useState(null), memoryFeed = _mem[0], setMemoryFeed = _mem[1];
    var _pre = hooks.useState(null), prefetchFeed = _pre[0], setPrefetchFeed = _pre[1];
    var _si = hooks.useState(null), selfImprovement = _si[0], setSelfImprovement = _si[1];
    var _cq = hooks.useState(null), cognitiveQuality = _cq[0], setCognitiveQuality = _cq[1];
    var _dw = hooks.useState(null), decisionWorkspace = _dw[0], setDecisionWorkspace = _dw[1];
    var _rv = hooks.useState(null), review = _rv[0], setReview = _rv[1];
    var _rm = hooks.useState(null), relationshipMap = _rm[0], setRelationshipMap = _rm[1];
    var _tm = hooks.useState(null), topicMap = _tm[0], setTopicMap = _tm[1];
    var _so = hooks.useState(null), selectedObject = _so[0], setSelectedObject = _so[1];
    var _dm = hooks.useState(null), detailMap = _dm[0], setDetailMap = _dm[1];
    var _tab = hooks.useState(0), activeTab = _tab[0], setActiveTab = _tab[1];
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
        authFetch(BASE + '/api/agent-loop').then(function (r) { return r.json(); }).catch(function () { return null; }),
        authFetch(BASE + '/api/memory-feed').then(function (r) { return r.json(); }).catch(function () { return {recent: [], layers: [], error: 'fetch failed'}; }),
        authFetch(BASE + '/api/prefetch-feed').then(function (r) { return r.json(); }).catch(function () { return {recent: [], stats: {}, error: 'fetch failed'}; }),
        authFetch(BASE + '/api/self-improvement').then(function (r) { return r.json(); }).catch(function () { return {memory_updates: {}, recent_skills: [], recent_tool_calls: [], error: 'fetch failed'}; }),
        authFetch(BASE + '/api/cognitive-quality').then(function (r) { return r.json(); }).catch(function () { return {latest: {}, reports: [], health: {}, recent_ops: [], error: 'fetch failed'}; }),
        authFetch(BASE + '/api/decision-workspace').then(function (r) { return r.json(); }).catch(function () { return {error: 'fetch failed'}; }),
        authFetch(BASE + '/api/review').then(function (r) { return r.json(); }).catch(function () { return {error: 'fetch failed'}; }),
        authFetch(BASE + '/api/topic-map').then(function (r) { return r.json(); }).catch(function () { return {error: 'fetch failed'}; }),
        authFetch(BASE + '/api/relationship-map').then(function (r) { return r.json(); }).catch(function () { return {error: 'fetch failed'}; })
      ]).then(function (results) {
        setArch(results[0]);
        setHealth(results[1]);
        setAgentLoop(results[2]);
        setMemoryFeed(results[3]);
        setPrefetchFeed(results[4]);
        setSelfImprovement(results[5]);
        setCognitiveQuality(results[6]);
        setDecisionWorkspace(results[7]);
        setReview(results[8]);
        setTopicMap(results[9]);
        setDetailMap(results[10]);
      });
      var onResize = function () { fitToScreen(); };
      window.addEventListener('resize', onResize);
      return function () { window.removeEventListener('resize', onResize); };
    }, []);

    hooks.useEffect(function () {
      if (activeTab === 2) fitToScreen();
    }, [activeTab]);

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
      setDetail({name: n.label || name, desc: n.desc || '', src: safeSrc, path: path, loc: loc || n.loc || '', code: null, loading: false, showCode: false});
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

    var TABS = ['架构图', '运行态', '决策工作台'];
    var tabChildren = [];
    TABS = ['认知概览', '复盘与修订', '系统蓝图'];
    if (activeTab === 2) {
      tabChildren.push(
        h('div', {ref: canvasRef, key: 'canvas', className: 'eh-canvas', onMouseDown: onMouseDown, onMouseMove: onMouseMove, onMouseUp: onMouseUp, onMouseLeave: onMouseLeave}, canvasChildren)
      );
      tabChildren.push(h(GlossaryPanel, {key: 'glossary', open: glossaryOpen, onToggle: function () { setGlossaryOpen(!glossaryOpen); }}));
    } else if (activeTab === 0) {
      tabChildren.push(
        h('div', {className: 'eh-feeds', key: 'feeds'},
          h(OverallStatusPanel, {health: health, review: review, map: relationshipMap}),
          h(GraphHubPanel, {key: 'star-map', globalData: relationshipMap, detailData: detailMap, topicData: topicMap, onReview: function () { setActiveTab(1); }, onObjectSelect: setSelectedObject}),
          h(TimelinePanel, {key: 'event-timeline', events: topicMap && topicMap.recent_events}),
          h(PrefetchFeedPanel, {key: 'recall-observability', data: prefetchFeed}),
          h(Collapsible, {title: '展开运行细节', defaultOpen: false},
            h('div', {className: 'eh-feeds-grid'},
              h('div', {className: 'eh-feeds-col'},
                h('div', {className: 'eh-graph-caption'}, 'Legacy / HY 诊断：仅用于旧系统排障，不参与 Cognitive OS Ledger 健康判断。'),
                h(CognitiveQualityPanel, {data: cognitiveQuality})
              ),
              h('div', {className: 'eh-feeds-col'}, h(CognitiveHealthPanel, {data: cognitiveQuality}))
            ),
            h('div', {className: 'eh-feeds-grid'},
              h('div', {className: 'eh-feeds-col'}, h(MemoryFeedPanel, {data: memoryFeed})),
              h('div', {className: 'eh-feeds-col'}, h(SelfImprovementPanel, {data: selfImprovement}))
            ),
          )
        )
      );
    } else {
      tabChildren.push(h(ActionReviewPanel, {key: 'review', data: review, topicMap: topicMap, selectedObject: selectedObject}));
    }

    return h('div', {className: 'eh-page'},
      h('div', {className: 'eh-announcer', 'aria-live': 'polite', 'aria-atomic': 'true'}, health ? ('服务' + (isOk ? '正常' : '异常') + ' · 账本 ' + (srv.vdb_points || '?')) : ''),
      // Header
      h('div', {className: 'eh-header'},
        h('div', {className: 'eh-kicker'}, 'Hermes Evolution Hub'),
        h('div', {className: 'eh-title'}, '进化中枢'),
        h('div', {className: 'eh-subtitle'},
          'Hermes 架构图、Cognitive OS 决策账本与系统健康状态的可视化面板。点击模块查看源码路径与连接关系。')
      ),
      // Controls
      h('div', {className: 'eh-controls'},
        h('div', {className: 'eh-status'},
          h('span', {className: 'eh-pill'},
            h('span', {className: 'eh-dot', style: {background: isOk ? '#4ade80' : '#ef4444', boxShadow: isOk ? '0 0 8px #4ade80' : '0 0 8px #ef4444'}}),
            '服务: ', h('b', null, health ? (isOk ? '正常' : '异常') : '检测中')
          ),
          h('span', {className: 'eh-pill'}, '账本: ', h('b', null, srv.vdb_points || '?')),
          h('span', {className: 'eh-pill'}, 'API: ', h('b', null, agentLoop ? agentLoop.total_api : '?'))
        ),
        h('div', {className: 'eh-tabs'},
          TABS.map(function (name, i) {
            return h('button', {
              key: 'tab-' + i,
              className: 'eh-tab' + (activeTab === i ? ' eh-tab-active' : ''),
              onClick: function () { setActiveTab(i); }
            }, name);
          })
        )
      ),
      // Tab content
      h('div', {className: 'eh-tab-content'}, tabChildren)
    );
  }

  window.__HERMES_PLUGINS__.register('hermes-evolution-hub', EvolutionHubPage);
})();
