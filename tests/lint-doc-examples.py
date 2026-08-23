#!/usr/bin/env python3

"""Run zizmor over the workflow examples in the docs.

The examples are the thing most people copy, so they should hold up to the same audit the repo's
own workflows get. Nothing else checks them, and a doc edit is exactly the kind of change nobody
thinks to re-audit.
"""

import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import traceback
import unittest

DOCS = ("README.md", "MIGRATING.md", "Changes.md")

# The persona the repo lints its own workflows with. Kept in sync with precious.toml.
PERSONA = "pedantic"

# A block that says `# your platforms here` leaves the matrix value null, which zizmor rejects as
# an invalid workflow. It skips such a file with a warning rather than failing, so without this the
# audit quietly checks nothing. See `assert_nothing_was_skipped`.
PLACEHOLDER = re.compile(r"^ *# your platforms here.*$", re.M)
REAL_PLATFORM = """          - os-name: Linux-x86_64
            runs-on: ubuntu-24.04
            target: x86_64-unknown-linux-musl"""

# The examples cannot pin this repo's own actions, because there is no released SHA to pin to yet.
# Rewriting them to a fake pin means the audit has to come back completely clean, rather than
# needing an allow list that would also hide a genuinely unpinned third-party action.
OWN_ACTION = re.compile(r"(houseabsolute/actions-rust-release(?:/publish)?)@v\d+")
FAKE_PIN = r"\g<1>@" + "0" * 40 + " # v0.0.0"

# What a job fragment gets wrapped in so that it is a workflow zizmor will look at. Only the
# fragments need this. The full examples bring their own.
WRAPPER = """name: example

on:
  push:
    tags:
      - "v[0-9]*"

permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  cancel-in-progress: false

jobs:
"""


def die(message: str) -> None:
    """Exit with the code precious treats as a hard error rather than a lint failure."""
    print(message, file=sys.stderr)
    sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--zizmor", default="zizmor", help="the zizmor executable to run"
    )
    args = parser.parse_args()

    if shutil.which(args.zizmor) is None:
        die(f"Could not find '{args.zizmor}' on PATH.")

    wide = [line for doc in DOCS for line in too_wide_in(Path(doc))]

    examples = [(name, body) for doc in DOCS for name, body in examples_in(Path(doc))]
    if not examples:
        # Every doc losing its examples at once is far more likely to be a bug in the extraction
        # above than a real edit, and passing on zero inputs is the failure mode of this whole
        # script.
        die(f"Found no workflow examples in {', '.join(DOCS)}.")

    with tempfile.TemporaryDirectory() as td:
        workflows = Path(td) / ".github" / "workflows"
        workflows.mkdir(parents=True)
        for name, body in examples:
            (workflows / name).write_text(body)

        print(f"Auditing {len(examples)} examples with zizmor --persona {PERSONA}:")
        for name, _ in examples:
            print(f"  {name}")

        found = audit(args.zizmor, Path(td), [name for name, _ in examples])

    # Reported last so that it is the part still on screen when the run ends.
    if wide:
        print(
            f"\n{len(wide)} line(s) in the docs' YAML blocks are wider than {MAX_WIDTH} "
            "characters:\n",
            file=sys.stderr,
        )
        for line in wide:
            print(f"  {line}", file=sys.stderr)
        print(
            "\nGitHub does not wrap the contents of a code block, so one long line puts a "
            "horizontal scroll bar under the whole example.",
            file=sys.stderr,
        )

    return found or (1 if wide else 0)


# Narrow enough that GitHub renders the examples without a horizontal scroll bar.
MAX_WIDTH = 88

# The 40 characters of a commit SHA are not something an example can trim, so a line pinning an
# action gets to be that much longer. The rest of it, including the version comment Dependabot
# maintains, is still held to `MAX_WIDTH`.
PINNED_SHA = re.compile(r"^( *-? *uses: \S+@)[0-9a-f]{40}")


def measured(line: str) -> str:
    """The part of a line that has to fit in `MAX_WIDTH`."""
    return PINNED_SHA.sub(r"\g<1>", line)


def too_wide_in(doc: Path) -> list[str]:
    """Return one message per over-long line in the doc's YAML blocks."""
    found = []
    text = doc.read_text()
    for block in re.finditer(r"```yaml\n(.*?)```", text, re.S):
        # Count from the line the block's contents start on.
        first = text.count("\n", 0, block.start(1)) + 1
        for offset, line in enumerate(block.group(1).split("\n")):
            width = len(measured(line))
            if width > MAX_WIDTH:
                found.append(
                    f"{doc}:{first + offset} is {width} characters: {line.strip()}"
                )
    return found


# The blocks that are not examples are snippets of inputs. None of them can contain any of this,
# so a block that does and still fails to classify is an example this script has stopped
# recognising, not a snippet.
LOOKS_LIKE_A_WORKFLOW = re.compile(r"^ *(jobs:|runs-on:|steps:|- uses:)", re.M)


def examples_in(doc: Path) -> list[tuple[str, str]]:
    """Return every workflow example in a doc, as (file name, workflow) pairs."""
    found = []
    for i, block in enumerate(re.findall(r"```yaml\n(.*?)```", doc.read_text(), re.S)):
        # A fenced block inside a list item is indented along with the item. Line endings are
        # normalised because both checks in `as_workflow` are written against "\n".
        block = textwrap.dedent(block.replace("\r\n", "\n"))
        workflow = as_workflow(block)
        if workflow is None:
            if LOOKS_LIKE_A_WORKFLOW.search(block):
                die(
                    f"Block {i + 1} of {doc} looks like a workflow example but does not match "
                    "either shape `as_workflow` knows about, so it would go unaudited. Either "
                    "the example changed shape, or `as_workflow` needs to learn the new one."
                    f"\n\n{textwrap.indent(block, '  ')}"
                )
            continue
        found.append((f"{doc.stem}-{i}.yml", workflow))
    return found


def as_workflow(block: str) -> str | None:
    """Turn one fenced block into a workflow to audit, or None if it is not one.

    Some blocks are whole workflows, some are a job or two on their own, and the rest are input
    snippets that have nothing to audit.
    """
    if block.startswith("name:") and "\njobs:\n" in block:
        workflow = block
    elif re.match(r"^[a-z][a-z-]*:\n +name:", block):
        workflow = WRAPPER + textwrap.indent(block, "  ")
    else:
        return None

    workflow = PLACEHOLDER.sub(REAL_PLATFORM, workflow)
    return OWN_ACTION.sub(FAKE_PIN, workflow)


def audit(zizmor: str, root: Path, names: list[str]) -> int:
    """Run zizmor over the extracted workflows and report what it says."""
    result = subprocess.run(
        # Offline because the online audits check that a pinned SHA really exists in the action's
        # repository. The examples' pins for this repo's own actions are fakes, put there so the
        # unpinned-uses audit has something to look at, so those audits would always fail here.
        # Whether a real pin has gone stale is a question for the docs, not for zizmor.
        [zizmor, "--offline", "--persona", PERSONA, "--format", "json", str(root)],
        capture_output=True,
        text=True,
    )

    assert_everything_was_audited(result.stderr, names)

    # zizmor exits 11-14 depending on the worst severity it found, and 0 when it found nothing.
    # Anything else means zizmor itself failed, which is not a lint failure.
    if result.returncode not in (0, 11, 12, 13, 14):
        die(
            f"zizmor failed with exit code {result.returncode}:\n{result.stderr.strip()}"
        )

    findings = json.loads(result.stdout)
    if not findings:
        print(f"\nNo findings in {len(names)} examples.")
        return 0

    print(f"\n{len(findings)} finding(s) in the doc examples:\n", file=sys.stderr)
    for finding in findings:
        print(f"  {describe(finding)}", file=sys.stderr)
    print(
        "\nThese are the workflows in the docs, not this repo's own. Fix the example in the "
        "doc it came from.",
        file=sys.stderr,
    )
    return 1


def describe(finding: dict) -> str:
    """One line naming a finding and where in which example it is."""
    ident = finding.get("ident", "?")
    description = finding.get("desc", "")

    locations = finding.get("locations") or []
    if not locations:
        return f"{ident}: {description}"

    symbolic = locations[0].get("symbolic") or {}
    path = ((symbolic.get("key") or {}).get("Local") or {}).get("verbatim_path", "")
    # zizmor counts rows from zero, but everyone reading this counts lines from one.
    row = (
        ((locations[0].get("concrete") or {}).get("location") or {})
        .get("start_point", {})
        .get("row")
    )
    where = Path(path).name or "?"
    if row is not None:
        where += f":{row + 1}"

    detail = symbolic.get("annotation") or description
    return f"{ident} [{where}]: {detail}"


# zizmor logs this for each input it really audited. Checking for these rather than for the
# warnings it emits when it gives up is deliberate. There is more than one way for it to give up,
# each with its own wording, and the one for unparsable YAML does not even name the file.
COMPLETED = re.compile(r"completed (?P<path>\S+)")


def assert_everything_was_audited(stderr: str, names: list[str]) -> None:
    """Fail unless zizmor audited every example.

    An input zizmor cannot read is skipped with a warning on stderr, not an error, and the run
    still exits 0. That is indistinguishable from an audit that found nothing, which would make
    this whole check quietly vacuous.
    """
    audited = {Path(m.group("path")).name for m in COMPLETED.finditer(stderr)}
    missing = [name for name in names if name not in audited]
    if missing:
        die(
            f"zizmor did not audit {len(missing)} of the {len(names)} examples, so it skipped "
            f"them rather than checking them: {', '.join(missing)}\n\n{stderr.strip()}"
        )


class TestAsWorkflow(unittest.TestCase):
    """Unit tests for turning a fenced block into something auditable."""

    def test_input_snippets_are_not_workflows(self) -> None:
        self.assertIsNone(as_workflow("executable-name: my-project\n"))
        self.assertIsNone(as_workflow("with:\n  latest: false\n"))

    def test_a_whole_workflow_is_kept(self) -> None:
        block = (
            "name: Release\n\non:\n  push:\n\njobs:\n  package:\n    name: Package\n"
        )
        self.assertEqual(as_workflow(block), block)

    def test_a_job_fragment_is_wrapped(self) -> None:
        workflow = as_workflow("publish:\n  name: Publish\n  runs-on: ubuntu-24.04\n")
        self.assertIsNotNone(workflow)
        assert workflow is not None
        self.assertTrue(workflow.startswith("name: example"))
        self.assertIn("\n  publish:\n    name: Publish\n", workflow)

    def test_the_platform_placeholder_is_replaced(self) -> None:
        """Left alone, the null matrix makes zizmor skip the file entirely."""
        workflow = as_workflow(
            "name: x\n\njobs:\n  package:\n    name: p\n    strategy:\n"
            "      matrix:\n        platform:\n          # your platforms here\n"
        )
        assert workflow is not None
        self.assertNotIn("your platforms here", workflow)
        self.assertIn("os-name: Linux-x86_64", workflow)

    def test_this_repos_own_actions_are_given_a_fake_pin(self) -> None:
        workflow = as_workflow(
            "name: x\n\njobs:\n  j:\n    name: j\n    steps:\n"
            "      - uses: houseabsolute/actions-rust-release@v1\n"
            "      - uses: houseabsolute/actions-rust-release/publish@v1\n"
            "      - uses: houseabsolute/actions-rust-release@v0\n"
        )
        assert workflow is not None
        self.assertNotIn("@v0", workflow)
        self.assertNotIn("@v1\n", workflow)
        self.assertEqual(workflow.count("@" + "0" * 40), 3)

    def test_other_actions_are_left_alone(self) -> None:
        """Rewriting these would hide a genuinely unpinned action in an example."""
        workflow = as_workflow(
            "name: x\n\njobs:\n  j:\n    name: j\n    steps:\n"
            "      - uses: actions/checkout@v7\n"
        )
        assert workflow is not None
        self.assertIn("actions/checkout@v7", workflow)


class TestTooWideIn(unittest.TestCase):
    """Unit tests for the check that keeps the examples free of a horizontal scroll bar."""

    def setUp(self) -> None:
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.dir = Path(td.name)

    def write(self, body: str) -> Path:
        doc = self.dir / "doc.md"
        doc.write_text(body)
        return doc

    def test_reports_a_long_line_with_its_place_in_the_doc(self) -> None:
        doc = self.write(
            "intro\n\n```yaml\nshort: yes\n" + "long: " + "x" * 90 + "\n```\n"
        )
        found = too_wide_in(doc)
        self.assertEqual(len(found), 1)
        self.assertIn(f"{doc}:5 is 96 characters", found[0])

    def test_ignores_text_outside_a_yaml_block(self) -> None:
        self.assertEqual(too_wide_in(self.write("x" * 200 + "\n")), [])

    def test_only_the_sha_is_free_on_a_pinned_uses_line(self) -> None:
        doc = self.write(
            "```yaml\n      - uses: some/action@"
            + "a" * 40
            + " # v1.2.3 and then some more\n```\n"
        )
        self.assertEqual(too_wide_in(doc), [])

    def test_a_pinned_uses_line_with_a_long_comment_is_still_too_wide(self) -> None:
        doc = self.write(
            "```yaml\n      - uses: some/action@"
            + "a" * 40
            + " # "
            + "x" * 80
            + "\n```\n"
        )
        self.assertEqual(len(too_wide_in(doc)), 1)

    def test_does_not_exempt_a_uses_line_pinned_to_a_tag(self) -> None:
        doc = self.write("```yaml\n      - uses: some/" + "a" * 80 + "@v1\n```\n")
        self.assertEqual(len(too_wide_in(doc)), 1)


class TestAssertEverythingWasAudited(unittest.TestCase):
    """Unit tests for the guard against zizmor quietly auditing nothing."""

    STDERR = (
        " INFO audit: zizmor: \U0001f308 completed /tmp/x/.github/workflows/a.yml\n"
        " INFO audit: zizmor: \U0001f308 completed /tmp/x/.github/workflows/b.yml\n"
    )

    def test_passes_when_every_example_was_audited(self) -> None:
        assert_everything_was_audited(self.STDERR, ["a.yml", "b.yml"])

    def test_fails_when_an_example_was_skipped(self) -> None:
        with self.assertRaises(SystemExit) as cm:
            assert_everything_was_audited(self.STDERR, ["a.yml", "b.yml", "c.yml"])
        self.assertEqual(cm.exception.code, 2)

    def test_fails_on_unparsable_yaml(self) -> None:
        """This skip does not name the file, which is why the check is a positive one."""
        stderr = (
            " WARN collect_inputs: zizmor::registry::input: failed to parse input: "
            "did not find expected node content at line 6 column 1\n"
        )
        with self.assertRaises(SystemExit):
            assert_everything_was_audited(stderr, ["a.yml"])


class TestDescribe(unittest.TestCase):
    """The point of a finding is knowing which example to go and fix."""

    def test_names_the_example_and_the_line(self) -> None:
        finding = {
            "ident": "unpinned-uses",
            "desc": "unpinned action reference",
            "locations": [
                {
                    "symbolic": {
                        "key": {"Local": {"verbatim_path": "/tmp/x/README-0.yml"}},
                        "annotation": "action is not pinned to a hash",
                    },
                    # zizmor counts rows from zero.
                    "concrete": {"location": {"start_point": {"row": 41}}},
                }
            ],
        }
        self.assertEqual(
            describe(finding),
            "unpinned-uses [README-0.yml:42]: action is not pinned to a hash",
        )

    def test_survives_a_finding_with_no_location(self) -> None:
        self.assertEqual(describe({"ident": "x", "desc": "y", "locations": []}), "x: y")


class TestExamplesIn(unittest.TestCase):
    """Tests against the real docs, so that a doc rewrite cannot silently empty this out."""

    def test_an_unrecognised_workflow_block_is_fatal(self) -> None:
        """Silently dropping an example is the failure mode this whole script has to avoid."""
        with tempfile.TemporaryDirectory() as td:
            doc = Path(td) / "doc.md"
            doc.write_text("```yaml\n# a comment first\nname: x\n\njobs:\n  j:\n```\n")
            with self.assertRaises(SystemExit) as cm:
                examples_in(doc)
            self.assertEqual(cm.exception.code, 2)

    def test_an_input_snippet_is_not_fatal(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            doc = Path(td) / "doc.md"
            doc.write_text("```yaml\nexecutable-name: my-project\n```\n")
            self.assertEqual(examples_in(doc), [])

    def test_the_readme_has_an_example(self) -> None:
        found = examples_in(Path(__file__).parent.parent / "README.md")
        self.assertTrue(found, "found no workflow example in README.md")
        self.assertIn("jobs:", found[0][1])


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--test":
        unittest.main(argv=["unittest"])
    else:
        try:
            sys.exit(main())
        except SystemExit:
            raise
        except Exception:
            # Exit 1 means "zizmor found something in a doc". A crash in here is not that, and
            # precious would otherwise report a broken linter as a lint failure.
            traceback.print_exc()
            die("This script failed. See the traceback above.")
