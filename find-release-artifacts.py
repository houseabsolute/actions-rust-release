#!/usr/bin/env python3

import argparse
import json
import os
import re
import sys
import unittest
import urllib.error
import urllib.request
from typing import Dict, List


def main() -> None:
    args = parse_arguments()

    regex = compile_regex(args.artifact_regex, args.executable_name)
    artifacts = list_artifacts(args.api_url, args.repo, args.run_id, args.token)
    if not artifacts:
        sys.exit(f"No artifacts were found for run {args.run_id} in {args.repo}.")

    matched = newest_per_name([a for a in artifacts if regex.search(a["name"])])
    if not matched:
        msg = (
            f"No artifacts in run {args.run_id} matched the regex '{regex.pattern}'.\n"
        )
        msg += "The artifacts for this run are:\n"
        msg += "\n".join(f"  {a['name']}" for a in sorted_by_name(artifacts))
        sys.exit(msg)

    print(f"Matched {len(matched)} of {len(artifacts)} artifacts:")
    for artifact in sorted_by_name(matched):
        print(f"  {artifact['name']}")

    # Downloading by ID rather than by name means we never have to worry about how an artifact name
    # would be interpreted as a glob.
    write_github_output(",".join(str(a["id"]) for a in sorted_by_name(matched)))


def parse_arguments() -> argparse.Namespace:
    """Parse and return command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable-name")
    parser.add_argument("--artifact-regex")
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--api-url", default="https://api.github.com")
    args = parser.parse_args()

    args.token = os.environ.get("GITHUB_TOKEN")
    if not args.token:
        sys.exit("The GITHUB_TOKEN environment variable must be set.")

    return args


def compile_regex(artifact_regex: str, executable_name: str) -> re.Pattern:
    """Return the regex used to pick release artifacts out of the run."""
    if artifact_regex:
        try:
            return re.compile(artifact_regex)
        except re.error as e:
            sys.exit(f"The 'artifact-regex' input is not a valid regex: {e}")

    if not executable_name:
        sys.exit(
            "You must provide either the 'executable-name' or the 'artifact-regex' input."
        )

    return re.compile(rf"\A{re.escape(executable_name)}.*\.(tar\.[a-z]+|zip)\Z")


def list_artifacts(api_url: str, repo: str, run_id: str, token: str) -> List[Dict]:
    """Return every artifact belonging to the given workflow run."""
    artifacts: List[Dict] = []
    seen = 0
    page = 1

    while True:
        url = f"{api_url}/repos/{repo}/actions/runs/{run_id}/artifacts?per_page=100&page={page}"
        body = get_json(url, token)

        this_page = body.get("artifacts", [])
        if not this_page:
            break

        seen += len(this_page)
        # Artifacts that expired or were deleted cannot be downloaded, so ignoring them here gives
        # a much better error than a failure in `actions/download-artifact`.
        artifacts.extend(a for a in this_page if not a.get("expired"))

        if seen >= body.get("total_count", 0):
            break
        page += 1

    return artifacts


def sorted_by_name(artifacts: List[Dict]) -> List[Dict]:
    """Sort artifacts by name so that output and IDs are in a stable order."""
    return sorted(artifacts, key=lambda a: a["name"])


def newest_per_name(artifacts: List[Dict]) -> List[Dict]:
    """Keep only the most recently uploaded artifact for each name.

    Re-running a workflow can leave more than one artifact with the same name attached to the run.
    Since they all get downloaded into the same directory, we would otherwise be at the mercy of
    download order for which one ends up in the release.
    """
    newest: Dict[str, Dict] = {}
    for artifact in artifacts:
        current = newest.get(artifact["name"])
        if current is None or artifact["id"] > current["id"]:
            newest[artifact["name"]] = artifact

    return list(newest.values())


def get_json(url: str, token: str) -> dict:
    """Make an authenticated GitHub API request and return the decoded response."""
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except json.JSONDecodeError as e:
        sys.exit(f"GitHub API request to {url} did not return valid JSON: {e}")
    except urllib.error.HTTPError as e:
        msg = f"GitHub API request to {url} failed with status {e.code}."
        if e.code in (403, 404):
            msg += "\nDoes the job running this action have the 'actions: read' permission?"
        sys.exit(msg)
    except urllib.error.URLError as e:
        sys.exit(f"GitHub API request to {url} failed: {e.reason}")


def write_github_output(artifact_ids: str) -> None:
    """Write the artifact IDs to GitHub Actions output."""
    output_file = os.environ.get("GITHUB_OUTPUT", os.devnull)
    if not output_file:
        sys.exit("GITHUB_OUTPUT environment variable not set.")

    with open(output_file, "a") as f:
        print(f"artifact-ids={artifact_ids}", file=f)


class TestFindReleaseArtifacts(unittest.TestCase):
    """Unit tests for artifact matching."""

    def test_default_regex(self) -> None:
        regex = compile_regex("", "ubi")
        matches = [
            "ubi-Linux-gnu-x86_64.tar.gz",
            "ubi-Windows-msvc-x86_64.zip",
            "ubi-macOS-arm64.tar.xz",
        ]
        for name in matches:
            with self.subTest(name=name):
                self.assertTrue(regex.search(name))

        non_matches = [
            "ubi",
            "ubi-coverage-report",
            "ubi-Linux-gnu-x86_64.tar.gz.sha256",
            "other-project-Linux-gnu-x86_64.tar.gz",
            "coverage.zip",
        ]
        for name in non_matches:
            with self.subTest(name=name):
                self.assertFalse(regex.search(name))

    def test_default_regex_escapes_executable_name(self) -> None:
        regex = compile_regex("", "a.b")
        self.assertTrue(regex.search("a.b-Linux-gnu-x86_64.tar.gz"))
        self.assertFalse(regex.search("axb-Linux-gnu-x86_64.tar.gz"))

    def test_explicit_regex_wins(self) -> None:
        regex = compile_regex("^only-this$", "ubi")
        self.assertTrue(regex.search("only-this"))
        self.assertFalse(regex.search("ubi-Linux-gnu-x86_64.tar.gz"))

    def test_default_regex_matches_bare_archive_name(self) -> None:
        # A user who sets the `archive-name` input can end up with an archive named after the
        # executable and nothing else.
        regex = compile_regex("", "ubi")
        self.assertTrue(regex.search("ubi.tar.gz"))

    def test_sorted_by_name(self) -> None:
        artifacts = [{"name": "b.tar.gz", "id": 2}, {"name": "a.zip", "id": 1}]
        self.assertEqual([a["id"] for a in sorted_by_name(artifacts)], [1, 2])

    def test_newest_per_name(self) -> None:
        artifacts = [
            {"name": "a.tar.gz", "id": 1},
            {"name": "b.tar.gz", "id": 2},
            {"name": "a.tar.gz", "id": 3},
        ]
        self.assertEqual(
            [a["id"] for a in sorted_by_name(newest_per_name(artifacts))], [3, 2]
        )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        unittest.main(argv=["unittest"])
    else:
        main()
