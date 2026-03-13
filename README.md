# memory-eval

Agent 记忆系统评测 Pipeline，基于 LoCoMo-10 数据集。

## 目录结构

```
memory-eval/
├── eval_pipeline.py   # 主评测代码
├── requirements.txt   # 依赖
├── data/              # 放数据集
│   └── locomo10.json  # 需要手动下载（见下方）
└── results/           # 评测结果自动输出到这里
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 下载 LoCoMo-10 数据集

```bash
wget https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json -O data/locomo10.json
```

### 3. 设置 API Key

```bash
export OPENAI_API_KEY=你的key
```

### 4. 运行评测

```bash
# 跑所有策略
python eval_pipeline.py --data data/locomo10.json --strategy all --output results/all.json

# 只跑 RAG
python eval_pipeline.py --data data/locomo10.json --strategy rag --top-k 5

# 只测单跳+时序，节省费用
python eval_pipeline.py --data data/locomo10.json --strategy all --categories single-hop temporal

# 快速验证（每条对话只跑 3 个 QA）
python eval_pipeline.py --data data/locomo10.json --strategy all --max-qa 3
```

### 5. 接入 Mem0

```bash
pip install mem0ai
export MEM0_API_KEY=你的key  # 或者只用 OPENAI_API_KEY 跑本地模式
python eval_pipeline.py --data data/locomo10.json --strategy mem0
```

## 支持的 Memory 策略

| 策略 | 说明 | 额外依赖 |
|---|---|---|
| no_memory | 无记忆，baseline | 无 |
| full_history | 全量历史塞进 prompt | 无 |
| rag | 向量检索（OpenAI embedding） | numpy |
| mem0 | Mem0 记忆系统 | mem0ai |

## 扩展新策略

继承 MemoryStrategy，实现 reset / observe / retrieve 三个方法即可：

```python
class MyMemory(MemoryStrategy):
    @property
    def name(self): return my_memory
    def reset(self): ...
    def observe(self, speaker, text): ...
    def retrieve(self, query) -> str: ...
```

然后在 main() 的 all_strategies 里加一行就能跑了。
