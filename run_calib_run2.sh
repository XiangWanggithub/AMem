#!/bin/bash
# Launch σ calibration run2 for LoCoMo and LME (sequential).
# Run after run1s complete.
set -e
cd /home/kailong/Quant/memory-eval

echo "=== Starting LoCoMo calibration run2 ==="
conda run -n metamem python -u eval_pipeline.py \
  --data data/locomo10.json --strategy src_memory --mode selective \
  --conv-ids conv-26 --max-qa 9999 \
  --output results/sma_calib_locomo_2.json
echo "[$(date '+%Y-%m-%d %H:%M:%S')] LoCoMo run2 complete"

echo "=== Starting LME calibration run2 (all 6 types) ==="
for qt in single-session-user single-session-assistant single-session-preference multi-session temporal-reasoning knowledge-update; do
  echo "[$(date '+%H:%M:%S')] Starting: $qt"
  conda run -n metamem python -u eval_longmemeval.py \
    --strategy src --mode selective --n 5 \
    --question-types $qt \
    --output results/sma_calib_lme_${qt}_run2.json
  echo "[$(date '+%H:%M:%S')] Done: $qt"
done
echo "[$(date '+%Y-%m-%d %H:%M:%S')] LME run2 complete"

echo "=== Computing σ ==="
conda run -n metamem python compute_sigma.py \
  --locomo1 results/sma_calib_locomo_1.json \
  --locomo2 results/sma_calib_locomo_2.json \
  --lme-dir results/ --lme-suffix run
