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
        uses: actions/checkout@v7
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
        uses: actions/checkout@v7
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
matches the `release-tag-regex` (a semantic version, like `v1.2.3`, by default). When it does, it
will:

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
- **Default**: `^v?\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$`

A [Python regex](https://docs.python.org/3/library/re.html#regular-expression-syntax) matching the
tags which should produce a release. It is matched against the tag name with `re.match`, so it is
anchored at the start whether or not you write a `^`.

The default matches a [semantic version](https://semver.org/) with an optional leading `v`. All of
these produce a release:

| Tag             |                             |
| --------------- | --------------------------- |
| `v1.2.3`        | the usual case              |
| `1.2.3`         | the leading `v` is optional |
| `v1.2.3-rc1`    | a pre-release               |
| `v1.2.3+build4` | with build metadata         |

While these do not:

| Tag       |                      |
| --------- | -------------------- |
| `nightly` | not a version at all |
| `v1.2`    | not three components |
| `latest`  | a moving tag         |

Set your own regex if that isn't what you want. `^v\d+\.\d+\.\d+$` refuses pre-releases; `.*`
releases on every tag.

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

### `release-name`

- **Required**: no

The title of the release. If this is not set, GitHub uses the tag name as the title.

### `generate-release-notes`

- **Required**: no
- **Default**: `"false"`

Set this to `"true"` to have GitHub generate release notes from the commits and pull requests since
the last release. If you set both this and `changes-file`, the generated notes are appended to the
contents of the changes file.

### `draft`

- **Required**: no
- **Default**: `"false"`

Set this to `"true"` to create the release as a draft, so that you can review it before publishing
it yourself.

### `prerelease`

- **Required**: no
- **Default**: `"false"`

Set this to `"true"` to mark the release as a prerelease.

### `latest`

- **Required**: no

Set this to `"true"` or `"false"` to control whether the release is marked as the latest release. If
you leave this unset, GitHub decides based on the release date, which is usually what you want.

This cannot be `"true"` when `draft` or `prerelease` is `"true"`, because GitHub will not mark
either of those as the latest release. The action rejects that combination up front rather than
letting it fail once your archives have already been built.

### `target`

- **Required**: no

The branch name or commit SHA that the tag is created from, if the tag does not already exist. This
defaults to the repository's default branch.

### `discussion-category`

- **Required**: no

The name of a discussion category. If this is set, then publishing the release also creates a
discussion in that category.

### `repository`

- **Required**: no
- **Default**: `${{ github.repository }}`

The `owner/repo` to create the release in. This defaults to the repository running the workflow.

If you set this, you almost certainly need to set the `token` input as well, since the workflow's
own token has no access to another repository.

### `token`

- **Required**: no
- **Default**: `${{ github.token }}`

The token used to create the release. The default is the workflow's own token, which needs the
`contents: write` permission.

## Immutable Releases

This action works with
[immutable releases](https://docs.github.com/en/code-security/concepts/supply-chain-security/immutable-releases).
It creates the release as a draft, uploads the archives to it, and only then publishes it, which is
the order GitHub requires when a repository has immutability turned on.

Immutability is a repository setting rather than something a release asks for, so this action cannot
turn it on for you. You enable it under **Settings > General** for the repository, or with the
[REST API](https://docs.github.com/en/rest/repos/repos).

Note that once a release is published in a repository with immutability enabled, it cannot be
changed. This action never updates an existing release. If a release already exists for the tag it
is about to use, it fails rather than trying to add to it.

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
