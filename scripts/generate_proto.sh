#!/bin/bash
# Compile les fichiers .proto en code Python gRPC
# Usage: bash scripts/generate_proto.sh
#
# Utilise le python du venv s'il existe (.venv/), sinon python global.

set -euo pipefail

PROTO_DIR="proto"
OUT_DIR="src/grpc_server/generated"

if [[ -x ".venv/Scripts/python.exe" ]]; then
  PY=".venv/Scripts/python.exe"
elif [[ -x ".venv/bin/python" ]]; then
  PY=".venv/bin/python"
else
  PY="python"
fi

echo "Using Python: $PY"
echo "Generating gRPC Python code from proto files..."

# v1 (legacy, figé — deprecate en IA-M6)
"$PY" -m grpc_tools.protoc \
  -I"$PROTO_DIR" \
  --python_out="$OUT_DIR" \
  --grpc_python_out="$OUT_DIR" \
  "$PROTO_DIR"/challenge.proto

# v2 (MVP — 4 services : CodeReview, ChallengeGeneration, TalentDetection, Plagiarism)
"$PY" -m grpc_tools.protoc \
  -I"$PROTO_DIR" \
  --python_out="$OUT_DIR" \
  --grpc_python_out="$OUT_DIR" \
  "$PROTO_DIR"/skilluv_ai.proto

# Post-process : grpc_tools emet `import foo_pb2` (absolu). Comme les stubs vivent
# dans un package, on remplace par `from . import foo_pb2` pour que l'import
# fonctionne en mode `from src.grpc_server.generated import ...`.
# Why: relative imports evitent d'avoir a bricoler sys.path.
for stub in "$OUT_DIR"/challenge_pb2_grpc.py "$OUT_DIR"/skilluv_ai_pb2_grpc.py; do
  if [[ -f "$stub" ]]; then
    "$PY" -c "
import re, sys
p = sys.argv[1]
s = open(p, 'r', encoding='utf-8').read()
s = re.sub(r'^import (\w+_pb2) as ', r'from . import \1 as ', s, flags=re.MULTILINE)
open(p, 'w', encoding='utf-8').write(s)
" "$stub"
  fi
done

echo "Done. Generated files in $OUT_DIR/"
