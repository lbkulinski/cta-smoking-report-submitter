# CTA Smoking Report Submitter

An AWS Lambda function that automatically submits smoking-on-a-train reports to the Chicago Transit Authority (CTA) via their chatbot API.

## How It Works

The function is triggered by DynamoDB stream events (`NEW_AND_OLD_IMAGES`). A record is a new report if it is an `INSERT`, or a `MODIFY` whose `NewImage.reportedAt` differs from `OldImage.reportedAt`. `REMOVE` events (TTL or manual) and unchanged `MODIFY`s are ignored, as are records with a missing or malformed `reportedAt`. For each new report, it:

1. Looks up station names from the [Chicago Open Data Portal](https://data.cityofchicago.org/resource/8pix-ypme.json)
2. Walks through the CTA's Dialogflow-based chatbot, providing:
   - Issue type: "Smoking on a train"
   - Train line (e.g. Red Line, Blue Line)
   - Car number
   - Next station
   - Direction of travel
   - Time of incident: "Just now"

## Input Schema (DynamoDB NewImage)

| Field | Type | Description |
|---|---|---|
| `carNumberLine` | String | Partition key, e.g. `2435#RED` (with `reportedAt`, the stable report identifier) |
| `line` | String | CTA line code (e.g. `RED`, `BLUE`) |
| `carNumber` | String | Rail car number |
| `nextStationId` | String | `map_id` of the next station |
| `destinationId` | String | `map_id` of the terminal station (`"0"` = Loop) |
| `reportedAt` | String | ISO 8601 instant, e.g. `2026-02-21T21:00:22.399660Z` |
| `runNumber` | String (nullable) | Train run number |

## Deduplication

Before submitting, the Lambda does a conditional `PutItem` (`attribute_not_exists(reportKey)`) into its own table (env `DEDUPE_TABLE`, default `processed-cta-smoking-posts`): partition key `reportKey` (S) = `<carNumberLine>#<reportedAt>`, TTL attribute `ttl` (N, now + 7 days). If the receipt exists the report is skipped. If submission fails, the receipt is deleted so the retry can resubmit. The role needs `dynamodb:PutItem` and `dynamodb:DeleteItem` on that table.

## Requirements

No third-party dependencies beyond `boto3`, which the Lambda runtime provides.

## Deployment

Package and deploy as an AWS Lambda function with a DynamoDB stream event source mapping.

```bash
zip lambda.zip lambda_function.py
```

## Tests

```bash
python3 -m unittest discover -s tests
```
