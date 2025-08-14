#!/usr/bin/env python3

# Mostly written by Claude.ai.

import os
import sys
import glob
import shutil
import argparse
import tempfile
import subprocess
import time
from pathlib import Path
import unittest
from typing import List, Optional


def main() -> None:
    """Main function to process command line arguments and create release archives."""
    args = parse_arguments()
    validate_arguments(args)

    if args.working_directory:
        os.chdir(args.working_directory)

    archive_name = get_archive_name(
        args.executable_name, args.target, args.archive_name
    )
    archive_file = create_archive_path(archive_name)
    executable_name = get_executable_name(args.executable_name)

    found_files = find_executable(executable_name, args.target)
    found_files.extend(gather_additional_files(args.extra_files, args.changes_file))

    create_archive(archive_file, found_files, executable_name)
    write_github_output(archive_file)


def parse_arguments() -> argparse.Namespace:
    """Parse and return command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable-name", required=True)
    parser.add_argument("--target")
    parser.add_argument("--archive-name")
    parser.add_argument("--changes-file", default="Changes.md")
    parser.add_argument("--extra-files")
    parser.add_argument("--working-directory")
    return parser.parse_args()


def validate_arguments(args: argparse.Namespace) -> None:
    """Validate command line arguments."""
    if not args.executable_name:
        sys.exit("You must provide an executable-name when using this action.")

    if not (args.target or args.archive_name):
        sys.exit(
            "You must provide either a target or archive-name when using this action."
        )

    if not args.extra_files:
        if args.changes_file and not Path(args.changes_file).is_file():
            sys.exit(f"Changes file '{args.changes_file}' does not exist.")


def get_archive_name(
    executable_name: str, target: Optional[str], archive_name: Optional[str]
) -> str:
    """Generate the archive name based on inputs."""
    if archive_name:
        return archive_name
    return (
        f"{executable_name}-{target_to_archive_name(target)}"
        if target
        else executable_name
    )


def create_archive_path(archive_name: str) -> str:
    """Create and return the full archive path with appropriate extension."""
    archive_extension = (
        ".zip" if os.environ.get("RUNNER_OS") == "Windows" else ".tar.gz"
    )
    return str(Path.cwd() / f"{archive_name}{archive_extension}")


def get_executable_name(base_name: str) -> str:
    """Get the platform-appropriate executable name."""
    return f"{base_name}.exe" if os.environ.get("RUNNER_OS") == "Windows" else base_name


def find_executable(executable_name: str, target: Optional[str]) -> List[str]:
    """Find the executable in possible locations."""
    look_for = [
        Path("target") / target / "release" / executable_name if target else None,
        Path("target") / "release" / executable_name,
    ]
    look_for = [str(p) for p in look_for if p]

    for file in look_for:
        if Path(file).is_file():
            print(f"Found executable at {file}")
            return [file]

    msg = "Could not find executable in any of:\n"
    msg += "\n".join(f"  {f}" for f in look_for)
    sys.exit(msg)


def gather_additional_files(
    extra_files_globs: Optional[str], changes_file: Optional[str]
) -> List[str]:
    """Gather additional files to include in the archive."""
    if not extra_files_globs:
        files = glob.glob("README*")
        if changes_file:
            files += [changes_file]
        return files

    from os.path import isdir

    globs = []
    for g in extra_files_globs.splitlines():
        g = g.strip()
        if not g:
            continue

        if isdir(g):
            globs.append(g.removesuffix("/") + "/**")
        else:
            globs.append(g)

    # Collect all matching files
    files = [changes_file] if changes_file else []
    for g in globs:
        files.extend(glob.glob(g, recursive=True))

    return files


def create_archive(
    archive_file: str, found_files: List[str], executable_name: str
) -> None:
    """Create the archive with the specified files."""
    td = None
    try:
        td = tempfile.mkdtemp()

        for file in found_files:
            shutil.copy2(file, td)

        # Set executable permissions
        exec_path = Path(td) / executable_name
        if exec_path.exists():
            exec_path.chmod(0o755)

        # Create archive
        original_dir = os.getcwd()
        try:
            os.chdir(td)
            if os.environ.get("RUNNER_OS") == "Windows":
                cmd = ["7z", "a", archive_file] + glob.glob("*")
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    sys.exit(f"Failed to create archive. Error: {result.stderr}")
            else:
                cmd = ["tar", "czf", archive_file] + glob.glob("*")
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    sys.exit(f"Failed to create archive. Error: {result.stderr}")

            print(f"Created archive at {archive_file}")
        finally:
            os.chdir(original_dir)
    finally:
        if td:
            # Retry cleanup a few times on Windows
            for _ in range(3):
                try:
                    shutil.rmtree(td, ignore_errors=True)
                    break
                except Exception:
                    if os.environ.get("RUNNER_OS") == "Windows":
                        time.sleep(1)
                    else:
                        raise


def write_github_output(archive_file: str) -> None:
    """Write the archive information to GitHub Actions output."""
    output_file = os.environ.get("GITHUB_OUTPUT", os.devnull)
    if not output_file:
        sys.exit("GITHUB_OUTPUT environment variable not set.")

    with open(output_file, "a") as f:
        print(f"archive-file={Path(archive_file).name}", file=f)


def target_to_archive_name(target: str) -> str:
    """Convert a Rust target triple to an archive name segment."""
    parts = target.split("-")
    cpu = parts.pop(0).replace("aarch64", "arm64")

    if parts[0] in ("apple", "pc", "sun", "unknown"):
        parts.pop(0)
    os_name = parts.pop(0)

    # If there's more it's something like "-gnu" or "-msvc"
    if parts:
        os_name = f"{os_name}-{parts[0]}"

    os_mappings = {
        "darwin": "macOS",
        "freebsd": "FreeBSD",
        "ios": "iOS",
        "netbsd": "NetBSD",
        "openbsd": "OpenBSD",
    }

    os_name = os_mappings.get(os_name, os_name.capitalize())
    return f"{os_name}-{cpu}"


class TestExtraFilesGlobs(unittest.TestCase):
    """Test cases for handling extra files."""

    from unittest.mock import patch
    from collections import namedtuple

    ExtraFilesTestDefinition = namedtuple(
        "ExtraFilesTestDefinition", ["name", "arguments", "expected"]
    )

    @patch("os.path.isdir")
    @patch("glob.glob")
    def test_extra_files_empty(self, mocked_glob, mocked_isdir):
        mocked_glob.side_effect = lambda g, *kargs, **kwargs: []
        mocked_isdir.return_value = False

        test_definitions = [
            self.ExtraFilesTestDefinition(
                name="empty arguments", arguments=("\n".join([]), None), expected=[]
            ),
            self.ExtraFilesTestDefinition(
                name="keeps changes_file",
                arguments=("\n".join([]), "CHANGES.md"),
                expected=["CHANGES.md"],
            ),
        ]

        for test_input in test_definitions:
            with self.subTest(test_input.name):
                self.assertCountEqual(
                    gather_additional_files(*test_input.arguments), test_input.expected
                )

    @patch("os.path.isdir")
    @patch("glob.glob")
    def test_extra_files_literals(self, mocked_glob, mocked_isdir):
        mocked_glob.side_effect = lambda g, *args, **kwargs: {
            "README.md": ["README.md"],
            "CHANGES.md": ["CHANGES.md"],
            "dir/file.txt": ["dir/file.txt"],
        }.get(g, [])
        mocked_isdir.return_value = False

        test_definitions = [
            self.ExtraFilesTestDefinition(
                name="keeps singular literal file",
                arguments=("\n".join(["README.md"]), None),
                expected=["README.md"],
            ),
            self.ExtraFilesTestDefinition(
                name="keeps singular literal nested file",
                arguments=("\n".join(["dir/file.txt"]), None),
                expected=["dir/file.txt"],
            ),
            self.ExtraFilesTestDefinition(
                name="combines singular literal nested file and changes file",
                arguments=("\n".join(["dir/file.txt"]), "CHANGES.md"),
                expected=["dir/file.txt", "CHANGES.md"],
            ),
            self.ExtraFilesTestDefinition(
                "combines un- and nested file with changes file",
                arguments=("\n".join(["dir/file.txt", "README.md"]), "CHANGES.md"),
                expected=["README.md", "dir/file.txt", "CHANGES.md"],
            ),
        ]

        for test_input in test_definitions:
            with self.subTest(test_input.name):
                self.assertCountEqual(
                    gather_additional_files(*test_input.arguments), test_input.expected
                )

    @patch("os.path.isdir")
    @patch("glob.glob")
    def test_extra_files_directory(self, mocked_glob, mocked_isdir):
        mocked_glob.side_effect = lambda g, *args, **kwargs: {
            "README.md": ["README.md"],
            "dir/file.txt": ["dir/file.txt"],
            "directory/**": ["directory/file1.txt", "directory/file2.txt"],
        }.get(g, [])
        mocked_isdir.side_effect = lambda g, *args, **kwargs: g in [
            "directory/",
            "directory",
            "dir",
            "dir/",
        ]

        test_definitions = [
            self.ExtraFilesTestDefinition(
                name="handles directory (no trailing slash), combines with changes file",
                arguments=("\n".join(["directory"]), "CHANGES.md"),
                expected=["directory/file1.txt", "directory/file2.txt", "CHANGES.md"],
            ),
            self.ExtraFilesTestDefinition(
                name="handles directory (trailing slash), combines with changes file",
                arguments=("\n".join(["directory/"]), "CHANGES.md"),
                expected=["directory/file1.txt", "directory/file2.txt", "CHANGES.md"],
            ),
        ]

        for test_input in test_definitions:
            with self.subTest(test_input.name):
                self.assertCountEqual(
                    gather_additional_files(*test_input.arguments), test_input.expected
                )

    @patch("os.path.isdir")
    @patch("glob.glob")
    def test_extra_files_globs(self, mocked_glob, mocked_isdir):
        mocked_glob.side_effect = lambda g, *args, **kwargs: {
            "README.md": ["README.md"],
            "dir/**": ["dir/file1.txt", "dir/file2.txt"],
            "dir/*/file*.txt": ["dir/a/file1.txt", "dir/b/file2.txt"],
        }.get(g, [])
        mocked_isdir.return_value = False

        test_definitions = [
            self.ExtraFilesTestDefinition(
                name="handles globs, combines with changes file",
                arguments=("\n".join(["dir/**"]), "CHANGES.md"),
                expected=["dir/file1.txt", "dir/file2.txt", "CHANGES.md"],
            ),
            self.ExtraFilesTestDefinition(
                name="handles globs, combines with literal files",
                arguments=("\n".join(["README.md", "dir/**"]), None),
                expected=["README.md", "dir/file1.txt", "dir/file2.txt"],
            ),
            self.ExtraFilesTestDefinition(
                name="handles more complex globs, combines with changes file",
                arguments=("\n".join(["dir/*/file*.txt"]), "CHANGES.md"),
                expected=["dir/a/file1.txt", "dir/b/file2.txt", "CHANGES.md"],
            ),
        ]

        for test_input in test_definitions:
            with self.subTest(test_input.name):
                self.assertCountEqual(
                    gather_additional_files(*test_input.arguments), test_input.expected
                )

    @patch("os.path.isdir")
    @patch("glob.glob")
    def test_extra_files_excludes_hidden(self, mocked_glob, mocked_isdir):
        # glob.glob by default doesn't match hidden files/dirs
        mocked_glob.side_effect = lambda g, *args, **kwargs: {
            "dir/**": ["dir/file1.txt", "dir/subdir/file2.txt"],  # No .hidden files
            "**/*.txt": ["file.txt", "dir/visible.txt"],  # No .hidden.txt
        }.get(g, [])
        mocked_isdir.return_value = False

        test_definitions = [
            self.ExtraFilesTestDefinition(
                name="recursive glob excludes hidden files and directories",
                arguments=("\n".join(["dir/**"]), None),
                expected=["dir/file1.txt", "dir/subdir/file2.txt"],
            ),
            self.ExtraFilesTestDefinition(
                name="pattern glob excludes hidden files",
                arguments=("\n".join(["**/*.txt"]), None),
                expected=["file.txt", "dir/visible.txt"],
            ),
            self.ExtraFilesTestDefinition(
                name="multiple globs exclude hidden files, includes changes file",
                arguments=("\n".join(["dir/**", "**/*.txt"]), "CHANGES.md"),
                expected=[
                    "dir/file1.txt",
                    "dir/subdir/file2.txt",
                    "file.txt",
                    "dir/visible.txt",
                    "CHANGES.md",
                ],
            ),
        ]

        for test_input in test_definitions:
            with self.subTest(test_input.name):
                self.assertCountEqual(
                    gather_additional_files(*test_input.arguments), test_input.expected
                )

    @patch("os.path.isdir")
    @patch("glob.glob")
    def test_extra_files_includes_explicit_hidden(self, mocked_glob, mocked_isdir):
        # When explicitly specified, hidden files should be included
        mocked_glob.side_effect = lambda g, *args, **kwargs: {
            ".gitignore": [".gitignore"],
            ".config/settings.json": [".config/settings.json"],
        }.get(g, [])
        mocked_isdir.return_value = False

        test_definitions = [
            self.ExtraFilesTestDefinition(
                name="includes explicitly specified nested hidden file",
                arguments=("\n".join([".config/settings.json"]), None),
                expected=[".config/settings.json"],
            ),
            self.ExtraFilesTestDefinition(
                name="combines explicit hidden files with changes file",
                arguments=("\n".join([".gitignore"]), "CHANGES.md"),
                expected=[".gitignore", "CHANGES.md"],
            ),
        ]

        for test_input in test_definitions:
            with self.subTest(test_input.name):
                self.assertCountEqual(
                    gather_additional_files(*test_input.arguments), test_input.expected
                )


class TestTargetToArchiveName(unittest.TestCase):
    """Test cases for target_to_archive_name function."""

    def test_target_conversion(self):
        tests = {
            "aarch64-apple-darwin": "macOS-arm64",
            "x86_64-apple-darwin": "macOS-x86_64",
            "x86_64-pc-windows-msvc": "Windows-msvc-x86_64",
            "i686-unknown-linux-gnu": "Linux-gnu-i686",
            # ... other test cases ...
        }

        for target, expected in tests.items():
            with self.subTest(target=target):
                self.assertEqual(target_to_archive_name(target), expected)


if __name__ == "__main__":
    if len(os.sys.argv) > 1 and os.sys.argv[1] == "--test":
        unittest.main(argv=["unittest"])
    else:
        main()
