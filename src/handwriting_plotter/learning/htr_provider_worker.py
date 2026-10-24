"""External Python entrypoint for locally installed CRNN/TrOCR HTR providers.

This file is executed by an explicitly selected Python environment. Keeping all
ML imports inside its functions preserves a working default CADPisun install.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import sys
import time
from io import BytesIO
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = "hp-htr-worker/1"
CRNN_REVISION = "1d772a7a73611d46673f297736bf185785993346"
TROCR_REVISION = "dab1d389051f5ffc56e35e779f29d7133d853088"
CRNN_SHA256 = "add8c3f1d5757574d6f9620fc2a951ca59d0b1f1f4f4c835658ca15468c79870"
TROCR_SHA256 = "ea5ca3352ab4ab9e380a515f1fb3e739110233a31ff95a8dc665bad45f41cabf"
MAX_LINES = 256
MAX_CROP_BYTES = 4 * 1024 * 1024


def _event(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


def _fail(code: str, message: str) -> int:
    _event({"event": "error", "code": code, "message": message[:1024]})
    return 2


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _apply_memory_limit(limit: int) -> None:
    if os.name == "nt":
        return
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, OSError, ValueError) as exc:
        raise RuntimeError("HTR_MEMORY_LIMIT_UNAVAILABLE") from exc


def _read_request() -> dict[str, Any]:
    raw = sys.stdin.buffer.readline()
    if not raw:
        raise ValueError("HTR_REQUEST_MISSING")
    data = json.loads(raw.decode("utf-8"))
    if not isinstance(data, dict) or set(data) != {
        "protocol_version", "request_id", "provider_id", "timeout_seconds", "memory_limit_bytes", "lines"
    }:
        raise ValueError("HTR_REQUEST_FIELDS_INVALID")
    if data["protocol_version"] != PROTOCOL_VERSION:
        raise ValueError("HTR_PROTOCOL_UNSUPPORTED")
    if data["provider_id"] not in {"crnn-rukopys", "trocr-rukopys"}:
        raise ValueError("HTR_PROVIDER_UNSUPPORTED")
    lines = data["lines"]
    if not isinstance(lines, list) or not 1 <= len(lines) <= MAX_LINES:
        raise ValueError("HTR_LINE_COUNT_INVALID")
    seen: set[str] = set()
    for line in lines:
        if not isinstance(line, dict) or set(line) != {"line_id", "crop_sha256", "png_base64"}:
            raise ValueError("HTR_LINE_FIELDS_INVALID")
        line_id = line["line_id"]
        if not isinstance(line_id, str) or not line_id or line_id in seen:
            raise ValueError("HTR_LINE_ID_INVALID")
        seen.add(line_id)
        crop = base64.b64decode(line["png_base64"].encode("ascii"), validate=True)
        if not crop or len(crop) > MAX_CROP_BYTES or hashlib.sha256(crop).hexdigest() != line["crop_sha256"]:
            raise ValueError("HTR_CROP_INVALID")
        line["_crop"] = crop
    return data


def _load_crnn(model_root: Path):
    path = model_root / "Hukyl--crnn-rukopys" / "best.pt"
    if not path.is_file():
        raise FileNotFoundError("HTR_CRNN_WEIGHTS_MISSING")
    if _hash_file(path) != CRNN_SHA256:
        raise ValueError("HTR_CRNN_WEIGHTS_HASH_MISMATCH")
    import cv2
    import torch
    import torch.nn as nn

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)

    class CRNN(nn.Module):
        def __init__(self, num_classes: int, rnn_hidden: int) -> None:
            super().__init__()
            self.cnn = nn.Sequential(
                nn.Conv2d(1, 64, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2, 2),
                nn.Conv2d(64, 128, 3, padding=1), nn.ReLU(), nn.MaxPool2d(2, 2),
                nn.Conv2d(128, 256, 3, padding=1), nn.BatchNorm2d(256), nn.ReLU(),
                nn.Conv2d(256, 256, 3, padding=1), nn.ReLU(), nn.MaxPool2d((2, 1)),
                nn.Conv2d(256, 512, 3, padding=1), nn.BatchNorm2d(512), nn.ReLU(),
                nn.Conv2d(512, 512, 3, padding=1), nn.ReLU(), nn.MaxPool2d((2, 1)),
            )
            # The published state dict stores this LSTM under rnn.0.
            self.rnn = nn.Sequential(nn.LSTM(512, rnn_hidden, bidirectional=True, batch_first=False))
            self.fc = nn.Linear(rnn_hidden * 2, num_classes)

        def forward(self, pixels):  # noqa: ANN001
            features = self.cnn(pixels)
            features = features.squeeze(2) if features.shape[2] == 1 else features.mean(dim=2)
            output, _hidden = self.rnn(features.permute(2, 0, 1))
            return torch.log_softmax(self.fc(output), dim=-1)

    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(checkpoint, dict):
        raise ValueError("HTR_CRNN_CHECKPOINT_INVALID")
    chars, config, state = checkpoint.get("chars"), checkpoint.get("config"), checkpoint.get("model_state")
    if not isinstance(chars, list) or not isinstance(config, dict) or not isinstance(state, dict):
        raise ValueError("HTR_CRNN_CHECKPOINT_INVALID")
    model = CRNN(len(chars), int(config["rnn_hidden"]))
    model.load_state_dict(state, strict=True)
    model.eval()

    def recognize(content: bytes) -> str:
        image = cv2.imdecode(__import__("numpy").frombuffer(content, dtype=__import__("numpy").uint8), cv2.IMREAD_GRAYSCALE)
        if image is None or image.size == 0:
            raise ValueError("HTR_CROP_DECODE_FAILED")
        height = int(config.get("img_height", 32))
        width = max(4, min(int(image.shape[1] * height / image.shape[0]), int(config.get("img_max_width", 512))))
        pixels = cv2.resize(image, (width, height), interpolation=cv2.INTER_AREA)
        tensor = (torch.from_numpy(pixels).float().unsqueeze(0) / 127.5 - 1.0).unsqueeze(0)
        with torch.inference_mode():
            indices = model(tensor)[:, 0, :].argmax(-1).tolist()
        output: list[str] = []
        previous: int | None = None
        for index in indices:
            if index != previous and index != 0:
                output.append(str(chars[index]))
            previous = index
        return "".join(output)

    return recognize, CRNN_REVISION, CRNN_SHA256


def _load_trocr(model_root: Path):
    directory = model_root / "Hukyl--trocr-rukopys"
    weights = directory / "model.safetensors"
    if not weights.is_file():
        raise FileNotFoundError("HTR_TROCR_WEIGHTS_MISSING")
    if _hash_file(weights) != TROCR_SHA256:
        raise ValueError("HTR_TROCR_WEIGHTS_HASH_MISMATCH")
    from PIL import Image
    from transformers import TrOCRProcessor, VisionEncoderDecoderModel
    import torch

    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    processor = TrOCRProcessor.from_pretrained(directory, local_files_only=True)
    model = VisionEncoderDecoderModel.from_pretrained(
        directory, local_files_only=True, trust_remote_code=False, use_safetensors=True,
    ).eval()
    model.config.use_cache = True
    model.generation_config.use_cache = True

    def recognize(content: bytes) -> str:
        image = Image.open(BytesIO(content)).convert("RGB")
        pixels = processor(images=image, return_tensors="pt").pixel_values
        generated = model.generate(pixels, num_beams=1, max_new_tokens=96, use_cache=True)
        return str(processor.batch_decode(generated, skip_special_tokens=True)[0])

    return recognize, TROCR_REVISION, TROCR_SHA256


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-root", required=True)
    args = parser.parse_args(argv)
    try:
        request = _read_request()
        _apply_memory_limit(int(request["memory_limit_bytes"]))
        if request["provider_id"] == "crnn-rukopys":
            recognize, revision, model_hash = _load_crnn(Path(args.model_root))
        else:
            recognize, revision, model_hash = _load_trocr(Path(args.model_root))
        results: list[dict[str, Any]] = []
        total = len(request["lines"])
        for completed, line in enumerate(request["lines"], start=1):
            started = time.monotonic()
            text = recognize(line["_crop"])
            results.append({
                "line_id": line["line_id"], "crop_sha256": line["crop_sha256"], "text": text,
                "elapsed_ms": (time.monotonic() - started) * 1000.0, "confidence": None,
            })
            _event({"event": "progress", "completed": completed, "total": total, "stage": "recognizing"})
        _event({"event": "complete", "lines": results, "model_revision": revision, "model_sha256": model_hash})
        return 0
    except Exception as exc:  # provider boundary: expose only bounded technical code/message
        code = str(exc) if str(exc).startswith("HTR_") else "HTR_PROVIDER_FAILED"
        return _fail(code, str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
