"""
lambda_function.py
-------------------
This is the function AWS Lambda runs automatically every time a new image
lands in the S3 bucket. It:
  1. Reads which file triggered it from the S3 event payload
  2. Downloads that image from S3
  3. Runs it through the CV classifier (damage_detector.py)
  4. Writes the verdict to DynamoDB so the dashboard can display it

DEPLOYMENT NOTE:
Lambda needs damage_detector.py (and its dependency, opencv) packaged
alongside this file. See infra/deploy.sh for how to build that zip,
since opencv-python is too large to just pip install inline - Lambda
has a package size limit, so production setups typically use a Lambda
Layer or a container image. deploy.sh documents both options.

TRIGGER SETUP (done once, via AWS Console or CloudFormation):
    S3 bucket "package-images-bucket" -> Event notification on
    "PUT" / "ObjectCreated" -> invoke this Lambda function.
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3

from damage_detector import classify_package

# Environment variables set in the Lambda console (Configuration > Environment variables)
# so we never hardcode resource names in code.
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "PackageInspections")

s3_client = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(DYNAMODB_TABLE)


def lambda_handler(event, context):
    """
    Entry point AWS invokes. `event` is the S3 event notification payload,
    which looks like:
    {
      "Records": [
        {
          "s3": {
            "bucket": {"name": "package-images-bucket"},
            "object": {"key": "incoming/photo123.jpg"}
          }
        }
      ]
    }
    """
    results = []

    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        # S3 keys can be URL-encoded (e.g. spaces become '+'); decode before use
        key = record["s3"]["object"]["key"].replace("+", " ")

        try:
            result = process_image(bucket, key)
            results.append(result)
        except Exception as exc:
            # Never let one bad image crash the whole batch - log and continue,
            # and still write a record so the dashboard shows the failure
            # instead of the item silently vanishing.
            print(f"ERROR processing s3://{bucket}/{key}: {exc}")
            write_failure_record(bucket, key, str(exc))
            results.append({"key": key, "error": str(exc)})

    return {
        "statusCode": 200,
        "body": json.dumps({"processed": len(results), "results": results}),
    }


def process_image(bucket: str, key: str) -> dict:
    """Download one image from S3, classify it, and persist the result."""
    print(f"Processing s3://{bucket}/{key}")

    response = s3_client.get_object(Bucket=bucket, Key=key)
    image_bytes = response["Body"].read()

    verdict = classify_package(image_bytes)

    record = {
        "inspection_id": str(uuid.uuid4()),   # DynamoDB partition key
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bucket": bucket,
        "image_key": key,
        "damaged": verdict["damaged"],
        "confidence": verdict["confidence"],
        "reason": verdict["reason"],
        "status": "completed",
    }

    table.put_item(Item=record)
    print(f"Wrote result for {key}: damaged={verdict['damaged']} "
          f"confidence={verdict['confidence']}")

    return record


def write_failure_record(bucket: str, key: str, error_message: str) -> None:
    """So a corrupt/unreadable image shows up on the dashboard as
    'needs review' instead of just disappearing without a trace."""
    table.put_item(Item={
        "inspection_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "bucket": bucket,
        "image_key": key,
        "damaged": None,
        "confidence": 0.0,
        "reason": f"processing error: {error_message}",
        "status": "failed",
    })
