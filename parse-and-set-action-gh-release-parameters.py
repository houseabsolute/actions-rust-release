#!/usr/bin/env python3

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any, Dict
import uuid


def main():
    args = parse_arguments()
    validate_arguments(args)

    vars = json.loads(os.environ["ACTION_GH_RELEASE_PARAMETERS"])
    # Every file in this directory came from an artifact we matched, which means it is either an
    # archive or its checksum file.
    vars["files"] = f"{args.artifact_directory}/*"
    vars["fail_on_unmatched_files"] = True

    if args.changes_file:
        vars["body_path"] = str(Path(args.working_directory) / args.changes_file)

    if args.fake_tag:
        vars["tag_name"] = args.fake_tag

    write_github_output(vars)


def parse_arguments() -> argparse.Namespace:
    """Parse and return command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--working-directory", required=True)
    parser.add_argument("--artifact-directory", required=True)
    parser.add_argument("--changes-file", required=True)
    parser.add_argument("--fake-tag")
    return parser.parse_args()


def validate_arguments(args: argparse.Namespace) -> None:
    """Validate command line arguments."""
    if not args.working_directory or not os.path.isdir(args.working_directory):
        sys.exit("You must provide directory for the --working-directory option.")

    if not args.artifact_directory or not os.path.isdir(args.artifact_directory):
        sys.exit("You must provide a directory for the --artifact-directory option.")

    files = sorted(
        p.name for p in Path(args.artifact_directory).iterdir() if p.is_file()
    )
    if not files:
        sys.exit(
            f"The artifact directory '{args.artifact_directory}' does not contain any files."
        )

    print(f"Releasing {len(files)} files:")
    for file in files:
        print(f"  {file}")

    if args.changes_file:
        changes_path = Path(args.working_directory) / args.changes_file
        if not changes_path.is_file():
            sys.exit(f"Changes file '{changes_path}' does not exist.")


def write_github_output(vars: Dict[str, Any]) -> None:
    """Write the release parameters to GitHub Actions output."""
    output_file = os.environ.get("GITHUB_OUTPUT", os.devnull)
    if not output_file:
        sys.exit("GITHUB_OUTPUT environment variable not set.")

    with open(output_file, "a") as f:
        # for each key in sorted order from vars, print it to the output file
        for key in sorted(vars.keys()):
            value = vars[key]
            # `action-gh-release` compares its inputs against the string "true", so Python's `True`
            # would silently turn a parameter off.
            value = str(value).lower() if isinstance(value, bool) else str(value)
            if "\n" in value:
                # Any parameter the caller passes through can be multi-line, `body` in particular,
                # and a bare `key=value` would corrupt the output file.
                delimiter = f"EOF_{key}_{uuid.uuid4().hex}"
                print(f"{key}<<{delimiter}\n{value}\n{delimiter}", file=f)
            else:
                print(f"{key}={value}", file=f)


main()
