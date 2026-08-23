# Migrating from v0 to v1

In v0 this repo was one action that packaged your executable and created the GitHub Release. In v1
it is two:

- `houseabsolute/actions-rust-release` packages your executable and uploads it as a workflow
  artifact. You call it once per platform, from inside your build matrix, the same way you called
  v0.
- `houseabsolute/actions-rust-release/publish` collects those artifacts and creates one release. You
  call it once, from a job that runs after all of your build jobs.

The reason for the split is that v0 created the release from inside the matrix. A platform that
finished early would publish its archive while other platforms were still building, or failing, so a
release missing a platform's executable could go public. Every leg of the matrix also raced to
create the same release.

Migrating is mostly mechanical: leave your existing invocation in place, drop the release-specific
inputs from it, and add a new job.

## The workflow change

Before, in v0:

```yaml
name: Release

on:
  push:
    # This decides which tags start a run. v0 then decided which of
    # those actually released, using its `release-tag-prefix` input.
    tags:
      - "v[0-9]*"
      - "[0-9]*"

# Individual jobs ask for more where they need it.
permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  # Never cancel a release that is part way through creating one.
  cancel-in-progress: false

jobs:
  release:
    name: Release - ${{ matrix.platform.os-name }}
    strategy:
      matrix:
        platform:
          # your platforms here
    runs-on: ${{ matrix.platform.runs-on }}
    permissions:
      contents: write # v0 created the release from this job.
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: houseabsolute/actions-rust-cross@21b0f18dc621b25bfae556ff2791fca4173121e8 # v1.0.8
        with:
          target: ${{ matrix.platform.target }}
          args: "--locked --release"
          strip: true
      - name: Publish artifacts and release
        uses: houseabsolute/actions-rust-release@v0
        with:
          executable-name: my-project
          target: ${{ matrix.platform.target }}
```

After, in v1:

```yaml
name: Release

on:
  push:
    # This decides which tags start a run. The publish action then
    # decides which of those actually release, using its
    # `release-tag-regex` input. Its default accepts a version with
    # or without a leading "v", so both patterns are here.
    tags:
      - "v[0-9]*"
      - "[0-9]*"

# Individual jobs ask for more where they need it.
permissions:
  contents: read

concurrency:
  group: ${{ github.workflow }}-${{ github.ref }}
  # Never cancel a release that is part way through creating one.
  cancel-in-progress: false

jobs:
  package:
    name: Package - ${{ matrix.platform.os-name }}
    strategy:
      matrix:
        platform:
          # your platforms here, unchanged
    runs-on: ${{ matrix.platform.runs-on }}
    permissions:
      contents: read # Checkout only. Uploading the artifact does not use this token.
    steps:
      - uses: actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1
        with:
          persist-credentials: false
      - uses: houseabsolute/actions-rust-cross@21b0f18dc621b25bfae556ff2791fca4173121e8 # v1.0.8
        with:
          target: ${{ matrix.platform.target }}
          args: "--locked --release"
          strip: true
      - name: Package artifacts
        uses: houseabsolute/actions-rust-release@867cc107fb205972460c7905075c476852cd76f9 # v1.0.0
        with:
          executable-name: my-project
          target: ${{ matrix.platform.target }}

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
      - uses: houseabsolute/actions-rust-release/publish@867cc107fb205972460c7905075c476852cd76f9 # v1.0.0
        with:
          executable-name: my-project
```

A few things about this are easy to miss:

- The `publish` job needs `actions: read` as well as `contents: write`. The publish action asks the
  GitHub API which artifacts belong to the current run, and that is the permission which allows it.
- The `publish` job must run on a Linux runner. The action fails immediately if it does not. It only
  moves artifacts around and talks to the API, so it has no reason to run anywhere else.
- The `publish` job needs a checkout. `changes-file` defaults to `Changes.md`, and the action fails
  if that file is not in the working directory. Set `changes-file: ""` if you would rather release
  with no description and skip the checkout.
- The `uses:` lines here are pinned to a commit SHA rather than a tag, and the SHA shown for each of
  this repo's actions is the v1.0.0 release, so you can copy them as they are. See
  [the note on pinning in the README](README.md#pinning-actions-to-a-commit) for why.
- The `package` job no longer needs `contents: write`. It only uploads a workflow artifact now, so
  you can drop that permission from it.

## Where each input went

The packaging action keeps these, unchanged:

| Input               |                                   |
| ------------------- | --------------------------------- |
| `executable-name`   | still required                    |
| `target`            |                                   |
| `archive-name`      |                                   |
| `extra-files`       |                                   |
| `changes-file`      | used to pick the files to package |
| `working-directory` |                                   |

These moved to the `publish` action, and the packaging action no longer accepts them:

| v0 input                       | v1 replacement                       |
| ------------------------------ | ------------------------------------ |
| `release-tag-prefix`           | `release-tag-regex`, see below       |
| `action-gh-release-parameters` | named inputs on `publish`, see below |

The `publish` action also takes `executable-name`, `changes-file`, and `working-directory`. They
take the same values as the packaging versions, but none of the three does the same job on both
actions, and setting one does not set the other. The README has
[a table of what each one means where](README.md#inputs-both-actions-take).

## Replacing `action-gh-release-parameters`

v0 passed this JSON blob straight through to `softprops/action-gh-release`. v1 creates the release
with the `gh` CLI instead, which removes a third-party action from the path your release token
travels through. Tying this action's interface to another project's input names was a mistake, so
the parameters people actually used are now named inputs on `publish`:

| JSON key in v0             | v1 input on `publish`    |
| -------------------------- | ------------------------ |
| `name`                     | `release-name`           |
| `draft`                    | `draft`                  |
| `prerelease`               | `prerelease`             |
| `make_latest`              | `latest`                 |
| `target_commitish`         | `target-commitish`       |
| `repository`               | `repository`             |
| `token`                    | `token`                  |
| `discussion_category_name` | `discussion-category`    |
| `generate_release_notes`   | `generate-release-notes` |

One of these needs a second look:

- `make_latest` accepted `legacy` as a third value. `latest` takes only `"true"` or `"false"`, and
  rejects anything else during input validation. Leaving it unset is the same as `legacy`: GitHub
  decides based on the release date.

So this:

```yaml
action-gh-release-parameters: |
  { "name": "Release ${{ github.ref_name }}", "prerelease": true }
```

becomes this:

```yaml
release-name: Release ${{ github.ref_name }}
prerelease: true
```

These keys have no v1 replacement:

| JSON key in v0                     |                                                              |
| ---------------------------------- | ------------------------------------------------------------ |
| `body`, `body_path`                | `changes-file` already does this                             |
| `append_body`, `preserve_order`    | `gh` cannot do these                                         |
| `files`, `fail_on_unmatched_files` | v0 set these itself; `publish` uses `artifact-regex` instead |
| `tag_name`                         | v1 always releases on the tag it was called for              |

`tag_name` is the one real loss here. v0 passed your JSON through untouched, so setting it released
on a tag of your choosing rather than the one that triggered the workflow. There is no way to do
that in v1.

Those two tables cover every input `softprops/action-gh-release` accepts, so nothing else you could
have written in the JSON is missing from them.

## Behavior changes to watch for

### `publish` finds your archives by name

v0 released the archive it had just built, because it was the same action. v1 has to work out which
of the run's artifacts belong in the release, which it does with the `artifact-regex` input. The
default is `\A<executable-name>.*\.(tar\.[a-z]+|zip)\Z`, matching what the packaging action
produces.

If you set `archive-name` to something that does not start with your `executable-name`, that default
will not match it and `publish` will fail with an error about no artifacts matching the regex. Set
`artifact-regex` to something that does match.

This is also what keeps unrelated artifacts, like coverage reports or logs, out of your releases.

### `latest` cannot be combined with `draft` or `prerelease`

GitHub will not mark a draft or a prerelease as the latest release. v1 rejects that combination
during input validation. If you passed both `make_latest` and `prerelease` in the v0 JSON, the
`make_latest` was being ignored anyway, because of the boolean bug described below. Now it is an
error.

### The default set of tags that release is narrower

`release-tag-prefix` defaulted to `v`, so every tag starting with `v` produced a release, including
`v-nightly` and `vendor-bump`. `release-tag-regex` defaults to
`^v?\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$`, which is a semantic version with an
optional leading `v`.

If you tag releases as something else, a date or `nightly`, set the regex or you will stop getting
releases. `release-tag-regex: "^v"` reproduces the old default exactly. `.*` releases on every tag.

### An existing release is no longer updated

v0 would add to a release that already existed for the tag. v1 fails instead. That behavior cannot
work at all in a repository with immutable releases enabled, and quietly adding to someone else's
release is not a good default anywhere.

### `changes-file` is resolved against `working-directory`

v0 looked for it in the repo root no matter what `working-directory` was set to. If you use both
inputs and your changes file lives in the repo root rather than the project directory, you need to
say so with a path like `../Changes.md`.

### Booleans now actually take effect

v0 wrote boolean parameters as Python's `True` rather than `true`. `softprops/action-gh-release`
compares its inputs against the string `"true"`, so every boolean v0 set was silently ignored. v0
tried to force `draft` on and never managed it, which is why v0 releases were always published
directly.

`draft` defaults to off in v1, so that behavior is unchanged. It just works now if you set it.

## Outputs

The packaging action keeps `artifact-id` and `artifact-url`, and gains `archive-file`, the name of
the archive it created.

The `publish` action has its own outputs: `artifact-ids`, the workflow artifacts it downloaded to
build the release from, and `release-tag`, the tag of the release it created. Both are empty when no
release was created.
