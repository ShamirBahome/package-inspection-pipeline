# Package Inspection Pipeline

Upload a photo of a package → the system automatically checks it for damage → results show up on a live dashboard.

This is a small, end-to-end **AWS + computer vision** project: event-driven, serverless, and free-tier friendly. Good portfolio piece for cloud / robotics / fulfillment-style roles.

---

## What it does

1. You upload an image to an **S3** bucket (stand-in for a camera on a conveyor).
2. S3 triggers a **Lambda** function.
3. The Lambda runs a **damage detector** (classical OpenCV heuristics out of the box).
4. The verdict is saved in **DynamoDB**.
5. A second Lambda exposes results over **API Gateway**.
6. The **dashboard** polls that API and shows CLEARED vs FLAGGED packages.

```
  Image upload
       │
       ▼
      S3  ──triggers──►  Lambda (ingest)
                              │
                              │  classify_package()
                              ▼
                          DynamoDB
                              │
                              ▼
                     Lambda (read API)  ◄── GET /inspections
                              │
                              ▼
                         Dashboard
```

**Example result**

```json
{
  "damaged": true,
  "confidence": 0.81,
  "reason": "low contour solidity (0.62); high edge density (0.19)"
}
```

---

## Who this is for

- You want a **working demo** you can show in interviews (local tests + optional live AWS).
- You care about **cloud-native plumbing** (S3 events, Lambda, DynamoDB, API Gateway), not only a model in a notebook.
- You may later swap the heuristic detector for a trained CNN without rewriting the AWS side.

---

## Repo structure

| Path | Purpose |
|------|---------|
| `model/damage_detector.py` | Damage detection (works with no training data) |
| `model/train_classifier.py` | Optional ResNet18 upgrade once you have labeled photos |
| `lambda/lambda_function.py` | Ingest Lambda — S3 → classify → DynamoDB |
| `lambda/api_get_inspections.py` | Read API Lambda — `GET /inspections` |
| `lambda/test_lambda_local.py` | Local test with mocked AWS |
| `infra/setup_dynamodb.py` | Creates the DynamoDB table |
| `infra/iam_policy.json` | Least-privilege IAM policy for the Lambdas |
| `infra/deploy.sh` | Packages and deploys both Lambdas |
| `dashboard/index.html` | Simple live / demo dashboard |

---

## Prerequisites

**Local demo (no AWS)**

- Python 3.10+
- `pip`

**Full AWS deploy**

- An AWS account ([free tier](https://aws.amazon.com/free/) is enough)
- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html) installed
- Credentials configured (`aws configure`)

---

## 1. Run it locally (no AWS needed)

Clone and install:

```bash
git clone https://github.com/ShamirBahome/package-inspection-pipeline.git
cd package-inspection-pipeline

python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### Test the damage detector

```bash
python model/damage_detector.py
```

You should see one **intact** and one **damaged** synthetic box classified differently.

### Test the Lambda logic (mocked S3 / DynamoDB)

```bash
cd lambda
python test_lambda_local.py
cd ..
```

Both test cases should print `PASSED`.

### Preview the dashboard

Open `dashboard/index.html` in your browser (double-click or drag into Chrome/Safari).

It uses **demo data** until you point `API_ENDPOINT` at a real API Gateway URL (see deploy steps below).

---

## 2. Deploy to AWS (step by step)

Pick a region and stick to it (examples use `us-east-1`). Replace names if you change them — keep S3 bucket name, table name, and IAM ARNs consistent.

### Step A — Configure AWS CLI

```bash
aws configure
```

Enter access key, secret, default region (e.g. `us-east-1`), and output format `json`.

Confirm:

```bash
aws sts get-caller-identity
```

### Step B — Create the DynamoDB table

```bash
pip install boto3   # if not already installed
python infra/setup_dynamodb.py
```

This creates table `PackageInspections` with a GSI `status-timestamp-index` (used by the dashboard API).

### Step C — Create the S3 bucket

Bucket names are globally unique. Default in this repo is `package-images-bucket` — **change it** if that name is taken.

```bash
# Replace YOUR_BUCKET and REGION
aws s3 mb s3://YOUR_BUCKET --region us-east-1
```

If you rename the bucket, also update the ARN in `infra/iam_policy.json`:

```text
arn:aws:s3:::YOUR_BUCKET/*
```

### Step D — Create the Lambda IAM role

1. AWS Console → **IAM** → **Roles** → **Create role**
2. Trusted entity: **AWS service** → **Lambda**
3. Skip attaching managed policies for now → name it e.g. `package-inspection-lambda-role` → Create
4. Open the role → **Add permissions** → **Create inline policy** → JSON tab
5. Paste the contents of `infra/iam_policy.json` (remove the `_comment` fields if the console rejects them — AWS policy JSON does not allow custom keys)
6. Create the policy

Copy the role ARN (looks like):

```text
arn:aws:iam::123456789012:role/package-inspection-lambda-role
```

> **Note:** The API Lambda also needs `dynamodb:Query` on the table and its index. That is already included in `infra/iam_policy.json`.

### Step E — Find an OpenCV Lambda Layer

OpenCV is too large to zip into a normal Lambda package. Attach a **Lambda Layer** that provides OpenCV for Python.

Options:

1. Search AWS Console → Lambda → Layers → “Add a layer” → browse public / community layers for `opencv` + your region + `python3.12`, **or**
2. Search the web for `opencv python lambda layer` + your region and copy a public ARN.

You need an ARN like:

```text
arn:aws:lambda:us-east-1:ACCOUNT_ID:layer:opencv:VERSION
```

Keep the layer’s Python version aligned with the deploy script (`python3.12`).

### Step F — Deploy both Lambdas

From the repo root:

```bash
bash infra/deploy.sh \
  "arn:aws:iam::YOUR_ACCOUNT:role/package-inspection-lambda-role" \
  "arn:aws:lambda:us-east-1:ACCOUNT:layer:opencv:VERSION"
```

This creates (or updates):

| Function | Role |
|----------|------|
| `package-inspection-ingest` | Runs CV on new S3 images |
| `package-inspection-api` | Serves recent inspections over HTTP |

### Step G — Connect S3 → ingest Lambda

1. S3 → your bucket → **Properties** → **Event notifications** → **Create**
2. Event types: **All object create events**
3. Destination: Lambda function `package-inspection-ingest`
4. Save

Also grant S3 permission to invoke the function if the console asks you to (it usually offers to add it).

### Step H — Create API Gateway for the read API

1. **API Gateway** → **Create API** → **HTTP API**
2. Add integration → Lambda → `package-inspection-api`
3. Route: `GET /inspections`
4. Enable **CORS** (allow `*` origin for a portfolio demo)
5. Deploy and copy the **invoke URL**, e.g.:

```text
https://abc123.execute-api.us-east-1.amazonaws.com
```

Your inspections endpoint will be:

```text
https://abc123.execute-api.us-east-1.amazonaws.com/inspections
```

### Step I — Point the dashboard at your API

Edit `dashboard/index.html` and set:

```js
const API_ENDPOINT = "https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/inspections";
```

Open the file in a browser. Status should switch from demo data to **Live** once the API responds.

---

## 3. Try an end-to-end upload

```bash
# Upload any JPEG/PNG of a package (or a test photo)
aws s3 cp ./my-package.jpg s3://YOUR_BUCKET/incoming/my-package.jpg
```

Then:

1. Check CloudWatch logs for `package-inspection-ingest` if nothing appears.
2. Refresh the dashboard — you should see a new CLEAR or FLAGGED row.
3. Or curl the API:

```bash
curl "https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/inspections"
```

---

## How the detector works (short version)

Without labeled training data, `damage_detector.py` uses classical CV:

| Signal | Idea |
|--------|------|
| **Edge density** (Canny) | Torn / crushed surfaces → noisier edges |
| **Contour solidity** | Intact boxes ≈ rectangles (solidity near 1.0); damaged shapes have dents / holes |

Votes from those signals produce `damaged`, `confidence`, and a human-readable `reason`.

Later, train with `model/train_classifier.py` (ResNet18 transfer learning) and swap at the `[SWAP POINT]` in `classify_package()` — same return shape, so Lambdas and AWS wiring stay unchanged.

---

## Troubleshooting

| Problem | What to check |
|---------|----------------|
| Lambda timeout / OpenCV import error | Layer ARN region + Python version match `python3.12` |
| `AccessDenied` on S3 or DynamoDB | IAM role policy ARNs match your real bucket / table names |
| Dashboard stuck on demo data | `API_ENDPOINT` URL, CORS on API Gateway, browser console network tab |
| Upload does nothing | S3 event notification target; CloudWatch logs for `package-inspection-ingest` |
| API returns empty `items` | Confirm ingest wrote rows; query uses GSI `status-timestamp-index` and `status=completed` |

---

## Cost note

This design stays cheap for demos: S3 + Lambda + DynamoDB on-demand + API Gateway. Delete the bucket contents, Lambdas, table, and API when you are done experimenting to avoid surprise charges.

---

shamirhabome
