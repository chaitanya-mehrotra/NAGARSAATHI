import { test } from "node:test";
import assert from "node:assert/strict";
import { validatePhoto, validateAnalysis, verification } from "./validation.js";
test("uploads enforce type and size", () => {
  assert.match(validatePhoto({ type: "image/svg+xml", size: 50 }), /JPEG/);
  assert.match(validatePhoto({ type: "image/png", size: 10485761 }), /10 MB/);
  assert.equal(validatePhoto({ type: "image/webp", size: 10485760 }), "");
});
test("valid empty detections remain distinct from malformed analysis", () => {
  const empty = {
    model_version: "v1",
    image_width: 1280,
    image_height: 720,
    detections: [],
  };
  assert.equal(validateAnalysis(empty), empty);
  assert.throws(() => validateAnalysis({}));
  assert.equal(verification("pothole", []), "Could not verify");
});
test("boxes must be ordered and within original dimensions", () => {
  const a = {
    model_version: "v1",
    image_width: 1280,
    image_height: 720,
    detections: [
      { class_name: "pothole", confidence: 0.92, bbox: [100, 200, 400, 450] },
    ],
  };
  assert.equal(validateAnalysis(a), a);
  assert.throws(() =>
    validateAnalysis({
      ...a,
      detections: [{ ...a.detections[0], bbox: [400, 200, 100, 450] }],
    }),
  );
  assert.throws(() =>
    validateAnalysis({
      ...a,
      detections: [{ ...a.detections[0], confidence: 2 }],
    }),
  );
});
test("both selection allows partial support", () => {
  assert.equal(
    verification("both", [{ class_name: "pothole" }]),
    "Partially supported",
  );
  assert.equal(
    verification("pothole", [{ class_name: "waterlogging" }]),
    "Possible mismatch",
  );
  assert.equal(
    verification("both", [
      { class_name: "pothole" },
      { class_name: "waterlogging" },
    ]),
    "Supported by image",
  );
});
