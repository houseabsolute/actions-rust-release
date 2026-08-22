#!/usr/bin/env python3

"""
Check that the release the publish action just created looks the way its inputs asked for.

`check-release.py` looks at the workflow artifact, which tells us that packaging worked. Nothing
looked at the release itself, which is how a bug where every boolean passed to the old release
action was silently ignored survived for so long. This asks GitHub what it actually created.
"""

import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List


def main() -> None:
    args = parse_args()
    release = fetch_release(args.tag, args.repository)

    errors: List[str] = []
    errors.extend(check_flags(release, args))
    errors.extend(check_notes(release, args))
    errors.extend(
        check_assets(release["assets"], args.executable_name, args.expect_asset_count)
    )

    if errors:
        print(json.dumps(release, indent=2), file=sys.stderr)
        sys.exit(
            "The release does not match the inputs it was created with:\n"
            + "\n".join(f"  - {e}" for e in errors)
        )

    print(f"The release for '{args.tag}' matches the inputs it was created with.")


def parse_args() -> argparse.Namespace:
    """Parse and return command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--executable-name", required=True)
    parser.add_argument("--expect-title")
    parser.add_argument("--expect-draft", action="store_true")
    parser.add_argument("--expect-immutable", action="store_true")
    parser.add_argument("--expect-prerelease", action="store_true")
    # The file whose contents should be the start of the release body.
    parser.add_argument("--expect-notes-from")
    # GitHub appends its generated notes to the body, so the body has to be longer than the file.
    parser.add_argument("--expect-generated-notes", action="store_true")
    parser.add_argument("--expect-asset-count", type=int, required=True)

    args = parser.parse_args()

    if not args.tag.strip():
        sys.exit(
            "The tag is empty, which means the publish action did not create a release. "
            "Guard this step with an `if:` if that is expected."
        )
    if args.expect_immutable and args.expect_draft:
        sys.exit(
            "A draft release is never immutable, so --expect-immutable and --expect-draft "
            "cannot both be used."
        )
    # Without a notes file there is nothing to compare the generated notes against, so the check
    # would quietly pass without looking at anything.
    if args.expect_generated_notes and not args.expect_notes_from:
        sys.exit(
            "--expect-generated-notes only works together with --expect-notes-from."
        )

    return args


def fetch_release(tag: str, repository: str) -> Dict:
    """Ask GitHub what it created. The token comes from GH_TOKEN in the environment."""
    result = subprocess.run(
        [
            "gh",
            "release",
            "view",
            tag,
            "--repo",
            repository,
            "--json",
            "name,body,isDraft,isPrerelease,isImmutable,assets",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # An older `gh` does not know every field asked for above, and saying the release could
        # not be read would point at the publish action rather than at the CLI.
        if "Unknown JSON field" in result.stderr:
            sys.exit(
                f"This `gh` is too old for one of the fields this check needs: "
                f"{result.stderr.strip()}"
            )
        sys.exit(
            f"Could not read the release for '{tag}' in {repository}: {result.stderr.strip()}"
        )

    return json.loads(result.stdout)


def check_flags(release: Dict, args: argparse.Namespace) -> List[str]:
    """Check the parts of the release that come straight from a boolean or string input."""
    errors = []

    if args.expect_title and release["name"] != args.expect_title:
        errors.append(
            f"the title is '{release['name']}', but 'release-name' asked for "
            f"'{args.expect_title}'"
        )
    if release["isDraft"] != args.expect_draft:
        errors.append(
            f"isDraft is {release['isDraft']}, but 'draft' asked for {args.expect_draft}"
        )
    if release["isPrerelease"] != args.expect_prerelease:
        errors.append(
            f"isPrerelease is {release['isPrerelease']}, but 'prerelease' asked for "
            f"{args.expect_prerelease}"
        )
    # A release only becomes immutable when it is published, so a draft is never immutable no
    # matter what the repository setting says. Checking this is the only way to know the
    # create-as-draft, upload, then publish sequence really happened.
    if args.expect_immutable and not release["isImmutable"]:
        errors.append(
            "isImmutable is false, so this release was not published into an immutable "
            "release repository the way it should have been"
        )

    return errors


def check_notes(release: Dict, args: argparse.Namespace) -> List[str]:
    """Check that the changes file, and GitHub's own notes, ended up in the release body."""
    if not args.expect_notes_from:
        return []

    errors = []
    notes = Path(args.expect_notes_from).read_text()
    body = release["body"] or ""

    # The body arrives with CRLF line endings, so compare the text rather than the exact bytes.
    if normalize(notes) not in normalize(body):
        first_line = next(
            (line for line in notes.splitlines() if line.strip()), "<empty>"
        )
        errors.append(
            f"the body does not contain the contents of {args.expect_notes_from}, which starts "
            f"with '{first_line}'"
        )
    if args.expect_generated_notes and "Full Changelog" not in body:
        # GitHub prepends the notes we supply to the ones it generates, and what it generates
        # always ends with a "Full Changelog" link, even when no pull requests are in range. A
        # body without one means 'generate-release-notes' did nothing.
        errors.append(
            "the body has no 'Full Changelog' link, so 'generate-release-notes' added nothing"
        )

    return errors


def normalize(text: str) -> str:
    """Make text comparable across the line ending and trailing whitespace GitHub adds."""
    return "\n".join(line.rstrip() for line in text.splitlines()).strip()


def check_assets(
    assets: List[Dict], executable_name: str, expected_count: int
) -> List[str]:
    """
    Check that every archive was attached along with its checksum file.

    The expected count comes from the workflow, since only it knows how many platforms it built.
    A leg of the build matrix silently dropping out of the release is the exact failure that
    splitting packaging from publishing was meant to prevent.
    """
    errors = []
    names = sorted(asset["name"] for asset in assets)

    if len(names) != expected_count:
        errors.append(
            f"the release has {len(names)} assets, but {expected_count} were expected: {names}"
        )

    for name in names:
        if not name.startswith(executable_name):
            errors.append(f"the asset '{name}' is not one of ours")

    ours = [n for n in names if n.startswith(executable_name)]
    archives = [n for n in ours if not n.endswith(".sha256")]
    for archive in archives:
        if f"{archive}.sha256" not in names:
            errors.append(f"the archive '{archive}' has no checksum file")

    if not archives:
        errors.append("the release has no archives attached")

    return errors


class TestVerifyRelease(unittest.TestCase):
    """Unit tests for the checks that do not need to talk to GitHub."""

    def assets(self, *names: str) -> List[Dict]:
        return [{"name": name} for name in names]

    def test_matched_archives_and_checksums(self) -> None:
        self.assertEqual(
            check_assets(
                self.assets(
                    "test-project-Linux-x86_64.tar.gz",
                    "test-project-Linux-x86_64.tar.gz.sha256",
                    "test-project-Windows-x86_64.zip",
                    "test-project-Windows-x86_64.zip.sha256",
                ),
                "test-project",
                4,
            ),
            [],
        )

    def test_missing_checksum(self) -> None:
        errors = check_assets(
            self.assets("test-project-Linux-x86_64.tar.gz"), "test-project", 1
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("no checksum file", errors[0])

    def test_foreign_asset(self) -> None:
        """A `--latest false` read as a file name would show up as an asset called "false"."""
        errors = check_assets(
            self.assets("false", "test-project.tar.gz", "test-project.tar.gz.sha256"),
            "test-project",
            3,
        )
        self.assertIn("the asset 'false' is not one of ours", errors)

    def test_no_archives(self) -> None:
        errors = check_assets(self.assets(), "test-project", 0)
        self.assertIn("no archives attached", errors[0])

    def test_wrong_asset_count(self) -> None:
        """A missing platform means someone downloads a release without their archive in it."""
        errors = check_assets(
            self.assets("test-project.tar.gz", "test-project.tar.gz.sha256"),
            "test-project",
            8,
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("2 assets, but 8 were expected", errors[0])

    def notes_args(self, **overrides) -> argparse.Namespace:
        defaults = {
            "expect_notes_from": None,
            "expect_generated_notes": False,
        }
        return argparse.Namespace(**{**defaults, **overrides})

    def test_generated_notes_need_a_full_changelog_link(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            notes = str(Path(td) / "Changes.md")
            Path(notes).write_text("## 1.0.0\n\n- A change\n")
            args = self.notes_args(expect_notes_from=notes, expect_generated_notes=True)

            errors = check_notes({"body": "## 1.0.0\r\n\r\n- A change\r\n"}, args)
            self.assertEqual(len(errors), 1)
            self.assertIn("Full Changelog", errors[0])

            body = (
                "## 1.0.0\r\n\r\n- A change\r\n\r\n"
                "**Full Changelog**: https://x/compare/a...b"
            )
            self.assertEqual(check_notes({"body": body}, args), [])

    def test_missing_notes_are_reported(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            notes = str(Path(td) / "Changes.md")
            Path(notes).write_text("## 1.0.0\n\n- A change\n")
            errors = check_notes(
                {"body": "something else"}, self.notes_args(expect_notes_from=notes)
            )
            self.assertEqual(len(errors), 1)
            self.assertIn("## 1.0.0", errors[0])

    def flag_args(self, **overrides) -> argparse.Namespace:
        defaults = {
            "expect_title": None,
            "expect_draft": False,
            "expect_prerelease": False,
            "expect_immutable": False,
        }
        return argparse.Namespace(**{**defaults, **overrides})

    def test_immutable_is_only_checked_when_asked_for(self) -> None:
        """A workflow that publishes a draft has nothing to say about immutability."""
        # No isImmutable key at all, so reading it without being asked to is a KeyError rather
        # than a silent pass.
        release = {"name": "x", "isDraft": True, "isPrerelease": False}
        self.assertEqual(
            check_flags(release, self.flag_args(expect_draft=True)),
            [],
        )

    def test_a_published_release_has_to_be_immutable(self) -> None:
        release = {
            "name": "x",
            "isDraft": False,
            "isPrerelease": False,
            "isImmutable": False,
        }
        errors = check_flags(release, self.flag_args(expect_immutable=True))
        self.assertEqual(len(errors), 1)
        self.assertIn("isImmutable is false", errors[0])

        release["isImmutable"] = True
        self.assertEqual(
            check_flags(release, self.flag_args(expect_immutable=True)), []
        )

    def test_notes_ignore_line_endings(self) -> None:
        self.assertEqual(normalize("a \r\nb\r\n"), "a\nb")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        unittest.main(argv=["unittest"])
    else:
        main()
