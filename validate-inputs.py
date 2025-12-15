#!/usr/bin/env python3

import argparse
import glob
import os
import json
from pathlib import Path
import re
from typing import Dict, List, Union
import tempfile
import unittest

PACKAGE_MODE = "package"
PUBLISH_MODE = "publish"


def main() -> None:
    """Main function for running the validator."""
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument("repo_root")
    parser.add_argument("--mode", choices=[PACKAGE_MODE, PUBLISH_MODE], required=True)
    args = parser.parse_args()

    validator = InputValidator(args.repo_root, args.mode)
    errors = validator.validate()

    if not errors:
        print("All inputs are valid.")
        sys.exit(0)
    else:
        for error in errors:
            print(error, file=sys.stderr)
        sys.exit(1)


class InputValidator:
    """Validate inputs for a GitHub Action that handles Rust binary releases."""

    def __init__(self, repo_root: Union[str, Path], mode: str = PACKAGE_MODE):
        """
        Create a new InputValidator by collecting environment variables.

        Args:
            repo_root: Path to the repository root
            mode: Which action's inputs are being validated, "package" or "publish"
        """
        self.repo_root = Path(repo_root)
        self.mode = mode
        self.inputs: Dict[str, str] = {
            key.replace("INPUTS_", "").lower(): value
            for key, value in os.environ.items()
            if key.startswith("INPUTS_")
        }

    def validate(self) -> List[str]:
        """
        Validate all inputs according to specifications.

        Returns:
            List of validation errors. Empty list means all inputs are valid.
        """
        validation_errors: List[str] = []

        if self.mode == PACKAGE_MODE:
            # Check for required executable-name parameter
            if not self.inputs.get("executable_name"):
                validation_errors.append("'executable-name' is a required parameter")

            # Validate that either target or archive-name is present
            if not self.inputs.get("target") and not self.inputs.get("archive_name"):
                validation_errors.append(
                    "Either 'target' or 'archive-name' must be provided"
                )
        else:
            # The publish action only needs the executable name in order to construct a default
            # regex, so an explicit regex makes it unnecessary.
            if not self.inputs.get("executable_name") and not self.inputs.get(
                "artifact_regex"
            ):
                validation_errors.append(
                    "Either 'executable-name' or 'artifact-regex' must be provided"
                )

            if self.inputs.get("artifact_regex"):
                try:
                    re.compile(self.inputs["artifact_regex"])
                except re.error as e:
                    validation_errors.append(
                        f"'artifact-regex' is not a valid regex: {e}"
                    )

        # Validate release-tag-regex if present
        if "release_tag_regex" in self.inputs:
            if not self.inputs["release_tag_regex"]:
                validation_errors.append(
                    "'release-tag-regex' cannot be empty if provided"
                )
            else:
                try:
                    _ = re.compile(self.inputs["release_tag_regex"])
                except re.error as e:
                    validation_errors.append(
                        f"Invalid regex pattern for 'release-tag-regex': {e}"
                    )

        # Validate working directory if present
        working_dir = self.inputs.get("working_directory", ".")
        path = Path(working_dir)
        if not path.is_absolute():
            path = self.repo_root / path

        working_dir_is_valid = True
        if not path.exists():
            working_dir_is_valid = False
            validation_errors.append(
                f"'working-directory' does not exist: {working_dir}"
            )
        elif not path.is_dir():
            working_dir_is_valid = False
            validation_errors.append(
                f"'working-directory' is not a directory: {working_dir}"
            )

        # Everything below resolves relative paths against the working directory, the same way
        # make-archive.py does, so there's nothing useful to say if that directory is bogus.
        if working_dir_is_valid:
            # Validate changes file exists and is a file if this was set.
            changes_file = self.inputs.get("changes_file")
            if changes_file:
                changes_path = path / changes_file
                if not changes_path.exists():
                    validation_errors.append(
                        f"Changes file '{changes_file}' not found in working directory"
                    )
                elif not changes_path.is_file():
                    validation_errors.append(
                        f"Changes file '{changes_file}' exists but is not a regular file"
                    )

            # Validate extra-files if present
            if self.inputs.get("extra_files"):
                validation_errors.extend(self.validate_extra_files(path))

        # Validate action-gh-release-parameters JSON if present
        if self.inputs.get("action_gh_release_parameters"):
            try:
                json.loads(self.inputs["action_gh_release_parameters"])
            except json.JSONDecodeError:
                validation_errors.append(
                    "'action-gh-release-parameters' must be valid JSON"
                )

        return validation_errors

    def validate_extra_files(self, working_dir: Path) -> List[str]:
        """
        Validate the extra-files input.

        Args:
            working_dir: The resolved working directory. Relative paths are resolved against
                this, because that's what make-archive.py does when it packages them.
        """
        validation_errors: List[str] = []

        extra_files = self.inputs["extra_files"].strip()
        if extra_files:
            files = [f.strip() for f in extra_files.splitlines()]
            for file_path in files:
                # Empty lines are okay.
                if file_path:
                    path = Path(file_path)
                    if not path.is_absolute():
                        path = working_dir / path

                    # Note that the "*" test, and the globbing itself, have to match what
                    # make-archive.py does, or we will accept things it cannot package. It globs
                    # the entry as given after chdir'ing to the working directory, so we glob with
                    # the working directory as the root, not by joining paths. Otherwise a
                    # workspace path containing something like "[" would change how we match.
                    if "*" in file_path:
                        # An absolute pattern ignores root_dir, and matches for a relative one
                        # come back relative to it.
                        matches = [
                            working_dir / m
                            for m in glob.glob(file_path, root_dir=working_dir)
                        ]
                        if not matches:
                            validation_errors.append(
                                f"Extra file '{file_path}' does not match any paths"
                            )
                        for match in matches:
                            if not match.is_file():
                                validation_errors.append(
                                    f"Extra file '{file_path}' is not a file"
                                )
                    else:
                        if not path.exists():
                            validation_errors.append(
                                f"Extra file '{file_path}' does not exist"
                            )
                        elif path.is_dir():
                            validation_errors.append(
                                f"Extra file '{file_path}' is a directory"
                            )

        return validation_errors


class TestInputValidator(unittest.TestCase):
    """Unit tests for the InputValidator."""

    def setUp(self) -> None:
        """Set up test environment with a clean temp directory."""
        # Clear any existing INPUTS_ environment variables
        for key in list(os.environ.keys()):
            if key.startswith("INPUTS_"):
                del os.environ[key]

        # Create a new temporary directory for each test
        self.temp_dir = tempfile.mkdtemp()

        # Create a default Changes.md file that most tests need
        self.create_file("Changes.md", "# Changes")

    def tearDown(self) -> None:
        """Clean up the temporary test directory."""
        import shutil

        shutil.rmtree(self.temp_dir)

    def create_file(self, name: str, content: str = "") -> Path:
        """Create a file in the test directory with given content."""
        path = Path(self.temp_dir) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        return path

    def create_directory(self, name: str) -> Path:
        """Create a directory in the test directory."""
        path = Path(self.temp_dir) / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def setup_env(self, inputs: Dict[str, str]) -> None:
        """Set up environment variables for testing."""
        for key, value in inputs.items():
            env_key = f"INPUTS_{key.upper().replace('-', '_')}"
            os.environ[env_key] = value

    def test_get_inputs_from_env(self) -> None:
        """Test getting inputs from environment variables."""
        inputs = {
            "executable-name": "my-app",
            "target": "x86_64-unknown-linux-gnu",
            "release-tag-regex": "v.*",
            "working-directory": self.temp_dir,
        }
        self.setup_env(inputs)

        validator = InputValidator(self.temp_dir)
        for key, value in validator.inputs.items():
            self.assertEqual(value, inputs[key.replace("_", "-")])

    def test_validate_release_tag_regex(self) -> None:
        """Test validation with missing executable-name."""
        inputs = {
            "executable-name": "my-app",
            "target": "x86_64-unknown-linux-gnu",
            "release-tag-regex": "[asd",
            "working-directory": self.temp_dir,
        }
        self.setup_env(inputs)
        validator = InputValidator(self.temp_dir)
        errors = validator.validate()
        self.assertTrue(any("release-tag-regex" in error for error in errors))

    def test_validate_missing_executable_name(self) -> None:
        """Test validation with missing executable-name."""
        self.setup_env(
            {"target": "x86_64-unknown-linux-gnu", "working-directory": self.temp_dir}
        )
        validator = InputValidator(self.temp_dir)
        errors = validator.validate()
        self.assertTrue(any("executable-name" in error for error in errors))

    def test_validate_empty_executable_name(self) -> None:
        """An empty value is as good as missing - the action always sets the env var."""
        self.setup_env(
            {
                "executable-name": "",
                "target": "",
                "archive-name": "",
                "extra-files": "",
                "working-directory": self.temp_dir,
            }
        )
        validator = InputValidator(self.temp_dir)
        errors = validator.validate()
        self.assertTrue(any("executable-name" in error for error in errors))
        self.assertTrue(any("archive-name" in error for error in errors))

    def test_validate_missing_target_and_archive_name(self) -> None:
        """Test validation with missing target and archive-name."""
        self.setup_env(
            {"executable-name": "my-app", "working-directory": self.temp_dir}
        )
        validator = InputValidator(self.temp_dir)
        errors = validator.validate()
        self.assertTrue(any("target" in error for error in errors))

    def test_validate_working_directory(self) -> None:
        """Test validation of working directory."""
        # Test with valid directory
        self.setup_env(
            {
                "executable-name": "my-app",
                "target": "x86_64-unknown-linux-gnu",
                "working-directory": self.temp_dir,
            }
        )
        validator = InputValidator(self.temp_dir)
        errors = validator.validate()
        self.assertFalse(errors)

        # Test with non-existent directory
        self.setup_env(
            {
                "executable-name": "my-app",
                "target": "x86_64-unknown-linux-gnu",
                "working-directory": str(Path(self.temp_dir) / "nonexistent"),
            }
        )
        validator = InputValidator(self.temp_dir)
        errors = validator.validate()
        self.assertTrue(any("does not exist" in error for error in errors))

    def test_validate_extra_files_in_working_directory(self) -> None:
        """Extra files are resolved from the working directory, like make-archive.py does."""
        self.create_directory("sub")
        self.create_file("sub/extra.txt", "extra")
        self.create_file("sub/README.md", "readme")
        inputs = {
            "executable-name": "my-app",
            "target": "x86_64-unknown-linux-gnu",
            "working-directory": "sub",
        }

        self.create_file("sub/docs/guide.txt", "guide")
        self.setup_env({**inputs, "extra-files": "extra.txt\nREADME*\ndo*/guide.txt"})
        self.assertFalse(InputValidator(self.temp_dir).validate())

        # A file that only exists at the repo root is not visible from the working directory.
        self.create_file("root-only.txt", "root")
        self.setup_env({**inputs, "extra-files": "root-only.txt"})
        errors = InputValidator(self.temp_dir).validate()
        self.assertTrue(any("does not exist" in error for error in errors))

        # A glob is only checked against the working directory too.
        self.setup_env({**inputs, "extra-files": "root-only*"})
        errors = InputValidator(self.temp_dir).validate()
        self.assertTrue(any("does not match any paths" in error for error in errors))

    def test_validate_changes_file(self) -> None:
        """Test validation of changes file."""
        # Test with changes file present
        self.setup_env(
            {
                "executable-name": "my-app",
                "target": "x86_64-unknown-linux-gnu",
                "working-directory": self.temp_dir,
            }
        )
        validator = InputValidator(self.temp_dir)
        errors = validator.validate()
        self.assertFalse(errors)

        # Test with empty string for changes file
        self.setup_env(
            {
                "executable-name": "my-app",
                "target": "x86_64-unknown-linux-gnu",
                "working-directory": self.temp_dir,
                "changes-file": "",
            }
        )
        validator = InputValidator(self.temp_dir)
        errors = validator.validate()
        self.assertFalse(errors)

        # Test with explicit path for changes file
        self.setup_env(
            {
                "executable-name": "my-app",
                "target": "x86_64-unknown-linux-gnu",
                "working-directory": self.temp_dir,
                "changes-file": "Changes.md",
            }
        )
        validator = InputValidator(self.temp_dir)
        errors = validator.validate()
        self.assertFalse(errors)

        # Test with missing changes file
        os.unlink(Path(self.temp_dir) / "Changes.md")
        self.setup_env(
            {
                "executable-name": "my-app",
                "target": "x86_64-unknown-linux-gnu",
                "working-directory": self.temp_dir,
            }
        )
        validator = InputValidator(self.temp_dir)
        errors = validator.validate()
        self.assertTrue("not found in working directory" in error for error in errors)

    def test_publish_mode_needs_name_or_regex(self) -> None:
        """Publish mode accepts either executable-name or artifact-regex."""
        self.setup_env({"working-directory": self.temp_dir})
        errors = InputValidator(self.temp_dir, PUBLISH_MODE).validate()
        self.assertTrue(any("artifact-regex" in error for error in errors))

        self.setup_env(
            {"working-directory": self.temp_dir, "artifact-regex": r"\Aubi-.+\Z"}
        )
        self.assertFalse(InputValidator(self.temp_dir, PUBLISH_MODE).validate())

        self.setup_env({"working-directory": self.temp_dir, "executable-name": "ubi"})
        self.assertFalse(InputValidator(self.temp_dir, PUBLISH_MODE).validate())

    def test_publish_mode_ignores_package_inputs(self) -> None:
        """Publish mode does not require target or archive-name."""
        self.setup_env({"executable-name": "ubi", "working-directory": self.temp_dir})
        self.assertFalse(InputValidator(self.temp_dir, PUBLISH_MODE).validate())

    def test_publish_mode_invalid_regex(self) -> None:
        """Publish mode rejects a regex that does not compile."""
        self.setup_env({"working-directory": self.temp_dir, "artifact-regex": "a["})
        errors = InputValidator(self.temp_dir, PUBLISH_MODE).validate()
        self.assertTrue(any("not a valid regex" in error for error in errors))


if __name__ == "__main__":
    if len(os.sys.argv) > 1 and os.sys.argv[1] == "--test":
        unittest.main(argv=["unittest"])
    else:
        main()
