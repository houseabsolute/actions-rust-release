## 0.0.4

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
