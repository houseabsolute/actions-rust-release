#!/usr/bin/env python3

import contextlib
import io
import os
from pathlib import Path
import re
import sys
import tempfile
from typing import NamedTuple
import unittest


class Decision(NamedTuple):
    """Whether to release, and a sentence saying why.

    The reason is the whole point. Someone looking at a workflow that did not release wants to know
    which rule stopped it, not just that something did.
    """

    should_release: bool
    reason: str
    # Which rule made the call. `describe` uses this instead of working it out again from the
    # inputs, which is how the regex explanation ended up printing for a forced release that
    # never consulted the regex.
    decided_by: str


def main() -> None:
    """Decide whether the current ref should produce a release."""
    ref_type = os.environ.get("REF_TYPE", "")
    ref_name = os.environ.get("REF_NAME", "")
    release_tag_regex = os.environ.get("RELEASE_TAG_REGEX", "")

    forced = is_true(os.environ.get("FORCE_RELEASE", ""))
    decision = should_release_for(ref_type, ref_name, release_tag_regex, forced)
    should_release = decision.should_release

    for line in describe(decision, ref_type, ref_name, release_tag_regex):
        print(line)

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
) -> Decision:
    """Return whether the given ref should produce a release, and why."""
    # Checked before the regex so that forcing a release cannot trip over a bad one.
    if force_release:
        return Decision(
            True,
            "`_force-release-for-testing` is set, so this releases whatever the ref is.",
            "force",
        )

    # Only tags ever produce a release, no matter what the regex says.
    if ref_type != "tag":
        where = (
            f'the {ref_type} "{ref_name}"'
            if ref_type
            else "something that is not a tag"
        )
        return Decision(
            False,
            f"this workflow is running for {where}, and only tags release.",
            "ref-type",
        )

    try:
        # This is `match`, not `search`, so the regex is anchored at the start whether or not the
        # caller wrote a "^".
        matched = re.match(release_tag_regex, ref_name) is not None
    except re.error as e:
        sys.exit(f"The 'release-tag-regex' input is not a valid regex: {e}")

    if matched:
        return Decision(
            True, f'the tag "{ref_name}" matches the `release-tag-regex`.', "regex"
        )
    return Decision(
        False, f'the tag "{ref_name}" does not match the `release-tag-regex`.', "regex"
    )


def describe(
    decision: Decision, ref_type: str, ref_name: str, release_tag_regex: str
) -> list[str]:
    """Turn a decision into the lines to print for whoever is reading the log."""
    verdict = "Releasing" if decision.should_release else "Not releasing"
    # Printed either way, because knowing what it was set to is useful, but saying so avoids
    # sending someone off to debug a regex that had no part in the outcome.
    unused = "" if decision.decided_by == "regex" else "  (not consulted)"
    lines = [
        f"{verdict}: {decision.reason}",
        "",
        f"  ref type:          {ref_type or '(unset)'}",
        f"  ref name:          {ref_name or '(unset)'}",
        f"  release-tag-regex: {release_tag_regex or '(unset)'}{unused}",
    ]

    # Only worth explaining when the regex is what made the call. A branch never reaches it, and a
    # forced release short-circuits before it, so in both cases this would muddy the reason above.
    if decision.decided_by == "regex":
        lines += [
            "",
            "The regex is applied with `re.match`, so it is anchored at the start of the tag "
            "whether or not you wrote a `^`. The end is not anchored unless you write a `$`.",
        ]

    if not decision.should_release:
        lines += [
            "",
            "Every step that would create the release is skipped. This is not a failure.",
        ]

    return lines


class TestShouldRelease(unittest.TestCase):
    """Unit tests for should_release_for."""

    # Kept in sync with the `release-tag-regex` default in publish/action.yml.
    DEFAULT_REGEX = r"^v?\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$"

    def test_default_regex_matches_semantic_versions(self) -> None:
        for tag in ("v1.2.3", "1.2.3", "v1.2.3-rc1", "v1.2.3+build4", "v10.20.30"):
            with self.subTest(tag=tag):
                self.assertTrue(
                    should_release_for(
                        "tag", tag, self.DEFAULT_REGEX, False
                    ).should_release
                )

    def test_default_regex_rejects_other_tags(self) -> None:
        for tag in ("nightly", "latest", "v1.2", "vibes", "v-2026-07-26", "v1.2.3.4"):
            with self.subTest(tag=tag):
                self.assertFalse(
                    should_release_for(
                        "tag", tag, self.DEFAULT_REGEX, False
                    ).should_release
                )

    def test_branches_never_release(self) -> None:
        # Even a branch whose name the regex would happily match.
        self.assertFalse(
            should_release_for("branch", "v1.2.3", "^v.*", False).should_release
        )
        self.assertFalse(
            should_release_for("branch", "main", ".*", False).should_release
        )

    def test_regex_is_anchored_at_the_start_only(self) -> None:
        """`re.match` anchors the start for you, but not the end."""
        self.assertTrue(
            should_release_for("tag", "v1.2.3", "v.*", False).should_release
        )
        self.assertFalse(
            should_release_for("tag", "not-v1.2.3", "v.*", False).should_release
        )
        # The end is not anchored unless you say so, which is the easy one to get wrong.
        self.assertTrue(
            should_release_for(
                "tag", "v1.2.3-rc1", r"^v\d+\.\d+\.\d+", False
            ).should_release
        )

    def test_custom_regex(self) -> None:
        strict = r"^v\d+\.\d+\.\d+$"
        self.assertTrue(
            should_release_for("tag", "v1.2.3", strict, False).should_release
        )
        self.assertFalse(
            should_release_for("tag", "v1.2.3-rc1", strict, False).should_release
        )

    def test_release_on_every_tag(self) -> None:
        self.assertTrue(
            should_release_for("tag", "anything", ".*", False).should_release
        )

    def test_empty_regex_matches_every_tag(self) -> None:
        """validate-inputs.py rejects an empty regex, but do not depend on that silently."""
        self.assertTrue(should_release_for("tag", "anything", "", False).should_release)

    def test_force_release_overrides_everything(self) -> None:
        self.assertTrue(
            should_release_for("branch", "main", "^v.*", True).should_release
        )

    def test_force_release_is_checked_before_the_regex(self) -> None:
        self.assertTrue(
            should_release_for("tag", "v1.2.3", "[unterminated", True).should_release
        )

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
                with contextlib.redirect_stdout(io.StringIO()) as captured:
                    main()
                self.printed = captured.getvalue()
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

    def test_prints_the_reason_it_is_releasing(self) -> None:
        self.run_main(REF_TYPE="tag", REF_NAME="v1.2.3", RELEASE_TAG_REGEX="^v.*")
        self.assertIn('Releasing: the tag "v1.2.3" matches', self.printed)
        self.assertIn("release-tag-regex: ^v.*", self.printed)

    def test_prints_the_reason_it_is_not_releasing(self) -> None:
        self.run_main(REF_TYPE="branch", REF_NAME="main", RELEASE_TAG_REGEX="^v.*")
        self.assertIn(
            "Not releasing: this workflow is running for the branch", self.printed
        )
        self.assertIn("only tags release", self.printed)
        self.assertIn("This is not a failure", self.printed)
        # The regex never ran, so explaining how it is anchored would be noise.
        self.assertNotIn("anchored", self.printed)

    def test_prints_the_reason_a_tag_was_rejected(self) -> None:
        self.run_main(REF_TYPE="tag", REF_NAME="nightly", RELEASE_TAG_REGEX="^v.*")
        self.assertIn('Not releasing: the tag "nightly" does not match', self.printed)
        # Here the regex is the reason, so how it is applied is worth saying.
        self.assertIn("anchored at the start", self.printed)

    def test_forced_on_a_tag_does_not_explain_the_regex(self) -> None:
        """Forcing short-circuits before the regex, so explaining it would be a lie."""
        self.run_main(
            REF_TYPE="tag",
            REF_NAME="v1.2.3",
            RELEASE_TAG_REGEX="^v.*",
            FORCE_RELEASE="true",
        )
        self.assertIn("`_force-release-for-testing` is set", self.printed)
        self.assertNotIn("anchored", self.printed)
        self.assertIn("(not consulted)", self.printed)

    def test_prints_the_reason_it_was_forced(self) -> None:
        self.run_main(
            REF_TYPE="branch",
            REF_NAME="main",
            RELEASE_TAG_REGEX="^v.*",
            FORCE_RELEASE="true",
        )
        self.assertIn("Releasing: `_force-release-for-testing` is set", self.printed)

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
