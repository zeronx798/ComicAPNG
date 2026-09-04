# ComicAPNG Version Bump and Release SOP

This procedure covers the desktop application version. It does not automatically change the
Plugin API version, bundled plugin versions, APNG private-metadata schema, or ZIP schema. Those
versions are independent and should change only when their own compatibility contract changes.

## 1. Choose the version

Use a stable three-part version without a leading `v`, for example `1.2.3`.

- Increase the patch component for compatible fixes.
- Increase the minor component for compatible features.
- Increase the major component for incompatible application-level changes.
- Keep the application version at `X.Y.Z` during release-candidate testing. The RC suffix belongs
  to the Git tag, such as `vX.Y.Z-rc.1`, not to the application version.

## 2. Verify the working context

```sh
git branch --show-current
git status --short
```

Confirm that the version bump is being made on the intended branch and that unrelated local work
will not be included accidentally.

## 3. Update both authoritative values

Change the same `X.Y.Z` value in:

1. `pyproject.toml`, under `[project] version`. Packaging and PyInstaller read this value.
2. `src/comicapng/__init__.py`, in `__version__`. The application UI reads this value.

`ComicAPNG.spec` already reads `pyproject.toml`; do not add another hard-coded version there.

Do not mass-replace version-like values. Test fixtures, release-tag grammar examples, plugin
manifest versions, API versions, and file-format schema versions may intentionally differ.

## 4. Refresh the editable installation

From the repository root:

```sh
python -m pip install -e ".[dev]"
```

On Windows with the repository virtual environment:

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

## 5. Verify the version and source policy

```sh
python -c "import comicapng; print(comicapng.__version__)"
python -m pytest -q
python -m ruff check .
python scripts/check_source_ascii.py
python scripts/validate_packaging.py
```

The reported version must equal the value in `pyproject.toml`. The version synchronization test
fails when the two authoritative source values differ.

## 6. Build and smoke-test a native package

Windows:

```powershell
.\scripts\build.ps1
```

Linux or macOS:

```sh
./scripts/build.sh
```

Confirm the About dialog/version label and run the normal APNG, ZIP, source-plugin, and frozen
smoke checks appropriate to the release.

## 7. Review and commit

```sh
git diff --check
git diff -- pyproject.toml src/comicapng/__init__.py
git status --short
git add pyproject.toml src/comicapng/__init__.py tests/test_version.py docs/version-bump-sop.md README.md docs/tech-specs.md
git commit -m "chore(release): bump version to X.Y.Z"
```

Adjust the `git add` list if the SOP itself did not change. Merge the reviewed commit into `main`
before tagging; the release workflow rejects tags whose commit is not contained in `origin/main`.

## 8. Create an RC tag

Replace `X.Y.Z` with the application version:

```sh
git switch main
git pull --ff-only origin main
git tag -a vX.Y.Z-rc.1 -m "ComicAPNG vX.Y.Z RC1"
git push origin vX.Y.Z-rc.1
```

Download and test all four generated prerelease artifacts. If changes are needed, merge a new
commit and create `vX.Y.Z-rc.2`; never move an already published RC tag.

## 9. Create the stable tag

After an RC is accepted and the intended commit is on current `main`:

```sh
git switch main
git pull --ff-only origin main
git tag -a vX.Y.Z -m "ComicAPNG vX.Y.Z"
git push origin vX.Y.Z
```

Verify the GitHub Release contains the four expected native archives and `SHA256SUMS.txt`. Never
rename RC assets into stable assets or move, delete, rewrite, or force-push a published release tag.
