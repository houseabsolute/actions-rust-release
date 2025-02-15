# GitHub Action to Release Rust Projects

This action helps you create
[GitHub Releases](https://docs.github.com/en/repositories/releasing-projects-on-github/managing-releases-in-a-repository)
for Rust projects that produce an executable.

Here's an example from the release workflow for
[my tool `precious`](https://github.com/houseabsolute/precious):

```yaml
jobs:
  release:
    name: Release - ${{ matrix.platform.release_for }}
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
        uses: actions/checkout@v3
      - name: Build executable
        uses: houseabsolute/actions-rust-cross@v0
        with:
          target: ${{ matrix.platform.target }}
          args: "--locked --release"
          strip: true
      - name: Publish artifacts and release
        uses: houseabsolute/actions-rust-release@v0
        with:
          executable-name: ubi
          target: ${{ matrix.platform.target }}
        if: matrix.toolchain == 'stable'
```

## What It Does

This action will do the following:

- Package an executable, along with any additional files you specify (defaults to `README*` and
  `Changes.md`). It will produce a tarball on all platforms but Windows, where it produces a zip
  file.
- Create a SHA256 checksum file for the tarball or zip file using `shasum`.
- Upload the archive and checksum files as artifacts for your workflow.
- If this action is called for a tag that matches the specified prefix (defaults to `v`), then it
  will also create/update a GitHub Release for this tag, attaching the archive and checksum files as
  release artifacts

If you have a matrix build that creates executables for many platforms, you should call this action
for each platform. It should work on any platform supported by GitHub Actions (Linux, macOS,
Windows).

## Input Parameters

This action takes the following parameters:

### `executable-name`

- **Required**: yes

The name of the executable that your project compiles to. In most cases, this is just the name of
your project, like `cross` or `mise`.

### `release-tag-prefix`

- **Required**: no
- **Default**: `"v"`

The prefix for release tags. The default is "v", so that tags like "v1.2.3" trigger a release.

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

The name of the file that contains the changelog for this project. This will be used to generate a
description for the GitHub Release.

If you set this to an empty string, then no changelog file will be included.

### `working-directory`

- **Required**: no
- **Default**: `"."`

The current working directory in which all actions are performed. This defaults to the checked out
repo's root. You use relative paths to set this to a subdirectory in the repo.

### `action-gh-release-parameters`

- **Required**: no

This must be a string containing valid JSON. The JSON should be an object where the keys are the
parameters for
[the `softprops/action-gh-release@v2` action](https://github.com/softprops/action-gh-release).

Note that the `actions-rust-release` action will always set the `draft` and `files` parameters, so
any values you set for these parameter will be in the JSON string will be ignored.

## Outputs

This action provides two outputs.

### `artifact-id`

The ID of the workflow artifact that was created.

### `artifact-url`

The URL of the workflow artifact that was created.

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
