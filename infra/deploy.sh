#!/bin/bash
# deploy.sh
# ---------
# Packages and deploys both Lambda functions.
#
# IMPORTANT: opencv-python is too large (100MB+) to just pip-install into
# a plain Lambda zip - Lambda's zipped deployment package limit is 50MB
# (250MB unzipped). Two ways to handle this:
#   Option A (used below): use a prebuilt "opencv-python-headless" Lambda
#             Layer (search "opencv lambda layer" - several public ARNs
#             exist per AWS region), so your own zip only needs your code.
#   Option B: package the whole thing as a container image instead
#             (Lambda supports up to 10GB container images). More setup,
#             but avoids depending on someone else's public layer.
# This script uses Option A since it's the fastest path to a working demo.
#
# Prerequisites:
#   - AWS CLI installed and configured (aws configure)
#   - An IAM role already created for Lambda execution, using
#     infra/iam_policy.json as its permissions policy
#   - Run infra/setup_dynamodb.py first
#
# Usage:
#   bash deploy.sh <lambda-execution-role-arn> <opencv-layer-arn>

set -e  # stop immediately if any command fails

ROLE_ARN=$1
OPENCV_LAYER_ARN=$2

if [ -z "$ROLE_ARN" ] || [ -z "$OPENCV_LAYER_ARN" ]; then
  echo "Usage: bash deploy.sh <lambda-execution-role-arn> <opencv-layer-arn>"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT_DIR"

echo "== Packaging image-processing Lambda (S3 trigger) =="
mkdir -p build/ingest
cp lambda/lambda_function.py build/ingest/
cp model/damage_detector.py build/ingest/
(cd build/ingest && zip -r ../ingest.zip .)

echo "== Deploying ingest Lambda =="
aws lambda create-function \
  --function-name package-inspection-ingest \
  --runtime python3.12 \
  --role "$ROLE_ARN" \
  --handler lambda_function.lambda_handler \
  --zip-file fileb://build/ingest.zip \
  --layers "$OPENCV_LAYER_ARN" \
  --timeout 30 \
  --memory-size 512 \
  --environment "Variables={DYNAMODB_TABLE=PackageInspections}" \
  || aws lambda update-function-code \
       --function-name package-inspection-ingest \
       --zip-file fileb://build/ingest.zip
# ^ if create-function fails because it already exists, update it instead

echo "== Packaging read API Lambda (no CV deps needed - lighter package) =="
mkdir -p build/api
cp lambda/api_get_inspections.py build/api/
(cd build/api && zip -r ../api.zip .)

echo "== Deploying read API Lambda =="
aws lambda create-function \
  --function-name package-inspection-api \
  --runtime python3.12 \
  --role "$ROLE_ARN" \
  --handler api_get_inspections.lambda_handler \
  --zip-file fileb://build/api.zip \
  --timeout 10 \
  --memory-size 128 \
  --environment "Variables={DYNAMODB_TABLE=PackageInspections}" \
  || aws lambda update-function-code \
       --function-name package-inspection-api \
       --zip-file fileb://build/api.zip

echo ""
echo "Done. Remaining manual steps (one-time, via AWS Console):"
echo "  1. S3 bucket 'package-images-bucket' -> Properties -> Event notifications"
echo "     -> trigger 'package-inspection-ingest' on 'All object create events'"
echo "  2. API Gateway -> Create HTTP API -> GET /inspections -> integrate with"
echo "     'package-inspection-api' -> enable CORS -> copy the invoke URL"
echo "  3. Paste that invoke URL into dashboard/index.html's API_ENDPOINT constant"
