"""
setup_dynamodb.py
------------------
Run this ONCE to create the DynamoDB table that stores inspection
results. Requires AWS credentials configured locally (aws configure)
with permission to create DynamoDB tables.

Usage:
    python setup_dynamodb.py
"""

import boto3

TABLE_NAME = "PackageInspections"


def create_table():
    dynamodb = boto3.client("dynamodb")

    existing_tables = dynamodb.list_tables()["TableNames"]
    if TABLE_NAME in existing_tables:
        print(f"Table '{TABLE_NAME}' already exists - nothing to do.")
        return

    dynamodb.create_table(
        TableName=TABLE_NAME,
        KeySchema=[
            # Partition key: each inspection gets a unique UUID, so writes
            # spread evenly across partitions (avoids "hot partition" issues
            # you'd get from using something like date as the key).
            {"AttributeName": "inspection_id", "KeyType": "HASH"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "inspection_id", "AttributeType": "S"},
            {"AttributeName": "status", "AttributeType": "S"},
            {"AttributeName": "timestamp", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                # Lets the dashboard efficiently query "show me the most
                # recent completed/failed inspections" without scanning
                # the whole table.
                "IndexName": "status-timestamp-index",
                "KeySchema": [
                    {"AttributeName": "status", "KeyType": "HASH"},
                    {"AttributeName": "timestamp", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
            }
        ],
        # On-demand billing: you pay per request, not per provisioned
        # throughput. Ideal for a low/spiky-traffic project like this one -
        # no capacity planning needed and nothing to pay for while idle.
        BillingMode="PAY_PER_REQUEST",
    )

    print(f"Creating table '{TABLE_NAME}'... (this takes ~30-60 seconds)")
    waiter = dynamodb.get_waiter("table_exists")
    waiter.wait(TableName=TABLE_NAME)
    print(f"Table '{TABLE_NAME}' is ready.")


if __name__ == "__main__":
    create_table()
