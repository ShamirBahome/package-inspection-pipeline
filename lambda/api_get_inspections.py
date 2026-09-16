"""
api_get_inspections.py
-----------------------
A second, separate Lambda function - this one is NOT triggered by S3.
It's triggered by API Gateway (a plain HTTP GET request) and its only
job is to read recent results from DynamoDB and hand them back as JSON
so the dashboard (dashboard/index.html) has something to fetch.

Kept as its own function (rather than piling this onto lambda_function.py)
because it has a completely different trigger type and IAM permissions -
read-only DynamoDB access, no S3 access needed at all. Separating them
keeps each function's permissions minimal and its purpose obvious.

DEPLOYMENT:
    API Gateway (HTTP API) -> GET /inspections -> this Lambda
    Enable CORS on the API Gateway route so the dashboard (served from
    a different origin, e.g. S3 static site or localhost) can call it.
"""

import json
import os

import boto3
from boto3.dynamodb.conditions import Key

DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "PackageInspections")
DEFAULT_LIMIT = 50

dynamodb = boto3.resource("dynamodb")
table = dynamodb.Table(DYNAMODB_TABLE)


def lambda_handler(event, context):
    """
    Handles GET /inspections?status=completed&limit=20

    Returns the most recent inspections, newest first, using the
    status-timestamp-index GSI so this is a fast indexed query instead
    of a full table scan (which gets slow and expensive as data grows).
    """
    query_params = event.get("queryStringParameters") or {}
    status = query_params.get("status", "completed")
    limit = min(int(query_params.get("limit", DEFAULT_LIMIT)), 200)  # cap to prevent abuse

    try:
        response = table.query(
            IndexName="status-timestamp-index",
            KeyConditionExpression=Key("status").eq(status),
            ScanIndexForward=False,  # False = descending, so newest results come first
            Limit=limit,
        )
        items = response.get("Items", [])
    except Exception as exc:
        return _response(500, {"error": str(exc)})

    return _response(200, {"count": len(items), "items": items})


def _response(status_code: int, body: dict) -> dict:
    """API Gateway (HTTP API / proxy integration) expects this exact shape."""
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            # Required so the dashboard, likely served from a different
            # origin, is allowed by the browser to read this response.
            "Access-Control-Allow-Origin": "*",
        },
        "body": json.dumps(body, default=str),  # default=str handles Decimal from DynamoDB
    }
