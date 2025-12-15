#!/usr/bin/env python3

import os
import re


def main() -> None:
    """Check whether the current tag matches the given regex pattern."""

    should_release = False
    if os.environ.get("ref_type", None) == "tag":
        match = re.match(
            os.environ.get("release_tag_regex", ""), os.environ.get("ref_name", "")
        )
        should_release = match is not None

    with open(os.environ["GITHUB_OUTPUT"], "a") as f:
        f.write(f"should_release={str(should_release).lower()}\n")


if __name__ == "__main__":
    main()
