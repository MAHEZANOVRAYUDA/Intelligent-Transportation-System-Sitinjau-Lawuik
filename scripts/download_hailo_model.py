"""Utility script to download official pre-compiled Hailo-8L models."""

from __future__ import annotations

import argparse
import logging
import pathlib
import sys
import urllib.request

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

MODELS_CONFIG = {
    "yolov8n": {
        "url": "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v2.14.0/hailo8l/yolov8n.hef",
        "filename": "yolov8n.hef",
    },
    "yolov8s": {
        "url": "https://hailo-model-zoo.s3.eu-west-2.amazonaws.com/ModelZoo/Compiled/v2.14.0/hailo8l/yolov8s.hef",
        "filename": "yolov8s.hef",
    },
}


def download_model(model_name: str = "yolov8n", output_dir: pathlib.Path | None = None) -> pathlib.Path:
    if model_name not in MODELS_CONFIG:
        raise ValueError(f"Model {model_name} tidak dikenal. Pilihan: {list(MODELS_CONFIG.keys())}")

    if output_dir is None:
        output_dir = pathlib.Path(__file__).resolve().parent.parent / "models"

    output_dir.mkdir(parents=True, exist_ok=True)
    cfg = MODELS_CONFIG[model_name]
    target_path = output_dir / cfg["filename"]

    if target_path.exists() and target_path.stat().st_size > 1000:
        logger.info("Model %s sudah ada di %s (%d bytes). Lewati download.", model_name, target_path, target_path.stat().st_size)
        return target_path

    logger.info("Mengunduh model %s dari %s...", model_name, cfg["url"])
    urllib.request.urlretrieve(cfg["url"], target_path)
    logger.info("Berhasil mengunduh %s (%d bytes).", target_path, target_path.stat().st_size)
    return target_path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download official pre-compiled Hailo-8L models")
    parser.add_argument("--model", choices=["yolov8n", "yolov8s"], default="yolov8n", help="Model variant")
    args = parser.parse_args()
    try:
        download_model(args.model)
    except Exception as e:
        logger.error("Download gagal: %s", e)
        sys.exit(1)
