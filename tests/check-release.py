#!/usr/bin/env python3

# Written by Claude.ai

import os
import sys
import glob
import hashlib
import subprocess
import argparse
import tempfile
from pathlib import Path
from typing import Tuple


def main() -> None:
    """Main function to validate GitHub artifacts."""
    args = parse_args()

    # Store the original working directory
    original_dir = os.getcwd()

    # Create and change to a clean temporary directory
    with tempfile.TemporaryDirectory() as td:
        try:
            os.chdir(td)

            download_artifact(args.artifact_id, args.repo, args.github_token)
            extract_artifact()

            archive_file, checksum_file = find_archive_files(
                args.executable_name, args.target
            )
            verify_checksum(checksum_file, archive_file)
            extract_archive(archive_file)
            verify_archive_contents(args.executable_name, args.changes_file)

            print("All validation checks passed successfully")
        finally:
            # Change back to the original directory before the temp directory is cleaned up. This
            # avoids errors on Windows.
            os.chdir(original_dir)


def parse_args() -> argparse.Namespace:
    """Parse and return command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-id", required=True)
    parser.add_argument("--executable-name", required=True)
    parser.add_argument("--github-token", required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--no-changes-file", dest="changes_file", action="store_false")
    parser.set_defaults(changes_file=True)

    return parser.parse_args()


def download_artifact(artifact_id: str, repo: str, github_token: str) -> None:
    """Download artifact from GitHub."""
    subprocess.run(
        [
            "curl",
            "-L",
            "-H",
            "Accept: application/vnd.github+json",
            "-H",
            f"Authorization: Bearer {github_token}",
            "-o",
            "artifact.zip",
            f"https://api.github.com/repos/{repo}/actions/artifacts/{artifact_id}/zip",
        ],
        check=True,
    )


def extract_artifact() -> None:
    """Extract the downloaded artifact zip file."""
    subprocess.run(["unzip", "artifact.zip"], check=True)


def find_archive_files(executable_name: str, target: str) -> Tuple[str, str]:
    """Find and return the archive and checksum files."""
    is_windows = "windows" in target.lower()
    glob_pattern = (
        f"{executable_name}*.zip*" if is_windows else f"{executable_name}*.tar.gz*"
    )
    files = glob.glob(glob_pattern)

    if len(files) != 2:
        sys.exit(f"Expected 2 files in artifact, found {len(files)}: {files}")

    archive_file = next((f for f in files if "sha256" not in f), None)
    checksum_file = next((f for f in files if "sha256" in f), None)

    if not archive_file:
        sys.exit("Archive file not found in artifact")
    if not checksum_file:
        sys.exit("Checksum file not found in artifact")

    return archive_file, checksum_file


def verify_checksum(checksum_file: str, archive_file: str) -> None:
    """Verify the checksum of the archive file."""
    if not Path(checksum_file).is_file():
        return

    checksum, filename = parse_checksum_file(checksum_file)

    if filename != archive_file:
        sys.exit(
            f"Checksum filename '{filename}' doesn't match archive '{archive_file}'"
        )

    calculated_checksum = calculate_file_sha256(filename)
    if checksum != calculated_checksum:
        sys.exit("Checksum verification failed")


def parse_checksum_file(checksum_file: str) -> Tuple[str, str]:
    """Parse the checksum file and return the checksum and filename."""
    with open(checksum_file) as f:
        checksum_contents = f.read().strip()

    try:
        checksum, filename = checksum_contents.split(None, 1)
        filename = filename.strip("* ")
        return checksum, filename
    except ValueError:
        sys.exit(f"Invalid checksum file format: {checksum_contents}")


def calculate_file_sha256(filename: str) -> str:
    """Calculate SHA256 hash of a file."""
    sha256 = hashlib.sha256()
    with open(filename, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()


def extract_archive(archive_file: str) -> None:
    """Extract the archive file."""
    if not Path(archive_file).is_file():
        return

    if archive_file.endswith(".zip"):
        subprocess.run(["unzip", archive_file], check=True)
    else:
        subprocess.run(["tar", "xzf", archive_file], check=True)


def verify_archive_contents(executable_name: str, include_changes_file: bool) -> None:
    """Verify the contents of the extracted archive."""
    expected_files = ["README.md"]
    if include_changes_file:
        expected_files.append("Changes.md")

    if os.environ.get("RUNNER_OS") == "Windows":
        executable_name = executable_name + ".exe"

    expected_files.append(executable_name)

    for file in expected_files:
        if not Path(file).is_file():
            sys.exit(f"Expected file '{file}' not found in archive")

    # Check executable permissions
    exec_path = Path(executable_name)
    if not os.access(exec_path, os.X_OK):
        sys.exit(f"'{executable_name}' is not executable")


if __name__ == "__main__":
    main()
