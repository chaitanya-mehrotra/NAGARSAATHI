import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

from backend import inference


class Tensor:
    def __init__(self, values):
        self.values = values

    def cpu(self):
        return self

    def tolist(self):
        return self.values


class CombinedInferenceTests(unittest.TestCase):
    def detect(self, classes, scores):
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / "photo.png"
            Image.new("RGB", (100, 80)).save(image)
            boxes = SimpleNamespace(
                xyxy=Tensor([[1, 2, 90, 70] for _ in classes]),
                conf=Tensor(scores), cls=Tensor(classes),
            )
            model = Mock()
            model.predict.return_value = [SimpleNamespace(boxes=boxes)]
            with patch.object(inference, "load_model", return_value=model):
                return inference.detect_potholes(image)

    def test_both_labels_are_reported_with_original_coordinates(self):
        result = self.detect([0, 1], [.8, .9])
        self.assertEqual([box["label"] for box in result["detections"]],
                         ["waterlogging", "pothole"])
        self.assertEqual(result["image_width"], 100)
        self.assertEqual(result["image_height"], 80)
        self.assertEqual(result["detections"][0]["bbox_xyxy"], [1, 2, 90, 70])
        self.assertEqual(result["model_version"], "nagarsaathi-yolo11n-v3")

    def test_scores_below_threshold_are_not_reported(self):
        self.assertEqual(self.detect([1], [.2])["detections"], [])

    def test_empty_result_remains_a_successful_empty_analysis(self):
        self.assertEqual(self.detect([], [])["detections"], [])

    def test_unknown_class_is_not_renamed_to_a_pothole(self):
        with self.assertRaisesRegex(RuntimeError, "Unexpected model class"):
            self.detect([2], [.9])
