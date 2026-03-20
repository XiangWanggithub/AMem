# MemOS 技术分析文档

> 基于 MemOS 开源代码 (https://github.com/MemTensor/MemOS) 和论文 (arXiv:2507.03724) 的深度分析。
>
> 分析时间：2026-03-19  
> 分析者：Grace

---

## 目录

1. [整体架构概览](#1-整体架构概览)
2. [记忆写入机制与流程](#2-记忆写入机制与流程)
3. [记忆 Reorganize 机制与流程](#3-记忆-reorganize-机制与流程)
4. [记忆搜索机制与流程](#4-记忆搜索机制与流程)
5. [OpenClaw 插件实现](#5-openclaw-插件实现)
6. [与 Mem0 的对比](#6-与-mem0-的对比)

---

## 1. 整体架构概览

### 1.1 核心理念

MemOS 把 memory 当作**操作系统级资源**来管理，类比 OS 管理 CPU/内存/IO。核心抽象是 **MemCube**（记忆立方体）—— 每个 MemCube 是一个独立的记忆容器，封装内容 + 元数据（来源、版本、权限等）。

### 1.2 三层记忆类型（论文愿景）

| 层级 | 类型 | 状态 |
|---|---|---|
| **Plaintext Memory（文本记忆）** | 结构化 facts（key-value + tags），存 Qdrant + Neo4j | 当前开源版主要实现 |
| **Activation Memory（激活态记忆）** | KV Cache / Hidden State 级别，推理时注入 | 论文愿景，未完整实现 |
| **Parametric Memory（参数记忆）** | 写入模型权重（LoRA 等），类似可控 fine-tune | 论文愿景，未完整实现 |

### 1.3 存储架构

- **Qdrant（向量数据库）**：存储 memory 的 embedding 向量 + 全部 metadata，用于语义搜索
- **Neo4j（图数据库）**：存储 memory 节点 + 节点间关系（PARENT/RELATED），用于图结构管理和关系检索
- **两者同步写入**：每条 memory 在 Qdrant 和 Neo4j 中各有一份，通过 vector_sync 字段标记同步状态

### 1.4 两种 TextMemory 实现

| | GeneralTextMemory | TreeTextMemory |
|---|---|---|
| **存储** | Qdrant only | Qdrant + Neo4j 图关系 |
| **搜索** | 单路向量搜索 | 多路并行召回（向量 + BM25 + 联网） |
| **后处理** | 无 | Reranker + 去重 + 层级加权 |
| **Reorganizer** | 无 | 有（后台线程，周期性聚类建树） |
| **适用场景** | 简单、快速 | 大量记忆、需要层级组织 |

---

## 2. 记忆写入机制与流程

### 2.1 数据流概览

```
用户对话 messages
    │
    ▼
┌──────────────────────────┐
│  MemReader (LLM 提取)     │
│  extractor_llm.generate() │
│  使用 extraction prompt   │
└────────────┬─────────────┘
             │ 输出结构化 JSON
             ▼
┌──────────────────────────┐
│  解析为 TextualMemoryItem │
│  包含 memory + metadata   │
└────────────┬─────────────┘
             │
     ┌───────┴───────┐
     ▼               ▼
┌──────────┐   ┌──────────┐
│  Qdrant   │   │  Neo4j   │
│  向量存储  │   │  图存储   │
└──────────┘   └──────────┘
```

### 2.2 Extraction Prompt 核心要求

MemOS 使用一个详细的 extraction prompt（`src/memos/templates/mem_reader_prompts.py`）：

1. **第三人称视角**：写 "The user felt exhausted" 而不是 "I felt exhausted"
2. **时间解析**：将相对时间（"yesterday"）转为绝对日期（"June 25, 2025"），区分事件时间和消息时间
3. **人名消歧**：解析代词、别名为全名，区分同名人物
4. **不遗漏信息**：宁可多提取，不要少提取（prioritize completeness over conciseness）
5. **输出格式**：严格的 JSON 结构，含完整示例

### 2.3 LLM 输出的 JSON 格式

```json
{
  "memory list": [
    {
      "key": "LGBTQ support group attendance",
      "memory_type": "LongTermMemory",
      "value": "On May 8, 2023, Caroline shared with Melanie that she had attended an LGBTQ support group the day before (May 7, 2023) and found the transgender stories really touching.",
      "tags": ["LGBTQ", "support group", "community", "transgender"]
    }
  ],
  "summary": "During their conversation on May 8, 2023, Caroline and Melanie discussed..."
}
```

### 2.4 结构化字段说明

| 字段 | 说明 | 来源 |
|---|---|---|
| **memory (value)** | 事实陈述，含完整时间/人物/事件。LLM 会融合多轮对话信息为一条完整描述 | LLM extraction |
| **key** | 简短唯一标题，用于去重和快速定位 | LLM extraction |
| **memory_type** | LongTermMemory（重要事实/事件）或 UserMemory（用户个人属性/偏好） | LLM extraction |
| **tags** | 关键词列表，辅助理解和可选过滤 | LLM extraction |
| **background** | 整段对话的上下文摘要。同一次 extraction 的所有 memories 共享同一个 background | LLM extraction 的 summary 字段 |
| **confidence** | 提取置信度（0-1），目前基本都是 0.99 | LLM extraction 或系统默认 |
| **status** | 生命周期状态：activated（可搜索）/ archived（已归档） | 系统管理 |
| **vector_sync** | 向量同步状态：success / failed | 写入时自动标记 |

### 2.5 一条真实 Memory 示例

```
key:         "Volunteering at LGBTQ+ youth center"
memory:      "Caroline volunteered at an LGBTQ+ youth center. She described it as a 
              gratifying experience where she had the chance to talk to similar young
              people. She felt fulfilled guiding and supporting them, and even got to
              share her own story to let them know they're not alone."
type:        fact
memory_type: LongTermMemory
tags:        ["volunteering", "LGBTQ+", "youth center", "community support"]
confidence:  0.99
status:      activated
background:  "During a conversation on May 8, 2023, Caroline and Melanie discussed..."
```

### 2.6 JSON 输出保障机制

MemOS 没有使用 OpenAI 的 response_format 或 function calling，而是靠三层保障：

1. **Prompt 模板 + 示例**：给 LLM 详细的 JSON 格式说明和完整 input/output 示例
2. **重试机制**：最多重试 3 次（retry_if_exception_type(json.JSONDecodeError)）
3. **容错解析**：
   - `find("{")` 跳过 JSON 前面的废话
   - 去掉 markdown 代码块标记
   - 自动补上缺失的结尾花括号

### 2.7 记忆类型详解

#### WorkingMemory（工作记忆）
- **不是 LLM 分类的**，是系统自动生成
- 每条 LongTermMemory/UserMemory 写入时，系统自动复制一份标记为 WorkingMemory
- 相当于"最近活跃的记忆缓存"
- **数量上限 20 条**，超了按 FIFO 淘汰最老的
- 搜索时作为独立召回路径，优先返回近期记忆

#### LongTermMemory（长期记忆）
- **LLM 分类的**：重要的事实、事件、经历
- 例："Caroline attended an LGBTQ support group on May 7, 2023"
- **数量上限 1500 条**
- 参与 reorganizer 聚类建树

#### UserMemory（用户记忆）
- **LLM 分类的**：用户个人属性信息
- 例："Caroline is interested in counseling and mental health work"
- 偏好、性格、习惯、身份等个人画像
- **数量上限 480 条**
- 独立 scope 参与 reorganizer 聚类建树

**类比人类记忆**：
- WorkingMemory = 你正在想的事（工作台上的纸）
- LongTermMemory = 你记得的所有事实经历（档案柜）
- UserMemory = 你对自己的认知（"我是什么样的人"）

### 2.8 双写流程（Qdrant + Neo4j）

写入时先写 Qdrant，再写 Neo4j：

```python
vector_sync_status = "success"
try:
    # 1. 先写 Qdrant
    self.vec_db.add([VecDBItem(id=id, vector=embedding, payload={...})])
except Exception:
    vector_sync_status = "failed"

# 2. 再写 Neo4j，带上 vector_sync 状态
metadata["vector_sync"] = vector_sync_status
# MERGE (n:Memory {id: $id}) SET n.memory = $memory, ...
```

如果 Qdrant 写入失败，vector_sync = "failed"，搜索时会被过滤掉。

### 2.9 多轮对话信息提取

**不是按轮提取，而是按 session 整体理解后提取。** LLM 一次性看到整个 session 的所有 turns，做信息融合：

```
对话原文:
Turn 3: Caroline: "I went to a support group yesterday"
Turn 5: Caroline: "The transgender stories were so touching"
Turn 8: Melanie: "That's brave of you!"
Turn 9: Caroline: "It really helped me feel accepted"

LLM 融合提取为一条:
"On May 8, 2023, Caroline shared that she attended an LGBTQ support group
the day before (May 7, 2023). She found the transgender stories touching
and felt the experience helped her feel accepted."
```

---

## 3. 记忆 Reorganize 机制与流程

> 注意：Reorganizer 仅在 **TreeTextMemory** 模式下可用，GeneralTextMemory 没有此功能。

### 3.1 Reorganizer 架构

GraphStructureReorganizer 是一个后台运行的异步系统，包含两个独立线程：

**Thread 1: Message Consumer Loop**
- 消费 PriorityQueue 中的消息
- 每次 add 新 memories 后触发
- 处理 add/remove/merge/update 事件

**Thread 2: Structure Organizer Loop**
- 每 100 秒检查一次，或有新节点加入时立即触发
- 分别对 LongTermMemory 和 UserMemory 执行 optimize_structure()

### 3.2 optimize_structure() 流程

```
Step 1: 加载候选节点
        条件：activated 且没有 parent 的节点
        最低门槛：至少 20 个节点才开始
    │
    ▼
Step 2: 按 embedding 相似度分区（partition）
        使用向量聚类算法将节点分组
    │
    ▼
Step 3: 对每个 cluster（>=4 个节点）：
    ├─ 3a. 大 cluster → local sub-clustering（LLM 辅助）
    ├─ 3b. 每个子聚类 → LLM 生成 summary parent node
    └─ 3c. 在 Neo4j 中创建 PARENT 关系
    │
    ▼
Step 4: 如果 sub-parents >= 4，再生成上层 parent（递归建树）
    │
    ▼
Step 5: 超时保护：最长 600 秒
```

### 3.3 树状结构示例

```
           [Topic: Caroline's LGBTQ Journey]          <- 顶层 summary parent
              /              \
  [Concept: Support Groups]   [Concept: Advocacy]    <- 中层 summary parent
     /     |      \               /       \
 [fact1] [fact2] [fact3]     [fact4]    [fact5]      <- 叶子 = 原始 memories
```

所有层级的节点（包括 summary parents）**都在 Qdrant 里有向量**，搜索时可以直接命中任意层级。

### 3.4 Merge（合并）机制

当 LLM 提取出新 memory 时，如果发现跟已有 memory 高度相似：

```
旧: "Caroline started learning piano recently"      -> status: activated
新: "Caroline has been playing piano for two months" -> 触发 merge

结果:
新: merged memory -> status: activated
旧:               -> status: archived（仍存在但搜不到）
```

### 3.5 status 状态流转

```
activated  ───→  archived
   │                ▲
   │                │
   └─── merge ──────┘
```

- **创建时** → activated（可被搜索）
- **被合并时** → archived（存在但不可搜索）

### 3.6 树状结构的好处

1. **多粒度检索**：宏观问题命中 topic/concept 级 summary，细节问题命中 fact 级叶子
2. **减少噪声**：相关 facts 聚成 cluster，检索更精准
3. **去重和冲突消解**：merge 机制保留最新版，archive 旧版
4. **token 效率**：1 个 topic summary 比 10 条 facts 信息量更大但 token 更少

---

## 4. 记忆搜索机制与流程

### 4.1 GeneralTextMemory 的搜索（简单模式）

```
query -> embedding -> Qdrant 向量搜索（cosine similarity）
                      filter: {user_name, status=activated, vector_sync=success}
                      -> 返回 top_k
```

纯向量语义搜索，跟普通 RAG 基本一致。

### 4.2 TreeTextMemory 的搜索（完整模式）

```
query
  │
  ▼
_parse_task()
  │  (fine 模式下) LLM 解析 query 意图
  ▼
_retrieve_paths()  <- ThreadPool 并行启动多路召回（最多 5 路）
  │
  ├─ Path A: WorkingMemory
  │  Qdrant 向量搜索, scope="WorkingMemory"
  │  优先召回最近的 20 条活跃记忆
  │
  ├─ Path B: LongTermMemory + UserMemory
  │  Qdrant 向量搜索, scope="LongTermMemory"+"UserMemory"
  │  包括叶子节点和 summary parent 都能被搜到
  │
  ├─ Path C: Internet（如果开启）
  │  联网搜索补充外部知识
  │
  ├─ Path D: BM25 Keyword（如果开启 fulltext）
  │  关键词匹配，不走向量
  │  补充语义搜索可能遗漏的精确匹配
  │
  └─ Path E/F: ToolMemory / SkillMemory / PreferenceMemory
     特殊类型记忆的独立召回
  │
  ▼
post_retrieve()
  ├─ deduplicate: 去重
  ├─ Reranker: cosine_local, 按 level_weights 加权排序
  │   level_weights: {"topic": 1.0, "concept": 1.0, "fact": 1.0}
  │   通过 background 字段判断节点层级
  └─ 截断 top_k -> 返回最终结果
```

### 4.3 tags 在搜索中的实际角色

**tags 在默认搜索流程中不直接参与匹配。** 搜索核心是 memory (value) 的向量相似度。

tags 的实际用途：
1. **辅助理解**：返回给 LLM 时帮助理解 memory 主题
2. **可选过滤**：API 的 search_filter 支持按 tags 过滤（如 `{"tags": "LGBTQ"}`），但默认不启用
3. **管理分类**：在 dashboard 中按 tag 分组查看

### 4.4 各字段在搜索中的角色

| 字段 | 搜索时角色 |
|---|---|
| **memory (value)** | 核心：embedding 后跟 query 向量做 cosine 匹配 |
| **key** | 不参与匹配，仅展示/去重 |
| **tags** | 可选 filter，默认不参与 |
| **type/memory_type** | 可选 scope filter（如只搜 LongTermMemory） |
| **confidence** | 不参与排序 |
| **background** | 不参与匹配（TreeTextMemory 中用于 reranker 判断层级） |
| **status** | 必须是 activated 才会被搜到 |
| **vector_sync** | 必须是 success 才会被搜到 |

### 4.5 搜索模式

- **fast 模式**：跳过 LLM query 解析，直接向量搜索，速度快
- **fine 模式**：先用 LLM 解析 query 意图（TaskGoalParser），再做多路召回，精度高但更慢

---

## 5. OpenClaw 插件实现

> 基于 MemOS Cloud OpenClaw Plugin (https://github.com/MemTensor/MemOS-Cloud-OpenClaw-Plugin)

### 5.1 插件生命周期 Hook

插件通过 OpenClaw 的两个 lifecycle hook 工作：

```
用户发送消息
    │
    ▼
┌─ before_agent_start (Recall) ────────────┐
│  1. 拿用户 prompt 作为 query               │
│     query = queryPrefix + 用户消息         │
│     (queryPrefix 默认: "important user     │
│      context preferences decisions ")      │
│                                           │
│  2. POST /search/memory                    │
│     返回相关记忆 (top_k, 过滤相似度<0.45)  │
│                                           │
│  3. 注入到 LLM 上下文                       │
│     prependContext: 记忆内容                │
│     appendSystemContext: MemOS 使用协议     │
└───────────────────────────────────────────┘
    │
    ▼
  LLM 生成回复（带记忆上下文）
    │
    ▼
┌─ agent_end (Add) ────────────────────────┐
│  POST /add/message                        │
│  captureStrategy: "last_turn"             │
│  存入: 用户消息 + AI 回复                   │
│  标记: user_id, conversation_id, tags     │
└───────────────────────────────────────────┘
```

### 5.2 LLM 看到的完整 Context

```
[System] 你是一个助手...

[MemOS Recall]
- 用户喜欢户外活动
- 用户有轻微膝盖问题
- 用户偏好低强度运动

[对话历史]
User: 昨天聊的那个项目怎么样了？
AI: 进展顺利...

[当前消息]
User: 推荐一个适合我的运动
```

记忆通过 prependContext（前置）注入，不混入对话历史。

### 5.3 关键配置参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| captureStrategy | "last_turn" | 每轮对话结束后存入最后一轮 |
| recallGlobal | true | 搜索时跨所有会话（不限制 conversation_id） |
| memoryLimitNumber | 6 | 最多返回 6 条 fact memory |
| preferenceLimitNumber | 6 | 最多返回 6 条偏好 memory |
| relativity | 0.45 | 相似度阈值，低于此值不返回 |
| resetOnNew | true | 新会话时重置 conversation_id（不清空记忆） |
| asyncMode | true | 异步 add（不等 LLM extraction 完成） |
| queryPrefix | "important user context..." | 搜索 query 前缀，偏向个人偏好类记忆 |

### 5.4 /add/message vs /product/add

| | /add/message（插件用） | /product/add（eval 用） |
|---|---|---|
| **输入** | 原始对话消息 | 原始对话消息 |
| **处理** | 存 raw message，后台异步做 LLM extraction | 同步做 LLM extraction，等完成才返回 |
| **延迟** | 低（不等 LLM） | 高（等 LLM extraction，30-60s/session） |
| **适用场景** | 实时对话，不能阻塞用户 | 评测/批量导入，可以等待 |

### 5.5 conversation_id 与 resetOnNew

- resetOnNew = true 时，新会话开始会分配新的 conversation_id
- **不会清空记忆**，只是换了会话标识
- 搜索时 recallGlobal = true，跨所有 conversation_id 搜索
- conversation_id 的作用是标记 memory 来源，方便管理和可选的会话内搜索

---

## 6. 与 Mem0 的对比

### 6.1 存储对比

| 维度 | Mem0 | MemOS |
|---|---|---|
| **存储** | Qdrant（纯向量） | Qdrant + Neo4j（向量+图） |
| **Memory 格式** | flat string（一句话） | 结构化对象（key/value/tags/background/...） |
| **元数据** | user_id + timestamp | key, tags, confidence, background, sources, version, status |

Mem0 存的一条 memory：
```
"Caroline went to an LGBTQ support group"
```

MemOS 存的同一件事：
```
key:        "LGBTQ support group attendance"
value:      "On May 8, 2023, Caroline shared with Melanie that she had attended
             an LGBTQ support group the day before and found the transgender
             stories really touching."
type:       fact
memory_type: LongTermMemory
tags:       ["LGBTQ", "support group", "community", "transgender"]
confidence: 0.99
background: "During a conversation on May 8, 2023, Caroline and Melanie discussed..."
```

### 6.2 Extraction 对比

| 维度 | Mem0 | MemOS |
|---|---|---|
| **Prompt 质量** | 简单的 "extract facts" | 详细：要求解析相对日期、第三人称、消歧人名 |
| **处理粒度** | 逐条 message 独立提取 | 整个 session 一次性理解后提取 |
| **信息融合** | 无（每条 fact 来自单条消息） | 有（LLM 会融合多轮对话的信息为一条完整 memory） |
| **时间处理** | 不要求时间解析 | 明确要求相对时间转绝对日期 |

### 6.3 搜索对比

| 维度 | Mem0 | MemOS (General) | MemOS (Tree) |
|---|---|---|---|
| **召回方式** | 单路向量搜索 | 单路向量搜索 | 多路并行（向量+BM25+联网） |
| **Reranker** | 无 | 无 | cosine_local 层级加权 |
| **去重** | 无 | 无 | 有 |
| **记忆分类** | 无 | 按 memory_type 可选过滤 | 按 memory_type 独立召回 |

### 6.4 核心差异总结

MemOS 的优势**不是搜索算法更好**（GeneralTextMemory 模式下搜索逻辑跟 Mem0 几乎一样），而是：

1. **存的东西质量更高**：LLM extraction prompt 更详细，生成的 facts 更完整、含时间信息
2. **信息融合**：多轮对话合并为一条完整的 memory，而不是碎片化的 flat facts
3. **TreeTextMemory 模式下有多路召回 + rerank**：但需要额外的 Neo4j + reorganizer 支持
4. **生命周期管理**：merge/archive 机制可以保持记忆最新、去重

---

## 附录：我们的评测配置

```
LLM:        MiniMax M2.5（fact extraction + QA answering + judging）
Embedding:  bge-large-en-v1.5（本地 GPU，端口 8002）
Vector DB:  Qdrant（Docker 容器，外部端口 38033）
Graph DB:   Neo4j Community（Docker 容器，外部端口 28077）
Reranker:   cosine_local（不用额外模型）
API:        MemOS Server（Docker 容器，外部端口 18001）
Memory 模式: GeneralTextMemory（非 TreeTextMemory）
数据集:     LoCoMo-10, 测试对话 conv-26（419 turns, 19 sessions, 199 QA）
```
