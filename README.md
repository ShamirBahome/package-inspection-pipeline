# Package Inspection Pipeline

Event-driven computer-vision pipeline that flags damaged packages — built as a portfolio project aligned with Amazon Robotics / SDE cloud-native work.

**Flow:** image lands in S3 → Lambda runs a damage detector → result written to DynamoDB → dashboard polls an API Gateway endpoint.

## Architecture

```
Camera / upload  →  S3  →  Lambda (ingest)  →  DynamoDB
                              ↑                      ↓
                     damage_detector.py        Lambda (API)
                                                     ↓
                                              dashboard/index.html
```

## Repo layout

```
package-inspection-pipeline/
├── model/
│   ├── damage_detector.py      # Classical CV detector (works out of the box)
│   └── train_classifier.py     # Optional ResNet18 transfer-learning upgrade
├── lambda/
│   ├── lambda_function.py      # S3-triggered ingest
│   ├── api_get_inspections.py  # HTTP GET /inspections
│   └── test_lambda_local.py    # Local test with mocked AWS
├── infra/
│   ├── setup_dynamodb.py
│   ├── iam_policy.json
│   └── deploy.sh
├── dashboard/
│   └── index.html
└── README.md
```

## Quick local test (no AWS)

```bash
# Needs: Python 3.10+, opencv-python, numpy
pip install opencv-python-headless numpy

python model/damage_detector.py
python lambda/test_lambda_local.py
```

Open `dashboard/index.html` in a browser — it shows demo data until you set `API_ENDPOINT`.

## AWS deploy (free tier friendly)

1. Configure credentials: `aws configure`
2. Create the DynamoDB table: `python infra/setup_dynamodb.py`
3. Create an IAM role for Lambda using `infra/iam_policy.json` (least privilege)
4. Create S3 bucket `package-images-bucket` (or rename consistently in policy + console)
5. Attach a public OpenCV Lambda Layer ARN for your region, then:

```bash
bash infra/deploy.sh <lambda-execution-role-arn> <opencv-layer-arn>
```

6. S3 → Event notification → invoke `package-inspection-ingest` on object create
7. API Gateway HTTP API → `GET /inspections` → `package-inspection-api` (enable CORS)
8. Paste the invoke URL into `dashboard/index.html` as `API_ENDPOINT`

## Why this design

- **Classical CV first** so the full pipeline is demoable without a labeled dataset
- **Same return shape** (`damaged`, `confidence`, `reason`) so you can swap in a trained CNN later without touching Lambda/AWS wiring
- **Separate ingest vs read Lambdas** for least-privilege IAM
- **GSI on status+timestamp** so the dashboard never full-table-scans
- **Failure records** written on errors so bad images show up instead of vanishing

## Resume bullet (example)

> Built an event-driven AWS package-inspection pipeline (S3 → Lambda → DynamoDB) with classical CV damage detection, a read API, and an ops-style dashboard; designed for swap-in of a trained CNN without changing cloud plumbing.
