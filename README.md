# memory-eval

Agent 记忆系统评测 Pipeline，基于 LoCoMo-10 数据集，用于比较不同 memory strategy 在长对话问答任务上的效果、延迟与 token 成本。

目前项目已支持多种策略，包括 baseline、RAG、Mem0、MemOS、OpenViking，并支持将 **answer model** 与 **memory system internal model / judge model** 解耦配置。

## 目录结构

```text
memory-eval/
├── eval_pipeline.py        # 主评测代码
├── run_glm.sh             # 单次实验脚本（读取 .env，转发参数给 eval_pipeline.py）
├── run_batch_glm47.sh     # GLM-4.7 批量实验脚本
├── requirements.txt       # Python 依赖
├── data/                  # 数据集目录
│   └── locomo10.json      # LoCoMo-10 数据集（需手动下载）
├── results/               # 实验结果输出目录
├── openviking_workspace/  # OpenViking 本地 workspace（不追踪）
└── qdrant_storage/        # 本地向量存储 / 中间数据
```

## 支持的 Memory 策略

| 策略 | 说明 | 备注 |
|---|---|---|
| `no_memory` | 无记忆，baseline | 最低成本下界 |
| `full_history` | 全量历史直接塞进 prompt | 效果上界，token 成本高 |
| `rag` | Session-level chunk RAG 检索 | 使用本地 embedding server + `bge-large-en-v1.5` |
| `mem0` | Mem0 记忆系统 | 依赖 `mem0ai` |
| `memos` | MemOS / MemTensor 风格 memory strategy | self-hosted |
| `openviking` | OpenViking hierarchical memory | embedded/local mode |

## 环境准备

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

请确保所使用的 Python 环境已安装项目依赖，以及对应 memory framework 所需的额外依赖。

### 2. 下载 LoCoMo-10 数据集

```bash
mkdir -p data
wget https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json -O data/locomo10.json
```

### 3. 配置环境变量

推荐使用 `.env` 文件，由 `run_glm.sh` / `run_batch_glm47.sh` 自动加载。

常见变量示例：

```bash
OPENAI_API_KEY=...
OPENAI_BASE_URL=...

ANSWER_API_KEY=...
ANSWER_BASE_URL=...
ANSWER_MODEL=glm-4.7

EMBEDDING_BASE_URL=http://<embedding-server>/v1
EMBEDDING_MODEL=bge-large-en-v1.5
```

说明：
- `OPENAI_*` 常用于默认 client、judge 或 memory strategy 内部模型
- `ANSWER_*` 用于单独指定 answer model（例如 GLM-4.7）
- 当前实验里常见配置是：
  - memory 内部模型 / judge：MiniMax M2.5
  - answer model：GLM-4.7

## 基本运行方式

### 直接运行 `eval_pipeline.py`

```bash
# 跑所有策略
python eval_pipeline.py --data data/locomo10.json --strategy all --output results/all.json

# 只跑 RAG
python eval_pipeline.py --data data/locomo10.json --strategy rag --top-k 5

# 只测部分类别，节省费用
python eval_pipeline.py --data data/locomo10.json --strategy all --categories single-hop temporal

# 快速验证（每条对话只跑前 3 个 QA）
python eval_pipeline.py --data data/locomo10.json --strategy all --max-qa 3

# 只跑指定对话
python eval_pipeline.py --data data/locomo10.json --strategy openviking --conv-ids conv-26 conv-30
```

## GLM 脚本

### `run_glm.sh`

单次实验脚本。作用：
- 自动加载 `.env`
- 使用当前项目约定的 Python 环境
- 将命令行参数原样转发给 `eval_pipeline.py`

示例：

```bash
./run_glm.sh --data data/locomo10.json --strategy openviking --model glm-4.7 \
  --conv-ids conv-26 conv-30 --output results/conv26_30_openviking_glm47.json
```

### `run_batch_glm47.sh`

批量实验脚本。作用：
- 将多组 `run_glm.sh` 实验按顺序串起来执行
- 适合跑成套的 GLM-4.7 对比实验

可以把它理解为：
- `run_glm.sh` = 单次实验执行器
- `run_batch_glm47.sh` = 多次实验调度器

## 各策略说明

### RAG

当前 RAG 实现特点：
- chunk 粒度：**session-level**
- embedding：本地 `bge-large-en-v1.5`
- 检索：内存向量相似度（numpy cosine similarity）
- query 改写：通过 LLM 进行 statement-style rewrite

### Mem0

```bash
pip install mem0ai
python eval_pipeline.py --data data/locomo10.json --strategy mem0
```

### MemOS / MemTensor (`memos`)

该策略通常依赖 self-hosted 服务（如 Neo4j / Qdrant / API server）。
在使用前请先确保相关服务可用，并且 `eval_pipeline.py` 中对应配置已正确填写。

### OpenViking

OpenViking 使用本地 workspace（默认 `openviking_workspace/`），运行时会生成大量中间状态与 memory 文件，因此该目录默认不纳入 git 追踪。

## Retry 机制

当前 `answer()` 阶段已加入 rate limit retry：
- 默认最多重试 3 次
- 当前 delay 配置为 **10s / 20s / 30s**
- 用于缓解 GLM 等模型在评测阶段偶发的 429 限流错误

## 输出结果

实验结果默认写入 `results/` 目录：
- `*.json`：结构化评测结果
- `*.log`：运行日志

建议命名方式：
- `conv26_30_openviking_glm47.json`
- `conv26_30_memos_glm47.json`
- `all10_openviking_glm47.json`

这样便于按：
- 对话范围
- 策略
- answer model
进行区分。

## 扩展新策略

继承 `MemoryStrategy`，实现 `reset / observe / retrieve` 三个方法即可：

```python
class MyMemory(MemoryStrategy):
    @property
    def name(self):
        return "my_memory"

    def reset(self):
        ...

    def observe(self, speaker, text, session_date=None, session_idx=0, blip_caption=None):
        ...

    def retrieve(self, query) -> str:
        ...
```

然后在 `main()` 的 strategy builder 中注册即可。
