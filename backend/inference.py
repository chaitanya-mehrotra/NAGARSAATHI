"""Combined detector. Box coordinates refer to the EXIF-corrected RGB image."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from threading import RLock

from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parent
def configured_path(value):
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path

METADATA = json.loads(configured_path(os.environ.get(
    "MODEL_METADATA_PATH", "backend/combined_model_metadata.json"
)).read_text())
_LOCK = RLock()
_MODEL = None
_DEVICE = os.environ.get("NAGARSAATHI_DEVICE", "cpu")


def load_model():
    """Call once during backend startup; subsequent calls reuse this process's model."""
    global _MODEL
    with _LOCK:
        if _MODEL is None:
            from ultralytics import YOLO
            weights = configured_path(os.environ.get(
                "YOLO_MODEL_PATH", "backend/models/nagarsaathi-combined-v3.pt"
            ) or "backend/models/nagarsaathi-combined-v3.pt")
            if hashlib.sha256(weights.read_bytes()).hexdigest() != METADATA["model_sha256"]:
                raise RuntimeError("Checkpoint does not match the selected model metadata")
            config_dir = Path(os.environ.get("NAGARSAATHI_DATA_DIR", ROOT / "data")) / "ultralytics"
            config_dir.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("YOLO_CONFIG_DIR", str(config_dir))
            os.environ.setdefault("YOLO_AUTOINSTALL", "false")
            candidate = YOLO(str(weights))
            expected = {int(key): value for key, value in METADATA["class_map"].items()}
            if dict(candidate.names) != expected:
                raise RuntimeError("Model classes do not match the selected metadata")
            _MODEL = candidate
        return _MODEL


def _read_image(image_path):
    with Image.open(image_path) as image:
        if image.format not in {"JPEG", "PNG"}:
            raise ValueError("Use a JPEG or PNG photo")
        if getattr(image, "n_frames", 1) != 1:
            raise ValueError("Use a single-frame photo")
        return ImageOps.exif_transpose(image).convert("RGB")


def canonicalize_image(source_path, destination_path):
    """Save an orientation-corrected PNG for both detection and frontend display."""
    destination = Path(destination_path)
    if destination.suffix.lower() != ".png":
        raise ValueError("The canonical destination must end in .png")
    image = _read_image(source_path)
    # Fresh image removes metadata, including EXIF orientation.
    canonical = Image.new("RGB", image.size)
    canonical.paste(image)
    canonical.save(destination, format="PNG")
    return str(destination)


def detect_potholes(image_path) -> dict:
    """Return the brief's detection fields; raise on failure, never fake success.

    Backend should pass its saved canonical image. Input orientation is corrected
    defensively; returned dimensions/boxes always refer to that corrected image.
    Backend owns analysis_status and review_state.
    """
    image = _read_image(image_path)
    width, height = image.size
    settings = METADATA["input_settings"]
    threshold = METADATA["confidence_threshold"]
    detections = []
    with _LOCK:
        model = load_model()
        result = model.predict(
            source=image, imgsz=settings["imgsz"],
            # Match the evaluation pipeline: low-score NMS, then threshold.
            conf=settings["candidate_confidence"], iou=settings["nms_iou"],
            max_det=settings["max_det"], rect=True, half=False,
            augment=False, device=_DEVICE, verbose=False, save=False,
        )[0]
        if result.boxes is not None:
            coordinates = result.boxes.xyxy.cpu().tolist()
            confidences = result.boxes.conf.cpu().tolist()
            classes = result.boxes.cls.cpu().tolist()
            for box, score, class_id in zip(coordinates, confidences, classes):
                if score < threshold:
                    continue
                label = METADATA["class_map"].get(str(int(class_id)))
                if label not in {"pothole", "waterlogging"}:
                    raise RuntimeError("Unexpected model class")
                x1, y1, x2, y2 = box
                box = [max(0.0, min(float(x1), width)),
                       max(0.0, min(float(y1), height)),
                       max(0.0, min(float(x2), width)),
                       max(0.0, min(float(y2), height))]
                if box[2] <= box[0] or box[3] <= box[1]:
                    continue
                detections.append({"class_id": int(class_id), "label": label,
                                   "confidence": float(score), "bbox_xyxy": box})
    detections.sort(key=lambda entry: entry["confidence"], reverse=True)
    return {"image_width": width, "image_height": height,
            "model_version": METADATA["model_version"],
            "confidence_threshold": threshold, "detections": detections}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the NAGARSAATHI pothole/waterlogging model")
    parser.add_argument("image", help="Path to a JPEG or PNG")
    parser.add_argument("--output", default="prediction.json")
    parser.add_argument("--annotated", default="prediction.jpg")
    args = parser.parse_args()
    prediction = detect_potholes(args.image)
    Path(args.output).write_text(json.dumps(prediction, indent=2))
    from PIL import ImageDraw
    photo = _read_image(args.image)
    draw = ImageDraw.Draw(photo)
    for detection in prediction["detections"]:
        box = detection["bbox_xyxy"]
        draw.rectangle(box, outline="red", width=3)
        draw.text((box[0], max(0, box[1] - 14)),
                  f"{detection['label']} {detection['confidence']:.2f}", fill="red")
    photo.save(args.annotated)
    print(json.dumps(prediction, indent=2))
    print(f"Saved {args.output} and {args.annotated}")
