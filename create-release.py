#!/usr/bin/env python3

import argparse
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
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


class TestReleaseFiles(unittest.TestCase):
    """Unit tests for collecting the files to attach."""

    def test_missing_directory(self) -> None:
        """Nothing was downloaded, which means the find step matched no artifacts."""
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit) as cm:
                release_files(str(Path(td) / "nope"))
            self.assertIn("does not exist", str(cm.exception))

    def test_empty_directory(self) -> None:
        """This is where the old `fail_on_unmatched_files` behavior lives now."""
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(SystemExit) as cm:
                release_files(td)
            self.assertIn("does not contain any files", str(cm.exception))

    def test_sorted_and_files_only(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            for name in ("b.tar.gz", "a.tar.gz", "a.tar.gz.sha256"):
                (Path(td) / name).write_text("x")
            (Path(td) / "a-directory").mkdir()
            self.assertEqual(
                [Path(f).name for f in release_files(td)],
                ["a.tar.gz", "a.tar.gz.sha256", "b.tar.gz"],
            )


class TestReleaseExists(unittest.TestCase):
    """Unit tests for the check that keeps us from touching an existing release."""

    def test_exists(self) -> None:
        with mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 0, "", "")
            self.assertTrue(release_exists("v1.2.3", "me/repo"))
        self.assertEqual(
            run.call_args[0][0],
            ["gh", "release", "view", "v1.2.3", "--repo", "me/repo"],
        )

    def test_does_not_exist(self) -> None:
        with mock.patch("subprocess.run") as run:
            run.return_value = subprocess.CompletedProcess([], 1, "", "not found")
            self.assertFalse(release_exists("v1.2.3", None))
        self.assertNotIn("--repo", run.call_args[0][0])


class TestMain(unittest.TestCase):
    """
    Unit tests for the wiring, which is where the check and the create call meet.

    These stub `subprocess.run`, so `gh` is never actually invoked.
    """

    def run_main(self, returncode: int, *extra_args: str) -> mock.Mock:
        """Run main() against a directory with one archive in it, with `gh` stubbed out."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "test-project.tar.gz").write_text("x")
            argv = [
                "create-release.py",
                "--tag=v1.2.3",
                f"--artifact-directory={td}",
                *extra_args,
            ]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch("subprocess.run") as run:
                    run.return_value = subprocess.CompletedProcess(
                        [], returncode, "", ""
                    )
                    main()
                    return run

    def test_creates_the_release(self) -> None:
        run = self.run_main(1)
        # The first call is the existence check, the second creates the release.
        self.assertEqual(run.call_count, 2)
        command = run.call_args[0][0]
        self.assertEqual(command[:4], ["gh", "release", "create", "v1.2.3"])
        self.assertTrue(command[-1].endswith("test-project.tar.gz"))

    def test_refuses_to_touch_an_existing_release(self) -> None:
        """An immutable release cannot be updated, so re-running has to fail loudly."""
        with self.assertRaises(SystemExit) as cm:
            self.run_main(0, "--repository=me/repo")
        self.assertIn("already exists", str(cm.exception))
        self.assertIn("me/repo", str(cm.exception))

    def test_does_not_create_after_finding_a_release(self) -> None:
        """The existence check has to be the only thing that ran before we give up."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.tar.gz").write_text("x")
            argv = ["create-release.py", "--tag=v1", f"--artifact-directory={td}"]
            with mock.patch.object(sys, "argv", argv):
                with mock.patch("subprocess.run") as run:
                    run.return_value = subprocess.CompletedProcess([], 0, "", "")
                    with self.assertRaises(SystemExit):
                        main()
                    self.assertEqual(run.call_count, 1)


class TestParseArguments(unittest.TestCase):
    """Unit tests for turning the action's string inputs into arguments."""

    def parse(self, *args: str) -> argparse.Namespace:
        argv = ["create-release.py", "--tag=v1", "--artifact-directory=/a", *args]
        with mock.patch.object(sys, "argv", argv):
            return parse_arguments()

    def test_booleans_come_in_as_strings(self) -> None:
        args = self.parse("--draft=false", "--prerelease=true")
        self.assertFalse(args.draft)
        self.assertTrue(args.prerelease)

    def test_latest_is_normalized(self) -> None:
        self.assertEqual(self.parse("--latest=  TRUE ").latest, "true")
        self.assertEqual(self.parse().latest, "")

    def test_latest_rejects_anything_else(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            self.parse("--latest=maybe")
        self.assertIn("must be 'true' or 'false'", str(cm.exception))


class TestActionInvocation(unittest.TestCase):
    """
    Check how publish/action.yml calls this script.

    A value starting with a "-" is read as another option when it follows a space, so every
    argument has to use the `--opt=value` form. Nothing about running the script catches a
    reformat back to the spaced form, so this reads the action itself.
    """

    def test_every_argument_uses_the_equals_form(self) -> None:
        action = Path(__file__).parent / "publish" / "action.yml"
        text = action.read_text()
        invocation = re.search(
            r"create-release\.py \\\n(.*?)\n      env:", text, re.DOTALL
        )
        self.assertIsNotNone(
            invocation, f"could not find the create-release.py invocation in {action}"
        )

        # Only lines that are an argument, so that a "--word " inside a comment in the same
        # block is not scanned as if it were one.
        flags = re.findall(r"^ +(--[a-z-]+)([= ])", invocation.group(1), re.MULTILINE)
        self.assertTrue(flags, "found the invocation but no arguments in it")
        for flag, separator in flags:
            with self.subTest(flag=flag):
                self.assertEqual(
                    separator, "=", f"{flag} must use the --opt=value form"
                )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        unittest.main(argv=["unittest"])
    else:
        main()
