# Memory Eval 项目总结

## 项目概述

基于 LoCoMo-10 数据集，对比评测不同 Agent 记忆系统的效果。使用 MiniMax M2.5 作为 answer + judge 模型，本地 bge-large-en-v1.5 作为 embedding 模型。

- **数据集**: LoCoMo-10 (10 段长对话，每段 ~600 轮，~26000 tokens)
- **测试对话**: conv-26 (419 turns, 19 sessions, 199 QA)
- **QA 分类**: single-hop (32) / temporal (37) / multi-hop (13) / open-domain (70) / adversarial (47)
- **评测指标**: LLM-as-a-Judge (0-1) + F1 score

## 最终结果 (conv-26 全量 199 QA)

| 策略 | Judge 总体 | single-hop | temporal | multi-hop | open-domain | adversarial | Token 消耗 |
|------|-----------|------------|----------|-----------|-------------|------------|-----------|
| no_memory | 0.231 | - | 0.014 | - | - | - | ~50k |
| RAG (session_top5) | 0.601 | - | 0.649 | - | - | - | 964k |
| full_history | 0.764 | - | 0.770 | - | - | - | 3.4M |
| Mem0 v0 (per-session) | ~0.0 | - | 0.0 | - | - | - | - |
| **Mem0 v6 (优化版)** | **0.603** | 0.312 | **0.676** | 0.308 | 0.557 | **0.894** | 64k |

### 结论
- Mem0 v6 总体 (0.603) 与 RAG (0.601) 持平，略低于 full_history (0.764)
- temporal 得分 (0.676) 略优于 RAG (0.649)，说明日期前缀优化生效
- adversarial 得分最高 (0.894)，Mem0 对对抗性问题处理较好
- multi-hop 和 single-hop 得分偏低，可能是 Mem0 存储格式过于碎片化

## Mem0 调优经验 (v0 → v6)

### 问题 1: Facts 无主语
- **现象**: 提取的 facts 是 "Went to an LGBTQ support group"，没有谁去的
- **原因**: 输入给 Mem0 的 message content 只有文本，没有 speaker 名字。`role: user/assistant` 不携带人名信息
- **解决**: content 加人名前缀 `"{speaker}: {text}"`（官方做法）

### 问题 2: Facts 无时间信息  
- **现象**: "Went to an LGBTQ support group yesterday"，不知道 yesterday 是哪天
- **原因**: session_date 没有写入 content。官方用 MemoryClient (云端 API) 的 metadata timestamp 由服务端处理，但本地 Memory 的 metadata 只存 payload，extraction LLM 看不到
- **解决**: content 加日期前缀 `"[{session_date}] {speaker}: {text}"`

### 问题 3: 自定义 extraction prompt 不生效 ⚠️ 最关键
- **现象**: 设了 `add(prompt=CUSTOM_PROMPT)` 但 facts 风格不变
- **原因**: `add()` 的 `prompt` 参数**只对 procedural memory 生效**！普通 memory 用的是 `config.custom_fact_extraction_prompt`
- **解决**: 通过 `Memory.from_config({"custom_fact_extraction_prompt": prompt})` 设置

### 问题 4: Per-turn add 全部返回 0 facts
- **现象**: 419 次 add 全返回空
- **原因**: 加 timing 日志时引入 bug（`name 't0' is not defined`），每次 add 都抛异常被 except 捕获
- **教训**: 修改代码后一定要检查完整的 try-except 块

### 问题 5: Qdrant 只读错误
- **现象**: 靠后的 turns 写入时遇到数据库只读
- **原因**: `on_disk=True` 使 qdrant 向量数据直接在磁盘上操作（mmap），大量写入触发锁
- **解决**: `on_disk=False`（`path` 参数已保证持久化，运行时向量在内存操作）

### 问题 6: GPU OOM 导致进程被杀
- **现象**: 进程跑到一半消失，日志停在某个 turn
- **原因**: GPU 3 被其他训练任务占了 15.8GB，bge-large 加载时 OOM
- **教训**: 跑前检查 `nvidia-smi` 确认显存够用

### 问题 7: JSON 解析偶发错误
- **现象**: `Expecting property name enclosed in double quotes`
- **原因**: MiniMax M2.5 偶尔返回单引号 dict 格式而非标准 JSON
- **影响**: 不影响整体，Mem0 会跳过该 batch

## Mem0 官方 LoCoMo 评测方法

代码: `github.com/mem0ai/mem0/tree/main/evaluation`

关键实现：
1. **Message 格式**: `{"role": "user", "content": "{speaker_a}: {text}"}`，人名在 content 里
2. **batch_size=2**: 每次传 2 条消息给 add()
3. **双视角存储**: speaker_a 和 speaker_b 各自独立 user_id，角色互换
4. **custom_instructions**: 强调人名、日期、不用 "user"
5. **MemoryClient (云端 API)**: 官方用的是云端 API，不是本地 Memory

## 运行命令

### 环境准备
```bash
# SSH 到 Stan 服务器
ssh -i ~/.ssh/id_ed25519 shared@149.36.1.161

# 激活 conda 环境
conda activate qwen_quant

# 检查 GPU 显存
nvidia-smi
```

### 评测脚本
```bash
cd /home/w00857628/memory-eval

# Mem0 策略（全量）
CUDA_VISIBLE_DEVICES=3 python3 -u eval_pipeline.py \
    --data data/locomo10.json \
    --strategy mem0 \
    --conv-ids conv-26 \
    --max-qa 9999 \
    --output results/conv26_mem0_v6_full.json

# RAG 策略
python3 -u eval_pipeline.py \
    --data data/locomo10.json \
    --strategy rag \
    --conv-ids conv-26 \
    --max-qa 9999 \
    --output results/conv26_rag_full.json

# full_history 策略
python3 -u eval_pipeline.py \
    --data data/locomo10.json \
    --strategy full_history \
    --conv-ids conv-26 \
    --max-qa 9999 \
    --output results/conv26_full_history_full.json

# no_memory 基线
python3 -u eval_pipeline.py \
    --data data/locomo10.json \
    --strategy no_memory \
    --conv-ids conv-26 \
    --max-qa 9999 \
    --output results/conv26_no_memory_full.json
```

### 常用参数
- `--conv-ids conv-1,conv-2,conv-26`: 指定跑哪些对话，默认 all
- `--max-sessions N`: 每对话最多跑 N 个 session
- `--max-qa N`: 每对话最多跑 N 个 QA，9999=全部
- `--categories single-hop,temporal,multi-hop,open-domain,adversarial`: 按类型过滤 QA

### 监控
```bash
# 实时日志
tail -f results/conv26_mem0_v6_full.log

# 查看当前进度
grep -E '\[.*/.*\]' results/conv26_mem0_v6_full.log | tail -5

# 查看结果
grep '评测结果汇总' results/conv26_mem0_v6_full.log -A10
```

## 架构决策

- **MiniMax M2.5 thinking model**: 需要 `reasoning_split=True` 去掉 `<think>` 标签，否则 JSON 解析失败
- **retry 逻辑**: MiniMax API 偶尔返回空响应，加了 3 次重试
- **本地 embedding**: bge-large-en-v1.5 (1024 dims)，避免依赖外部 API
- **Qdrant 本地模式**: `path` 持久化 + `on_disk=False` 避免写入锁

## 下一步

- [ ] 测试其他 conversation (conv-1 ~ conv-10)
- [ ] 考虑 Mem0ᵍ (graph memory) 变体
- [ ] 优化 multi-hop / single-hop 得分

## 文件说明

```
memory-eval/
├── eval_pipeline.py              # 主评测脚本
├── PROJECT_NOTES.md             # 本文件
├── data/
│   └── locomo10.json            # LoCoMo-10 数据集
├── results/
│   ├── conv26_no_memory_final.json
│   ├── conv26_rag_final.json
│   ├── conv26_full_history_final.json
│   ├── conv26_mem0_v0.json       # Mem0 per-session 基线
│   └── conv26_mem0_v6_full.json # Mem0 优化版全量结果
└── qdrant_storage/              # Mem0 向量数据库（运行后生成）
```
