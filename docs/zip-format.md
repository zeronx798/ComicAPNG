# ComicAPNG ZIP Exchange Format v1

ComicAPNG ZIP is a small, human-inspectable serialization of the unified document model. An
archive contains ordinary image files at its root and an optional `metadata.json` file. The format
is source-independent, database-free, and compatible with standard ZIP extraction tools.

## Layout

ComicAPNG-generated archives use the current editable page order and deterministic, non-padded
filenames. The extension describes the stored image bytes.

```text
1.jpg
2.png
3.webp
metadata.json
```

JPEG, PNG, WebP, BMP, and TIFF input bytes are retained byte-for-byte when Pillow identifies their
format safely. Other decoded image formats are normalized to PNG.

## metadata.json

The root object is versioned. Empty optional fields are omitted. This example shows all principal
v1 categories:

```json
{
  "format": "ComicAPNG",
  "version": 1,
  "book": {
    "reading_direction": "rtl",
    "cover_duration_ms": 10000,
    "body_duration_ms": 5000,
    "text": {
      "Title": "Example"
    }
  },
  "source": {
    "plugin_id": "org.comicapng.source.example",
    "resource_id": "resource-123",
    "data": {
      "tags": [
        "source-tag"
      ]
    }
  },
  "pages": [
    {
      "filename": "1.jpg",
      "source_width": 800,
      "source_height": 1200,
      "duration_ms": 750,
      "source": {
        "source_page_index": 1,
        "source_id": "page-1"
      }
    },
    {
      "filename": "2.png",
      "source_width": 1200,
      "source_height": 800
    }
  ],
  "cover": "2.png"
}
```

`book` contains document-wide settings and user metadata. `source` contains optional JSON-only
source identity and data. The example `plugin_id` is intentionally generic; real modules may store
source-specific identifiers in `plugin_id`, `resource_id`, or `data`. Readers preserve validated
values strictly as provenance.

Each item in `pages` is bound to exactly one archive image by its exact filename. `cover` is also an
exact page filename reference. Per-page duration, dimensions, and source information are
page-bound.

## Import trust rules

An archive containing supported images only is imported in natural filename order as a normal
image-only document.

When page metadata is present, the complete declared filename set must exactly equal the complete
set of supported image entries. Metadata order may differ from natural order and becomes the
editable order after a valid match. Matching is exact and case-sensitive.

One missing, renamed, duplicated, or unexpected image marks every page-bound and page-reference
field untrusted as a unit. The review dialog lists found, referenced, missing, unexpected, and
invalid references. The available choices are trusted document/source metadata with natural-order
images, image-only import, or cancellation with the current document preserved.

Readable images remain available for image-only import when metadata is malformed or unsupported.
ComicAPNG reports the metadata problem before the import choice.

## Security and limits

ComicAPNG processes archive entries individually. It validates every entry name, rejects absolute
paths, parent traversal, backslash paths, drive-qualified paths, duplicate names, and encrypted
image entries, and copies only recognized images into application-owned sequential working files.
Unrelated files such as README files, `.DS_Store`, and `Thumbs.db` are ignored as page content.

The v1 implementation inspects both declared and actual copied sizes and applies these limits:

- 10,000 archive entries;
- 512 MiB per entry;
- 2 GiB total uncompressed data;
- 8 MiB for `metadata.json`.

The temporary image workspace remains owned by the Create/Edit document. Reordering changes only
the document's ordered page collection. Replacing or cancelling an import and exiting the
application clean the owned workspace.
