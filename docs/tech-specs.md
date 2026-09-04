# ComicAPNG Technical Specifications

## 1. Project Goals

ComicAPNG is a native, document-oriented desktop application for building, editing, exporting,
extracting, and reading page-based image documents. Local files, archive imports, and source
modules converge on a common editable model. Individual sources are input implementations rather
than product identities, and output writers remain independent from them.

One logical APNG animation frame represents one page. The project favors standards-compatible
files, bounded interactive memory use, metadata-independent reading and extraction, and a single
coherent cross-platform interface. The high-level boundaries and data flows are summarized in
[architecture.md](architecture.md).

ComicAPNG private metadata provides optional enhancements. Standard PNG/APNG structure supplies
basic reading and extraction, while recognized metadata adds document settings and geometry.

## 2. Supported Platforms

The automated build matrix produces four native targets:

| Target | GitHub-hosted runner | Archive |
| --- | --- | --- |
| Windows x64 | `windows-latest` | `ComicAPNG-Windows-x64.zip` |
| Linux x64 | `ubuntu-22.04` | `ComicAPNG-Linux-x64.tar.gz` |
| macOS Intel | `macos-15-intel` | `ComicAPNG-macOS-x64.zip` |
| macOS Apple Silicon | `macos-latest` | `ComicAPNG-macOS-arm64.zip` |

Python 3.11 is selected explicitly in CI. Each PyInstaller target is built natively on its matching
operating-system runner.

## 3. Document-Oriented Architecture

The conceptual dependency flow is:

```text
Local files / APNG / ZIP / source modules
                    |
                    v
         Import and materialization
                    |
                    v
             Document model
                    |
                    v
       Editor / document services
                    |
                    v
          APNG / ZIP / future formats
```

Input adapters discover or decode resources, and core-owned importers and bridges create the
editable document. Exporters operate solely on that document. The current reader uses a separate
read-only `ApngDocument` abstraction for PNG and APNG. Editing, reading, and export therefore share
the same source-independent boundary.

The application uses:

- Python 3.11 or newer as the implementation language.
- PySide6 for the Qt desktop interface.
- Pillow for image identification, decoding, EXIF orientation, RGBA conversion, resizing, metadata access, and APNG frame compositing during reads.
- qtawesome as the single mature icon-library source.
- platformdirs for user cache and log locations.
- Source-module-specific adapters and dependencies behind Plugin API v1.

`MainWindow` is the only `QMainWindow`. It owns one `QStackedWidget` containing the Sources, Create, Extract, and Read pages. Menus, status reporting, preferences, language selection, plugin settings, and fullscreen transitions remain within that main window; dialogs are subordinate windows.

The core package contains UI-independent models and image/APNG/ZIP logic. UI pages submit longer operations to cancellable `QRunnable` workers in the global Qt thread pool. Persistent preferences, reader positions, normal window geometry and position, and the maximized state use `QSettings` through `AppSettings`. Saved geometry is restored only when a useful rectangle remains visible on a currently available screen.

Localization is JSON-backed. `I18n` selects either English or Simplified Chinese, loads English as a fallback, and formats named placeholders at lookup time.

## 4. Source Module API v1

Source modules currently implement Plugin API v1, a source-focused input interface. A module
provides resource discovery, source metadata, and materialization into resources that the
core-owned bridge converts to an editable document. Qt composition, application commands, and
format writers remain core-owned. Its version constant is `1`, and the allowed capabilities are
`search`, `comic_details`, `chapters`, and
`materialize_pages`. See [source-modules.md](source-modules.md) for the architectural contract and
the distinction between built-in modules and possible future external plugins.

ComicAPNG owns every DTO crossing the boundary:

- `PluginManifest`
- `SourceSearchResult` and `SourceSearchPage`
- `SourceComic`
- `SourceChapter`
- `SourcePage`
- `MaterializedChapter`
- `PluginError`

The DTO boundary keeps upstream implementation objects inside each source module. Messages contain
JSON-compatible scalar, list, and object values; filesystem paths are serialized as strings and
reconstructed as `Path` values at the application boundary.

Discovery reads bundled manifest JSON before importing implementation modules. A manifest has this
format:

```json
{
  "id": "org.comicapng.source.example",
  "name": "Example Source",
  "version": "0.1.0",
  "api_version": 1,
  "entrypoint": "comicapng_source_example.plugin:create_plugin",
  "capabilities": [
    "search",
    "comic_details",
    "chapters",
    "materialize_pages"
  ],
  "official": false
}
```

The example identifier and entrypoint are illustrative. Real built-in manifests use their own
identifiers and packaged module paths. Discovery validates the plugin ID, semantic version shape,
API version, entrypoint shape, known capabilities, and duplicate IDs. `PluginManager` persists
enabled state in `QSettings`, exposes version and availability status, and owns a lazily restarted
host client. The Preferences dialog lists available source modules and provides the initial enabled
and default-cover settings. External plugin support belongs to a future architecture stage covering
discovery, installation, updates, dependency management, compatibility, and trust.

### Plugin Host and IPC

All source operations execute in a separate Plugin Host process. Process isolation protects GUI
stability, separates network work from the Qt event thread, and gives cancellation a process-level
fallback. Source modules remain trusted application components.

Development launches `python -m comicapng.plugins.host`. A frozen GUI launches the same executable
with `--plugin-host`. The GUI creates an ephemeral loopback listener, passes its port and a one-use
random token to the child, verifies the child's greeting, and then exchanges newline-delimited JSON
over that local connection. This transport supports the Windows GUI bootloader. The token
authorizes one local host session and is omitted from logs.

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

The fixed operation allowlist above is the complete remote surface. The host runs source calls
through one worker, and ComicAPNG schedules selected chapters sequentially to bound host-level
concurrency alongside any page concurrency inside a source library.

Expected failures use controlled codes: `NetworkError`, `SourceUnavailable`, `NotFound`,
`AuthenticationRequired`, `PartialDownload`, `Cancelled`, `InvalidSourceData`,
`DependencyUnavailable`, `InvalidRequest`, `IncompatibleApi`, and `InternalPluginError`. The UI
receives a safe message and short technical type; complete tracebacks remain in application or host
logs. Host operation logs include plugin ID, task ID, and operation while omitting authentication
secrets.

Cancellation sets the active host event and stops scheduling later chapters. A cooperative plugin
checks this event between safe stages. After a two-second grace period, the GUI uses host
termination as a bounded fallback, discards the cancelled result, and restarts the host lazily on
the next call.

The application supplies every materialization directory. Returned page and cover paths must
resolve inside that directory, exist, and decode as ordinary images. Page indexes must be
contiguous and nonempty. Validation rejects empty manifests, missing or unreadable images, and
upstream partial-download reports before document conversion.

Source workspaces live below the platform-specific ComicAPNG cache under `sources/<plugin>/<task>`.
Cancelled, APNG-pack, and ZIP-export workspaces are removed. An Open-in-Create workspace is retained
until application shutdown, keeping every `ComicPage` path valid. APNG/ZIP import workspaces use the
sibling `imports` cache, remain alive while Create/Edit references them, and are removed on
replacement, cancellation, or application shutdown. Plain Download writes below the destination
selected by the user.

## 5. Built-in Source Modules

Built-in source modules are release-managed application components. Their manifests,
implementations, dependencies, and notices ship with the application. They exercise the same API
boundary that keeps the core independent from individual sources. External plugin installation is
planned as a separate architecture stage.

### Deterministic Test Source

`org.comicapng.source.test` is a built-in, offline module. It exposes fixed resource metadata and
ten varied RGBA fixture pages so normal CI and manual checks can validate host IPC, cancellation,
source-to-document conversion, reordering, fixed-canvas APNG export, timing, cover identity, and
transparency with stable local resources. `scripts/generate_reorder_fixtures.py --output <directory>`
produces the same ordered pages for local-file import.

### JMComic Source Module

JMComic is one built-in source module and an example implementation of the source-module
architecture. Its adapter targets `jmcomic` 2.7.x; source-specific mapping and calls occur behind
the adapter and Plugin Host boundary. The module returns ComicAPNG-owned records and materialized
images; the common source bridge, editor, APNG writer, and ZIP writer handle everything after that
boundary. See its
[module README](../src/comicapng/extensions/jmcomic/README.md) for the implementation summary.
Explicit opt-in and authorized manual tests cover network-backed behavior; normal CI uses mocks and
the deterministic module.

## 6. Project Text Policy

Primary Python, test, script, workflow YAML, TOML, spec, PowerShell, batch, and shell files are
ASCII-only. Emoji are prohibited throughout project text. Qtawesome supplies interface icons.

Localized UTF-8 interface strings belong under `src/comicapng/resources/i18n/`. UTF-8 prose belongs
in Markdown documentation, including `docs/README_zh.md`. Automation applies the ASCII policy to
primary source and workflow files and the emoji policy to project text through
`scripts/check_source_ascii.py` and `tests/test_ascii_source.py`.

## 7. Unified Document Model

`ComicBook` contains an ordered list of `ComicPage` records, metadata, a reading direction, and default cover/body durations. A page references a source image, carries its oriented dimensions, may override its own duration, may hold optional JSON-only source data, and may be marked as the cover. `ComicMetadata.source` is an optional `SourceMetadata` record containing `plugin_id`, `resource_id`, and a JSON-only `data` object. Raw source tags remain distinct from editable PNG text fields.

`ComicBook.pages` is the sole authoritative mutable Create order, regardless of whether a page came
from local-file import, APNG or ZIP import, a built-in source module, or a future input adapter.
Natural, archive, or source ordering constructs the initial list. Thumbnail refreshes, cover
changes, metadata edits, and thumbnail generation preserve the document's current order.

`ComicBook.move_page(source_index, target_index)` and `move_pages(source_indices, target_index)` provide the shared reorder implementation. The target is the final index after moved pages are removed; moving index 1 to final index 3 transforms `[A, B, C, D]` into `[A, C, D, B]`. A multi-page move preserves selected-page relative order and inserts the block at the requested final index. Both methods mutate the existing page list and preserve `ComicPage` identity.

The Create thumbnail view uses a snapped row-major icon layout and converts a drop position into an
explicit before/after item boundary as the order input. Drag/drop sends row indexes to the shared
model API, then reapplies model order to the existing thumbnail items while retaining selection and
the current item. A right-click on an unselected page selects it; a right-click on an already
selected page preserves the selection. Context actions operate on the current clicked page and are
Move Up, Move Down, Move to Top, and Move to Bottom. The UI enables each action when it changes the
order. These actions also call the shared model API.

Exactly zero or one page may be marked as the cover. During APNG export, a selected cover appears
exactly once as logical frame 0. The existing page order applies when the cover is unset. ZIP export
preserves editable order and records the cover by filename. The first imported page is selected as
the cover by default.

The default cover duration is 10,000 milliseconds and the default body duration is 5,000 milliseconds. The UI displays three-decimal seconds and changes values in one-second increments while the model and file writer retain integer milliseconds.

The current reader provides manual navigation and reads stored frame durations as document
information.

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

The source is scaled proportionally to the nearest bounded integer size and centered with integer
offsets. Enlargement is allowed, and complete artwork retains its aspect ratio. Resizing uses
Pillow `Image.Resampling.LANCZOS`.

Sources are EXIF-transposed before rendering and converted to RGBA. A new transparent RGBA canvas is allocated and the fitted source is alpha-composited at the calculated offset. Remaining pixels stay `(0, 0, 0, 0)`. Source alpha is preserved through the composite.

## 9. APNG Encoding

ComicAPNG uses a custom streaming PNG/APNG chunk writer. Pillow decodes each source image, applies
EXIF orientation, converts to RGBA, and performs Lanczos resizing.

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

Pixel rows use PNG filter type 0 and are compressed incrementally with zlib level 6. Compressed
payloads are split at 1 MiB. The writer uses a temporary file, flushes it to disk, and atomically
replaces the destination after successful completion. Replacing an existing output requires
explicit overwrite approval.

## 10. APNG Decoding and Extraction

`ApngDocument` opens a file with Pillow and requires the decoded format to be PNG. It records canvas size, logical frame count, animation status, metadata, and whether the PNG contains a separate default image. A separate default image is skipped when logical comic pages are indexed.

Individual pages are loaded on demand. Pillow seeks to the physical frame, resolves the APNG frame
state, loads it, and ComicAPNG returns a copied, fully composited RGBA image. Generic APNG and static
PNG files use this path, with ComicAPNG metadata remaining optional.

Extraction writes logical pages as `1.png` through `N.png`. It preserves valid user PNG text and raw
EXIF when available; private container JSON remains associated with the source document. Replacing
existing numeric destinations requires overwrite approval. Each page is saved through a temporary
file and atomically moved into place.

The optional original-bounds mode is metadata-driven. It accepts validated ComicAPNG geometry
within the canvas, crops the known rendered rectangle, and restores the recorded source size with
Lanczos resampling if necessary. Other inputs retain the full composited canvas; alpha values are
not crop signals.

## 11. Import and Export Pipelines

### Import pipeline

Every editable input becomes a normal `ComicBook` before it reaches Create/Edit:

- Local image files and recursively discovered directory images are content-validated and added in
  natural filename order.
- Source modules return ComicAPNG-owned metadata records and materialized images. The common source
  bridge creates normal pages, and source ordering establishes only their initial sequence.
- APNG and ZIP importers decode or copy page resources into application-owned workspaces, then
  attach only validated metadata.

APNG import requires an animation-control chunk; static PNG remains available through local-image
import. One-frame APNG files remain valid. Each logical frame is decoded as a fully composited
RGBA image and atomically materialized as a normal PNG-backed `ComicPage`. Frame order and durations
are retained. ComicAPNG original bounds are restored only when the private page list has exactly the
logical frame count and the individual geometry is valid within the canvas; other frames retain
their full canvas. Readable EXIF, PNG text, reading direction,
default timing, source data, and unknown safe private fields remain in the normal metadata model.

ZIP import validates every entry before copying recognized images to sequential application-owned
working files. It rejects traversal/absolute/backslash/drive paths, duplicate names, encrypted
images, more than 10,000 entries, entries over 512 MiB, and total declared or copied data over 2
GiB. `metadata.json` is limited to 8 MiB. The importer processes validated entries individually,
copies recognized images, and ignores unrelated non-image entries.

An image-only ZIP uses natural filename order. With valid metadata, the ordered page filename list
must be unique and its exact case-sensitive set must equal all supported image entries. A missing,
renamed, duplicated, or unexpected image, or an invalid cover reference, marks the entire
page-bound group untrusted before user review: order, duration, geometry, page source IDs/indexes,
cover, and other page references remain grouped. The review dialog shows found, referenced,
missing, unexpected, and invalid references. Available choices are trusted document/source
metadata with natural-order images, image-only import, or cancellation with the current document
preserved. Malformed metadata similarly permits image-only import. The selected document replaces
Create/Edit after this decision and thumbnail preparation succeed.

### Export pipeline

The APNG and ZIP exporters operate solely on a validated `ComicBook` snapshot and its current
editable order.

APNG export uses `ComicBook.export_pages()` to place the selected cover exactly once at frame 0,
then applies the fixed-canvas writer described above. ZIP export preserves current
editable order and stores the cover as an exact filename reference. It writes non-padded `1`
through `N` filenames using a canonical extension for the identified stored format. PNG, JPEG,
WebP, BMP, and TIFF bytes are copied directly; other decoded formats are normalized to PNG.
`metadata.json` schema v1 stores document metadata/settings, optional generic source metadata,
exact ordered page filename bindings, per-page timing/dimensions/source data, and the cover
filename. The detailed schema is documented in [zip-format.md](zip-format.md).

A future exporter can consume the same document model through another core-owned writer.

## 12. Metadata

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

The current JSON schema version is `2`. Version 1 files remain readable. The writer records:

- `format`: `ComicAPNG`
- `version`: `2`
- `cover_index`: `0`
- `reading_direction`: `ltr` or `rtl`
- `cover_duration_ms` and `body_duration_ms`
- optional generic `source` metadata
- `pages`: an ordered list of geometry and duration records

Each page record contains `source_width`, `source_height`, `render_width`, `render_height`, `offset_x`, `offset_y`, and `duration_ms`, plus optional JSON-only page source data. Source metadata is restored on APNG import and regenerated from the current model on later export.

The JSON encoder uses deterministic key ordering, ASCII escapes, a 1 MiB private-data limit, and a
nesting-depth limit. Malformed, oversized, deeply nested, or non-object private JSON is treated as
absent. Unknown private fields are retained by the metadata model and writer, allowing compatible
extensions, while known current fields are regenerated from the exported book. Standard PNG/APNG
structure supplies basic reading and extraction independently from the private schema.

## 13. Reader Architecture

The reader opens static PNG and APNG documents in a background worker and represents them through `ApngDocument`. Full-resolution frames are decoded on demand and held in a thread-safe least-recently-used `FrameCache`. The configured capacity is clamped from 3 through 9 pages, with a default of 5. Nearby pages are prefetched at low thread-pool priority.

The `ImageViewer` is a `QGraphicsView` that renders one or two `QImage` pages. It supports fit-page, fit-width, actual-size, and manual zoom from 5 percent through 2,000 percent. At actual or manual scale the user can pan and scroll. Single-page and dual-page layouts are available; the cover remains a single first page, and reading direction controls both horizontal key behavior and pair order.

Navigation is available from buttons, thumbnails, a page-number spin box, arrow keys, Page Up/Page
Down, Home/End, and the mouse wheel whenever vertical image scrolling is inactive. F11 and the
fullscreen button hide the sidebar, menu, and status bar until fullscreen exits.

Reading position is stored outside the comic. Its key is a SHA-256 fingerprint derived from file size plus samples from the beginning and end of the file. Fit mode, reading mode, direction, recent files, validated normal window geometry/position, maximized state, and other preferences are also external `QSettings` values.

## 14. Performance and Memory

Creator import, export, extraction, reader opening, frame rendering, prefetch, thumbnail generation,
and every GUI-side source request use cancellable Qt thread-pool workers so the UI thread remains
responsive. The Plugin Host handles search, details, cover loading, chapter materialization, and
source networking. Cancellation is checked between pages and during encoded scanlines.

Creator source thumbnails and reader frame thumbnails are stored as PNG files in a platform-appropriate user cache directory. Source keys include resolved path, file size, modification time, and requested thumbnail size. Reader thumbnail keys include a content fingerprint, frame index, and size. Visible reader thumbnails are generated lazily with a small surrounding margin.

Pillow decompression-bomb warnings are promoted to errors during source and frame decoding. Memory
allocation failures become user-facing resource-limit errors. A decoded RGBA canvas requires
roughly four bytes per pixel, cached pages multiply that cost, and Pillow may reconstruct earlier
APNG animation state when seeking. The writer streams compressed rows while holding the current
source and rendered canvas.

APNG is lossless and full-canvas ComicAPNG files can be substantially larger than JPEG-based comic archives.

## 15. Localization

Localization resources are packaged JSON files:

```text
src/comicapng/resources/i18n/en.json
src/comicapng/resources/i18n/zh_CN.json
```

UI source refers only to translation keys. English is always loaded as the fallback. Locale selection recognizes exact supported names, maps other Chinese locale names to `zh_CN`, and otherwise falls back to English. Changing the language is persisted and takes effect after restart. Packaging validation requires both files and identical key sets.

## 16. Packaging

`ComicAPNG.spec` is the shared PyInstaller definition. It reads the application version from `pyproject.toml`, starts from `src/comicapng/_pyinstaller_entry.py`, and includes:

- ComicAPNG localization and icon resources.
- qtawesome fonts and charmaps.
- Built-in source-module manifests, entrypoint modules, runtime dependencies, and distribution
  metadata.
- Native runtime components required by bundled source-module dependencies.
- PySide6 modules and Qt plugins discovered by PyInstaller hooks.
- `LICENSE`, `NOTICE`, and required third-party license notices.

Windows and Linux retain the project's tested one-file executable strategy. Windows uses the GUI
bootloader, suppresses the console window, and embeds the application icon. Each release archive
adds the executable, application PNG, license, and notice under one `ComicAPNG` directory.

macOS builds produce `ComicAPNG.app` separately on Intel and Apple Silicon. Bundle metadata includes `org.comicapng.ComicAPNG`, the project version, display name, high-resolution support, and the application icon. The archive preserves the `.app` directory structure and adds legal files beside it under a top-level `ComicAPNG` directory.

Automated macOS bundles use the ad-hoc signatures needed for Mach-O integrity, so Gatekeeper may
require manual approval. The spec accepts `COMICAPNG_CODESIGN_IDENTITY` and
`COMICAPNG_ENTITLEMENTS_FILE` for future Developer ID signing and notarization.

`scripts/validate_packaging.py` validates application resources, source manifests, pinned bundled
module dependencies, required native wrappers, Plugin Host startup, module listing, and offline
test-source IPC. `scripts/validate_frozen_archive.py` inspects the built
PyInstaller archive for native/offscreen Qt platform plugins, both locales, both source manifests,
bundled adapter metadata and native components, the icon, legal files, and qtawesome data. Each
native job also starts the frozen application in Qt offscreen mode. The frozen smoke path launches
another frozen instance as the Plugin Host, checks bundled-module health/import, and searches the
offline test source.

PyInstaller's PySide6 hooks use `PySide6/plugins/platforms` on Windows and
`PySide6/Qt/plugins/platforms` on Linux and macOS. The frozen validator recognizes those
platform-specific roots, including a macOS `.app` prefix such as `Contents/Frameworks`, and requires
each plugin inside the Qt platforms directory. Cocoa is the native macOS plugin. The offscreen
plugin is also required on every target because the noninteractive frozen smoke test explicitly
selects it.

## 17. GitHub Actions CI

The workflow is `.github/workflows/build.yml`, displayed in GitHub Actions as **Build ComicAPNG**. It supports `workflow_dispatch`, pull requests targeting `main`, pushes to `main`, and pushed tags matching `v*`.

A read-only `release_policy` job classifies the event before the build matrix. For valid release
tags it also verifies with `git merge-base --is-ancestor` that the tagged commit is already
contained in `origin/main`. Its scope is classification and ancestry validation.

### workflow_dispatch

Manual dispatch is the primary full pre-release test. It runs policy validation, all tests,
packaging validation, and all four native builds, then uploads four Actions artifacts. Release
publication remains exclusive to pushed release-tag events.

The Ubuntu job installs the small runtime library set required by the current PySide6 QtGui and XCB
components: `libegl1`, `libgl1`, `libxkbcommon-x11-0`, `libxcb-cursor0`, and `libdbus-1-3`. Linux
pytest uses `QT_QPA_PLATFORM=offscreen`, while normal application startup continues to use native
runtime platform selection.

### Pull Requests

Pull requests targeting `main` run the complete validation and four-platform build with read-only
repository permission. They upload test artifacts; publication permission is reserved for the
tag-gated release job.

### main push

A normal push or merge to `main` runs the same complete build and uploads workflow artifacts.
Release publication is reserved for the tag-gated release job.

### RC tag

A pushed tag such as `v1.2.3-rc.1` is classified as `rc`. After all four matrix entries succeed, the release job downloads their uploaded archives, creates `SHA256SUMS.txt`, and publishes a GitHub prerelease using that exact tag and GitHub-generated notes.

### stable tag

A pushed tag such as `v1.2.3` is classified as `stable`. It receives a new complete build from the
stable tagged commit. After all four builds succeed, the release job reuses those exact archives,
generates checksums, and publishes a normal GitHub Release. RC and stable builds remain distinct.

The Actions artifact names are:

- `ComicAPNG-Windows-x64`
- `ComicAPNG-Linux-x64`
- `ComicAPNG-macOS-x64`
- `ComicAPNG-macOS-arm64`

Each artifact contains the correspondingly named `.zip` or `.tar.gz` archive listed in Section 2.
Artifacts are retained for 14 days. The release job verifies and reuses exactly the four archives
produced by the completed build matrix before generating `SHA256SUMS.txt`.

Workflow-level, policy-job, and build-job permissions are `contents: read`. The tag-gated release
job alone receives `contents: write` and publishes through GitHub CLI with the repository-provided
`GITHUB_TOKEN`.

Concurrency groups ordinary runs by ref and permit obsolete non-tag runs to be cancelled. Every
tag gets a separate `release-<ref>` group, and tag runs set `cancel-in-progress` to false. This
isolates RC and stable release builds from branch activity.

## 18. Release Tag Grammar

Stable releases use exactly:

```text
^v[0-9]+\.[0-9]+\.[0-9]+$
```

Release candidates use exactly:

```text
^v[0-9]+\.[0-9]+\.[0-9]+-rc\.[0-9]+$
```

Examples are `v1.2.3` and `v1.2.3-rc.1`. These exact forms enter the release path. Other `v*` forms
fail the release-policy job with a clear diagnostic before the four-platform matrix starts, and
tags outside the `v*` pattern remain outside this workflow's tag trigger.

## 19. Release Procedure

The recommended sequence is:

The application-version update and validation steps are defined in the
[version bump and release SOP](version-bump-sop.md). Complete that SOP and merge the version-bump
commit before creating either an RC or stable tag.

1. Develop through pull requests and merge approved changes into `main`.
2. Open GitHub Actions, select **Build ComicAPNG**, run `workflow_dispatch` on `main`, download all four artifacts, and test the relevant native binaries.
3. Ensure the intended release commit is present on current `main`.
4. Create and push an annotated RC tag:

   ```sh
   git switch main
   git pull --ff-only origin main
   git tag -a v1.2.3-rc.1 -m "ComicAPNG v1.2.3 RC1"
   git push origin v1.2.3-rc.1
   ```

5. Download and test the generated prerelease assets. If changes are needed, merge them and create the next tag, such as `v1.2.3-rc.2` or `v1.2.3-rc.3`.
6. After an RC is accepted, make sure the desired commit is on current `main`, then create and push the stable tag:

   ```sh
   git switch main
   git pull --ff-only origin main
   git tag -a v1.2.3 -m "ComicAPNG v1.2.3"
   git push origin v1.2.3
   ```

7. GitHub Actions rebuilds all platforms from the stable tagged commit and publishes a normal release from those new archives.

RC and stable assets remain separate. Published release tags are immutable. When a tag is rejected,
inspect the diagnostic, correct the release state, and create the appropriate new tag.

## 20. Tests

The automated suite covers:

- APNG frame order, timing, transparency, full-canvas controls, and LRU bounds.
- Fixed-canvas geometry, proportional enlargement, centering, and transparent padding.
- Generic APNG extraction, numeric naming, overwrite safety, and geometry restoration.
- Independent EXIF, PNG text, private metadata, malformed JSON, and Unicode round trips.
- Natural filename ordering and content-based image validation.
- Three-decimal duration controls, default values, and one-second steps.
- Single-main-window architecture, dark-theme transparency, and icon policy.
- Plugin API DTO and manifest validation, host discovery, explicit IPC, and cancellation.
- Mocked network-backed source discovery, details, page groups, ordered five-page materialization,
  conversion to ordinary editable pages, manual order independence, cover retrieval, missing files,
  empty manifests, dependency failure, and partial failures.
- Model moves forward, backward, first-to-last, last-to-first, adjacent, no-op, multi-page block, identity, and cover preservation.
- Qt Create actions for an internal `QDropEvent`, arbitrary drag requests, before/after drop boundaries, multi-selection retention, Move Up, Move Down, Move to Top, Move to Bottom, and disabled boundary states.
- Deterministic ten-page source-to-document-to-APNG readback covering manual Create order, cover
  normalization, per-page identity, varied dimensions, proportional fixed-canvas rendering, and
  transparent padding.
- Window position/normal geometry/maximized persistence and changed-screen off-screen fallback.
- Generic and ComicAPNG APNG import, one-frame APNG recognition, static-PNG rejection, normal page reordering, metadata/source round trips, and owned workspace replacement.
- ZIP byte/format preservation, numeric names, valid metadata order, generic and source-specific
  metadata round trips, missing/unexpected/renamed page invalidation, mismatch recovery choices,
  malformed/absent metadata, traversal rejection, corrupted archives, and resource limits.
- ASCII primary-source and project-wide no-emoji policies.
- CI triggers, exact matrix/artifacts, permissions, event gating, valid RC/stable tags, malformed tags, checksum creation, and artifact reuse.

Ruff runs in both local build scripts and CI. Packaging checks validate source resources before PyInstaller and embedded runtime resources afterward. Native frozen applications are smoke-tested with Qt's offscreen platform.

## 21. Current Constraints

- Automated macOS builds use ad-hoc signatures and may trigger Gatekeeper.
- Native distribution targets Windows x64, Linux x64 with an Ubuntu 22.04 baseline, macOS Intel,
  and macOS Apple Silicon. The two macOS architectures ship as separate applications.
- Current distribution formats are native ZIP and tar.gz archives.
- Reader navigation is manual.
- Valid ComicAPNG geometry metadata enables original-page-dimension restoration.
- Very large pages and long comics can consume substantial memory and disk space despite bounded caches and streaming compression.
- Full-canvas lossless APNG output can be much larger than JPEG-based comic-book archives.
- Source modules run as trusted application components; process isolation targets stability and
  cancellation recovery.
- Some upstream network stages may continue through the cancellation grace period, after which the
  application terminates and lazily restarts the Plugin Host.
- Normal CI uses mocks and the deterministic source. Live network-backed discovery and
  materialization run through explicit authorized manual or opt-in tests.
