#!/bin/bash
cd /home/w00857628/memory-eval
set -a
source .env
set +a
exec /home/shared/miniconda3/envs/qwen_quant/bin/python -u eval_pipeline.py "$@"
