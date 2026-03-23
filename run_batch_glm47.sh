#!/bin/bash
set -e
cd /home/w00857628/memory-eval
set -a
source .env
set +a

PY=python3
PY_CONDA=/home/shared/miniconda3/envs/qwen_quant/bin/python
REMAINING_CONVS="conv-41 conv-42 conv-43 conv-44 conv-47 conv-48 conv-49 conv-50"
ALL_CONVS="conv-26 conv-30 conv-41 conv-42 conv-43 conv-44 conv-47 conv-48 conv-49 conv-50"

log() {
    echo ""
    echo "========================================"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1"
    echo "========================================"
}

# 1. OpenViking - 全10条对话
log "Step 1/4: OpenViking GLM-4.7 - all 10 convs"
$PY -u eval_pipeline.py \
    --data data/locomo10.json \
    --strategy openviking \
    --model glm-4.7 \
    --max-qa 999 \
    --conv-ids $ALL_CONVS \
    --output results/all10_openviking_glm47.json

# 2. RAG - 后8条对话
log "Step 2/4: RAG GLM-4.7 - remaining 8 convs"
$PY -u eval_pipeline.py \
    --data data/locomo10.json \
    --strategy rag \
    --model glm-4.7 \
    --max-qa 999 \
    --conv-ids $REMAINING_CONVS \
    --output results/remaining8_rag_glm47.json

# 3. MemOS - 后8条对话
log "Step 3/4: MemOS GLM-4.7 - remaining 8 convs"
$PY -u eval_pipeline.py \
    --data data/locomo10.json \
    --strategy memos \
    --model glm-4.7 \
    --max-qa 999 \
    --conv-ids $REMAINING_CONVS \
    --output results/remaining8_memos_glm47.json

# 4. Mem0 - 全10条对话
log "Step 4/4: Mem0 GLM-4.7 - all 10 convs"
$PY_CONDA -u eval_pipeline.py \
    --data data/locomo10.json \
    --strategy mem0 \
    --model glm-4.7 \
    --max-qa 999 \
    --conv-ids $ALL_CONVS \
    --output results/all10_mem0_glm47.json

log "ALL DONE!"
ls -la results/*glm47*.json
