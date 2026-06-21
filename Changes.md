## 0.0.8

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
