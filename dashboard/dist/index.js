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

      {name: 'Retrieval', x: 1500, y: 500, w: 100, h: 220, color: '#8ab4e6'},
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
      } else if (c[0] === 'Agent Init' && c[1] === '记忆文件') {
        // Agent Init -> local memory file: up to top corridor, across to Storage, then down
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
      } else if (c[0] === 'MemAgent' && ['L2_FACT', 'L3_SUMMARY', 'L4_IDENTITY'].indexOf(c[1]) >= 0) {
        // MemAgent -> L2/L3/L4: shared horizontal below MemAgent, then fan out
        x1 = a.x;
        y1 = a.y + 17;
        x2 = b.x;
        y2 = b.y - 17;
        var fanY = 500;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + fanY + ' L' + x2 + ',' + fanY + ' L' + x2 + ',' + y2;
      } else if (c[0] === '记忆检索' && c[1] === 'Embed Service') {
        // 记忆检索 -> Embed Service: up to Embed Service height, then right into retrieval cluster
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + y2 + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'System 1 Writer' && c[1] === 'L1_RAW') {
        // S1 -> L1_RAW: drop down then right to avoid System 2 Writer
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
      } else if (c[0] === '记忆预取' && c[1] === 'Embed Service') {
        // 记忆预取 -> Embed Service: auto recall goes through the retrieval path
        x1 = a.x + 65;
        y1 = a.y;
        x2 = b.x - 65;
        y2 = b.y;
        var prefetchEmbedCorridorX = 1100;
        d = 'M' + x1 + ',' + y1 + ' L' + prefetchEmbedCorridorX + ',' + y1 + ' L' + prefetchEmbedCorridorX + ',' + y2 + ' L' + x2 + ',' + y2;
      } else if (c[0] === 'Vector DB' && c[1] === 'System 2 Writer') {
        // Vector DB -> System 2 Writer: read existing memories for async schema/intention induction
        x1 = a.x;
        y1 = a.y - 17;
        x2 = b.x + 65;
        y2 = b.y;
        var system2ReadCorridorY = 260;
        d = 'M' + x1 + ',' + y1 + ' L' + x1 + ',' + system2ReadCorridorY + ' L' + x2 + ',' + system2ReadCorridorY + ' L' + x2 + ',' + y2;
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
