"""
test_lambda_local.py
---------------------
Lets you verify lambda_function.py's logic works correctly BEFORE
deploying to real AWS, by faking boto3's S3 and DynamoDB clients.
This is not a replacement for testing against a real (or moto-mocked)
AWS environment before going live - it's a fast sanity check.

Run with:
    python test_lambda_local.py
"""

import sys
import types
from unittest.mock import MagicMock

import cv2
import numpy as np


def make_fake_image_bytes(damaged: bool) -> bytes:
    """Reuse the same synthetic image generator idea as damage_detector.py's
    self-test, so this script has no external dependency on real photos."""
    canvas = np.full((300, 300, 3), 255, dtype=np.uint8)
    if not damaged:
        cv2.rectangle(canvas, (60, 60), (240, 240), (40, 40, 40), thickness=3)
    else:
        pts = np.array([
            [60, 60], [150, 90], [240, 60], [210, 150],
            [240, 240], [150, 210], [60, 240], [90, 150],
        ], dtype=np.int32)
        cv2.fillPoly(canvas, [pts], color=(80, 80, 80))
        cv2.polylines(canvas, [pts], isClosed=True, color=(20, 20, 20), thickness=2)
    _, buf = cv2.imencode(".png", canvas)
    return buf.tobytes()


def build_fake_boto3(image_bytes: bytes):
    """Create a fake `boto3` module: get_object() returns our synthetic
    image, and put_item() just records what it was called with so we can
    assert on it."""
    fake_boto3 = types.ModuleType("boto3")

    fake_s3 = MagicMock()
    fake_s3.get_object.return_value = {
        "Body": MagicMock(read=MagicMock(return_value=image_bytes))
    }

    fake_table = MagicMock()
    written_items = []
    fake_table.put_item.side_effect = lambda Item: written_items.append(Item)

    fake_dynamodb_resource = MagicMock()
    fake_dynamodb_resource.Table.return_value = fake_table

    fake_boto3.client = lambda service, **kw: fake_s3 if service == "s3" else MagicMock()
    fake_boto3.resource = lambda service, **kw: fake_dynamodb_resource if service == "dynamodb" else MagicMock()

    return fake_boto3, written_items


def run_test(damaged: bool):
    image_bytes = make_fake_image_bytes(damaged)
    fake_boto3, written_items = build_fake_boto3(image_bytes)

    # Inject the fake boto3 BEFORE importing lambda_function, so its
    # top-level `import boto3` picks up our fake instead of the real SDK
    sys.modules["boto3"] = fake_boto3
    sys.modules.pop("lambda_function", None)  # force re-import with the fake
    # Make sure damage_detector is importable from sibling/model path
    import os
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    model_path = os.path.join(root, "model")
    if model_path not in sys.path:
        sys.path.insert(0, model_path)
    if os.path.dirname(__file__) not in sys.path:
        sys.path.insert(0, os.path.dirname(__file__))

    import lambda_function

    fake_event = {
        "Records": [{
            "s3": {
                "bucket": {"name": "test-bucket"},
                "object": {"key": f"incoming/{'damaged' if damaged else 'intact'}.png"},
            }
        }]
    }

    response = lambda_function.lambda_handler(fake_event, context=None)
    print(f"\n--- Test case: {'damaged' if damaged else 'intact'} package ---")
    print("Lambda response:", response)
    print("Item written to DynamoDB:", written_items[0])
    assert written_items[0]["damaged"] == damaged, "Verdict didn't match expected outcome!"
    print("PASSED")


if __name__ == "__main__":
    run_test(damaged=False)
    run_test(damaged=True)
    print("\nAll local Lambda tests passed.")
