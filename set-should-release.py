#!/usr/bin/env python3

import os
from pathlib import Path
import re
import sys
import tempfile
import unittest


def main() -> None:
    """Decide whether the current ref should produce a release."""
    ref_type = os.environ.get("REF_TYPE", "")
    ref_name = os.environ.get("REF_NAME", "")
    release_tag_regex = os.environ.get("RELEASE_TAG_REGEX", "")

    forced = is_true(os.environ.get("FORCE_RELEASE", ""))
    should_release = should_release_for(ref_type, ref_name, release_tag_regex, forced)

    print(
        f"ref_type={ref_type} ref_name={ref_name} "
        f"release-tag-regex={release_tag_regex} "
        f"-> should-release={str(should_release).lower()}"
    )

    # Not defaulting to os.devnull here. If this is somehow run outside of Actions, every gated
    # step reads an empty output and skips, and the job goes green having released nothing.
    output_file = os.environ.get("GITHUB_OUTPUT")
    if not output_file:
        sys.exit("GITHUB_OUTPUT environment variable not set.")

    with open(output_file, "a") as f:
        print(f"should-release={str(should_release).lower()}", file=f)
        # The step that builds a fake tag needs to know this too, and one place deciding it is
        # better than the same rule written twice in two languages.
        print(f"force-release={str(forced).lower()}", file=f)


def is_true(value: str) -> bool:
    """Interpret an action input as a boolean.

    Inputs arrive as strings, so a caller writing `false` would otherwise be as true as `true`.
    """
    return value.strip().lower() not in ("", "false", "0")


def should_release_for(
    ref_type: str, ref_name: str, release_tag_regex: str, force_release: bool
) -> bool:
    """Return whether the given ref should produce a release."""
    # Checked before the regex so that forcing a release cannot trip over a bad one.
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
        self.assertTrue(should_release_for("tag", "v1.2.3", "^v.*", False))
        self.assertFalse(should_release_for("tag", "1.2.3", "^v.*", False))

    def test_branches_never_release(self) -> None:
        # Even a branch whose name the regex would happily match.
        self.assertFalse(should_release_for("branch", "v1.2.3", "^v.*", False))
        self.assertFalse(should_release_for("branch", "main", ".*", False))

    def test_regex_is_anchored_at_the_start_only(self) -> None:
        """`re.match` anchors the start for you, but not the end."""
        self.assertTrue(should_release_for("tag", "v1.2.3", "v.*", False))
        self.assertFalse(should_release_for("tag", "not-v1.2.3", "v.*", False))
        # The end is not anchored unless you say so, which is the easy one to get wrong.
        self.assertTrue(
            should_release_for("tag", "v1.2.3-rc1", r"^v\d+\.\d+\.\d+", False)
        )

    def test_custom_regex(self) -> None:
        strict = r"^v\d+\.\d+\.\d+$"
        self.assertTrue(should_release_for("tag", "v1.2.3", strict, False))
        self.assertFalse(should_release_for("tag", "v1.2.3-rc1", strict, False))

    def test_release_on_every_tag(self) -> None:
        self.assertTrue(should_release_for("tag", "anything", ".*", False))

    def test_empty_regex_matches_every_tag(self) -> None:
        """validate-inputs.py rejects an empty regex, but do not depend on that silently."""
        self.assertTrue(should_release_for("tag", "anything", "", False))

    def test_force_release_overrides_everything(self) -> None:
        self.assertTrue(should_release_for("branch", "main", "^v.*", True))

    def test_force_release_is_checked_before_the_regex(self) -> None:
        self.assertTrue(should_release_for("tag", "v1.2.3", "[unterminated", True))

    def test_invalid_regex_is_fatal(self) -> None:
        with self.assertRaises(SystemExit):
            should_release_for("tag", "v1.2.3", "[unterminated", False)

    def test_is_true(self) -> None:
        for value in ("true", "TRUE", " true ", "yes", "1"):
            with self.subTest(value=value):
                self.assertTrue(is_true(value))

        # An input written as `false` is the whole reason this function exists.
        for value in ("", "false", "False", "0", "  "):
            with self.subTest(value=value):
                self.assertFalse(is_true(value))


class TestMain(unittest.TestCase):
    """Tests for what actually lands in GITHUB_OUTPUT.

    The bug this replaced was a mismatch between the key written here and the key the action
    read, which no test of should_release_for could have caught.
    """

    def run_main(self, **env: str) -> str:
        with tempfile.TemporaryDirectory() as td:
            output = Path(td) / "output"
            output.touch()
            os.environ["GITHUB_OUTPUT"] = str(output)
            for key, value in env.items():
                os.environ[key] = value
            try:
                main()
            finally:
                for key in list(env) + ["GITHUB_OUTPUT"]:
                    os.environ.pop(key, None)
            return output.read_text()

    def test_writes_should_release(self) -> None:
        out = self.run_main(REF_TYPE="tag", REF_NAME="v1.2.3", RELEASE_TAG_REGEX="^v.*")
        self.assertIn("should-release=true\n", out)
        self.assertIn("force-release=false\n", out)

    def test_writes_should_release_false(self) -> None:
        out = self.run_main(
            REF_TYPE="branch", REF_NAME="main", RELEASE_TAG_REGEX="^v.*"
        )
        self.assertIn("should-release=false\n", out)

    def test_force_release(self) -> None:
        out = self.run_main(
            REF_TYPE="branch",
            REF_NAME="main",
            RELEASE_TAG_REGEX="^v.*",
            FORCE_RELEASE="true",
        )
        self.assertIn("should-release=true\n", out)
        self.assertIn("force-release=true\n", out)

    def test_missing_github_output_is_fatal(self) -> None:
        os.environ.pop("GITHUB_OUTPUT", None)
        os.environ["REF_TYPE"] = "tag"
        os.environ["REF_NAME"] = "v1.2.3"
        os.environ["RELEASE_TAG_REGEX"] = "^v.*"
        try:
            with self.assertRaises(SystemExit):
                main()
        finally:
            for key in ("REF_TYPE", "REF_NAME", "RELEASE_TAG_REGEX"):
                os.environ.pop(key, None)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        unittest.main(argv=["unittest"])
    else:
        main()
