# GitHub Action to Release Rust Projects

This repo provides two actions which together create
[GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
for Rust projects that produce an executable:

- `houseabsolute/actions-rust-release` packages your executable into an archive and uploads it as a
  workflow artifact. You call this once per platform, typically from inside a build matrix.
- `houseabsolute/actions-rust-release/publish` collects those archives and turns them into a single
  GitHub Release. You call this once, from a job that runs after all of your build jobs.

Here's an example from the release workflow for
[my tool `precious`](https://github.com/houseabsolute/precious):

```yaml
jobs:
  package:
    name: Package - ${{ matrix.platform.release_for }}
    strategy:
      matrix:
        platform:
          - os_name: Linux-x86_64
            os: ubuntu-24.04
            target: x86_64-unknown-linux-musl

          - os_name: macOS-x86_64
            os: macOS-latest
            target: x86_64-apple-darwin

            # more release targets here ...

    runs-on: ${{ matrix.platform.os }}
    steps:
      - name: Checkout
        uses: actions/checkout@v6
      - name: Build executable
        uses: houseabsolute/actions-rust-cross@v1
        with:
          target: ${{ matrix.platform.target }}
          args: "--locked --release"
          strip: true
      - name: Package artifacts
        uses: houseabsolute/actions-rust-release@v1
        with:
          executable-name: precious
          target: ${{ matrix.platform.target }}

  release:
    name: Create GitHub release
    needs: package
    runs-on: ubuntu-24.04
    permissions:
      actions: read
      contents: write
    steps:
      - name: Checkout
        uses: actions/checkout@v6
      - name: Publish release
        uses: houseabsolute/actions-rust-release/publish@v1
        with:
          executable-name: precious
```

## Why Two Actions?

Packaging happens once per platform, so it belongs in your build matrix. Releasing happens once per
tag, so it does not.

Keeping them separate means nothing is published until every platform has been built and uploaded.
You decide when that is, with the `needs:` of the job you call `publish` from, so a target that
fails cannot leave you with a release that is missing its binary. It also means exactly one job
creates the release, rather than every leg of the matrix trying to create the same one at once.

## What They Do

The `actions-rust-release` action will:

- Package an executable, along with any additional files you specify (defaults to `README*` and
  `Changes.md`). It will produce a tarball on all platforms but Windows, where it produces a zip
  file.
- Create a SHA256 checksum file for the tarball or zip file using `shasum`.
- Upload the archive and checksum files as one artifact for your workflow.

It should work on any platform supported by GitHub Actions (Linux, macOS, Windows).

The `actions-rust-release/publish` action only creates a release when it is called for a tag that
matches the specified regex (defaults to `^v.*`). When it does, it will:

- Ask the GitHub API for the artifacts belonging to the current workflow run and pick out the ones
  matching the `artifact-regex` input.
- Download those artifacts.
- Create or update a GitHub Release for the tag, attaching every archive and checksum file it
  downloaded.

The job that calls it needs both the `contents: write` and `actions: read` permissions. The latter
is what allows it to list the run's artifacts.

This action must run on a Linux runner, and fails immediately if it does not. The packaging action
runs on every platform you build for, because it has to pick up that platform's build output, but
the publish action only moves artifacts around and talks to the GitHub API, so it has no reason to
run anywhere else.

## `actions-rust-release` Input Parameters

The packaging action takes the following parameters:

### `executable-name`

- **Required**: yes

The name of the executable that your project compiles to. In most cases, this is just the name of
your project, like `cross` or `mise`.

### `target`

- **Required:** no, if `archive-name` is provided.

The target triple that this release was compiled for. This should be one of the targets found by
running `rustup target list`.

Either this input or the `archive-name` input must be provided.

### `archive-name`

- **Required**: no, if `target` is provided

The name of the archive file to produce. This will contain the executable and any additional files
specified in the `files-to-package` input, if any. If this isn't given, then one will be created
based, starting with the `executable-name` and followed by elements from the `target` input.

Either this input or the `target` input must be provided.

### `extra-files`

- **Required**: no

This is a list of additional files or globs to include in the archive files for a release. This
should be provided as a newline-separate list.

Defaults to the file specified by the `changes-file` input and any file matching `README*` in the
project root.

If you _do_ specify any files, then you will need to also list the changes file and README
explicitly if you want them to be included. The value passed in `changes-files` will be ignored in
this case.

### `changes-file`

- **Required**: no
- **Default**: `"Changes.md"`

The name of the file that contains the changelog for this project. This is included in the archive.

If you set this to an empty string, then no changelog file will be included.

### `working-directory`

- **Required**: no
- **Default**: `"."`

The current working directory in which all actions are performed. This defaults to the checked out
repo's root. You can use relative paths to set this to a subdirectory in the repo.

## `actions-rust-release` Outputs

### `archive-file`

The name of the archive file that was created, without any directory.

### `artifact-id`

The ID of the workflow artifact that was created.

### `artifact-url`

The URL of the workflow artifact that was created.

## `actions-rust-release/publish` Input Parameters

The publishing action takes the following parameters:

### `executable-name`

- **Required**: no, if `artifact-regex` is provided

The name of the executable that your project compiles to. This is only used to construct the default
`artifact-regex`.

Either this input or the `artifact-regex` input must be provided.

### `artifact-regex`

- **Required**: no, if `executable-name` is provided
- **Default**: `\A<executable-name>.*\.(tar\.[a-z]+|zip)\Z`

A [Python regex](https://docs.python.org/3/library/re.html#regular-expression-syntax) matching the
names of the workflow run's artifacts which should be attached to the release. The regex is matched
against each artifact's name with `re.search`.

The default matches every archive that the `actions-rust-release` action creates for the given
executable. Artifacts which do not match are ignored entirely - they are never downloaded and never
released - so this is how you keep things like coverage reports, logs, or artifacts belonging to a
different executable out of your releases.

If nothing matches, the action fails and lists the run's artifacts, rather than quietly publishing
an empty release.

### `release-tag-regex`

- **Required**: no
- **Default**: `"^v.*"`

A [Python regex](https://docs.python.org/3/library/re.html#regular-expression-syntax) matching the
tags which should produce a release. It is matched against the tag name with `re.match`, so it is
anchored at the start whether or not you write a `^`.

The default, `^v.*`, matches every tag starting with `v`, so `v1.2.3` produces a release — but so
would `vibes`. A regex is more flexible than matching a prefix, so you can be stricter than that if
you want: `^v\d+\.\d+\.\d+$` releases only on tags that look like a full version. Note the trailing
`$`; without it, `v1.2.3-rc1` matches too, since only the start of the tag is anchored.

This is only consulted for tags. A push to a branch never produces a release, whatever the regex
says.

### `changes-file`

- **Required**: no
- **Default**: `"Changes.md"`

The name of the file that contains the changelog for this project. This will be used to generate a
description for the GitHub Release. It is looked for in the `working-directory`.

If you set this to an empty string, then the release will have no description.

### `working-directory`

- **Required**: no
- **Default**: `"."`

The directory which contains the `changes-file`. This defaults to the checked out repo's root.

### `action-gh-release-parameters`

- **Required**: no

This must be a string containing valid JSON. The JSON should be an object where the keys are the
parameters for
[the `softprops/action-gh-release@v3` action](https://github.com/softprops/action-gh-release).

Note that the publish action will always set the `files` and `fail_on_unmatched_files` parameters,
so any values you set for these parameters in the JSON string will be ignored.

## `actions-rust-release/publish` Outputs

### `artifact-ids`

A comma-separated list of the IDs of the artifacts that were attached to the release.

## Linting and Tidying this Code

The code in this repo is linted and tidied with
[`precious`](https://github.com/houseabsolute/precious). This repo contains a `mise.toml` file.
[Mise](https://mise.jdx.dev/) is a tool for managing dev tools with per-repo configuration. You can
install `mise` and use it to run `precious` as follows:

```
# Installs mise
curl https://mise.run | sh
# Installs precious and other dev tools
mise install
```

Once this is done, you can run `precious` via `mise`:

```
# Lints all code
mise exec -- precious lint -a
# Tidies all code
mise exec -- precious tidy -a
```

If you want to use `mise` for other projects, see [its documentation](https://mise.jdx.dev/) for
more details on how you can configure your shell to always activate `mise`.
