"""Retire only snapshotted releases/tags after the replacement is published.

This is an explicit, one-time operation: the default is a read-only plan, and
--apply still repeats every preflight check. No release asset is downloaded.
GitHub Actions supplies GH_TOKEN; all API calls use gh without a command shell.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from urllib.parse import quote


REPOSITORY = "Vxiey/Image-Draw-Bot"
KEEP_TAG = "v1.0.146-rc3"
SHA = re.compile(r"[0-9a-fA-F]{40}")


class CleanupError(RuntimeError):
    pass


class ApiError(CleanupError):
    def __init__(self, method, endpoint, status):
        self.status = status
        super().__init__(f"GitHub {method} {endpoint} failed (HTTP {status}).")


class GhApi:
    def request(self, method, endpoint):
        if method not in {"GET", "DELETE"}:
            raise CleanupError("Only metadata reads and explicit deletions are supported.")
        if method == "DELETE":
            # Keep mutation requests at least one second apart, including retries.
            time.sleep(1)
        try:
            result = subprocess.run(
                ["gh", "api", "--hostname", "github.com", "--method", method,
                 "--include", "-H", "Accept: application/vnd.github+json", endpoint],
                capture_output=True, text=True, encoding="utf-8", timeout=60,
                check=False, shell=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise CleanupError(f"Could not complete GitHub {method} {endpoint}.") from exc
        header, separator, body = result.stdout.replace("\r\n", "\n").partition("\n\n")
        status_line = header.split("\n", 1)[0]
        match = re.fullmatch(r"HTTP/\S+ (\d{3})(?: .*)?", status_line)
        if not separator or match is None:
            raise CleanupError(f"Missing HTTP status for GitHub {method} {endpoint}.")
        status = int(match.group(1))
        if result.returncode or status != (200 if method == "GET" else 204):
            raise ApiError(method, endpoint, status)
        if method == "DELETE":
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise CleanupError(f"Invalid JSON from GitHub GET {endpoint}.") from exc


def _positive_id(value):
    return type(value) is int and value > 0


def _tag_ref(value):
    if not isinstance(value, str) or not value.startswith("refs/tags/"):
        raise CleanupError("Deletion plans may contain only refs/tags/ references.")
    name = value[len("refs/tags/"):]
    if (not name or name.endswith(("/", ".")) or ".." in name or "@{" in name
            or re.search(r"[\x00-\x20\x7f~^:?*\[\\]", name)
            or any(part.startswith(".") or part.endswith(".lock") or not part
                   for part in name.split("/"))):
        raise CleanupError(f"Invalid tag reference: {value!r}")
    return value


def _sha(value):
    if not isinstance(value, str) or SHA.fullmatch(value) is None:
        raise CleanupError("Expected a complete 40-character Git object SHA.")
    return value.lower()


def _release_identity(row):
    if (not isinstance(row, dict) or not _positive_id(row.get("id"))
            or not isinstance(row.get("tag_name"), str)):
        raise CleanupError("Invalid release identity.")
    _tag_ref("refs/tags/" + row["tag_name"])
    return {"id": row["id"], "tag_name": row["tag_name"]}


def _ref_identity(row):
    if not isinstance(row, dict) or not isinstance(row.get("object"), dict):
        raise CleanupError("Invalid Git reference response.")
    object_type = row["object"].get("type")
    if object_type not in {"commit", "tag", "tree", "blob"}:
        raise CleanupError("Invalid Git reference object type.")
    return {"ref": _tag_ref(row.get("ref")), "sha": _sha(row["object"].get("sha")),
            "object_type": object_type}


class Retirement:
    def __init__(self, snapshot, keep_tag, expected_commit, api):
        if (not isinstance(snapshot, dict) or snapshot.get("schema_version") != 1
                or snapshot.get("repository") != REPOSITORY):
            raise CleanupError("Snapshot schema/repository does not match this retirement.")
        if keep_tag != KEEP_TAG or snapshot.get("keep_tag") != keep_tag:
            raise CleanupError(f"This retirement must preserve {KEEP_TAG}.")
        self.keep_tag = keep_tag
        self.keep_ref = "refs/tags/" + keep_tag
        self.expected_commit = _sha(expected_commit)
        self.api = api
        self.base = f"repos/{REPOSITORY}"
        if not isinstance(snapshot.get("releases"), list) or not isinstance(snapshot.get("tags"), list):
            raise CleanupError("Snapshot must include explicit releases and tags lists.")
        self.releases = [_release_identity(row) for row in snapshot["releases"]]
        self.tags = [
            _ref_identity({"ref": row.get("ref"),
                           "object": {"sha": row.get("sha"), "type": row.get("object_type")}})
            if isinstance(row, dict) else _ref_identity(row)
            for row in snapshot["tags"]
        ]
        if any(row["tag_name"] == keep_tag for row in self.releases):
            raise CleanupError("The keep release is included in the deletion plan.")
        if any(row["ref"] == self.keep_ref for row in self.tags):
            raise CleanupError("The keep tag is included in the deletion plan.")
        if (len({row["id"] for row in self.releases}) != len(self.releases)
                or len({row["ref"] for row in self.tags}) != len(self.tags)):
            raise CleanupError("Duplicate release IDs or tag refs in the snapshot.")

    def _optional(self, method, endpoint):
        try:
            return self.api.request(method, endpoint)
        except ApiError as exc:
            if exc.status != 404:
                raise
            return None

    def _ref_endpoint(self, ref, *, delete=False):
        # GitHub uses singular /ref/ for exact reads, plural /refs/ for deletion.
        _tag_ref(ref)
        return f"{self.base}/git/{'refs' if delete else 'ref'}/{quote(ref[5:], safe='/')}"

    def verify_keep(self):
        release = self.api.request(
            "GET", f"{self.base}/releases/tags/{quote(self.keep_tag, safe='')}"
        )
        identity = _release_identity(release)
        if (identity["tag_name"] != self.keep_tag or release.get("draft") is not False
                or not release.get("published_at")):
            raise CleanupError("The replacement release must be published and non-draft.")
        version = self.keep_tag[1:]
        required = {
            f"ImageDrawBot-{version}-Windows-x64.zip",
            f"ImageDrawBot-{version}-Windows-x64-Setup.exe",
            f"ImageDrawBot-{version}-SHA256.txt",
            f"ImageDrawBot-{version}-manifest.json",
        }
        assets = release.get("assets")
        if (not isinstance(assets, list) or len(assets) != 4
                or not all(isinstance(asset, dict) for asset in assets)
                or {asset.get("name") for asset in assets} != required):
            raise CleanupError("The replacement must have exactly the four required assets.")
        for asset in assets:
            if (not _positive_id(asset.get("size")) or asset.get("state") != "uploaded"
                    or not isinstance(asset.get("digest"), str)
                    or re.fullmatch(r"sha256:[0-9a-fA-F]{64}", asset["digest"]) is None):
                raise CleanupError("Every replacement asset needs a positive size and SHA256 digest.")

        tag = _ref_identity(self.api.request("GET", self._ref_endpoint(self.keep_ref)))
        if tag["ref"] != self.keep_ref:
            raise CleanupError("The keep tag response did not match the requested reference.")
        sha, object_type = tag["sha"], tag["object_type"]
        seen = set()
        while object_type == "tag":
            if sha in seen or len(seen) >= 10:
                raise CleanupError("Cannot resolve the replacement's annotated tag.")
            seen.add(sha)
            annotated = self.api.request("GET", f"{self.base}/git/tags/{sha}")
            if not isinstance(annotated, dict) or _sha(annotated.get("sha")) != sha:
                raise CleanupError("Unexpected annotated tag object.")
            target = annotated.get("object")
            if not isinstance(target, dict):
                raise CleanupError("Missing annotated tag target.")
            sha, object_type = _sha(target.get("sha")), target.get("type")
        if object_type != "commit" or sha != self.expected_commit:
            raise CleanupError("The replacement tag does not match the expected commit.")
        return {**identity, "commit": sha, "ref": tag,
                "assets": [{key: asset[key] for key in ("name", "size", "digest")}
                           for asset in assets]}

    def _list_releases(self):
        rows = []
        for page in range(1, 1001):
            batch = self.api.request("GET", f"{self.base}/releases?per_page=100&page={page}")
            if not isinstance(batch, list):
                raise CleanupError("Invalid release inventory.")
            rows.extend(_release_identity(row) for row in batch)
            if len(batch) < 100:
                return rows
        raise CleanupError("Release inventory pagination did not terminate.")

    def preflight(self):
        keep = self.verify_keep()
        planned_releases = {row["id"]: row for row in self.releases}
        planned_tags = {row["ref"]: row for row in self.tags}
        if keep["id"] in planned_releases:
            raise CleanupError("The keep release ID is included in the deletion plan.")
        releases = self._list_releases()
        refs = self.api.request("GET", f"{self.base}/git/matching-refs/tags/")
        if not isinstance(refs, list):
            raise CleanupError("Invalid tag inventory.")
        tags = [_ref_identity(row) for row in refs]
        release_map = {row["id"]: row for row in releases}
        tag_map = {row["ref"]: row for row in tags}
        if len(release_map) != len(releases) or len(tag_map) != len(tags):
            raise CleanupError("Duplicate entries in GitHub inventory; retry after concurrent changes stop.")
        if (release_map.get(keep["id"]) != {key: keep[key] for key in ("id", "tag_name")}
                or tag_map.get(self.keep_ref) != keep["ref"]):
            raise CleanupError("The replacement changed during inventory verification.")
        for row in releases:
            if row["id"] != keep["id"] and planned_releases.get(row["id"]) != row:
                raise CleanupError(f"Unexpected or changed release: {row!r}")
        for row in tags:
            if row["ref"] != self.keep_ref and planned_tags.get(row["ref"]) != row:
                raise CleanupError(f"Unexpected or changed tag: {row!r}")
        return {
            "keep": keep,
            "releases": [{**row, "present": row["id"] in release_map} for row in self.releases],
            "tags": [{**row, "present": row["ref"] in tag_map} for row in self.tags],
        }

    def delete_one(self, kind, row, keep_id):
        if self.verify_keep()["id"] != keep_id:
            raise CleanupError("The replacement release ID changed after preflight.")
        if kind == "release":
            if row["id"] == keep_id or row["tag_name"] == self.keep_tag:
                raise CleanupError("Refusing to delete the keep release.")
            endpoint = f"{self.base}/releases/{row['id']}"
            current = self._optional("GET", endpoint)
            if current is not None and _release_identity(current) != row:
                raise CleanupError(f"Release changed before deletion: {row!r}")
        else:
            if row["ref"] == self.keep_ref:
                raise CleanupError("Refusing to delete the keep tag.")
            current = self._optional("GET", self._ref_endpoint(row["ref"]))
            if current is not None and _ref_identity(current) != row:
                raise CleanupError(f"Tag changed before deletion: {row!r}")
            endpoint = self._ref_endpoint(row["ref"], delete=True)
        if current is None:
            return "already_absent"
        try:
            self.api.request("DELETE", endpoint)
        except ApiError as exc:
            if exc.status != 404:
                raise
            return "already_absent"
        return "deleted"


def _write_report(path, report):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def retire(snapshot, *, keep_tag, expected_commit, report_path, apply=False, api=None):
    report = {
        "schema_version": 1, "repository": REPOSITORY,
        "keep_tag": keep_tag, "expected_commit": expected_commit,
        "mode": "apply" if apply else "dry-run", "status": "started",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "canonical_snapshot_sha256": hashlib.sha256(
            json.dumps(snapshot, sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "actions": [],
    }
    try:
        retirement = Retirement(snapshot, keep_tag, expected_commit, api or GhApi())
        report["preflight"] = retirement.preflight()
        report["status"] = "preflight_passed"
        _write_report(report_path, report)
        if apply:
            for kind, rows in (("release", retirement.releases), ("tag", retirement.tags)):
                for row in rows:
                    action = {"kind": kind, **row, "status": "pending"}
                    report["actions"].append(action)
                    _write_report(report_path, report)
                    action["status"] = retirement.delete_one(
                        kind, row, report["preflight"]["keep"]["id"]
                    )
                    _write_report(report_path, report)
            final = retirement.preflight()
            if (final["keep"]["id"] != report["preflight"]["keep"]["id"]
                    or any(row["present"] for row in final["releases"] + final["tags"])):
                raise CleanupError("Final inventory does not contain only the keep release and tag.")
            report["final"] = final
        report["status"] = "complete" if apply else "dry_run_complete"
    except Exception as exc:
        report["status"] = "failed"
        report["error"] = str(exc)
        _write_report(report_path, report)
        raise
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    _write_report(report_path, report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--keep-tag", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--apply", action="store_true", help="Apply the exact verified snapshot.")
    args = parser.parse_args(argv)
    if args.snapshot.resolve() == args.report.resolve():
        parser.error("The report must not overwrite the snapshot.")
    try:
        snapshot = json.loads(args.snapshot.read_text(encoding="utf-8"))
        report = retire(snapshot, keep_tag=args.keep_tag, expected_commit=args.expected_commit,
                        report_path=args.report, apply=args.apply)
    except (CleanupError, OSError, ValueError) as exc:
        parser.exit(1, f"Release retirement stopped: {exc}\n")
    print(f"Release retirement: {report['status']}. Report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
