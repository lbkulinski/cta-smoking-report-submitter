# CTA Smoking Report Submitter

An AWS Lambda function that automatically submits smoking-on-a-train reports to the Chicago Transit Authority (CTA) via their chatbot API.

This is an unofficial project: it is not affiliated with or endorsed by the CTA, and it calls the same chatbot endpoint the CTA website uses.

## How It Works

The function is triggered by DynamoDB stream events (`NEW_AND_OLD_IMAGES`). A record is a new report if it is an `INSERT`, or a `MODIFY` whose `NewImage.reportedAt` differs from `OldImage.reportedAt`. `REMOVE` events (TTL or manual) and unchanged `MODIFY`s are ignored, as are records with a missing or malformed `reportedAt`. For each new report, it:

1. Looks up station names by map ID in the CTA train stations DynamoDB table (the same table the social bot uses)
2. Walks through the CTA's Dialogflow-based chatbot, providing:
   - Issue type: "Smoking on a train"
   - Train line (e.g. Red Line, Blue Line)
   - Car number
   - Next station
   - Direction of travel
   - Time of incident: "Just now"

## Environment Variables

All are required; there are no defaults.

| Variable | Description |
|---|---|
| `CTA_API_URL` | CTA Dialogflow chatbot endpoint |
| `STATIONS_TABLE_NAME` | DynamoDB stations table (partition key `mapId`, sort key `stopId`, attributes `name` and `descriptiveName`); needs `dynamodb:Query`. Branch-qualified stations such as Harlem on the Blue Line use their descriptive name without the line, e.g. `Harlem (O'Hare Branch)` |
| `CTA_AUTHORIZATION` | Value of the `authorization` header sent to the CTA endpoint (treat as a secret) |
| `PROCESSED_REPORTS_TABLE_NAME` | This function's own receipts table (see Deduplication) |

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

Before submitting, the Lambda does a conditional `PutItem` (`attribute_not_exists(reportKey)`) into its own table (required env `PROCESSED_REPORTS_TABLE_NAME`, e.g. `processed-cta-smoking-submissions`): partition key `reportKey` (S) = `<carNumberLine>#<reportedAt>`, TTL attribute `ttl` (N, now + 7 days). If the receipt exists the report is skipped. If submission fails, the receipt is deleted so the retry can resubmit. Failed records are returned as `batchItemFailures`, so the event source mapping must set `FunctionResponseTypes: [ReportBatchItemFailures]`. The role needs `dynamodb:PutItem` and `dynamodb:DeleteItem` on that table.

### Delivery guarantees

Stream delivery is at least once, so the function claims a receipt before acting. This favors skipping over duplicating: a report is not acted on twice, with one exception: if a request succeeds but its response is lost (for example a timeout), the call is treated as failed, the receipt is released, and the retry repeats it. A report can also be skipped if the function is killed between the claim and the action, or if releasing the receipt after a failed action also fails. Receipts expire after 7 days. This is an accepted trade-off.

## Requirements

Runs on the Python 3.14 Lambda runtime (the code itself needs 3.10 or newer, for `X | None` annotations). No third-party dependencies beyond `boto3`, which the Lambda runtime provides.

## Deployment

Package and deploy as an AWS Lambda function with a DynamoDB stream event source mapping.

```bash
zip lambda.zip lambda_function.py
```

### Event source mapping

Set `FunctionResponseTypes: [ReportBatchItemFailures]`, make sure the filter lets `INSERT` and `MODIFY` through, and use a bounded `MaximumRetryAttempts` plus an on-failure destination so a record that keeps failing cannot block the shard until stream retention expires. Records that can never succeed (missing attributes, an unknown line or station, no matching direction) are logged and skipped rather than retried; transient failures are returned in `batchItemFailures` and retried.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## CI/CD

- `.github/workflows/ci.yml` runs `ruff` and `pytest` on pull requests to `main` (Python 3.14).
- `.github/workflows/deploy.yml` runs CI (lint and tests), then updates the Lambda's code. It runs on every push to `main` and can also be run manually. It only updates code; environment variables, tables, IAM and the event source mapping are managed elsewhere.
- `.github/dependabot.yml` checks the Python dependencies and the workflow actions weekly.

Deploy setup (repository settings):

| Kind | Name | Description |
|---|---|---|
| Variable | `AWS_ROLE_ARN` | IAM role GitHub assumes via OIDC. Needs `lambda:UpdateFunctionCode` and `lambda:GetFunctionConfiguration` on the function (the latter is used by the post-deploy `aws lambda wait function-updated` step). Because the deploy job runs in the `production` environment, the role's trust policy must allow the subject `repo:lbkulinski/cta-smoking-report-submitter:environment:production` |
| Variable | `AWS_REGION` | Region of the Lambda |
| Variable | `LAMBDA_FUNCTION_NAME` | Name of the Lambda function |
| Environment | `production` | The deploy job runs in this environment. Optionally add required reviewers as an approval gate |

## License

[MIT](LICENSE)
