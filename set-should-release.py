#!/usr/bin/env python3

import os
import re
import sys
import unittest


def main() -> None:
    """Decide whether the current ref should produce a release."""
    ref_type = os.environ.get("REF_TYPE", "")
    ref_name = os.environ.get("REF_NAME", "")
    release_tag_regex = os.environ.get("RELEASE_TAG_REGEX", "")

    should_release = should_release_for(
        ref_type, ref_name, release_tag_regex, os.environ.get("FORCE_RELEASE", "")
    )

    print(
        f"ref_type={ref_type} ref_name={ref_name} "
        f"release-tag-regex={release_tag_regex} "
        f"-> should-release={str(should_release).lower()}"
    )

    output_file = os.environ.get("GITHUB_OUTPUT", os.devnull)
    with open(output_file, "a") as f:
        print(f"should-release={str(should_release).lower()}", file=f)


def should_release_for(
    ref_type: str, ref_name: str, release_tag_regex: str, force_release: str
) -> bool:
    """Return whether the given ref should produce a release."""
    if force_release:
        return True

    # Only tags ever produce a release, no matter what the regex says.
    if ref_type != "tag":
        return False

    try:
        # This is `match`, not `search`, so the regex is anchored at the start whether or not the
        # caller wrote a "^".
        return re.match(release_tag_regex, ref_name) is not None
    except re.error as e:
        sys.exit(f"The 'release-tag-regex' input is not a valid regex: {e}")


class TestShouldRelease(unittest.TestCase):
    """Unit tests for should_release_for."""

    def test_default_regex_matches_version_tags(self) -> None:
        self.assertTrue(should_release_for("tag", "v1.2.3", "^v.*", ""))
        self.assertFalse(should_release_for("tag", "1.2.3", "^v.*", ""))

    def test_branches_never_release(self) -> None:
        # Even a branch whose name the regex would happily match.
        self.assertFalse(should_release_for("branch", "v1.2.3", "^v.*", ""))
        self.assertFalse(should_release_for("branch", "main", ".*", ""))

    def test_regex_is_anchored_at_the_start(self) -> None:
        """`re.match` anchors for you, so an unanchored regex cannot match mid-string."""
        self.assertTrue(should_release_for("tag", "v1.2.3", "v.*", ""))
        self.assertFalse(should_release_for("tag", "not-v1.2.3", "v.*", ""))

    def test_custom_regex(self) -> None:
        strict = r"^v\d+\.\d+\.\d+$"
        self.assertTrue(should_release_for("tag", "v1.2.3", strict, ""))
        self.assertFalse(should_release_for("tag", "v1.2.3-rc1", strict, ""))

    def test_release_on_every_tag(self) -> None:
        self.assertTrue(should_release_for("tag", "anything", ".*", ""))

    def test_force_release_overrides_everything(self) -> None:
        self.assertTrue(should_release_for("branch", "main", "^v.*", "true"))

    def test_invalid_regex_is_fatal(self) -> None:
        with self.assertRaises(SystemExit):
            should_release_for("tag", "v1.2.3", "[unterminated", "")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        unittest.main(argv=["unittest"])
    else:
        main()
