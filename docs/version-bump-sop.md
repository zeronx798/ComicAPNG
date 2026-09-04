# ComicAPNG Version Bump and Release SOP

This procedure updates the desktop application version. Plugin API, bundled source-module, APNG
private-metadata, and ZIP schema versions follow independent compatibility contracts.

## 1. Choose the version

Use the stable three-part form `X.Y.Z`, for example `1.2.3`.

- Increase the patch component for compatible fixes.
- Increase the minor component for compatible features.
- Increase the major component for incompatible application-level changes.
- Keep the application version at `X.Y.Z` during release-candidate testing. Encode the RC suffix
  exclusively in the Git tag, such as `vX.Y.Z-rc.1`.

## 2. Verify the working context

```sh
git branch --show-current
git status --short
```

Confirm the intended branch and a worktree containing only the changes planned for this release.

## 3. Update both authoritative values

Change the same `X.Y.Z` value in:

1. `pyproject.toml`, under `[project] version`. Packaging and PyInstaller read this value.
2. `src/comicapng/__init__.py`, in `__version__`. The application UI reads this value.

Keep `pyproject.toml` as the sole version input used by `ComicAPNG.spec`.

Update the two authoritative values individually. Preserve independent values in test fixtures,
release-tag grammar examples, plugin manifests, API versions, and file-format schemas.

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
enforces equality between the two authoritative source values.

## 6. Build and smoke-test a native package

Windows:

```powershell
.\scripts\build.ps1
```

Linux or macOS:

```sh
./scripts/build.sh
```

Confirm the About dialog/version label and run the normal APNG, ZIP, source-module, and frozen
smoke checks appropriate to the release.

## 7. Review and commit

```sh
git diff --check
git diff -- pyproject.toml src/comicapng/__init__.py
git status --short
git add pyproject.toml src/comicapng/__init__.py tests/test_version.py docs/version-bump-sop.md README.md docs/tech-specs.md
git commit -m "chore(release): bump version to X.Y.Z"
```

Include the SOP in `git add` when it changes. Merge the reviewed commit into `main` before tagging;
the release workflow accepts release tags whose commit is contained in `origin/main`.

## 8. Create an RC tag

Replace `X.Y.Z` with the application version:

```sh
git switch main
git pull --ff-only origin main
git tag -a vX.Y.Z-rc.1 -m "ComicAPNG vX.Y.Z RC1"
git push origin vX.Y.Z-rc.1
```

Download and test all four generated prerelease artifacts. Published RC tags are immutable; apply
changes in a new commit and create `vX.Y.Z-rc.2`.

## 9. Create the stable tag

After an RC is accepted and the intended commit is on current `main`:

```sh
git switch main
git pull --ff-only origin main
git tag -a vX.Y.Z -m "ComicAPNG vX.Y.Z"
git push origin vX.Y.Z
```

Verify the GitHub Release contains the four expected native archives and `SHA256SUMS.txt`. Stable
assets come from the stable-tag build, and published release tags remain immutable.
