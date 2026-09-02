# ComicAPNG ZIP Exchange Format v1

ComicAPNG ZIP is a deliberately small, human-inspectable exchange format. An archive contains
ordinary image files at its root and an optional `metadata.json` file. It does not contain a
database and does not require ComicAPNG to extract it.

## Layout

ComicAPNG-generated archives use the current editable page order and deterministic, non-padded
filenames. The extension describes the stored image bytes.

```text
1.jpg
2.png
3.webp
metadata.json
```

JPEG, PNG, WebP, BMP, and TIFF input bytes are retained without image re-encoding when Pillow
identifies their format safely. A format that cannot be retained is normalized to PNG.

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
source identity and data. Each item in `pages` is bound to exactly one archive image by its exact
filename. `cover` is also an exact page filename reference. Per-page duration, dimensions, and
source information are page-bound.

## Import trust rules

When `metadata.json` is absent, supported images are imported in natural filename order. This is a
normal import and produces no warning.

When page metadata is present, the complete declared filename set must exactly equal the complete
set of supported image entries. Metadata order is allowed to differ from natural order and becomes
the editable order after a valid match. Matching is case-sensitive and does not use fuzzy repair.

One missing, renamed, duplicated, or unexpected image invalidates every page-bound and
page-reference field as a unit. ComicAPNG does not partially apply a matching prefix and does not
offer a force option. The review dialog lists found, referenced, missing, unexpected, and invalid
references. The user may then import only trusted book/source metadata, import images without any
metadata, or cancel without changing the current document.

Malformed or unsupported metadata never makes otherwise readable images unusable. ComicAPNG
reports the metadata problem and offers image-only import.

## Security and limits

ComicAPNG does not call `extractall`. It validates every entry name, rejects absolute paths,
parent traversal, backslash paths, drive-qualified paths, duplicate names, and encrypted image
entries, and copies only recognized images into application-owned sequential working files.
Unrelated files such as README files, `.DS_Store`, and `Thumbs.db` are ignored as page content.

The v1 implementation inspects both declared and actual copied sizes and applies these limits:

- 10,000 archive entries;
- 512 MiB per entry;
- 2 GiB total uncompressed data;
- 8 MiB for `metadata.json`.

The temporary image workspace remains owned by the Create/Edit document. Reordering changes only
the `ComicBook.pages` list. Replacing or cancelling an import and exiting the application clean the
owned workspace.
