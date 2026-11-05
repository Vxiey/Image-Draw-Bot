"""Deletion-safety regressions using an in-memory GitHub API; never access GitHub."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, unquote, urlsplit

import release_cleanup as cleanup


COMMIT = "a" * 40
BASE = "repos/" + cleanup.REPOSITORY
KEEP_REF = "refs/tags/" + cleanup.KEEP_TAG


def ref(name, sha, object_type="commit"):
    return {"ref": name, "object": {"sha": sha, "type": object_type}}


def fixture():
    snapshot = {
        "schema_version": 1, "repository": cleanup.REPOSITORY, "keep_tag": cleanup.KEEP_TAG,
        "releases": [{"id": 10, "tag_name": "v1.0.145-rc1"},
                     {"id": 20, "tag_name": "v1.0.146-rc2"}],
        "tags": [{"ref": "refs/tags/v1.0.145-rc1", "sha": "b" * 40, "object_type": "commit"},
                 {"ref": "refs/tags/v1.0.146-rc2", "sha": "c" * 40, "object_type": "tag"},
                 {"ref": "refs/tags/old/source", "sha": "d" * 40, "object_type": "commit"}],
        # This metadata must not become an additional deletion instruction.
        "previously_observed_releases": [{"id": 777, "tag_name": "missing-archival-entry"}],
    }
    version = cleanup.KEEP_TAG[1:]
    keep = {
        "id": 99, "tag_name": cleanup.KEEP_TAG, "draft": False,
        "published_at": "2026-11-05T22:00:00Z",
        "assets": [{"name": f"ImageDrawBot-{version}-{suffix}", "size": 100,
                    "state": "uploaded", "digest": "sha256:" + str(index) * 64}
                   for index, suffix in enumerate(
                       ("Windows-x64.zip", "Windows-x64-Setup.exe", "SHA256.txt", "manifest.json"), 1)],
    }
    return snapshot, keep


class FakeApi:
    def __init__(self, snapshot, keep):
        self.releases = {row["id"]: deepcopy(row) for row in snapshot["releases"]}
        self.releases[keep["id"]] = deepcopy(keep)
        self.refs = {row["ref"]: ref(row["ref"], row["sha"], row["object_type"])
                     for row in snapshot["tags"]}
        self.refs[KEEP_REF] = ref(KEEP_REF, COMMIT)
        self.annotated = {}
        self.calls = []
        self.before_request = None

    @property
    def deletes(self):
        return [endpoint for method, endpoint in self.calls if method == "DELETE"]

    def request(self, method, endpoint):
        self.calls.append((method, endpoint))
        if self.before_request:
            self.before_request(method, endpoint)
        parsed = urlsplit(endpoint)
        path = unquote(parsed.path)
        if method == "GET" and path == BASE + "/releases":
            page = int(parse_qs(parsed.query)["page"][0])
            return deepcopy(list(self.releases.values())[(page - 1) * 100:page * 100])
        if method == "GET" and path.startswith(BASE + "/releases/tags/"):
            tag = path[len(BASE + "/releases/tags/"):]
            rows = [row for row in self.releases.values() if row["tag_name"] == tag]
            if rows:
                return deepcopy(rows[0])
        elif path.startswith(BASE + "/releases/"):
            release_id = int(path.rsplit("/", 1)[1])
            if release_id in self.releases:
                if method == "DELETE":
                    del self.releases[release_id]
                    return None
                return deepcopy(self.releases[release_id])
        elif method == "GET" and path == BASE + "/git/matching-refs/tags/":
            return deepcopy(list(self.refs.values()))
        elif path.startswith(BASE + "/git/ref/") or path.startswith(BASE + "/git/refs/"):
            marker = "/git/refs/" if method == "DELETE" else "/git/ref/"
            name = "refs/" + path.split(marker, 1)[1]
            if name in self.refs:
                if method == "DELETE":
                    del self.refs[name]
                    return None
                return deepcopy(self.refs[name])
        elif method == "GET" and path.startswith(BASE + "/git/tags/"):
            sha = path.rsplit("/", 1)[1]
            if sha in self.annotated:
                return deepcopy(self.annotated[sha])
        raise cleanup.ApiError(method, endpoint, 404)


class ReleaseCleanupTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.report_path = Path(self.temporary.name) / "audit/report.json"
        self.snapshot, self.keep = fixture()
        self.api = FakeApi(self.snapshot, self.keep)

    def run_cleanup(self, **kwargs):
        return cleanup.retire(
            self.snapshot, keep_tag=cleanup.KEEP_TAG, expected_commit=COMMIT,
            report_path=self.report_path, api=self.api, **kwargs,
        )

    def assert_blocked(self, message):
        with self.assertRaisesRegex(cleanup.CleanupError, message):
            self.run_cleanup(apply=True)
        self.assertEqual(self.api.deletes, [])
        self.assertEqual(json.loads(self.report_path.read_text())["status"], "failed")

    def test_default_dry_run_records_exact_plan_without_mutating(self):
        original_releases, original_refs = deepcopy(self.api.releases), deepcopy(self.api.refs)
        report = self.run_cleanup()
        self.assertEqual(report["mode"], "dry-run")
        self.assertEqual(report["status"], "dry_run_complete")
        self.assertEqual(self.api.deletes, [])
        self.assertEqual(self.api.releases, original_releases)
        self.assertEqual(self.api.refs, original_refs)
        self.assertEqual([row["id"] for row in report["preflight"]["releases"]], [10, 20])
        self.assertEqual(report, json.loads(self.report_path.read_text()))
        self.assertEqual(report["preflight"]["keep"]["commit"], COMMIT)

    def test_apply_deletes_only_snapshot_releases_then_tags_and_writes_audit_first(self):
        def verify_audit(method, endpoint):
            if method == "DELETE":
                report = json.loads(self.report_path.read_text())
                self.assertEqual(report["status"], "preflight_passed")
                self.assertEqual(report["actions"][-1]["status"], "pending")
                self.assertEqual(report["preflight"]["keep"]["id"], 99)
        self.api.before_request = verify_audit
        report = self.run_cleanup(apply=True)
        self.assertEqual(self.api.deletes, [
            BASE + "/releases/10", BASE + "/releases/20",
            BASE + "/git/refs/tags/v1.0.145-rc1",
            BASE + "/git/refs/tags/v1.0.146-rc2",
            BASE + "/git/refs/tags/old/source",
        ])
        self.assertEqual(set(self.api.releases), {99})
        self.assertEqual(set(self.api.refs), {KEEP_REF})
        self.assertEqual(report["status"], "complete")
        self.assertEqual([action["status"] for action in report["actions"]], ["deleted"] * 5)

    def test_keep_guard_rejects_tag_name_ref_and_reused_release_id(self):
        for kind in ("release-name", "ref", "release-id"):
            with self.subTest(kind=kind):
                self.snapshot, self.keep = fixture()
                self.api = FakeApi(self.snapshot, self.keep)
                if kind == "release-name":
                    self.snapshot["releases"].append({"id": 123, "tag_name": cleanup.KEEP_TAG})
                elif kind == "ref":
                    self.snapshot["tags"].append(
                        {"ref": KEEP_REF, "sha": COMMIT, "object_type": "commit"}
                    )
                else:
                    self.snapshot["releases"].append({"id": 99, "tag_name": "old-tag"})
                self.assert_blocked("keep")

    def test_rejects_non_tag_refs_before_any_api_call(self):
        self.snapshot["tags"][0]["ref"] = "refs/heads/main"
        self.assert_blocked("only refs/tags")
        self.assertEqual(self.api.calls, [])

    def test_wrong_commit_stops_before_deleting(self):
        self.api.refs[KEEP_REF]["object"]["sha"] = "e" * 40
        self.assert_blocked("expected commit")

    def test_draft_or_unpublished_replacement_stops_before_deleting(self):
        for field, value in (("draft", True), ("published_at", None)):
            with self.subTest(field=field):
                self.api = FakeApi(self.snapshot, self.keep)
                self.api.releases[99][field] = value
                self.assert_blocked("published and non-draft")

    def test_missing_extra_or_duplicate_replacement_asset_stops_before_deleting(self):
        for kind in ("missing", "extra", "duplicate"):
            with self.subTest(kind=kind):
                self.api = FakeApi(self.snapshot, self.keep)
                assets = self.api.releases[99]["assets"]
                if kind == "missing":
                    assets.pop()
                elif kind == "extra":
                    assets.append({"name": "unplanned.zip"})
                else:
                    assets[0] = deepcopy(assets[1])
                self.assert_blocked("exactly the four")

    def test_asset_size_digest_and_upload_state_are_required(self):
        for field, value in (("size", 0), ("size", True), ("digest", None),
                             ("digest", "sha256:1234"), ("state", "new")):
            with self.subTest(field=field, value=value):
                self.api = FakeApi(self.snapshot, self.keep)
                self.api.releases[99]["assets"][0][field] = value
                self.assert_blocked("positive size and SHA256")

    def test_changed_ref_or_release_identity_fails_full_preflight(self):
        for kind in ("tag-sha", "tag-type", "release-name"):
            with self.subTest(kind=kind):
                self.api = FakeApi(self.snapshot, self.keep)
                if kind == "release-name":
                    self.api.releases[20]["tag_name"] = "renamed-release"
                elif kind == "tag-sha":
                    self.api.refs[self.snapshot["tags"][-1]["ref"]]["object"]["sha"] = "e" * 40
                else:
                    self.api.refs[self.snapshot["tags"][-1]["ref"]]["object"]["type"] = "tag"
                self.assert_blocked("Unexpected or changed")

    def test_unexpected_release_or_tag_blocks_all_deletions(self):
        for kind in ("release", "tag"):
            with self.subTest(kind=kind):
                self.api = FakeApi(self.snapshot, self.keep)
                if kind == "release":
                    self.api.releases[123] = {"id": 123, "tag_name": "unplanned"}
                else:
                    self.api.refs["refs/tags/unplanned"] = ref("refs/tags/unplanned", "e" * 40)
                self.assert_blocked("Unexpected or changed")

    def test_full_release_inventory_is_paginated_before_any_delete(self):
        for value in range(1000, 1100):
            row = {"id": value, "tag_name": "old-" + str(value)}
            self.snapshot["releases"].append(deepcopy(row))
            self.api.releases[value] = row
        self.api.releases[2000] = {"id": 2000, "tag_name": "unplanned-on-page-two"}
        self.assert_blocked("Unexpected or changed")
        self.assertIn(("GET", BASE + "/releases?per_page=100&page=2"), self.api.calls)

    def test_annotated_keep_tag_is_resolved_to_commit(self):
        self.api.refs[KEEP_REF] = ref(KEEP_REF, "e" * 40, "tag")
        self.api.annotated["e" * 40] = {
            "sha": "e" * 40, "object": {"sha": COMMIT, "type": "commit"}
        }
        self.assertEqual(self.run_cleanup()["preflight"]["keep"]["commit"], COMMIT)
        self.api.annotated["e" * 40]["object"]["sha"] = "f" * 40
        self.assert_blocked("expected commit")

    def test_fresh_release_check_catches_change_after_full_preflight(self):
        def change(method, endpoint):
            if method == "GET" and endpoint == BASE + "/releases/10":
                self.api.releases[10]["tag_name"] = "changed-after-preflight"
        self.api.before_request = change
        self.assert_blocked("Release changed before deletion")

    def test_fresh_tag_check_catches_change_after_full_preflight(self):
        self.snapshot["releases"] = []
        self.api.releases = {99: self.api.releases[99]}
        def change(method, endpoint):
            if method == "GET" and endpoint == BASE + "/git/ref/tags/v1.0.145-rc1":
                self.api.refs["refs/tags/v1.0.145-rc1"]["object"]["sha"] = "e" * 40
        self.api.before_request = change
        self.assert_blocked("Tag changed before deletion")

    def test_keep_is_rechecked_before_each_deletion(self):
        keep_reads = 0
        def remove_keep(method, endpoint):
            nonlocal keep_reads
            if endpoint == BASE + "/releases/tags/" + cleanup.KEEP_TAG:
                keep_reads += 1
                if keep_reads == 2:
                    del self.api.releases[99]
        self.api.before_request = remove_keep
        self.assert_blocked("HTTP 404")

    def test_missing_planned_items_and_completed_retries_are_idempotent(self):
        del self.api.releases[10]
        del self.api.refs["refs/tags/v1.0.145-rc1"]
        first = self.run_cleanup(apply=True)
        self.assertEqual(first["actions"][0]["status"], "already_absent")
        self.assertEqual(first["actions"][2]["status"], "already_absent")
        self.api.calls.clear()
        retry = self.run_cleanup(apply=True)
        self.assertEqual(self.api.deletes, [])
        self.assertEqual([action["status"] for action in retry["actions"]], ["already_absent"] * 5)
        self.assertEqual(retry["status"], "complete")

    def test_delete_404_is_tolerated_when_another_actor_just_removed_the_item(self):
        def concurrent_removal(method, endpoint):
            if method == "DELETE" and endpoint == BASE + "/releases/10":
                del self.api.releases[10]
        self.api.before_request = concurrent_removal
        report = self.run_cleanup(apply=True)
        self.assertEqual(report["actions"][0]["status"], "already_absent")
        self.assertEqual(report["status"], "complete")

    def test_non_404_failure_stops_and_partial_run_can_be_retried(self):
        def deny_second(method, endpoint):
            if method == "DELETE" and endpoint == BASE + "/releases/20":
                raise cleanup.ApiError(method, endpoint, 403)
        self.api.before_request = deny_second
        with self.assertRaisesRegex(cleanup.ApiError, "HTTP 403"):
            self.run_cleanup(apply=True)
        report = json.loads(self.report_path.read_text())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["actions"][0]["status"], "deleted")
        self.assertEqual(self.api.deletes, [BASE + "/releases/10", BASE + "/releases/20"])
        self.assertEqual(len(self.api.refs), 4)
        self.api.before_request = None
        self.api.calls.clear()
        self.assertEqual(self.run_cleanup(apply=True)["status"], "complete")
        self.assertNotIn(BASE + "/releases/10", self.api.deletes)

    def test_final_inventory_rejects_a_new_unplanned_tag_without_deleting_it(self):
        def add_tag(method, endpoint):
            if method == "DELETE" and endpoint == BASE + "/git/refs/tags/old/source":
                self.api.refs["refs/tags/unplanned"] = ref("refs/tags/unplanned", "e" * 40)
        self.api.before_request = add_tag
        with self.assertRaisesRegex(cleanup.CleanupError, "Unexpected or changed tag"):
            self.run_cleanup(apply=True)
        self.assertIn("refs/tags/unplanned", self.api.refs)
        self.assertIn(KEEP_REF, self.api.refs)
        self.assertIn(99, self.api.releases)
        self.assertEqual(json.loads(self.report_path.read_text())["status"], "failed")

    def test_cli_defaults_to_dry_run_and_cannot_overwrite_snapshot(self):
        path = Path(self.temporary.name) / "snapshot.json"
        path.write_text(json.dumps(self.snapshot))
        arguments = ["--snapshot", str(path), "--keep-tag", cleanup.KEEP_TAG,
                     "--expected-commit", COMMIT, "--report", str(self.report_path)]
        with patch.object(cleanup, "retire", return_value={"status": "dry_run_complete"}) as retire, \
             patch("builtins.print"):
            self.assertEqual(cleanup.main(arguments), 0)
        self.assertFalse(retire.call_args.kwargs["apply"])
        arguments[-1] = str(path)
        with patch.object(cleanup, "retire") as retire, patch("sys.stderr"):
            with self.assertRaises(SystemExit):
                cleanup.main(arguments)
        retire.assert_not_called()
        self.assertEqual(json.loads(path.read_text()), self.snapshot)


class GhApiTests(unittest.TestCase):
    def test_metadata_request_uses_argument_array_no_shell_and_parses_http_headers(self):
        result = SimpleNamespace(returncode=0, stdout='HTTP/2.0 200 OK\r\nContent-Type: application/json\r\n\r\n{"id": 1}')
        with patch.object(cleanup.subprocess, "run", return_value=result) as run:
            self.assertEqual(cleanup.GhApi().request("GET", BASE + "/releases/1"), {"id": 1})
        args, kwargs = run.call_args
        self.assertEqual(args[0][:5], ["gh", "api", "--hostname", "github.com", "--method"])
        self.assertIn("--include", args[0])
        self.assertEqual(args[0][-1], BASE + "/releases/1")
        self.assertFalse(kwargs["shell"])
        self.assertEqual(kwargs["timeout"], 60)

    def test_delete_requires_204_and_reads_404_from_http_status_not_stderr(self):
        for status in (204, 404, 403):
            result = SimpleNamespace(returncode=0 if status == 204 else 1,
                                     stdout=f"HTTP/2.0 {status} Status\nContent-Length: 0\n\n")
            with self.subTest(status=status), \
                 patch.object(cleanup.subprocess, "run", return_value=result), \
                 patch.object(cleanup.time, "sleep") as sleep:
                if status == 204:
                    self.assertIsNone(cleanup.GhApi().request("DELETE", BASE + "/releases/1"))
                else:
                    with self.assertRaises(cleanup.ApiError) as caught:
                        cleanup.GhApi().request("DELETE", BASE + "/releases/1")
                    self.assertEqual(caught.exception.status, status)
                sleep.assert_called_once_with(1)

    def test_authentication_or_transport_failure_without_status_is_not_a_404(self):
        with patch.object(cleanup.subprocess, "run",
                          return_value=SimpleNamespace(returncode=1, stdout="")):
            with self.assertRaisesRegex(cleanup.CleanupError, "Missing HTTP status"):
                cleanup.GhApi().request("GET", BASE + "/releases/1")


if __name__ == "__main__":
    unittest.main()
