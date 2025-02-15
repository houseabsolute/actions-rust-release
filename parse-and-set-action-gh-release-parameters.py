#!/usr/bin/env python3

import argparse
import json
import os
import sys
from typing import Any, Dict


def main():
    args = parse_arguments()
    validate_arguments(args)

    archive_path = os.path.join(args.working_directory, args.archive_file)
    if not os.path.isfile(archive_path):
        sys.exit(f"Archive file '{archive_path}' does not exist.")

    vars = json.loads(os.environ["ACTION_GH_RELEASE_PARAMETERS"])
    vars["draft"] = True
    # Appending a glob ensures we pick up the checksum file as well.
    vars["files"] = f"{archive_path}*"

    if args.changes_file:
        vars["body_path"] = args.changes_file

    if args.fake_tag:
        vars["tag_name"] = args.fake_tag

    write_github_output(args.archive_file, vars)


def parse_arguments() -> argparse.Namespace:
    """Parse and return command line arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--working-directory", required=True)
    parser.add_argument("--archive-file", required=True)
    parser.add_argument("--changes-file", required=True)
    parser.add_argument("--fake-tag")
    return parser.parse_args()


def validate_arguments(args: argparse.Namespace) -> None:
    """Validate command line arguments."""
    if not args.working_directory or not os.path.isdir(args.working_directory):
        sys.exit("You must provide directory for the --working-directory option.")

    if not args.archive_file:
        sys.exit("You must provide a file file for the --archive-file option.")

    if args.changes_file and not os.path.isfile(args.changes_file):
        sys.exit(f"Changes file '{args.changes_file}' does not exist.")


def write_github_output(archive_file: str, vars: Dict[str, Any]) -> None:
    """Write the archive information to GitHub Actions output."""
    output_file = os.environ.get("GITHUB_OUTPUT", os.devnull)
    if not output_file:
        sys.exit("GITHUB_OUTPUT environment variable not set.")

    with open(output_file, "a") as f:
        # for each key in sorted order from vars, print it to the output file
        for key in sorted(vars.keys()):
            print(f"{key}={vars[key]}", file=f)


main()
