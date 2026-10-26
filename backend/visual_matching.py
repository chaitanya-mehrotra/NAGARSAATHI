"""PC-only ORB/RANSAC matching of detected defect regions, not whole road backgrounds."""
import cv2
import numpy as np


def defect_crop(image, detections):
    boxes = [d['bbox_xyxy'] for d in detections if d['confidence'] >= .55]
    if not boxes:
        return None
    # A single distinctive defect is needed. Multiple-box photos need manual matching.
    if len(boxes) != 1:
        return None
    x1, y1, x2, y2 = boxes[0]
    return image.crop((int(x1), int(y1), int(x2), int(y2))).convert('L')


def compare_defects(first, first_detections, second, second_detections):
    a, b = defect_crop(first, first_detections), defect_crop(second, second_detections)
    empty = {'inliers': 0, 'inlier_ratio': 0.0, 'coverage': 0.0}
    if a is None or b is None or min(*a.size, *b.size) < 40:
        return empty
    def resized(photo):
        photo = photo.copy()
        photo.thumbnail((640, 640))
        return np.asarray(photo)
    aa, bb = resized(a), resized(b)
    orb = cv2.ORB_create(nfeatures=1500, edgeThreshold=12, fastThreshold=10)
    ka, da = orb.detectAndCompute(aa, None)
    kb, db = orb.detectAndCompute(bb, None)
    if da is None or db is None or len(da) < 20 or len(db) < 20:
        return empty
    pairs = cv2.BFMatcher(cv2.NORM_HAMMING).knnMatch(da, db, k=2)
    good = [m for pair in pairs if len(pair) == 2 for m, n in [pair] if m.distance < .7 * n.distance]
    # Several query points mapping to the same target are not independent evidence.
    unique = {m.trainIdx: m for m in sorted(good, key=lambda m: -m.distance)}
    good = list(unique.values())
    if len(good) < 20:
        return empty
    pa = np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    pb = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
    transform, mask = cv2.findHomography(pa, pb, cv2.RANSAC, 3.0)
    if transform is None or mask is None or not np.isfinite(transform).all():
        return empty
    inliers = int(mask.sum())
    selected = mask.ravel().astype(bool)
    if inliers < 4:
        return empty
    coverage = min(cv2.contourArea(cv2.convexHull(pa[selected])) / (aa.shape[0] * aa.shape[1]),
                   cv2.contourArea(cv2.convexHull(pb[selected])) / (bb.shape[0] * bb.shape[1]))
    return {'inliers':inliers, 'inlier_ratio':inliers / len(good), 'coverage':min(1.0, max(0.0,float(coverage)))}
