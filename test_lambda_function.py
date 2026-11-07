import itertools
import os
import unittest
from unittest import mock

os.environ.setdefault("CTA_API_URL", "https://cta.example/api")
os.environ.setdefault("STATIONS_URL", "https://stations.example/api")
os.environ.setdefault("CTA_AUTHORIZATION", "test-token")
os.environ.setdefault("PROCESSED_REPORTS_TABLE_NAME", "test-dedupe-table")

import lambda_function as lf  # noqa: E402

T1 = "2026-02-21T21:00:22.399660Z"
T2 = "2026-02-21T22:10:00.000001Z"

STATIONS = {"40900": "Howard", "41320": "Belmont", "40890": "O'Hare"}


def image(reported_at=T1, run_number="123", destination="40900", **overrides):
    img = {
        "carNumberLine": {"S": "2435#RED"},
        "carNumber": {"S": "2435"},
        "line": {"S": "RED"},
        "gsiPk": {"S": "REPORT"},
        "reportedAt": {"S": reported_at},
        "expiresAt": {"N": "1771700000"},
        "destinationId": {"S": destination},
        "nextStationId": {"S": "41320"},
    }
    if run_number is not None:
        img["runNumber"] = {"S": run_number}
    img.update(overrides)
    return img


_seq = itertools.count(1)


def record(event_name, new=None, old=None, sequence_number=None, **extra):
    ddb = {"SequenceNumber": sequence_number or str(next(_seq))}
    if new is not None:
        ddb["NewImage"] = new
    if old is not None:
        ddb["OldImage"] = old
    return {"eventName": event_name, "eventID": "e1", "dynamodb": ddb, **extra}


class HandlerTests(unittest.TestCase):
    def setUp(self):
        p = mock.patch.object(lf, "submit_report")
        self.submit = p.start()
        self.addCleanup(p.stop)
        c = mock.patch.object(lf, "claim_report", return_value=True)
        self.claim = c.start()
        self.addCleanup(c.stop)
        r = mock.patch.object(lf, "release_report")
        self.release = r.start()
        self.addCleanup(r.stop)

    def run_handler(self, *records):
        return lf.lambda_handler({"Records": list(records)}, None)

    def test_insert_submits_once_with_correct_fields(self):
        self.run_handler(record("INSERT", new=image()))
        self.submit.assert_called_once()
        report = self.submit.call_args.args[0]
        self.assertEqual(report["line"], "RED")
        self.assertEqual(report["carNumber"], "2435")
        self.assertEqual(report["nextStationId"], "41320")
        self.assertEqual(report["destinationId"], "40900")
        self.assertEqual(report["reportedAt"], T1)
        self.assertEqual(report["runNumber"], "123")
        self.assertEqual(report["reportKey"], f"2435#RED#{T1}")
        self.assertNotIn("date", report)
        self.assertNotIn("reportId", report)

    def test_modify_with_new_reported_at_submits(self):
        self.run_handler(record("MODIFY", new=image(T2), old=image(T1)))
        self.submit.assert_called_once()
        self.assertEqual(self.submit.call_args.args[0]["reportedAt"], T2)

    def test_modify_with_same_reported_at_is_ignored(self):
        self.run_handler(record("MODIFY", new=image(T1), old=image(T1)))
        self.submit.assert_not_called()

    def test_modify_without_old_image_is_ignored(self):
        self.run_handler(record("MODIFY", new=image(T1)))
        self.submit.assert_not_called()

    def test_ttl_remove_is_ignored(self):
        rec = record(
            "REMOVE",
            old=image(),
            userIdentity={"type": "Service", "principalId": "dynamodb.amazonaws.com"},
        )
        self.run_handler(rec)
        self.submit.assert_not_called()

    def test_manual_remove_is_ignored(self):
        rec = record("REMOVE", old=image(), userIdentity={"type": "IAMUser", "principalId": "AIDA..."})
        self.run_handler(rec)
        self.submit.assert_not_called()

    def test_missing_run_number_is_handled(self):
        self.run_handler(record("INSERT", new=image(run_number=None)))
        self.assertIsNone(self.submit.call_args.args[0]["runNumber"])

    def test_null_run_number_is_handled(self):
        self.run_handler(record("INSERT", new=image(runNumber={"NULL": True})))
        self.assertIsNone(self.submit.call_args.args[0]["runNumber"])

    def test_loop_destination_passes_through(self):
        self.run_handler(record("INSERT", new=image(destination="0")))
        self.assertEqual(self.submit.call_args.args[0]["destinationId"], "0")

    def test_malformed_or_missing_reported_at_skipped_without_failing_batch(self):
        missing = image()
        del missing["reportedAt"]
        bad = [
            record("INSERT", new=image("not-a-date")),
            record("INSERT", new=image("2026-02-21 21:00:22")),
            record("INSERT", new=image("2026-13-45T99:00:00Z")),
            record("INSERT", new=image(reportedAt={"N": "123"})),
            record("INSERT", new=missing),
            record("MODIFY", new=image("garbage"), old=image(T1)),
        ]
        good = record("INSERT", new=image(T2))
        result = self.run_handler(*bad, good)
        self.assertEqual(result, {"batchItemFailures": []})
        self.submit.assert_called_once()
        self.assertEqual(self.submit.call_args.args[0]["reportedAt"], T2)

    def test_instants_with_varied_fraction_digits_are_valid(self):
        for v in ["2026-02-21T21:00:22Z", "2026-02-21T21:00:22.399Z", "2026-02-21T21:00:22.399660123Z"]:
            self.assertTrue(lf.is_valid_instant(v), v)

    def test_permanent_error_is_skipped_not_retried(self):
        self.submit.side_effect = lf.PermanentError("station not found")
        result = self.run_handler(record("INSERT", new=image(), sequence_number="5"))
        self.assertEqual(result, {"batchItemFailures": []})
        self.release.assert_called_once()

    def test_record_missing_required_attribute_is_skipped_not_retried(self):
        img = image()
        del img["nextStationId"]
        result = self.run_handler(record("INSERT", new=img, sequence_number="6"))
        self.assertEqual(result, {"batchItemFailures": []})
        self.claim.assert_not_called()
        self.submit.assert_not_called()

    def test_submit_failure_is_reported_as_batch_item_failure(self):
        self.submit.side_effect = [RuntimeError("boom"), None]
        result = self.run_handler(
            record("INSERT", new=image(T1), sequence_number="100"),
            record("INSERT", new=image(T2), sequence_number="101"),
        )
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "100"}]})
        self.assertEqual(self.submit.call_count, 2)

    def test_failure_without_sequence_number_fails_whole_batch(self):
        self.submit.side_effect = RuntimeError("boom")
        rec = record("INSERT", new=image())
        del rec["dynamodb"]["SequenceNumber"]
        with self.assertRaises(RuntimeError):
            self.run_handler(rec)


class DedupeTests(HandlerTests):
    def test_claims_before_submitting_with_report_key(self):
        self.run_handler(record("INSERT", new=image()))
        self.claim.assert_called_once_with(f"2435#RED#{T1}")
        self.submit.assert_called_once()

    def test_already_claimed_report_is_not_submitted(self):
        self.claim.return_value = False
        result = self.run_handler(record("INSERT", new=image()))
        self.assertEqual(result, {"batchItemFailures": []})
        self.submit.assert_not_called()
        self.release.assert_not_called()

    def test_failed_submit_releases_receipt_and_reports_failure(self):
        self.submit.side_effect = RuntimeError("boom")
        result = self.run_handler(record("INSERT", new=image(), sequence_number="7"))
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "7"}]})
        self.release.assert_called_once_with(f"2435#RED#{T1}")

    def test_ignored_records_do_not_claim(self):
        self.run_handler(
            record("REMOVE", old=image()),
            record("MODIFY", new=image(T1), old=image(T1)),
            record("INSERT", new=image("bad")),
        )
        self.claim.assert_not_called()

    def test_claim_error_other_than_conflict_reports_failure_without_submitting(self):
        self.claim.side_effect = RuntimeError("throttled")
        result = self.run_handler(record("INSERT", new=image(), sequence_number="9"))
        self.assertEqual(result, {"batchItemFailures": [{"itemIdentifier": "9"}]})
        self.submit.assert_not_called()


class ClaimReportTests(unittest.TestCase):
    def test_claim_puts_conditional_item_with_ttl(self):
        client = mock.Mock()
        with mock.patch.object(lf, "_get_dynamodb", return_value=client), mock.patch.object(lf.time, "time", return_value=1000):
            self.assertTrue(lf.claim_report("k"))
        kwargs = client.put_item.call_args.kwargs
        self.assertEqual(kwargs["Item"], {"reportKey": {"S": "k"}, "ttl": {"N": str(1000 + 7 * 86400)}})
        self.assertEqual(kwargs["ConditionExpression"], "attribute_not_exists(reportKey)")

    def test_conflict_returns_false(self):
        err = Exception("x")
        err.response = {"Error": {"Code": "ConditionalCheckFailedException"}}
        client = mock.Mock()
        client.put_item.side_effect = err
        with mock.patch.object(lf, "_get_dynamodb", return_value=client):
            self.assertFalse(lf.claim_report("k"))

    def test_other_errors_propagate(self):
        client = mock.Mock()
        client.put_item.side_effect = Exception("boom")
        with mock.patch.object(lf, "_get_dynamodb", return_value=client), self.assertRaises(Exception):
            lf.claim_report("k")


class SubmitReportTests(unittest.TestCase):
    """Exercise submit_report with the CTA HTTP call mocked."""

    def run_submit(self, destination):
        chips = ["Howard-bound", "95th/Dan Ryan-bound"]
        sent = []

        def fake_send(user_id, message):
            sent.append(message)
            return {"chips": chips}

        report = lf.parse_new_image(image(destination=destination))
        with mock.patch.object(lf, "send_message", side_effect=fake_send), \
             mock.patch.object(lf, "get_stations", return_value=STATIONS), \
             mock.patch.object(lf, "extract_direction_chips", return_value=chips + ["Loop-bound"]):
            lf.submit_report(report)
        return sent

    def test_known_destination(self):
        sent = self.run_submit("40900")
        self.assertEqual(sent, ["hi", "Smoking on a train", "Red Line", "2435", "Belmont", "Howard-bound", "Just now"])

    def test_loop_destination_does_not_hit_station_lookup(self):
        sent = self.run_submit("0")
        self.assertEqual(sent[-2], "Loop-bound")

    def test_no_run_number_is_not_sent(self):
        sent = self.run_submit("40900")
        self.assertNotIn("123", sent)

    def test_unknown_line_is_a_permanent_error(self):
        report = lf.parse_new_image(image(line={"S": "SILVER"}))
        with self.assertRaises(lf.PermanentError):
            lf.submit_report(report)

    def test_unknown_destination_is_a_permanent_error(self):
        with self.assertRaises(lf.PermanentError):
            self.run_submit("99999")
