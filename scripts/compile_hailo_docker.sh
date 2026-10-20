#!/usr/bin/env bash
# ==============================================================================
# Script Kompilasi Model YOLOv8 ke Hailo-8L (.hef) Menggunakan Docker
# Referensi: Hailo AI Software Suite & Dataflow Compiler (DFC)
# ==============================================================================
set -e

MODEL_NAME=${1:-"yolov8n"}
ONNX_PATH=${2:-"models/${MODEL_NAME}.onnx"}
OUTPUT_DIR=${3:-"models"}
CALIB_DIR=${4:-"data/calibration"}

echo "=== Memulai Kompilasi Hailo DFC untuk ${MODEL_NAME} ==="
echo "Input ONNX : ${ONNX_PATH}"
echo "Output Dir : ${OUTPUT_DIR}"

if [ ! -f "${ONNX_PATH}" ]; then
    echo "ERROR: File ${ONNX_PATH} tidak ditemukan!"
    exit 1
fi

# Pastikan folder output ada
mkdir -p "${OUTPUT_DIR}"

# Menjalankan Hailo Model Zoo Compiler di dalam container Docker
# Catatan: Memerlukan Docker Desktop terpasang dengan WSL2 engine
docker run --rm \
    -v "$(pwd)":/workspace \
    -w /workspace \
    hailo_ai_software_suite:latest \
    hailomz compile "${MODEL_NAME}" \
        --ckpt "${ONNX_PATH}" \
        --hw-arch hailo8l \
        --classes 80 \
        --output-dir "${OUTPUT_DIR}"

echo "=== Kompilasi Selesai! File HEF tersimpan di ${OUTPUT_DIR} ==="
