#!/bin/bash
# Compile les fichiers .proto en code Python gRPC
# Usage: bash scripts/generate_proto.sh

set -euo pipefail

PROTO_DIR="proto"
OUT_DIR="src/grpc_server/generated"

echo "Generating gRPC Python code from proto files..."

python -m grpc_tools.protoc \
  -I"$PROTO_DIR" \
  --python_out="$OUT_DIR" \
  --grpc_python_out="$OUT_DIR" \
  "$PROTO_DIR"/challenge.proto

echo "Done. Generated files in $OUT_DIR/"
