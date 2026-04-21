#!/bin/bash
# Run all benchmark experiments across datasets and questioner types.
#
# Usage:
#   ./run_benchmark.sh                    # run all experiments
#   DATASET=DesignBench ./run_benchmark.sh  # run only one dataset
#   MAX_PROCESSES=8 ./run_benchmark.sh    # use more parallel workers
#
# Override any default via environment variables.

set -euo pipefail

DATA_FOLDER="${DATA_FOLDER:-../datasets/}"
MAX_PROCESSES="${MAX_PROCESSES:-4}"
MAX_ITERS="${MAX_ITERS:-20}"
NUM_EXP="${NUM_EXP:-5}"
N="${N:-5}"
M="${M:-5}"
DATASET="${DATASET:-all}"   # "all", "DesignBench", or "IDEA-Bench"

run_experiment() {
    local dataset=$1
    local questioner=$2
    local exp_id_start=$3
    echo ""
    echo "========================================================"
    echo " Dataset=$dataset  Questioner=$questioner  exp_id_start=$exp_id_start"
    echo "========================================================"
    python benchmark.py \
        --dataset       "$dataset" \
        --questioner    "$questioner" \
        --exp-id-start  "$exp_id_start" \
        --data-folder   "$DATA_FOLDER" \
        --max-processes "$MAX_PROCESSES" \
        --max-iters     "$MAX_ITERS" \
        --num-exp       "$NUM_EXP" \
        --N             "$N" \
        --M             "$M"
}

run_dataset() {
    local dataset=$1
    run_experiment "$dataset" APE 10
    run_experiment "$dataset" In-Context 20
}

if [[ "$DATASET" == "all" ]]; then
    run_dataset IDEA-Bench
    run_dataset DesignBench
else
    run_dataset "$DATASET"
fi

echo ""
echo "All benchmark experiments completed."
