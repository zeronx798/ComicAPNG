# ComicAPNG Architecture

ComicAPNG centers its architecture on documents. Input adapters produce page resources and
metadata; the core turns them into a common editable model; document services then edit or
serialize that model. The reader opens serialized PNG and APNG through a read-only document
abstraction.

```text
Local images / APNG / ZIP / source modules
                    |
                    v
         Import and materialization
                    |
                    v
        Unified editable document model
                    |
          +---------+---------+
          |                   |
          v                   v
        Editor          Export services
                              |
                    +---------+---------+
                    |         |         |
                    v         v         v
                  APNG       ZIP    Future formats
                    |
                    v
             Read-only document
                    |
                    v
                  Reader
```

The current reader opens PNG and APNG through a separate read-only `ApngDocument` abstraction.
This follows the same document-oriented product boundary while the editable `ComicBook` remains
the Create/Edit representation. Source modules integrate once at the import boundary.

## Document model

`ComicBook` is the current editable document implementation. It contains:

- an ordered collection of `ComicPage` records;
- document metadata, including optional generic source metadata;
- reading direction and default page durations;
- an optional cover identity.

Each page refers to a decoded image resource, records its dimensions, and may carry its own timing
or JSON-only source data. `ComicBook.pages` becomes the authoritative order as soon as an import
finishes. Original filenames, archive order, source chapter order, and source page indexes may
establish the initial sequence. Subsequent edits keep the document's chosen order authoritative.

Source provenance is optional descriptive data. The editor and exporters apply the same behavior
to every document.

## Import pipeline

All supported inputs cross a normalization boundary before editing:

1. The input adapter discovers and validates resources.
2. Images are identified and decoded as needed. APNG and ZIP imports, along with source-module
   operations, use application-managed workspaces; ordinary local files may remain referenced at
   their existing paths.
3. The importer or source bridge creates normal `ComicPage` records and a `ComicBook`.
4. Trusted document, page, and source metadata is attached as provenance independent from order.
5. The Create/Edit page receives the completed document only after validation and thumbnail
   preparation succeed.

Local files, APNG import, ZIP import, the deterministic test source, and network-backed source
modules therefore meet at the same model boundary. For source modules specifically, see
[Source Module Architecture](source-modules.md).

## Export pipeline

Exporters operate solely on a validated snapshot of the editable document and its current order.

- APNG export places the selected cover exactly once at the front, renders every page onto one
  fixed RGBA canvas, and writes standard APNG control and metadata chunks.
- ZIP export preserves current editable order, records the cover by filename, retains supported
  original image encodings where practical, and writes optional versioned `metadata.json`.
- A future format can consume the document model through another core-owned writer.

This dependency direction lets source modules, editor behavior, and output writers evolve
independently.

## Source boundary and future plugins

Source modules provide resource discovery, source metadata, and materialization into resources
that the core can convert into an editable document. The current release bundles its modules and
runs their operations through Plugin API v1 in a separate host process.

Bundled modules and future external plugins are distinct deployment concepts. External plugin
support belongs to a future architecture stage that adds explicit discovery, trust, compatibility,
dependency, installation, update, and lifecycle policies around the source boundary.

## Related documents

- [Source Module Architecture](source-modules.md)
- [Technical Specifications](tech-specs.md)
- [ZIP Exchange Format](zip-format.md)
