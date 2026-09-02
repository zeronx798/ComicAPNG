# ComicAPNG Technical Specifications

## 1. Project Goals

ComicAPNG is a native desktop application for discovering sources and creating, extracting, and reading PNG and APNG comic books. One logical APNG animation frame represents one comic page. The project favors standards-compatible files, bounded interactive memory use, metadata-independent reading and extraction, and a single coherent cross-platform interface.

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
- jmcomic 2.7.x as the backend of the official JMComic source extension.

`MainWindow` is the only `QMainWindow`. It owns one `QStackedWidget` containing the Sources, Create, Extract, and Read pages. Menus, status reporting, preferences, language selection, plugin settings, and fullscreen transitions remain within that main window; dialogs are subordinate windows.

The core package contains UI-independent models and image/APNG logic. UI pages submit longer operations to cancellable `QRunnable` workers in the global Qt thread pool. Persistent preferences and reader positions use `QSettings` through `AppSettings`.

Localization is JSON-backed. `I18n` selects either English or Simplified Chinese, loads English as a fallback, and formats named placeholders at lookup time.

## 4. Plugin API v1

Plugin API v1 is a deliberately source-oriented interface. It does not let extensions inject Qt widgets, invoke arbitrary application methods, replace the APNG writer, or modify unrelated application behavior. Its version constant is `1`, and the allowed capabilities are `search`, `comic_details`, `chapters`, and `materialize_pages`.

ComicAPNG owns every DTO crossing the boundary:

- `PluginManifest`
- `SourceSearchResult` and `SourceSearchPage`
- `SourceComic`
- `SourceChapter`
- `SourcePage`
- `MaterializedChapter`
- `PluginError`

Upstream implementation objects never reach the GUI. DTO messages contain JSON-compatible scalar, list, and object values; filesystem paths are serialized as strings and reconstructed as `Path` values at the application boundary.

Bundled manifests are discovered without importing implementation modules. A manifest has this format:

```json
{
  "id": "org.comicapng.source.jmcomic",
  "name": "JMComic",
  "version": "0.1.0",
  "api_version": 1,
  "entrypoint": "comicapng.extensions.jmcomic.plugin:create_plugin",
  "capabilities": [
    "search",
    "comic_details",
    "chapters",
    "materialize_pages"
  ],
  "official": true
}
```

Discovery validates the plugin ID, semantic version shape, API version, entrypoint shape, known capabilities, and duplicate IDs. `PluginManager` persists enabled state in `QSettings`, exposes version and availability status, and owns a lazily restarted host client. The Preferences dialog lists installed source plugins and provides the initial enabled and default-cover settings. There is no marketplace, remote installation, arbitrary pip installation, or update mechanism in v1.

### Plugin Host and IPC

All source operations execute in a separate Plugin Host process. Process isolation protects GUI stability, separates network work from the Qt event thread, and gives cancellation a process-level fallback. It is not a security sandbox and does not make untrusted code safe.

Development launches `python -m comicapng.plugins.host`. A frozen GUI launches the same executable with `--plugin-host`. The GUI creates an ephemeral loopback listener, passes its port and a one-use random token to the child, verifies the child's greeting, and then exchanges newline-delimited JSON over that local connection. This avoids relying on standard output in a Windows console-less executable. The token is not a user credential and is never logged.

Requests contain `request_id`, `operation`, and `payload`. Final responses contain `request_id`, `success`, `result`, and `error`. Long operations may emit progress messages containing `request_id`, `event: progress`, `current`, and `total`. The host has a fixed operation allowlist:

- `plugin.list`
- `plugin.health`
- `source.search`
- `source.get_comic`
- `source.get_chapters`
- `source.materialize_cover`
- `source.materialize_chapter`
- `source.cancel`
- `plugin.shutdown`

There is no generic remote Python invocation. The host runs source calls through one worker, so ComicAPNG schedules selected chapters sequentially instead of layering unbounded chapter concurrency over a source library's own page concurrency.

Expected failures use controlled codes: `NetworkError`, `SourceUnavailable`, `NotFound`, `AuthenticationRequired`, `PartialDownload`, `Cancelled`, `InvalidSourceData`, `DependencyUnavailable`, `InvalidRequest`, `IncompatibleApi`, and `InternalPluginError`. Ordinary UI errors receive a safe message and short technical type, not a Python traceback. Complete tracebacks remain in application or host logs. Host operation logs include plugin ID, task ID, and operation; authentication secrets are not added to messages.

Cancellation sets the active host event and stops scheduling later chapters. A cooperative plugin checks this event between safe stages. If an upstream call has not returned after a two-second cancellation grace period, the GUI terminates the host, discards the result, and restarts it lazily on the next call. This is predictable but is not claimed to interrupt every upstream network stage instantaneously.

The application supplies every materialization directory. Returned page and cover paths must resolve inside that directory, exist, and decode as ordinary images. Page indexes must be contiguous and nonempty. Empty manifests, missing or unreadable images, and upstream partial-download reports fail the operation rather than silently producing an incomplete book.

Source workspaces live below the platform-specific ComicAPNG cache under `sources/<plugin>/<task>`. Cancelled and quick-pack workspaces are removed. An Open-in-Create workspace is retained until application shutdown so no `ComicPage` references a deleted file. Plain Download writes below the destination selected by the user.

## 5. Official Source Extensions

### JMComic

The first-party plugin ID is `org.comicapng.source.jmcomic`, version `0.1.0`. ComicAPNG depends on `jmcomic>=2.7.5,<2.8`; 2.7.5 was verified as the current PyPI release during this implementation. The dependency is resolved at application build/install time. End users of frozen packages do not need Python or pip, and the plugin system does not install dependencies at runtime.

The adapter uses documented public jmcomic APIs:

- `JmOption.construct(...)` and `option.new_jm_client()`
- `client.search_site(search_query=query, page=page)`
- `client.get_album_detail(album_id)`
- album iteration for source-order chapters
- `client.download_album_cover(album_id, destination)`
- `download_photo(chapter_id, option=option)`
- `result.manifest.image_filepath_list`

Search remains paginated and maps `page_number`, `page_count`, `total`, album ID, title, and cheaply available tags. Direct JM IDs are passed through the normal upstream search call. Details map album ID, name, authors, description, tags, chapter count, page count, likes, and views when available. Missing optional values do not invalidate the details view. Chapters preserve upstream album iteration order and expose only ComicAPNG `SourceChapter` records.

For a chapter download, the adapter constructs a normal jmcomic option whose base directory is the application-provided destination, retains upstream image decoding, and calls `download_photo`. Final image order comes only from `result.manifest.image_filepath_list`; the adapter never guesses an output directory or reimplements image URL decoding. The upstream downloader's failed-image and failed-photo collections are also checked before returning. Cover materialization uses the upstream album-cover API and remains an editable proposed cover in the resulting `ComicBook`.

Selected chapters are materialized sequentially. Open in Create combines the optional cover followed by selected chapter order and then page order, creates ordinary `ComicPage` records in a normal `ComicBook`, suggests optional Title, Author, Source, SourceId, Tags, and SourceRef PNG text fields, and hands it to the existing Create editor. The source DTOs and source page indexes are no longer active ordering inputs after this transfer. The application does not retain a JM-specific editor path. Users can then reorder/delete pages, change the cover, change timing and direction, edit/remove metadata, and export normally.

Download and Pack uses the same bridge plus the normal `write_apng` implementation. It supports one APNG containing selected chapters or one APNG per chapter. The combined mode never interleaves chapters. Per-chapter mode proposes the same album cover for each output when cover inclusion is enabled. There is no JM-specific encoder.

The adapter configures upstream logging to propagate into the Plugin Host log. It contains no copied scraper implementation, browser automation, CAPTCHA handling, anti-bot bypass, paywall bypass, DRM bypass, login UI, or account-restriction bypass. Anonymous access is sufficient for the MVP; users must save only content they are authorized to access.

### Deterministic Test Source

`org.comicapng.source.test` is bundled with the application and performs no network activity. It exposes fixed search results, details, two chapters, a cover, and ten deterministic RGBA fixture pages. The pages use stable `PAGE 01` through `PAGE 10` labels, unique gradients, patterns, shapes, probe colors, dimensions, and aspect ratios. `scripts/generate_reorder_fixtures.py --output <directory>` produces the same ordered set for manual local import. Normal CI uses it for host IPC, cancellation, Source-to-Create, arbitrary model reordering, fixed-canvas APNG export, timing, ordering, cover identity, and transparency tests. Live JMComic testing is opt-in through `COMICAPNG_RUN_LIVE_SOURCE_TESTS=1` and is never enabled by the standard workflow.

## 6. Source Policy

Primary Python, test, script, workflow YAML, TOML, spec, PowerShell, batch, and shell files are ASCII-only. Emoji are prohibited throughout project text. Interface icons come from qtawesome rather than emoji or hand-drawn text symbols.

Localized UTF-8 interface strings belong under `src/comicapng/resources/i18n/`. UTF-8 prose belongs in Markdown documentation, including `docs/README_zh.md`. The `docs/` Markdown exception does not weaken checks for primary source or workflow files. `scripts/check_source_ascii.py` and `tests/test_ascii_source.py` enforce the source and emoji policies.

## 7. Comic Frame Model

`ComicBook` contains an ordered list of `ComicPage` records, metadata, a reading direction, and default cover/body durations. A page references a source image, carries its oriented dimensions, may override its own duration, and may be marked as the cover.

`ComicBook.pages` is the sole authoritative mutable Create order, regardless of whether a page came from local import, a directory, JMComic, the deterministic source, or a future Plugin API implementation. Natural or source ordering is used only to construct the initial list. Thumbnail refreshes, cover changes, metadata edits, and thumbnail generation never sort that list.

`ComicBook.move_page(source_index, target_index)` and `move_pages(source_indices, target_index)` provide the shared reorder implementation. The target is the final index after moved pages are removed; moving index 1 to final index 3 transforms `[A, B, C, D]` into `[A, C, D, B]`. A multi-page move preserves selected-page relative order and inserts the block at the requested final index. Both methods mutate the existing page list and preserve `ComicPage` identity.

The Create thumbnail view uses a snapped row-major icon layout and converts a drop position into an explicit before/after item boundary. It does not accept Qt's free visual position as page order. Drag/drop sends row indexes to the shared model API, then reapplies model order to the existing thumbnail items while retaining selection and the current item. A right-click on an unselected page selects it; a right-click on an already selected page preserves the selection. Context actions operate only on the current clicked page and are Move Up, Move Down, Move to Top, and Move to Bottom. Boundary actions are disabled. These actions also call the shared model API.

Exactly zero or one page may be marked as the cover. During export, a selected cover becomes logical frame 0 and is removed from its former position, so it is never duplicated. If no cover is selected, the existing page order is retained. The first imported page is selected as the cover by default.

The default cover duration is 10,000 milliseconds and the default body duration is 5,000 milliseconds. The UI displays three-decimal seconds and changes values in one-second increments while the model and file writer retain integer milliseconds.

The reader is manual. It reads stored frame durations but does not automatically advance pages from those timings. There is no timed-playback mode in the current implementation.

## 8. Fixed Canvas Rendering

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

## 9. APNG Encoding

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

## 10. APNG Decoding and Extraction

`ApngDocument` opens a file with Pillow and requires the decoded format to be PNG. It records canvas size, logical frame count, animation status, metadata, and whether the PNG contains a separate default image. A separate default image is skipped when logical comic pages are indexed.

Individual pages are loaded on demand. Pillow seeks to the physical frame, resolves the APNG frame state, loads it, and ComicAPNG returns a copied, fully composited RGBA image. This supports generic APNG files and static PNG files without ComicAPNG metadata.

Extraction writes logical pages as `1.png` through `N.png`. It preserves valid user PNG text and raw EXIF when available, but does not copy the ComicAPNG private container JSON into each extracted page. Existing numeric destinations are refused unless overwrite is enabled. Each page is saved through a temporary file and atomically moved into place.

The optional original-bounds mode is metadata-driven. It accepts only validated ComicAPNG geometry within the canvas, crops the known rendered rectangle, and restores the recorded source size with Lanczos resampling if necessary. Without trustworthy geometry, the full composited canvas is retained; alpha content is never guessed as a crop boundary.

## 11. Metadata

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

## 12. Reader Architecture

The reader opens static PNG and APNG documents in a background worker and represents them through `ApngDocument`. Full-resolution frames are decoded on demand and held in a thread-safe least-recently-used `FrameCache`. The configured capacity is clamped from 3 through 9 pages, with a default of 5. Nearby pages are prefetched at low thread-pool priority.

The `ImageViewer` is a `QGraphicsView` that renders one or two `QImage` pages. It supports fit-page, fit-width, actual-size, and manual zoom from 5 percent through 2,000 percent. At actual or manual scale the user can pan and scroll. Single-page and dual-page layouts are available; the cover remains a single first page, and reading direction controls both horizontal key behavior and pair order.

Navigation is available from buttons, thumbnails, a page-number spin box, arrow keys, Page Up/Page Down, Home/End, and the mouse wheel when the image itself does not need vertical scrolling. F11 and the fullscreen button hide the sidebar, menu, and status bar until fullscreen exits.

Reading position is stored outside the comic. Its key is a SHA-256 fingerprint derived from file size plus samples from the beginning and end of the file. Fit mode, reading mode, direction, recent files, window dimensions, and other preferences are also external `QSettings` values.

## 13. Performance and Memory

Creator import, export, extraction, reader opening, frame rendering, prefetch, thumbnail generation, and every GUI-side source request use cancellable Qt thread-pool workers so the UI thread remains responsive. Search, details, cover loading, chapter materialization, and source networking execute in the Plugin Host rather than the GUI process. Cancellation is checked between pages and during encoded scanlines.

Creator source thumbnails and reader frame thumbnails are stored as PNG files in a platform-appropriate user cache directory. Source keys include resolved path, file size, modification time, and requested thumbnail size. Reader thumbnail keys include a content fingerprint, frame index, and size. Visible reader thumbnails are generated lazily with a small surrounding margin.

Pillow decompression-bomb warnings are promoted to errors during source and frame decoding. Memory allocation failures become user-facing resource-limit errors. These controls reduce risk but do not make arbitrarily large images cheap: a decoded RGBA canvas requires roughly four bytes per pixel, cached pages multiply that cost, and Pillow may need to reconstruct earlier APNG animation state when seeking. The writer streams compressed rows but still holds the current source and rendered canvas.

APNG is lossless and full-canvas ComicAPNG files can be substantially larger than JPEG-based comic archives.

## 14. Localization

Localization resources are packaged JSON files:

```text
src/comicapng/resources/i18n/en.json
src/comicapng/resources/i18n/zh_CN.json
```

UI source refers only to translation keys. English is always loaded as the fallback. Locale selection recognizes exact supported names, maps other Chinese locale names to `zh_CN`, and otherwise falls back to English. Changing the language is persisted and takes effect after restart. Packaging validation requires both files and identical key sets.

## 15. Packaging

`ComicAPNG.spec` is the shared PyInstaller definition. It reads the application version from `pyproject.toml`, starts from `src/comicapng/_pyinstaller_entry.py`, and includes:

- ComicAPNG localization and icon resources.
- qtawesome fonts and charmaps.
- Both official source-extension manifests and entrypoint modules.
- jmcomic modules and distribution metadata.
- curl-cffi modules and native runtime components discovered from the installed distribution.
- PySide6 modules and Qt plugins discovered by PyInstaller hooks.
- `LICENSE`, `NOTICE`, and the jmcomic MIT license notice.

Windows and Linux retain the project's tested one-file executable strategy. Windows uses the GUI bootloader without a console window and embeds the application icon. Each release archive adds the executable, application PNG, license, and notice under one `ComicAPNG` directory.

macOS builds produce `ComicAPNG.app` separately on Intel and Apple Silicon. Bundle metadata includes `org.comicapng.ComicAPNG`, the project version, display name, high-resolution support, and the application icon. The archive preserves the `.app` directory structure and adds legal files beside it under a top-level `ComicAPNG` directory.

Automated macOS bundles are not signed with an Apple Developer ID and are not notarized. PyInstaller may apply ad-hoc signatures needed for Mach-O integrity. The spec accepts `COMICAPNG_CODESIGN_IDENTITY` and `COMICAPNG_ENTITLEMENTS_FILE` for future secrets-based signing, but CI does not currently supply them or perform notarization.

`scripts/validate_packaging.py` validates source resources, manifests, the selected jmcomic version, the installed curl-cffi native wrapper, Plugin Host startup, plugin listing, and test-source IPC without contacting JMComic. `scripts/validate_frozen_archive.py` inspects the built PyInstaller archive for native/offscreen Qt platform plugins, both locales, both manifests, jmcomic distribution metadata, curl-cffi native components, the icon, legal files, and qtawesome data. Each native job also starts the frozen application in Qt offscreen mode. The frozen smoke path launches another frozen instance as the Plugin Host, checks JMComic health/import, and searches the offline test source.

PyInstaller's PySide6 hooks use `PySide6/plugins/platforms` on Windows and `PySide6/Qt/plugins/platforms` on Linux and macOS. The frozen validator recognizes those platform-specific roots, including a macOS `.app` prefix such as `Contents/Frameworks`, but still requires each plugin to be inside the Qt platforms directory. Cocoa is the native macOS plugin. The offscreen plugin is also required on every target because the noninteractive frozen smoke test explicitly selects it.

## 16. GitHub Actions CI

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

## 17. Release Tag Grammar

Stable releases use exactly:

```text
^v[0-9]+\.[0-9]+\.[0-9]+$
```

Release candidates use exactly:

```text
^v[0-9]+\.[0-9]+\.[0-9]+-rc\.[0-9]+$
```

Examples are `v1.0.0` and `v1.0.0-rc.1`. Other `v*` tags, including alpha, beta, test, shortened, or arbitrary-hyphen forms, fail the release-policy job with a clear diagnostic before the four-platform matrix starts. They cannot publish. Tags not beginning with `v` are outside this workflow's tag trigger.

## 18. Release Procedure

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

## 19. Tests

The automated suite covers:

- APNG frame order, timing, transparency, full-canvas controls, and LRU bounds.
- Fixed-canvas geometry, proportional enlargement, centering, and transparent padding.
- Generic APNG extraction, numeric naming, overwrite safety, and geometry restoration.
- Independent EXIF, PNG text, private metadata, malformed JSON, and Unicode round trips.
- Natural filename ordering and content-based image validation.
- Three-decimal duration controls, default values, and one-second steps.
- Single-main-window architecture, dark-theme transparency, and icon policy.
- Plugin API DTO and manifest validation, host discovery, explicit IPC, and cancellation.
- Mocked JMComic search, details, chapters, ordered five-page download manifests, conversion to ordinary editable pages, manual order independence, cover download, missing files, empty manifests, dependency failure, and partial failures.
- Model moves forward, backward, first-to-last, last-to-first, adjacent, no-op, multi-page block, identity, and cover preservation.
- Qt Create actions for an internal `QDropEvent`, arbitrary drag requests, before/after drop boundaries, multi-selection retention, Move Up, Move Down, Move to Top, Move to Bottom, and disabled boundary states.
- Deterministic ten-page Source-to-Create-to-APNG readback covering manual Create order, cover normalization, per-page identity, varied dimensions, proportional fixed-canvas rendering, and transparent padding.
- ASCII primary-source and project-wide no-emoji policies.
- CI triggers, exact matrix/artifacts, permissions, event gating, valid RC/stable tags, malformed tags, checksum creation, and artifact reuse.

Ruff runs in both local build scripts and CI. Packaging checks validate source resources before PyInstaller and embedded runtime resources afterward. Native frozen applications are smoke-tested with Qt's offscreen platform.

## 20. Known Limitations

- Automated macOS builds are not Developer ID signed or notarized and may trigger Gatekeeper.
- The Linux binary is built on Ubuntu 22.04 and is not a universal Linux package.
- Windows ARM64 and Linux ARM64 builds are not provided.
- There is no AppImage package.
- macOS Intel and Apple Silicon builds are separate; there is no universal binary.
- The reader has no timed automatic-playback mode.
- Original page dimensions can be restored only when valid ComicAPNG geometry metadata exists.
- Very large pages and long comics can consume substantial memory and disk space despite bounded caches and streaming compression.
- Full-canvas lossless APNG output can be much larger than JPEG-based comic-book archives.
- Plugin process isolation is for stability and is not a malicious-code security sandbox.
- Upstream JMComic calls may not stop cooperatively at every network stage; cancellation may terminate and restart the host after its grace period.
- Login, account/cookie configuration, favorites, comments, rankings, subscriptions, scheduled downloads, and a plugin marketplace are not part of Plugin API v1.
- Normal CI uses mocks and the deterministic source. Real JMComic search, details, cover, and download behavior still require an explicit authorized manual or opt-in live test.
