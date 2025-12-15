#!/usr/bin/env python3

import os
import json
from pathlib import Path
import re
from typing import Dict, List, Union
import tempfile
import unittest


def main() -> None:
    """Main function for running the validator."""
    import sys

    validator = InputValidator(sys.argv[1])
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

    def __init__(self, repo_root: Union[str, Path]):
        """
        Create a new InputValidator by collecting environment variables.

        Args:
            repo_root: Path to the repository root
        """
        self.repo_root = Path(repo_root)
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

        # Check for required executable-name parameter
        if "executable_name" not in self.inputs:
            validation_errors.append("'executable-name' is a required parameter")

        # Validate that either target or archive-name is present
        if "target" not in self.inputs and "archive_name" not in self.inputs:
            validation_errors.append(
                "Either 'target' or 'archive-name' must be provided"
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

        if not path.exists():
            validation_errors.append(
                f"'working-directory' does not exist: {working_dir}"
            )
        elif not path.is_dir():
            validation_errors.append(
                f"'working-directory' is not a directory: {working_dir}"
            )

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
        if "extra_files" in self.inputs:
            validation_errors.extend(self.validate_extra_files())

        # Validate action-gh-release-parameters JSON if present
        if "action_gh_release_parameters" in self.inputs:
            try:
                json.loads(self.inputs["action_gh_release_parameters"])
            except json.JSONDecodeError:
                validation_errors.append(
                    "'action-gh-release-parameters' must be valid JSON"
                )

        return validation_errors

    def validate_extra_files(self) -> List[str]:
        validation_errors: List[str] = []

        extra_files = self.inputs["extra_files"].strip()
        if extra_files:
            files = [f.strip() for f in extra_files.split("\n")]
            if not files:
                validation_errors.append("'extra-files' is empty")
            for file_path in files:
                # Empty lines are okay.
                if file_path:
                    path = Path(file_path)
                    if not path.is_absolute():
                        path = self.repo_root / path

                    if "*" in path.name:
                        matches = list(path.parent.glob(path.name))
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


if __name__ == "__main__":
    if len(os.sys.argv) > 1 and os.sys.argv[1] == "--test":
        unittest.main(argv=["unittest"])
    else:
        main()
