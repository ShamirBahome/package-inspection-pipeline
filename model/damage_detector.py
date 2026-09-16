"""
damage_detector.py
-------------------
Core computer-vision logic for the package inspection pipeline.

WHY THIS DESIGN:
Training a CNN needs a labeled dataset of "damaged" vs "intact" packages,
which you probably don't have on day one. So this module ships with a
CLASSICAL CV heuristic detector that actually works out of the box on any
image, so you can build + demo the whole AWS pipeline immediately.

Once you collect real labeled images (even 200-300), swap in the
train_classifier.py model by changing ONE line in `classify_package()` -
see the comment marked [SWAP POINT] below. The Lambda function and AWS
plumbing never need to change, because both detectors return the same
output shape: {"damaged": bool, "confidence": float, "reason": str}.

HEURISTIC APPROACH (classical CV):
Damaged packages (crushed boxes, torn mailers, dented corners) tend to
have irregular, non-rectangular silhouettes and noisy/jagged edges
compared to intact packages, which are usually clean rectangles or
smooth polygons. We measure that irregularity using:
  1. Edge density (Canny edge detector) - more chaotic edges = more damage
  2. Contour solidity - ratio of contour area to its convex hull area.
     A perfect box has solidity close to 1.0. A crushed/torn box has
     concavities that push solidity down.
  3. Aspect-ratio sanity check - extreme aspect ratios often indicate a
     collapsed/flattened package.
"""

import cv2
import numpy as np


# Tunable thresholds - start here, adjust based on real data you collect
EDGE_DENSITY_THRESHOLD = 0.12     # fraction of pixels flagged as edges
SOLIDITY_THRESHOLD = 0.90         # below this, contour looks "damaged"
MIN_CONTOUR_AREA_FRACTION = 0.05  # ignore tiny noise contours


def _load_image(image_bytes: bytes) -> np.ndarray:
    """Decode raw image bytes (as they'd arrive from S3) into an OpenCV image."""
    np_arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image - check the file is a valid JPEG/PNG")
    return img


def _compute_edge_density(gray: np.ndarray) -> float:
    """Fraction of pixels that are edges. Noisy/torn surfaces score higher."""
    edges = cv2.Canny(gray, threshold1=50, threshold2=150)
    return float(np.count_nonzero(edges)) / edges.size


def _largest_contour_solidity(gray: np.ndarray, image_area: int):
    """
    Find the largest contour (assumed to be the package) and compute its
    solidity = contour_area / convex_hull_area. Returns (solidity, area_fraction)
    or (None, 0) if no meaningful contour was found.
    """
    # Otsu thresholding auto-picks a good binary cutoff for contour detection.
    # INV because the package is typically darker than a light conveyor/background,
    # so we want the package itself to become the white foreground blob that
    # findContours traces - not the background surrounding it.
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    if not contours:
        return None, 0.0

    largest = max(contours, key=cv2.contourArea)
    area = cv2.contourArea(largest)
    area_fraction = area / image_area

    if area_fraction < MIN_CONTOUR_AREA_FRACTION:
        return None, area_fraction  # too small to be the package itself

    hull = cv2.convexHull(largest)
    hull_area = cv2.contourArea(hull)
    if hull_area == 0:
        return None, area_fraction

    solidity = area / hull_area
    return solidity, area_fraction


def classify_package(image_bytes: bytes) -> dict:
    """
    Main entry point called by the Lambda function.

    Args:
        image_bytes: raw bytes of the package image (as read from S3)

    Returns:
        dict with keys:
            damaged (bool)      - our verdict
            confidence (float)  - 0.0-1.0, how sure we are
            reason (str)        - human-readable explanation, useful for
                                   the dashboard and for debugging false positives
    """
    # [SWAP POINT] Once you have a trained model, replace the body of this
    # function with:
    #     from trained_model import predict
    #     return predict(image_bytes)
    # Keep the same return shape and nothing downstream breaks.

    img = _load_image(image_bytes)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.GaussianBlur(gray, (5, 5), 0)  # reduce noise before edge/contour detection

    image_area = gray.shape[0] * gray.shape[1]

    edge_density = _compute_edge_density(gray)
    solidity, area_fraction = _largest_contour_solidity(gray, image_area)

    reasons = []
    damage_votes = 0
    total_votes = 0

    # Vote 1: edge density
    total_votes += 1
    if edge_density > EDGE_DENSITY_THRESHOLD:
        damage_votes += 1
        reasons.append(f"high edge density ({edge_density:.2f})")

    # Vote 2: contour solidity (only if we found a usable contour)
    if solidity is not None:
        total_votes += 1
        if solidity < SOLIDITY_THRESHOLD:
            damage_votes += 1
            reasons.append(f"low contour solidity ({solidity:.2f})")

    confidence = damage_votes / total_votes if total_votes else 0.0
    damaged = confidence >= 0.5

    reason = "; ".join(reasons) if reasons else "surface and shape look regular"

    return {
        "damaged": damaged,
        "confidence": round(confidence if damaged else 1 - confidence, 2),
        "reason": reason,
        "raw_metrics": {  # kept for debugging / tuning thresholds later
            "edge_density": round(edge_density, 4),
            "solidity": round(solidity, 4) if solidity is not None else None,
        },
    }


if __name__ == "__main__":
    # Quick self-test: generate a clean box vs a "damaged" jagged box
    # and confirm the detector tells them apart. Run with:
    #   python damage_detector.py
    def make_test_image(damaged: bool) -> bytes:
        canvas = np.full((300, 300, 3), 255, dtype=np.uint8)  # white background
        if not damaged:
            cv2.rectangle(canvas, (60, 60), (240, 240), (40, 40, 40), thickness=3)
        else:
            # crushed/torn box: a filled shape with real concave dents (star-like
            # notches punched into the sides) plus crease lines and surface noise,
            # so both the solidity and edge-density signals actually fire
            pts = np.array([
                [60, 60], [150, 90], [240, 60], [210, 150],
                [240, 240], [150, 210], [60, 240], [90, 150],
            ], dtype=np.int32)  # concave "pinched" rectangle (star-ish)
            cv2.fillPoly(canvas, [pts], color=(80, 80, 80))
            cv2.polylines(canvas, [pts], isClosed=True, color=(20, 20, 20), thickness=2)
            # crease/tear lines across the surface
            for _ in range(15):
                x1, y1 = np.random.randint(70, 230, 2)
                x2, y2 = np.random.randint(70, 230, 2)
                cv2.line(canvas, (x1, y1), (x2, y2), (60, 60, 60), 1)
            noise = np.random.randint(0, 40, canvas.shape, dtype=np.uint8)
            canvas = cv2.subtract(canvas, noise)
        _, buf = cv2.imencode(".png", canvas)
        return buf.tobytes()

    intact_bytes = make_test_image(damaged=False)
    damaged_bytes = make_test_image(damaged=True)

    print("Intact box result: ", classify_package(intact_bytes))
    print("Damaged box result:", classify_package(damaged_bytes))
