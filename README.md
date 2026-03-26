# CTA Smoking Report Submitter

An AWS Lambda function that automatically submits smoking-on-a-train reports to the Chicago Transit Authority (CTA) via their chatbot API.

## How It Works

The function is triggered by DynamoDB stream `INSERT` events. For each new record, it:

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
| `line` | String | CTA line code (e.g. `RED`, `BLUE`) |
| `carNumber` | String | Rail car number |
| `nextStationId` | String | `map_id` of the next station |
| `destinationId` | String | `map_id` of the terminal station (`"0"` = Loop) |
| `reportedAt` | String | ISO 8601 timestamp |
| `runNumber` | String (nullable) | Train run number |

## Requirements

No third-party dependencies — uses Python stdlib only (`urllib`, `json`, `uuid`, `logging`).

## Deployment

Package and deploy as an AWS Lambda function with a DynamoDB stream event source mapping.

```bash
zip lambda.zip lambda_function.py
```
