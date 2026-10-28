"""Real photo validation with the trained YOLO11n pothole/waterlogging detector.

The detector only assists review: a photo that does not support the citizen's
claimed category is never rejected automatically, it is routed to human review
and flagged (see jobs.py).
"""

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from threading import RLock
from typing import Any

from PIL import Image, ImageOps
from sqlalchemy import Engine, text

from app.adapters.storage import build_media_storage
from app.schemas import AcceptedLabel, ValidationRequest, ValidationResult
from app.settings import PROJECT_ROOT, Settings


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else PROJECT_ROOT / path


class YoloValidator:
    def __init__(self, settings: Settings, engine: Engine) -> None:
        self.settings = settings
        self.engine = engine
        self.media = build_media_storage(settings)
        self.weights = _resolve(settings.yolo_model_path)
        self.metadata: dict[str, Any] = json.loads(
            _resolve(settings.yolo_metadata_path).read_text(encoding="utf-8")
        )
        self._model: Any = None
        self._lock = RLock()

    def load(self) -> None:
        """Load once; verify the checkpoint hash and class map before any prediction."""
        with self._lock:
            if self._model is not None:
                return
            if hashlib.sha256(self.weights.read_bytes()).hexdigest() != self.metadata["model_sha256"]:
                raise RuntimeError("Checkpoint does not match the model metadata")
            from ultralytics import YOLO

            model = YOLO(str(self.weights))
            expected = {int(key): value for key, value in self.metadata["class_map"].items()}
            if dict(model.names) != expected:
                raise RuntimeError("Model classes do not match the model metadata")
            self._model = model

    def detect(self, content: bytes) -> list[dict[str, Any]]:
        with Image.open(BytesIO(content)) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
        settings = self.metadata["input_settings"]
        threshold = self.metadata["confidence_threshold"]
        self.load()
        with self._lock:
            result = self._model.predict(
                source=image,
                imgsz=settings["imgsz"],
                conf=settings["candidate_confidence"],
                iou=settings["nms_iou"],
                max_det=settings["max_det"],
                rect=True,
                half=False,
                augment=False,
                device=self.settings.yolo_device,
                verbose=False,
                save=False,
            )[0]
        found: list[dict[str, Any]] = []
        if result.boxes is not None:
            for score, class_id in zip(
                result.boxes.conf.cpu().tolist(), result.boxes.cls.cpu().tolist(), strict=True
            ):
                label = self.metadata["class_map"].get(str(int(class_id)))
                if label is None:
                    raise RuntimeError("Unexpected model class")
                if score >= threshold:
                    found.append({"label": label, "confidence": float(score)})
        return found

    def _lookup(self, request: ValidationRequest) -> tuple[str, str]:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text("""
                SELECT m.storage_key, r.claimed_category FROM media m
                JOIN reports r ON r.id=m.report_id
                WHERE m.id=:media AND r.id=:report AND m.original_sha256=:sha
            """),
                    {
                        "media": request.media_id,
                        "report": request.report_id,
                        "sha": request.media_sha256,
                    },
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            raise RuntimeError("Media is not bound to this report and hash")
        return row["storage_key"], row["claimed_category"]

    def _validate(self, request: ValidationRequest) -> ValidationResult:
        key, claimed = self._lookup(request)
        content = self.media.read(key)
        if hashlib.sha256(content).hexdigest() != request.media_sha256:
            raise RuntimeError("Stored photo does not match its recorded hash")
        best: dict[str, float] = {}
        for item in self.detect(content):
            best[item["label"]] = max(best.get(item["label"], 0.0), item["confidence"])
        base = {
            **request.model_dump(),
            "provider": "model",
            "provider_version": self.metadata["model_version"],
            "completed_at": datetime.now(UTC),
        }
        if not best:
            return ValidationResult(
                **base,
                decision="needs_review",
                labels=[],
                reason="no_pothole_or_waterlogging_detected",
            )
        # If the claimed defect is among the detections, the photo supports the claim.
        if claimed == "both" and {"pothole", "waterlogging"} <= best.keys():
            labels = {"both": min(best["pothole"], best["waterlogging"])}
        else:
            labels = {claimed: best[claimed]} if claimed in best else best
        return ValidationResult(
            **base,
            decision="accepted",
            labels=[AcceptedLabel(label=name, confidence=score) for name, score in labels.items()],
            reason=None,
        )

    async def validate(self, request: ValidationRequest) -> ValidationResult:
        return await asyncio.to_thread(self._validate, request)
