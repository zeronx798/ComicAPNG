# ComicAPNG Technical Specifications

## 1. Project Goals

ComicAPNG is a native desktop application for creating, extracting, and reading PNG and APNG comic books. One logical APNG animation frame represents one comic page. The project favors standards-compatible files, bounded interactive memory use, metadata-independent reading and extraction, and a single coherent cross-platform interface.

ComicAPNG private metadata is an enhancement rather than a file-validity requirement. Generic PNG and APNG files remain usable when EXIF, PNG text, or ComicAPNG metadata is absent or malformed.

## 2. Supported Platforms

The automated build matrix produces four native targets:

| Target | GitHub-hosted runner | Archive |
| --- | --- | --- |
| Windows x64 | `windows-latest` | `ComicAPNG-Windows-x64.zip` |
| Linux x64 | `ubuntu-22.04` | `ComicAPNG-Linux-x64.tar.gz` |
| macOS Intel | `macos-15-intel` | `ComicAPNG-macOS-x64.zip` |
| macOS Apple Silicon | `macos-latest` | `ComicAPNG-macOS-arm64.zip` |

Python 3.11 is selected explicitly in CI. PyInstaller builds are native: the project does not cross-compile one operating-system package from another operating system.

## 3. Application Architecture

The application uses:

- Python 3.11 or newer as the implementation language.
- PySide6 for the Qt desktop interface.
- Pillow for image identification, decoding, EXIF orientation, RGBA conversion, resizing, metadata access, and APNG frame compositing during reads.
- qtawesome as the single mature icon-library source.
- platformdirs for user cache and log locations.

`MainWindow` is the only `QMainWindow`. It owns one `QStackedWidget` containing the Create, Extract, and Read pages. Menus, status reporting, preferences, language selection, and fullscreen transitions remain within that main window; dialogs are subordinate windows.

The core package contains UI-independent models and image/APNG logic. UI pages submit longer operations to cancellable `QRunnable` workers in the global Qt thread pool. Persistent preferences and reader positions use `QSettings` through `AppSettings`.

Localization is JSON-backed. `I18n` selects either English or Simplified Chinese, loads English as a fallback, and formats named placeholders at lookup time.

## 4. Source Policy

Primary Python, test, script, workflow YAML, TOML, spec, PowerShell, batch, and shell files are ASCII-only. Emoji are prohibited throughout project text. Interface icons come from qtawesome rather than emoji or hand-drawn text symbols.

Localized UTF-8 interface strings belong under `src/comicapng/resources/i18n/`. UTF-8 prose belongs in Markdown documentation, including `docs/README_zh.md`. The `docs/` Markdown exception does not weaken checks for primary source or workflow files. `scripts/check_source_ascii.py` and `tests/test_ascii_source.py` enforce the source and emoji policies.

## 5. Comic Frame Model

`ComicBook` contains an ordered list of `ComicPage` records, metadata, a reading direction, and default cover/body durations. A page references a source image, carries its oriented dimensions, may override its own duration, and may be marked as the cover.

Exactly zero or one page may be marked as the cover. During export, a selected cover becomes logical frame 0 and is removed from its former position, so it is never duplicated. If no cover is selected, the existing page order is retained. The first imported page is selected as the cover by default.

The default cover duration is 10,000 milliseconds and the default body duration is 5,000 milliseconds. The UI displays three-decimal seconds and changes values in one-second increments while the model and file writer retain integer milliseconds.

The reader is manual. It reads stored frame durations but does not automatically advance pages from those timings. There is no timed-playback mode in the current implementation.

## 6. Fixed Canvas Rendering

For oriented source sizes `(width, height)`, the canvas rule is:

```text
canvas_width  = max(source page widths)
canvas_height = max(source page heights)
```

Every logical frame has those exact canvas dimensions. For each source page, ComicAPNG computes:

```text
scale = min(canvas_width / source_width, canvas_height / source_height)
```

The source is scaled proportionally to the nearest bounded integer size and centered with integer offsets. Enlargement is allowed. The algorithm neither stretches one axis independently nor crops artwork. If resizing is required, Pillow `Image.Resampling.LANCZOS` is used.

Sources are EXIF-transposed before rendering and converted to RGBA. A new transparent RGBA canvas is allocated and the fitted source is alpha-composited at the calculated offset. Remaining pixels stay `(0, 0, 0, 0)`. Source alpha is preserved through the composite.

## 7. APNG Encoding

ComicAPNG uses a custom streaming PNG/APNG chunk writer rather than Pillow's APNG save path. Pillow is still used to decode each source image, apply EXIF orientation, convert to RGBA, and perform Lanczos resizing.

The encoder writes:

- A standard PNG signature.
- An 8-bit RGBA `IHDR` using PNG color type 6.
- Optional standard `eXIf` data.
- User PNG text and private ComicAPNG JSON as UTF-8 `iTXt` chunks.
- `acTL` with the logical frame count and loop count `0`, meaning infinite animation looping in animation-oriented viewers.
- One `fcTL` per page.
- First-frame image data as `IDAT`; later frame data as sequenced `fdAT` chunks.
- A final `IEND`.

Every `fcTL` declares the complete canvas width and height at offset `(0, 0)`. Disposal is `0` (none) and blending is `0` (source), so each complete RGBA page replaces the preceding page, including transparent pixels. Frame durations are converted from integer milliseconds to an APNG numerator/denominator pair.

Pixel rows use PNG filter type 0 and are compressed incrementally with zlib level 6. Compressed payloads are split at 1 MiB. The writer uses a temporary file, flushes it to disk, and atomically replaces the destination only after successful completion. Existing output is refused unless the user explicitly approves overwrite.

## 8. APNG Decoding and Extraction

`ApngDocument` opens a file with Pillow and requires the decoded format to be PNG. It records canvas size, logical frame count, animation status, metadata, and whether the PNG contains a separate default image. A separate default image is skipped when logical comic pages are indexed.

Individual pages are loaded on demand. Pillow seeks to the physical frame, resolves the APNG frame state, loads it, and ComicAPNG returns a copied, fully composited RGBA image. This supports generic APNG files and static PNG files without ComicAPNG metadata.

Extraction writes logical pages as `1.png` through `N.png`. It preserves valid user PNG text and raw EXIF when available, but does not copy the ComicAPNG private container JSON into each extracted page. Existing numeric destinations are refused unless overwrite is enabled. Each page is saved through a temporary file and atomically moved into place.

The optional original-bounds mode is metadata-driven. It accepts only validated ComicAPNG geometry within the canvas, crops the known rendered rectangle, and restores the recorded source size with Lanczos resampling if necessary. Without trustworthy geometry, the full composited canvas is retained; alpha content is never guessed as a crop boundary.

## 9. Metadata

All metadata categories are optional and independently readable.

### EXIF

EXIF is serialized with Pillow and stored in the PNG `eXIf` chunk. The editor exposes description, artist, copyright, software, date/time, and user comment fields. It also accepts numeric custom tag IDs with text, integer, rational, or hexadecimal-byte values. Values are validated before output replacement. Extraction preserves the raw EXIF block when Pillow exposes it.

### PNG Text

User text is stored as UTF-8 `iTXt`. Keys must be valid PNG Latin-1 keywords from 1 through 79 bytes, with valid spacing and case-insensitive uniqueness. Field counts and encoded sizes are bounded. Arbitrary valid values, including Unicode text, are supported.

### ComicAPNG Private Metadata

The reserved `iTXt` key is:

```text
ComicAPNG.Metadata
```

The current JSON schema version is `1`. The writer records:

- `format`: `ComicAPNG`
- `version`: `1`
- `cover_index`: `0`
- `reading_direction`: `ltr` or `rtl`
- `pages`: an ordered list of geometry and duration records

Each page record contains `source_width`, `source_height`, `render_width`, `render_height`, `offset_x`, `offset_y`, and `duration_ms`.

The JSON encoder uses deterministic key ordering, ASCII escapes, a 1 MiB private-data limit, and a nesting-depth limit. Malformed, oversized, deeply nested, or non-object private JSON is treated as absent. Unknown private fields are retained by the metadata model and writer, allowing compatible extensions, while known current fields are regenerated from the exported book. Basic reading and extraction do not require the private schema.

## 10. Reader Architecture

The reader opens static PNG and APNG documents in a background worker and represents them through `ApngDocument`. Full-resolution frames are decoded on demand and held in a thread-safe least-recently-used `FrameCache`. The configured capacity is clamped from 3 through 9 pages, with a default of 5. Nearby pages are prefetched at low thread-pool priority.

The `ImageViewer` is a `QGraphicsView` that renders one or two `QImage` pages. It supports fit-page, fit-width, actual-size, and manual zoom from 5 percent through 2,000 percent. At actual or manual scale the user can pan and scroll. Single-page and dual-page layouts are available; the cover remains a single first page, and reading direction controls both horizontal key behavior and pair order.

Navigation is available from buttons, thumbnails, a page-number spin box, arrow keys, Page Up/Page Down, Home/End, and the mouse wheel when the image itself does not need vertical scrolling. F11 and the fullscreen button hide the sidebar, menu, and status bar until fullscreen exits.

Reading position is stored outside the comic. Its key is a SHA-256 fingerprint derived from file size plus samples from the beginning and end of the file. Fit mode, reading mode, direction, recent files, window dimensions, and other preferences are also external `QSettings` values.

## 11. Performance and Memory

Creator import, export, extraction, reader opening, frame rendering, prefetch, and thumbnail generation use cancellable Qt thread-pool workers so the UI thread remains responsive. Cancellation is checked between pages and during encoded scanlines.

Creator source thumbnails and reader frame thumbnails are stored as PNG files in a platform-appropriate user cache directory. Source keys include resolved path, file size, modification time, and requested thumbnail size. Reader thumbnail keys include a content fingerprint, frame index, and size. Visible reader thumbnails are generated lazily with a small surrounding margin.

Pillow decompression-bomb warnings are promoted to errors during source and frame decoding. Memory allocation failures become user-facing resource-limit errors. These controls reduce risk but do not make arbitrarily large images cheap: a decoded RGBA canvas requires roughly four bytes per pixel, cached pages multiply that cost, and Pillow may need to reconstruct earlier APNG animation state when seeking. The writer streams compressed rows but still holds the current source and rendered canvas.

APNG is lossless and full-canvas ComicAPNG files can be substantially larger than JPEG-based comic archives.

## 12. Localization

Localization resources are packaged JSON files:

```text
src/comicapng/resources/i18n/en.json
src/comicapng/resources/i18n/zh_CN.json
```

UI source refers only to translation keys. English is always loaded as the fallback. Locale selection recognizes exact supported names, maps other Chinese locale names to `zh_CN`, and otherwise falls back to English. Changing the language is persisted and takes effect after restart. Packaging validation requires both files and identical key sets.

## 13. Packaging

`ComicAPNG.spec` is the shared PyInstaller definition. It reads the application version from `pyproject.toml`, starts from `src/comicapng/_pyinstaller_entry.py`, and includes:

- ComicAPNG localization and icon resources.
- qtawesome fonts and charmaps.
- PySide6 modules and Qt plugins discovered by PyInstaller hooks.
- `LICENSE` and `NOTICE`.

Windows and Linux retain the project's tested one-file executable strategy. Windows uses the GUI bootloader without a console window and embeds the application icon. Each release archive adds the executable, application PNG, license, and notice under one `ComicAPNG` directory.

macOS builds produce `ComicAPNG.app` separately on Intel and Apple Silicon. Bundle metadata includes `org.comicapng.ComicAPNG`, the project version, display name, high-resolution support, and the application icon. The archive preserves the `.app` directory structure and adds legal files beside it under a top-level `ComicAPNG` directory.

Automated macOS bundles are not signed with an Apple Developer ID and are not notarized. PyInstaller may apply ad-hoc signatures needed for Mach-O integrity. The spec accepts `COMICAPNG_CODESIGN_IDENTITY` and `COMICAPNG_ENTITLEMENTS_FILE` for future secrets-based signing, but CI does not currently supply them or perform notarization.

`scripts/validate_packaging.py` validates source resources and installed native Qt plugins. `scripts/validate_frozen_archive.py` inspects the built PyInstaller archive for native/offscreen Qt platform plugins, both locales, the icon, legal files, and qtawesome data. Each native job also starts the frozen application in Qt offscreen mode.

PyInstaller's PySide6 hooks use `PySide6/plugins/platforms` on Windows and `PySide6/Qt/plugins/platforms` on Linux and macOS. The frozen validator recognizes those platform-specific roots, including a macOS `.app` prefix such as `Contents/Frameworks`, but still requires each plugin to be inside the Qt platforms directory. Cocoa is the native macOS plugin. The offscreen plugin is also required on every target because the noninteractive frozen smoke test explicitly selects it.

## 14. GitHub Actions CI

The workflow is `.github/workflows/build.yml`, displayed in GitHub Actions as **Build ComicAPNG**. It supports `workflow_dispatch`, pull requests targeting `main`, pushes to `main`, and pushed tags matching `v*`.

A read-only `release_policy` job classifies the event before the build matrix. For valid release tags it also verifies with `git merge-base --is-ancestor` that the tagged commit is already contained in `origin/main`. It never moves or deletes a tag.

### workflow_dispatch

Manual dispatch is the primary full pre-release test. It runs policy validation, all tests, packaging validation, and all four native builds. It uploads four Actions artifacts but never creates a tag or GitHub Release, even if the selected dispatch ref is itself a release tag.

The Ubuntu job installs the small runtime library set required by the current PySide6 QtGui and XCB components: `libegl1`, `libgl1`, `libxkbcommon-x11-0`, `libxcb-cursor0`, and `libdbus-1-3`. Linux pytest runs with `QT_QPA_PLATFORM=offscreen`; this is scoped to CI tests and does not change the application's normal runtime platform selection.

### Pull Requests

Pull requests targeting `main` run the complete validation and four-platform build with read-only repository permission. They upload test artifacts and cannot publish a release.

### main push

A normal push or merge to `main` runs the same complete build and uploads artifacts. It cannot publish a release.

### RC tag

A pushed tag such as `v1.0.0-rc.1` is classified as `rc`. After all four matrix entries succeed, the release job downloads their uploaded archives, creates `SHA256SUMS.txt`, and publishes a GitHub prerelease using that exact tag and GitHub-generated notes.

### stable tag

A pushed tag such as `v1.0.0` is classified as `stable`. It receives a new complete build from the stable tagged commit. After all four builds succeed, the release job reuses those exact archives, generates checksums, and publishes a normal GitHub Release. RC binaries are not renamed or promoted.

The Actions artifact names are:

- `ComicAPNG-Windows-x64`
- `ComicAPNG-Linux-x64`
- `ComicAPNG-macOS-x64`
- `ComicAPNG-macOS-arm64`

Each artifact contains the correspondingly named `.zip` or `.tar.gz` archive listed in Section 2. Artifacts are retained for 14 days. The release job verifies that exactly the four expected archives were downloaded before generating `SHA256SUMS.txt`; it does not run PyInstaller or rebuild binaries.

Workflow-level, policy-job, and build-job permissions are `contents: read`. Only the tag-gated release job has `contents: write`. Publishing uses the repository-provided `GITHUB_TOKEN` through GitHub CLI; no personal access token is used.

Concurrency groups ordinary runs by ref and permit obsolete non-tag runs to be cancelled. Every tag gets a separate `release-<ref>` group, and tag runs set `cancel-in-progress` to false. Branch activity therefore cannot cancel an RC or stable release build.

## 15. Release Tag Grammar

Stable releases use exactly:

```text
^v[0-9]+\.[0-9]+\.[0-9]+$
```

Release candidates use exactly:

```text
^v[0-9]+\.[0-9]+\.[0-9]+-rc\.[0-9]+$
```

Examples are `v1.0.0` and `v1.0.0-rc.1`. Other `v*` tags, including alpha, beta, test, shortened, or arbitrary-hyphen forms, fail the release-policy job with a clear diagnostic before the four-platform matrix starts. They cannot publish. Tags not beginning with `v` are outside this workflow's tag trigger.

## 16. Release Procedure

The recommended sequence is:

1. Develop through pull requests and merge approved changes into `main`.
2. Open GitHub Actions, select **Build ComicAPNG**, run `workflow_dispatch` on `main`, download all four artifacts, and test the relevant native binaries.
3. Ensure the intended release commit is present on current `main`.
4. Create and push an annotated RC tag:

   ```sh
   git switch main
   git pull --ff-only origin main
   git tag -a v1.0.0-rc.1 -m "ComicAPNG v1.0.0 RC1"
   git push origin v1.0.0-rc.1
   ```

5. Download and test the generated prerelease assets. If changes are needed, merge them and create the next tag, such as `v1.0.0-rc.2` or `v1.0.0-rc.3`.
6. After an RC is accepted, make sure the desired commit is on current `main`, then create and push the stable tag:

   ```sh
   git switch main
   git pull --ff-only origin main
   git tag -a v1.0.0 -m "ComicAPNG v1.0.0"
   git push origin v1.0.0
   ```

7. GitHub Actions rebuilds all platforms from the stable tagged commit and publishes a normal release from those new archives.

Do not rename RC assets into stable assets. Do not move, rewrite, delete, or force-push published release tags. If an incorrect tag is rejected, inspect it and resolve the mistake deliberately rather than relying on automation to alter it.

## 17. Tests

The automated suite covers:

- APNG frame order, timing, transparency, full-canvas controls, and LRU bounds.
- Fixed-canvas geometry, proportional enlargement, centering, and transparent padding.
- Generic APNG extraction, numeric naming, overwrite safety, and geometry restoration.
- Independent EXIF, PNG text, private metadata, malformed JSON, and Unicode round trips.
- Natural filename ordering and content-based image validation.
- Three-decimal duration controls, default values, and one-second steps.
- Single-main-window architecture, dark-theme transparency, and icon policy.
- ASCII primary-source and project-wide no-emoji policies.
- CI triggers, exact matrix/artifacts, permissions, event gating, valid RC/stable tags, malformed tags, checksum creation, and artifact reuse.

Ruff runs in both local build scripts and CI. Packaging checks validate source resources before PyInstaller and embedded runtime resources afterward. Native frozen applications are smoke-tested with Qt's offscreen platform.

## 18. Known Limitations

- Automated macOS builds are not Developer ID signed or notarized and may trigger Gatekeeper.
- The Linux binary is built on Ubuntu 22.04 and is not a universal Linux package.
- Windows ARM64 and Linux ARM64 builds are not provided.
- There is no AppImage package.
- macOS Intel and Apple Silicon builds are separate; there is no universal binary.
- The reader has no timed automatic-playback mode.
- Original page dimensions can be restored only when valid ComicAPNG geometry metadata exists.
- Very large pages and long comics can consume substantial memory and disk space despite bounded caches and streaming compression.
- Full-canvas lossless APNG output can be much larger than JPEG-based comic-book archives.
