#!/bin/bash
# Load test skilluv-ai avec ghz.
#
# Usage :
#   ./bench/run.sh [target] [method]
#
#   target : localhost:50051 (défaut) | ai.skilluv.example.com:443 | ...
#   method : review | plagiarism | analyze | all (défaut)
#
# Prérequis : `ghz` installé (github.com/bojand/ghz). Sur macOS: brew install ghz.
#
# NB : contre un backend Claude réel, les résultats de review_code seront
# artificiels (le cache Redis va absorber >90% des appels à cause du même
# submission_id). Pour un vrai stress test, forcer le cache miss côté service
# (SKILLUV_AI_CACHE_DISABLED=1) OU accepter que la latence mesurée = cache hit.

set -euo pipefail

TARGET="${1:-localhost:50051}"
METHOD="${2:-all}"
CONCURRENCY="${GHZ_CONCURRENCY:-10}"
DURATION="${GHZ_DURATION:-30s}"
PROTO_DIR="$(dirname "$0")/../proto"

echo "Target: $TARGET"
echo "Concurrency: $CONCURRENCY | Duration: $DURATION"
echo ""

run_bench() {
    local name="$1"
    local rpc="$2"
    local data_file="$3"
    echo "=== $name ==="
    ghz \
        --insecure \
        --proto "$PROTO_DIR/skilluv_ai.proto" \
        --import-paths "$PROTO_DIR" \
        --call "$rpc" \
        -D "$(dirname "$0")/ghz/$data_file" \
        --concurrency "$CONCURRENCY" \
        --duration "$DURATION" \
        --connections 5 \
        "$TARGET"
    echo ""
}

case "$METHOD" in
    review|all)
        run_bench "ReviewCode" \
            "skilluv.ai.v2.CodeReviewService.ReviewCode" \
            "review_code.json"
        ;;
esac

case "$METHOD" in
    plagiarism|all)
        run_bench "CheckPlagiarism" \
            "skilluv.ai.v2.PlagiarismService.CheckPlagiarism" \
            "check_plagiarism.json"
        ;;
esac

case "$METHOD" in
    analyze|all)
        run_bench "AnalyzePerformance" \
            "skilluv.ai.v2.TalentDetectionService.AnalyzePerformance" \
            "analyze_performance.json"
        ;;
esac
