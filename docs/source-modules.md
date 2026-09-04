# ComicAPNG Source Module Architecture

A source module is an input adapter. It lets ComicAPNG discover remote or generated resources and
bring them into the same document model used by local files and archive imports.

```text
Source module
      |
      v
Materialize resources
      |
      v
Document model
```

The application owns the document model, editor, APNG writer, and ZIP writer. Every materialized
resource follows this shared editing and export path.

## Responsibilities

A source module provides three kinds of behavior:

- **Resource discovery:** search or otherwise enumerate resources, then expose descriptive records
  and any available page groups.
- **Source metadata:** return stable source identifiers and optional descriptive data through
  ComicAPNG-owned transfer objects.
- **Document conversion:** materialize ordinary image resources in an application-provided
  workspace so the core-owned bridge can create editable pages and a document.

The current Plugin API v1 expresses these responsibilities through search, detail, chapter, cover,
and page-materialization operations. These names describe the existing page-oriented API while
the core remains source-neutral.

## Core-owned boundary

ComicAPNG owns the manifest schema and every data-transfer object that crosses the source boundary.
Implementation-specific objects remain inside the module. Plugin API v1 exposes fixed discovery,
metadata, and materialization operations, while Qt composition, application commands, document
ordering, and output writers remain core responsibilities.

Source operations run in the Plugin Host process, isolating failures from the GUI event loop and
providing a cancellation fallback. Source modules remain trusted application components.

## Manifest example

This generic placeholder illustrates the contract independently from bundled implementations:

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

Discovery validates identifiers, versions, entrypoints, capabilities, API compatibility, and
duplicate IDs before an implementation is loaded.

## Source metadata

Source provenance is optional JSON-only document data. A generic serialized example is:

```json
{
  "source": {
    "plugin_id": "org.comicapng.source.example",
    "resource_id": "resource-123",
    "data": {
      "source_ref": "reference-123",
      "tags": ["example-tag"]
    }
  }
}
```

Real modules may store source-specific identifiers or other JSON-compatible values in
`resource_id`, document-level `data`, and per-page source data. The core preserves validated values
strictly as provenance.

## Materialization and conversion

The application chooses each materialization directory. Returned page and cover paths must remain
inside it, exist, decode as supported images, and form a nonempty contiguous page sequence. Invalid
or partial results fail before a document reaches the editor.

The core source bridge then:

1. creates normal page records from the materialized resources;
2. uses source order only to establish the initial page list;
3. attaches optional document and page provenance;
4. proposes a cover when one is available;
5. validates and hands the ordinary document to Create/Edit or a common exporter.

## Built-in modules and future external plugins

Current source modules are built into the application package. Their manifests, implementations,
dependencies, and notices are shipped and validated with each release.

The deterministic Test Source is a built-in offline module used to exercise discovery,
materialization, conversion, ordering, export, cancellation, and frozen-package behavior.

JMComic is another built-in source module and an example implementation of the same architecture.
Its source-specific integration remains behind the adapter boundary, while the common core
supplies ComicAPNG's document model and output formats. Implementation notes live in the
[module README](../src/comicapng/extensions/jmcomic/README.md).

Built-in source modules and external plugins are separate extension types. The current architecture
stage packages built-in modules with the application. External plugin support is planned for a
future stage that defines discovery, installation, updates, dependency management, compatibility,
and trust for third-party code around the existing source contracts.
