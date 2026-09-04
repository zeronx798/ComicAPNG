# ComicAPNG

ComicAPNG is a cross-platform desktop application for building, editing, exporting, extracting,
and reading page-oriented image documents. Local images, archives, and source modules converge on
the same editable document model and shared product workflows.

```text
Local files / archives / source modules
                  |
                  v
         Unified document model
                  |
                  v
        Editor / reader services
                  |
                  v
       APNG / ZIP / future formats
```

APNG is the primary rendered format: one logical frame represents one page. ZIP provides a
human-inspectable exchange format. Source modules are adapters that discover resources,
materialize pages, and attach optional source metadata. The core owns editing and export.

Documentation:

- [Architecture and data flow](docs/architecture.md)
- [Source module architecture](docs/source-modules.md)
- [Simplified Chinese user guide](docs/README_zh.md)
- [Technical specifications](docs/tech-specs.md)
- [ZIP exchange format](docs/zip-format.md)
- [Version bump and release SOP](docs/version-bump-sop.md)

## Features

- Add local files or folders, import an existing APNG or ZIP, or materialize resources through an
  installed source module.
- Discover source metadata and pages through a source-independent editor and exporter boundary.
- Reorder or remove pages, choose a cover, configure timing and reading direction, and edit
  metadata in one Create/Edit workflow.
- Export standards-compliant, fixed-canvas APNG with proportional fitting and complete artwork.
- Export a human-inspectable ZIP that retains original image encodings where practical and adds
  optional versioned metadata.
- Edit standard and custom tag-ID-based EXIF fields and arbitrary valid PNG text fields.
- Extract pages from generic APNG files with optional ComicAPNG metadata.
- Read static PNG and APNG documents with thumbnails, zoom, fullscreen, dual-page mode, reading
  direction controls, and externally stored reading position.

Basic reading and extraction rely on standard PNG/APNG structure. Optional ComicAPNG private JSON,
EXIF, and PNG text add document metadata and enhanced geometry restoration.

## Requirements

- Python 3.11 or newer for development
- Project runtime and development dependencies are declared in `pyproject.toml` and installed by
  the commands below.

PyInstaller builds bundle the Python runtime for end users.

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

For command-line source-environment validation, use `-Check` with `launch.ps1` or `--check` with
`launch.cmd` and `launch.sh`.

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

Import that output directory into Create/Edit, or use the bundled offline Test Source to exercise
the same source-to-document path. The generated files serve as local test data and stay outside
version control. They can also test APNG import and ZIP export/import manually.

Primary source files are ASCII-only. All visible interface text is stored in packaged JSON localization resources. English and Simplified Chinese are included.

## Packaging

Use the platform build script from the matching environment:

```powershell
./scripts/build.ps1
```

```sh
sh ./scripts/build.sh
```

The shared `ComicAPNG.spec` collects application resources, bundled source-module manifests and
dependencies, native components, and third-party notices. Frozen smoke tests start the Plugin Host
and exercise the offline test source. Produce each target build on its native operating system.

The application bundle icon is generated from the same Font Awesome icon used by the interface. Run `python scripts/generate_app_icon.py` after intentionally changing that icon. The spec also accepts `COMICAPNG_CODESIGN_IDENTITY` and `COMICAPNG_ENTITLEMENTS_FILE` for future secrets-based macOS signing configuration.

## Builds and downloads

Development builds are available from the GitHub repository under **Actions**, then **Build ComicAPNG**, then **Artifacts** on any successful workflow run. A manual **Run workflow** on `main` performs the complete four-platform test and build, with results stored as workflow artifacts. The automated targets and archives are:

- Windows x64: `ComicAPNG-Windows-x64.zip`
- Linux x64: `ComicAPNG-Linux-x64.tar.gz`
- macOS Intel: `ComicAPNG-macOS-x64.zip`
- macOS Apple Silicon: `ComicAPNG-macOS-arm64.zip`

The Linux archive targets Ubuntu 22.04. macOS builds are architecture-specific and use the ad-hoc
signatures required for executable integrity. Gatekeeper may require manual approval until
Developer ID signing and notarization are configured.

Release-candidate tags use `vX.Y.Z-rc.N` and create GitHub prereleases. Stable tags use `vX.Y.Z` and create normal releases. Each valid tag receives its own complete build; the release job attaches those exact build archives plus `SHA256SUMS.txt`. Other `v*` tag forms are rejected. See the [version bump and release SOP](docs/version-bump-sop.md) and [release procedure](docs/tech-specs.md#19-release-procedure) for the recommended version, PR, manual-build, RC, and stable sequence.

## Formats

ComicAPNG writes standards-compliant, full-canvas APNG in effective document order. Page artwork
is proportionally fitted over transparent padding, and optional EXIF, PNG text, and private
ComicAPNG metadata provide additional document information.

ZIP is an editable exchange format: it stores ordinary images in current document order and may
include versioned `metadata.json`. Imports validate archive paths, resource limits, and exact page
bindings before applying page-specific metadata. See the [technical specifications](docs/tech-specs.md)
and [ZIP exchange format](docs/zip-format.md) for the detailed contracts.

## Known limitations

- Pillow must decode earlier animation state when seeking into some externally optimized APNG files. ComicAPNG hides this behind a frame-access abstraction and keeps only a small LRU of decoded full-resolution pages.
- Original page bounds are reconstructed when trustworthy ComicAPNG geometry metadata is present
  and the extraction option is enabled; other inputs retain their full canvas.
- PyInstaller builds must be produced separately on Windows, macOS, and Linux.
- Source modules run as trusted application components; process isolation provides stability and
  a cancellation fallback.
- Normal CI uses offline fixtures and mocks. Network-backed source checks run as explicit opt-in or
  manual tests.

## License

ComicAPNG is available under the Apache License 2.0. See `LICENSE` and `NOTICE`.
