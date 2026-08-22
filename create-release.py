#!/usr/bin/env python3

import argparse
from pathlib import Path
import subprocess
import sys
import unittest
from typing import List, Optional


def main() -> None:
    args = parse_arguments()

    files = release_files(args.artifact_directory)
    print(f"Releasing {len(files)} files:")
    for file in files:
        print(f"  {Path(file).name}")

    if release_exists(args.tag, args.repository):
        sys.exit(
            f"A release for the tag '{args.tag}' already exists"
            f"{f' in {args.repository}' if args.repository else ''}.\n"
            "This action does not update an existing release, because an immutable release "
            "cannot be updated at all. Delete the release first if you want to recreate it."
        )

    command = build_command(args, files)
    # The token is passed in the environment, so it is safe to print the command.
    print(f"Running: {' '.join(command)}")
    subprocess.run(command, check=True)


def parse_arguments() -> argparse.Namespace:
    """Parse and return command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--artifact-directory", required=True)
    parser.add_argument("--working-directory", default=".")
    parser.add_argument("--changes-file")
    parser.add_argument("--release-name")
    parser.add_argument("--target")
    parser.add_argument("--repository")
    parser.add_argument("--discussion-category")
    # These arrive as the strings the caller wrote in their workflow, not as flags, so that
    # `draft: false` cannot turn into a `--draft`.
    parser.add_argument("--draft", default="")
    parser.add_argument("--prerelease", default="")
    parser.add_argument("--generate-release-notes", default="")
    # Empty means "let GitHub decide based on the release date", which is what `gh` does when the
    # flag is absent, so this is deliberately a tri-state rather than a boolean. This is not an
    # argparse `choices` list, because that would compare against the raw value and reject a
    # `TRUE` that validate-inputs.py accepted, after everything has already been built.
    parser.add_argument("--latest", default="")

    args = parser.parse_args()
    args.latest = args.latest.strip().lower()
    if args.latest not in ("", "true", "false"):
        sys.exit(
            f"The 'latest' input must be 'true' or 'false' if set, but it is '{args.latest}'."
        )

    args.draft = is_true(args.draft)
    args.prerelease = is_true(args.prerelease)
    args.generate_release_notes = is_true(args.generate_release_notes)

    return args


def is_true(value: str) -> bool:
    """
    Interpret an action input as a boolean.

    Inputs arrive as strings, so a caller writing `false` would otherwise be as true as `true`.
    This matches the same helper in set-should-release.py.
    """
    return value.strip().lower() not in ("", "false", "0")


def release_files(artifact_directory: str) -> List[str]:
    """
    Return the files to attach to the release.

    Every file in this directory came from an artifact we matched, which means it is either an
    archive or its checksum file. Releasing nothing is always a mistake, so this is where the old
    `fail_on_unmatched_files` behavior lives now.
    """
    directory = Path(artifact_directory)
    if not directory.is_dir():
        sys.exit(f"The artifact directory '{artifact_directory}' does not exist.")

    files = sorted(str(p) for p in directory.iterdir() if p.is_file())
    if not files:
        sys.exit(
            f"The artifact directory '{artifact_directory}' does not contain any files."
        )

    return files


def release_exists(tag: str, repository: Optional[str]) -> bool:
    """
    Return whether a release for this tag already exists.

    A draft release counts, since `gh release create` will not overwrite one of those either.
    """
    command = ["gh", "release", "view", tag]
    if repository:
        command.extend(["--repo", repository])

    result = subprocess.run(command, capture_output=True, text=True)
    return result.returncode == 0


def build_command(args: argparse.Namespace, files: List[str]) -> List[str]:
    """
    Build the `gh release create` command line.

    Passing the files to `create` matters for more than brevity. When `gh` is given assets it
    creates the release as a draft, uploads them, and only then publishes, which is the sequence
    GitHub documents for repos that have immutable releases turned on.
    """
    command = ["gh", "release", "create", args.tag]

    if args.repository:
        command.extend(["--repo", args.repository])
    if args.release_name:
        command.extend(["--title", args.release_name])
    if args.target:
        command.extend(["--target", args.target])
    if args.discussion_category:
        command.extend(["--discussion-category", args.discussion_category])
    if args.draft:
        command.append("--draft")
    if args.prerelease:
        command.append("--prerelease")
    if args.latest:
        # `--latest=false` has to be one argument. A separate "false" would be read as a file to
        # upload, because `--latest` is a boolean flag.
        command.append(f"--latest={args.latest}")

    if args.generate_release_notes:
        command.append("--generate-notes")

    if args.changes_file:
        command.extend(
            ["--notes-file", str(Path(args.working_directory) / args.changes_file)]
        )
    elif not args.generate_release_notes:
        # Without one of the notes flags `gh` tries to open an editor, which fails on a runner.
        command.extend(["--notes", ""])

    command.extend(files)

    return command


class TestBuildCommand(unittest.TestCase):
    """Unit tests for the `gh release create` command construction."""

    def args(self, **overrides) -> argparse.Namespace:
        """The arguments for a release with everything left at its default."""
        defaults = {
            "tag": "v1.2.3",
            "artifact_directory": "/artifacts",
            "working_directory": ".",
            "changes_file": None,
            "release_name": None,
            "target": None,
            "repository": None,
            "discussion_category": None,
            "draft": False,
            "prerelease": False,
            "generate_release_notes": False,
            "latest": None,
        }
        return argparse.Namespace(**{**defaults, **overrides})

    def test_minimal(self) -> None:
        """The tag, the files, and empty notes so `gh` does not open an editor."""
        self.assertEqual(
            build_command(self.args(), ["/artifacts/a.tar.gz"]),
            ["gh", "release", "create", "v1.2.3", "--notes", "", "/artifacts/a.tar.gz"],
        )

    def test_changes_file_is_resolved_against_working_directory(self) -> None:
        """The changes file lives in the working directory, not the repo root."""
        command = build_command(
            self.args(changes_file="Changes.md", working_directory="sub-project"),
            ["/artifacts/a.tar.gz"],
        )
        self.assertIn("--notes-file", command)
        self.assertEqual(
            command[command.index("--notes-file") + 1], "sub-project/Changes.md"
        )
        self.assertNotIn("--notes", command)

    def test_generate_notes_suppresses_empty_notes(self) -> None:
        """Passing both `--generate-notes` and empty `--notes` would blank the notes."""
        command = build_command(self.args(generate_release_notes=True), ["/a.tar.gz"])
        self.assertIn("--generate-notes", command)
        self.assertNotIn("--notes", command)

    def test_latest_is_one_argument(self) -> None:
        """A split `--latest false` would make `gh` treat "false" as a file to upload."""
        self.assertIn(
            "--latest=false", build_command(self.args(latest="false"), ["/a"])
        )
        self.assertIn("--latest=true", build_command(self.args(latest="true"), ["/a"]))
        self.assertFalse(
            [a for a in build_command(self.args(), ["/a"]) if a.startswith("--latest")]
        )

    def test_all_options(self) -> None:
        """Every input maps to the flag it is documented as mapping to."""
        command = build_command(
            self.args(
                release_name="Release 1.2.3",
                target="main",
                repository="me/other-repo",
                discussion_category="Announcements",
                draft=True,
                prerelease=True,
                changes_file="Changes.md",
            ),
            ["/artifacts/a.tar.gz", "/artifacts/a.tar.gz.sha256"],
        )
        self.assertEqual(
            command,
            [
                "gh",
                "release",
                "create",
                "v1.2.3",
                "--repo",
                "me/other-repo",
                "--title",
                "Release 1.2.3",
                "--target",
                "main",
                "--discussion-category",
                "Announcements",
                "--draft",
                "--prerelease",
                "--notes-file",
                "Changes.md",
                "/artifacts/a.tar.gz",
                "/artifacts/a.tar.gz.sha256",
            ],
        )

    def test_latest_is_normalized_like_the_validator(self) -> None:
        """validate-inputs.py strips and lowercases, so anything it accepts has to work here."""
        for value in ("TRUE", "  true  ", "False"):
            with self.subTest(value=value):
                self.assertIn(
                    f"--latest={value.strip().lower()}",
                    build_command(self.args(latest=value.strip().lower()), ["/a"]),
                )

    def test_is_true(self) -> None:
        """A caller writing `draft: false` must not get a draft release."""
        for value in ("true", "TRUE", "  true  ", "yes", "1"):
            with self.subTest(value=value):
                self.assertTrue(is_true(value))
        for value in ("", "false", "FALSE", " false ", "0"):
            with self.subTest(value=value):
                self.assertFalse(is_true(value))

    def test_files_come_last(self) -> None:
        """Anything after the positional files would be read as another file."""
        command = build_command(self.args(draft=True), ["/artifacts/a.tar.gz"])
        self.assertEqual(command[-1], "/artifacts/a.tar.gz")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        unittest.main(argv=["unittest"])
    else:
        main()
