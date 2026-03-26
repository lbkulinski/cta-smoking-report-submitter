import json
import logging
import urllib.error
import urllib.request
import uuid

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CTA_API_URL = "https://is-prod.endpoints.prj-ccai-prod.cloud.goog/api/v1/dialogflow/detect-intent"
STATIONS_URL = "https://data.cityofchicago.org/resource/8pix-ypme.json?$limit=10000&$select=map_id,station_name"

_stations_cache: dict | None = None


def get_stations() -> dict:
    """Return a cached map_id → station_name dict, fetching from Chicago Open Data if needed."""
    global _stations_cache
    if _stations_cache is None:
        req = urllib.request.Request(STATIONS_URL)
        with urllib.request.urlopen(req, timeout=10) as resp:
            records = json.loads(resp.read())
        _stations_cache = {r["map_id"]: r["station_name"] for r in records}
        logger.info("Loaded %d stations from Chicago Open Data", len(_stations_cache))
    return _stations_cache


HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.5",
    "authorization": "Basic dXNlcm5hbWUxOnBhc3N3b3JkMg==",
    "content-type": "application/json; charset=UTF-8",
    "origin": "https://www.transitchicago.com",
    "referer": "https://www.transitchicago.com/",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "cross-site",
    "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
}

LINE_DISPLAY_NAMES = {
    "RED": "Red Line",
    "BLUE": "Blue Line",
    "BROWN": "Brown Line",
    "GREEN": "Green Line",
    "ORANGE": "Orange Line",
    "PURPLE": "Purple Line",
    "PINK": "Pink Line",
    "YELLOW": "Yellow Line",
}


def send_message(user_id: str, message: str) -> dict:
    body = json.dumps(
        {
            "message": message,
            "userId": user_id,
            "languageCode": "en-us",
            "isNewSession": False,
            "customParams": {"timezoneOffset": 300},
        }
    ).encode()

    req = urllib.request.Request(CTA_API_URL, data=body, headers=HEADERS, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        response = json.loads(resp.read())

    texts = [
        m["text"]["text"]
        for m in response.get("data", {}).get("queryResult", {}).get("responseMessages", [])
        if m.get("message") == "text"
    ]
    logger.info("send_message | sent=%r response=%s", message, texts)

    return response


def extract_direction_chips(response: dict) -> list:
    """Extract the direction chip options from a Dialogflow detect-intent response."""
    messages = response["data"]["queryResult"]["responseMessages"]
    for msg in messages:
        if msg.get("message") != "payload":
            continue
        try:
            rich = msg["payload"]["fields"]["richContent"]["listValue"]["values"]
            for group in rich:
                for item in group["listValue"]["values"]:
                    fields = item["structValue"]["fields"]
                    if fields.get("type", {}).get("stringValue") == "chips":
                        return [
                            opt["structValue"]["fields"]["text"]["stringValue"]
                            for opt in fields["options"]["listValue"]["values"]
                        ]
        except (KeyError, IndexError):
            continue
    return []


def resolve_direction(chips: list, destination_station_name: str) -> str:
    """
    Match a destination station name to a direction chip.
    Chips are formatted as "{terminal}-bound", e.g. "O'Hare-bound".
    Normalizes apostrophes and checks both directions to handle cases like
    "Dempster-Skokie" matching "Skokie-bound".
    """
    def normalize(s: str) -> str:
        return s.lower().replace("\u2019", "'").replace("\u2018", "'")

    dest = normalize(destination_station_name)
    for chip in chips:
        chip_norm = normalize(chip)
        terminal = chip_norm.removesuffix("-bound")
        if dest in chip_norm or terminal in dest:
            return chip
    raise ValueError(
        f"No direction chip matches destination '{destination_station_name}'. "
        f"Available: {chips}"
    )


def parse_new_image(new_image: dict) -> dict:
    """Deserialize a DynamoDB stream NewImage attribute map into a plain dict."""

    def s(key):
        return new_image[key]["S"]

    def nullable_s(key):
        item = new_image.get(key)
        return item["S"] if item else None

    return {
        "line": s("line"),
        "carNumber": s("carNumber"),
        "nextStationId": s("nextStationId"),
        "destinationId": s("destinationId"),
        "reportedAt": s("reportedAt"),
        "runNumber": nullable_s("runNumber"),
    }


def submit_report(report: dict) -> None:
    user_id = str(uuid.uuid4())
    line_display = LINE_DISPLAY_NAMES[report["line"]]
    logger.info(
        "Submitting smoking report | line=%s car=%s userId=%s",
        line_display,
        report["carNumber"],
        user_id,
    )

    # Steps 1–2: initiate session and select issue type
    send_message(user_id, "hi")
    send_message(user_id, "Smoking on a train")

    # Step 3: train line
    send_message(user_id, line_display)

    stations = get_stations()

    next_station_name = stations.get(report["nextStationId"])
    if not next_station_name:
        raise ValueError(
            f"nextStationId '{report['nextStationId']}' not found in stations"
        )

    destination_name = "Loop" if report["destinationId"] == "0" else stations.get(report["destinationId"])
    if not destination_name:
        raise ValueError(
            f"destinationId '{report['destinationId']}' not found in stations"
        )

    logger.info("Resolved stations | nextStation=%s destination=%s", next_station_name, destination_name)

    # Step 4: car number
    send_message(user_id, report["carNumber"])

    # Step 5: station — response includes direction chips
    station_resp = send_message(user_id, next_station_name)
    direction_chips = extract_direction_chips(station_resp)
    logger.info("Direction chips | %s", direction_chips)

    direction = resolve_direction(direction_chips, destination_name)
    logger.info("Resolved direction | %s", direction)

    # Step 6: direction
    send_message(user_id, direction)

    # Step 7: date/time — triggers submission and confirmation
    send_message(user_id, "Just now")

    logger.info("Report submitted successfully | userId=%s", user_id)


def lambda_handler(event: dict, context) -> dict:
    errors = []

    for record in event.get("Records", []):
        if record.get("eventName") != "INSERT":
            continue

        report_id = (
            record.get("dynamodb", {})
            .get("NewImage", {})
            .get("reportId", {})
            .get("S", "unknown")
        )
        try:
            report = parse_new_image(record["dynamodb"]["NewImage"])
            submit_report(report)
        except urllib.error.HTTPError as e:
            logger.exception("HTTP error submitting reportId=%s: %s", report_id, e)
            errors.append(f"reportId={report_id}: HTTP {e.code}")
        except Exception as e:
            logger.exception("Failed to submit reportId=%s: %s", report_id, e)
            errors.append(f"reportId={report_id}: {e}")

    if errors:
        # Raising causes Lambda to retry the batch — appropriate for transient failures
        raise RuntimeError(f"{len(errors)} report(s) failed: {errors}")

    return {"statusCode": 200}
