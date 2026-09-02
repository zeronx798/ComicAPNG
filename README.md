# ComicAPNG

ComicAPNG is a cross-platform PySide6 desktop application for discovering sources and creating, extracting, and reading APNG comic books. Every APNG frame is one comic page, and all workflows live in one native application window.

Documentation:

- [Simplified Chinese user guide](docs/README_zh.md)
- [Technical specifications](docs/tech-specs.md)
- [ZIP exchange format](docs/zip-format.md)

## Features

- Search installed source plugins, inspect comics and chapters, materialize decoded pages, and send them to the normal Create workflow.
- Use the official JMComic source backed by `jmcomic` 2.7.x or the deterministic offline test source.
- Add local files or folders, or import an existing APNG or ZIP into the same Create/Edit model.
- Export either standards-compliant APNG or a human-inspectable ZIP containing original image
  encodings where practical plus versioned metadata.
- Select multiple page thumbnails, box-select, remove, and drag pages to any insertion point.
- Right-click a page to move it up, down, to the top, or to the bottom.
- Select a cover, which is exported exactly once as APNG frame 0.
- Render every page to one fixed RGBA canvas without stretching or cropping artwork.
- Center proportionally fitted pages over transparent padding.
- Configure independent cover and body durations in three-decimal seconds. New comics default to 10.000 seconds for the cover and 5.000 seconds for body pages.
- Edit standard and custom tag-ID-based EXIF fields and arbitrary valid PNG text fields.
- Extract generic APNG files without requiring ComicAPNG metadata.
- Read static PNG and APNG comics manually with thumbnails, page jump, zoom, fit modes, fullscreen, dual-page mode, and left-to-right or right-to-left controls.
- Preserve reading position outside the comic using a content fingerprint.
- Restore normal window geometry, position, and maximized state with an off-screen safety check.
- Decode full-resolution creator and reader pages on demand, with a bounded reader cache and a separate disk thumbnail cache.

ComicAPNG private JSON metadata is optional. Generic standards-compliant APNG files remain readable and extractable when EXIF, PNG text, or ComicAPNG metadata is absent or malformed.

## Requirements

- Python 3.11 or newer for development
- PySide6
- Pillow
- platformdirs
- qtawesome
- jmcomic 2.7.x

End users can use a PyInstaller build and do not need Python installed.

## Development

Create a virtual environment, then install the project and development tools:

```sh
python -m venv .venv
.venv/bin/python -m pip install -e ".[dev]"
```

On Windows, use `.venv\Scripts\python.exe` instead.

Run the application:

Windows PowerShell:

```powershell
.\launch.ps1
```

Windows Command Prompt:

```bat
launch.cmd
```

macOS, Linux, or another POSIX shell:

```sh
sh ./launch.sh
```

The launchers prefer the project `.venv`, fall back to an available Python 3.11 or newer, validate the runtime dependencies, and run directly from `src`. After an editable installation, `python -m comicapng` and the `ComicAPNG` console entry point also remain available.

To validate a source environment without opening the GUI, use `-Check` with `launch.ps1` or `--check` with `launch.cmd` and `launch.sh`.

Run validation:

```sh
python scripts/check_source_ascii.py
python -m pytest
python -m ruff check .
```

Generate the ten deterministic varied pages used for manual reorder testing:

```sh
python scripts/generate_reorder_fixtures.py --output .tmp/reorder-fixtures
```

Import that output directory into Create/Edit, or use the bundled Test Source to exercise the same
Source-to-Create/Edit path without network access. The generated files are local test data and
need not be committed. They can also be used to test APNG import and ZIP export/import manually.

Primary source files are ASCII-only. All visible interface text is stored in packaged JSON localization resources. English and Simplified Chinese are included.

## Packaging

Use the platform build script from the matching environment:

```powershell
./scripts/build.ps1
```

```sh
sh ./scripts/build.sh
```

The shared `ComicAPNG.spec` collects qtawesome fonts, localization data, bundled source manifests, jmcomic metadata/modules, curl-cffi native components, and third-party notices. Frozen smoke tests start the Plugin Host and exercise the offline test source without contacting JMComic. Run each target build on its native operating system. PyInstaller does not cross-compile between Windows, macOS, and Linux.

The application bundle icon is generated from the same Font Awesome icon used by the interface. Run `python scripts/generate_app_icon.py` after intentionally changing that icon. The spec also accepts `COMICAPNG_CODESIGN_IDENTITY` and `COMICAPNG_ENTITLEMENTS_FILE` for future secrets-based macOS signing configuration.

## Builds and downloads

Development builds are available from the GitHub repository under **Actions**, then **Build ComicAPNG**, then **Artifacts** on any successful workflow run. A manual **Run workflow** on `main` performs the complete four-platform test and build without creating a tag or release. The automated targets and archives are:

- Windows x64: `ComicAPNG-Windows-x64.zip`
- Linux x64: `ComicAPNG-Linux-x64.tar.gz`
- macOS Intel: `ComicAPNG-macOS-x64.zip`
- macOS Apple Silicon: `ComicAPNG-macOS-arm64.zip`

The Linux archive is built on Ubuntu 22.04 and is not claimed to work on every Linux distribution. The two macOS builds are architecture-specific, not universal applications. Automated macOS builds are not signed with an Apple Developer ID and are not notarized, so Gatekeeper may require manual approval. PyInstaller may apply the ad-hoc signatures required for executable integrity, but those signatures do not establish developer trust.

Release-candidate tags use `vX.Y.Z-rc.N` and create GitHub prereleases. Stable tags use `vX.Y.Z` and create normal releases. Each valid tag receives its own complete build; the release job attaches those exact build archives plus `SHA256SUMS.txt`. Other `v*` tag forms are rejected. See the [release procedure](docs/tech-specs.md#18-release-procedure) for the recommended PR, manual-build, RC, and stable sequence.

## APNG format policy

ComicAPNG writes 8-bit RGBA full-canvas frames. Each `fcTL` declares the complete virtual canvas at offset zero. Frames use source blending and no disposal, so every page independently replaces the preceding page, including transparent pixels. Frame timing is stored in APNG control chunks but normal reader navigation is manual.

EXIF is stored in the standard PNG `eXIf` chunk. User PNG text and versioned ComicAPNG JSON use `iTXt`. Unsupported EXIF values are rejected before output replaces an existing file.

Create/Edit imports logical, fully composited APNG frames. Valid ComicAPNG geometry may restore
known original image bounds; generic APNG frames remain full-canvas and are never alpha-trimmed.
An ordinary static PNG is not accepted by the dedicated Import APNG action and remains available
through Add Images and the Reader.

ZIP export uses current editable order and deterministic names such as `1.jpg`, `2.png`, and
`3.webp`. ZIP import accepts image-only archives in natural order. If `metadata.json` page names do
not exactly match all supported archive images, all page-bound metadata is discarded before the
user chooses whether to keep document/source metadata, import only images, or cancel. See the
[ZIP exchange format](docs/zip-format.md) for the schema and security limits.

## Known limitations

- Pillow must decode earlier animation state when seeking into some externally optimized APNG files. ComicAPNG hides this behind a frame-access abstraction and keeps only a small LRU of decoded full-resolution pages.
- Original page bounds can be reconstructed only when trustworthy ComicAPNG geometry metadata exists and the user enables that extraction option. ComicAPNG never guesses a crop from alpha values.
- PyInstaller builds must be produced separately on Windows, macOS, and Linux.
- Plugin process isolation protects application stability but is not a security sandbox.
- Normal CI does not contact JMComic; live source behavior requires an explicit opt-in or manual test.

## License

ComicAPNG is available under the Apache License 2.0. See `LICENSE` and `NOTICE`.
