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
            os: ubuntu-20.04
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
explicitly if you want them to be included.

### `changes-file`

- **Required**: no
- **Default**: `"Changes.md"`

The name of the file that contains the changelog for this project. This will be used to generate a
description for the GitHub Release.

## Outputs

This action provides two outputs.

### `artifact-id`

The ID of the workflow artifact that was created.

### `artifact-url`

The URL of the workflow artifact that was created.
