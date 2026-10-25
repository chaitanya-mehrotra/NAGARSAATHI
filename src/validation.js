export const issueLabels = {
  pothole: "Pothole",
  waterlogging: "Waterlogging",
  both: "Both issues",
};
export const statusLabels = {
  open: "Open",
  in_progress: "In progress",
  resolved: "Resolved",
  rejected: "Rejected",
  submitted: "Submitted",
  under_review: "Under review",
};
export function validatePhoto(f) {
  return !f
    ? "Add a photo of the issue."
    : !["image/jpeg", "image/png", "image/webp"].includes(f.type)
      ? "Choose a JPEG, PNG or WebP image."
      : f.size > 10 * 1024 * 1024
        ? "Photo must be 10 MB or smaller."
        : "";
}
export function validateAnalysis(a) {
  if (
    !a ||
    typeof a.model_version !== "string" ||
    !Number.isInteger(a.image_width) ||
    !Number.isInteger(a.image_height) ||
    a.image_width < 1 ||
    a.image_height < 1 ||
    !Array.isArray(a.detections)
  )
    throw Error("Invalid analysis response");
  for (const d of a.detections)
    if (
      !["pothole", "waterlogging"].includes(d.class_name) ||
      !Number.isFinite(d.confidence) ||
      d.confidence < 0 ||
      d.confidence > 1 ||
      !Array.isArray(d.bbox) ||
      d.bbox.length !== 4 ||
      d.bbox.some((x) => !Number.isFinite(x)) ||
      d.bbox[0] < 0 ||
      d.bbox[1] < 0 ||
      d.bbox[2] > a.image_width ||
      d.bbox[3] > a.image_height ||
      d.bbox[0] >= d.bbox[2] ||
      d.bbox[1] >= d.bbox[3]
    )
      throw Error("Invalid detection response");
  return a;
}
export function verification(issue, detections) {
  const found = new Set(detections.map((d) => d.class_name));
  const expected = issue === "both" ? ["pothole", "waterlogging"] : [issue];
  const n = expected.filter((x) => found.has(x)).length;
  return n === expected.length
    ? "Supported by image"
    : n
      ? "Partially supported"
      : found.size
        ? "Possible mismatch"
        : "Could not verify";
}
