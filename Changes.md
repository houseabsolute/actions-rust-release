## 1.0.0 - unreleased

- **Breaking change**: Creating the GitHub release has moved out of this action and into a new
  `houseabsolute/actions-rust-release/publish` action. This action now only packages your executable
  and uploads it as a workflow artifact.

  This exists because almost everyone calls this action from inside a build matrix. When the same
  action both packaged and released, a matrix leg that finished early would publish its archive
  while other legs were still building - or failing - so a release missing one platform's executable
  could go public. Every leg of the matrix also raced to create the same release.

  To upgrade, drop the release-specific inputs from your existing invocation and add a job which
  runs after all of your build jobs:

  ```yaml
  publish:
    name: Publish GitHub release
    needs: package
    runs-on: ubuntu-24.04
    permissions:
      actions: read # The publish action lists this run's artifacts.
      contents: write # Creating the release writes to this repository.
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: houseabsolute/actions-rust-release/publish@v1
        with:
          executable-name: my-project
  ```

  The tag-matching and release inputs now belong to the `publish` action. The packaging action no
  longer accepts them. See [the migration guide](MIGRATING.md) for the details, including what
  happened to every v0 input.

- The `publish` action takes a new `artifact-regex` input. It asks the GitHub API which artifacts
  belong to the current workflow run, and only downloads and releases the ones whose names match.
  The default, `\A<executable-name>.*\.(tar\.[a-z]+|zip)\Z`, matches the archives created by the
  packaging action. This keeps unrelated artifacts, like coverage reports or logs, out of your
  releases. Note that the job calling `publish` needs the `actions: read` permission in order to
  list the run's artifacts.
- The `release-tag-prefix` input is replaced by `release-tag-regex`, which is a lot more flexible -
  it allows things like releasing on every tag, or only on tags without a pre-release suffix.
  Implemented by @s3rius (Pavel Kirilin). GH #16. The default is
  `^v?\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$`, which matches a semantic version with an
  optional leading `v`. This is narrower than the old default, which released on any tag starting
  with `v`. If you tag releases as something other than a version - `nightly`, or a date - you will
  need to set this input to keep releasing on those tags.
- The packaging action has a new `archive-file` output containing the name of the archive it
  created.
- The `publish` action must run on a Linux runner, and fails immediately if it does not. The
  packaging action still runs on every platform you build for, but the publish action only moves
  artifacts around and talks to the GitHub API, so it has no reason to run anywhere else.
- The `changes-file` used as the release description is now looked for in the `working-directory`.
  Previously it was looked for in the repo root, regardless of the `working-directory` input.
- **Breaking change**: The release is now created by the `gh` CLI, which is preinstalled on GitHub
  runners, instead of by `softprops/action-gh-release`. That removes a third-party action from the
  path your release token travels through.

  This replaces the `action-gh-release-parameters` input, which took a JSON blob of parameters for
  that action. Tying this action's interface to another project's input names was a mistake, so the
  parameters people actually use are now named inputs: `release-name`, `draft`, `prerelease`,
  `latest`, `target-commitish`, `repository`, `token`, `discussion-category`, and
  `generate-release-notes`.

  `target_commitish` keeps its GitHub name rather than becoming `target`, because the packaging
  action already has a `target` input meaning the Rust target triple, and the two are unrelated.

  The `body` and `body_path` parameters have no replacement, because `changes-file` already covers
  that. There is no replacement for `append_body` or `preserve_order`, which `gh` cannot do.

- **Breaking change**: The `publish` action no longer updates an existing release. If a release
  already exists for the tag it is about to use, it fails. Previously it would add to the existing
  release, which cannot work at all in a repository with immutable releases enabled.

- The `publish` action works with
  [immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).
  It creates the release as a draft, uploads the archives, and only then publishes it, which is the
  order GitHub requires when a repository has immutability turned on. Immutability itself is a
  repository setting, so you still turn it on yourself under **Settings > General**.

- Fixed a bug where boolean parameters passed to `softprops/action-gh-release` were written as
  Python's `True` rather than `true`. That action compares its inputs against the string `"true"`,
  so every boolean this action set was silently ignored, including `fail_on_unmatched_files`. This
  action used to force `draft` on, but because of the bug above it never actually took effect, and
  releases have always been published directly. The new `draft` input defaults to off, so that
  behavior is unchanged, and setting it now actually works.

- Setting `latest` to "true" together with `draft` or `prerelease` is now rejected during input
  validation. GitHub refuses to mark a draft or a prerelease as the latest release, so this used to
  fail with an opaque API error from the very last step, after every archive had been built.

- The `publish` action has a new `release-tag` output containing the tag of the release it created.
  This is empty when no release was created.

- Every action this action uses is now pinned to a commit hash rather than a tag, so a compromised
  or moved tag upstream cannot change what runs in your workflow.

## 0.0.9 - 2026-07-26

- The input validation step passed `inputs.executable_name` instead of `inputs.executable-name`, so
  the `executable-name` value never reached the validator and the check that it was set could never
  fire. Similarly, the `extra-files` value was passed in an environment variable named
  `INPUTS_extra-files`, which the validator never looked at, so `extra-files` was never validated.
- The validator checked whether inputs were _present_ rather than whether they had a value. Since
  the action always sets every one of these environment variables, even for inputs the caller
  omitted, none of those checks could ever fail. They now check the value.
- The validation of the `extra-files` input resolved relative paths against the repo root, but the
  packaging step resolves them against the `working-directory` input. With a `working-directory`
  other than `.`, this meant validation checked different files than were actually packaged, so it
  could reject files that exist or accept files that don't. Relative `extra-files` paths are now
  resolved against the working directory, matching the packaging step.
- The `extra-files` input is documented as accepting globs, and validation accepted them, but the
  packaging step passed each line through as a literal path. Passing a glob would pass validation
  and then fail the release with a `FileNotFoundError`. Globs in `extra-files` are now expanded when
  packaging.

## 0.0.8 - 2026-06-21

- Update all actions used by this action to get rid of Node.js deprecation warnings. GH #19.
  Reported by @simonhollingshead (Simon Hollingshead).

## 0.0.7 - 2026-03-15

- Updated various actions used by this action so that it no longer triggers warnings about Node.js
  20 deprecation.

## 0.0.6 - 2025-02-15

- Added validation for all input parameters. This should provide better errors when a required
  parameter is missing or a parameter is invalid (like referring to a path which does not exist).
- Added a new `action-gh-release-parameters` input parameter. This takes a JSON string which can
  contain most parameters accepted by the
  [the `softprops/action-gh-release@v2` action](https://github.com/softprops/action-gh-release)
  action.

## 0.0.5 - 2025-02-09

- Trying to do an actual release with `changes-file` set to an empty string caused the
  `softprops/action-gh-release` action to fail with an error like
  `EISDIR: illegal operation on a directory, read`. Fixed by @xen (yksen). GH PR #6. Fixes GH #7.

## 0.0.4 - 2024-12-08

- The `changes-file` parameter can be set to an empty string. If you do this, then the action will
  not look for a changelog file to include in the release. Based on a bug report by @magick93. GH
  #5.

## 0.0.3 - 2024-11-18

- Added a new `working-directory` parameter. When this is set, all actions are performed from inside
  this directory. Implemented by @Snoupix. GH #4.
- Fixed a bug where even when `extra-files` was set, the action would fail if there was no
  `Changes.md` file present. This contradicted the docs, which said that when `extra-files` was set,
  the `changes-file` parameter would be ignored. Reported by @jannes. GH #3.

## 0.0.2 - 2024-10-27

- Fixed a bug where the executable in the generated tarball or zip file did not have executable
  permissions set.

## 0.0.1 - 2024-09-14

- First release upon an unsuspecting world.
