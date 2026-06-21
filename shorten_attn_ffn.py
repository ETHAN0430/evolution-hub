import json
p = 'dashboard/dist/architecture.json'
with open(p, encoding='utf-8') as f:
    data = json.load(f)

data['NODES']['Multi-Head Self-Attention']['desc'] = (
    '一句话：让模型看到上下文里哪些词之间有关系。\n\n'
    '例子："我想吃苹果" 中，"吃" 会关注 "我" 和 "苹果"。\n\n'
    '原理：用 Query 和 Key 算相似度，再用权重对 Value 加权求和。多头 = 多组并行 Q/K/V。'
    'Decoder 里 Self-Attention + FFN 就是 Decoder，RoPE 把位置信息融进 Q/K，KV Cache 避免重复计算历史。'
)

data['NODES']['Feed-Forward Network']['desc'] = (
    '一句话：对每个 token 的向量单独做非线性变换，加工语义。\n\n'
    '例子：Attention 让 "吃" 带上了 "我" 和 "苹果" 的信息，FFN 把它进一步映射到 [食物动作] 语义空间。\n\n'
    '原理：两层全连接层夹激活函数（如 GELU）的 MLP。只处理当前位置向量，给模型增加非线性能力，让 Attention 的关系进一步组合变换。'
)

with open(p, 'w', encoding='utf-8') as f:
    json.dump(data, f, ensure_ascii=False, indent=2)
print('updated')
