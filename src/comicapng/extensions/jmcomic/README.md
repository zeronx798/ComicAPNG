# JMComic Source Module

JMComic is one built-in source module and an example implementation of ComicAPNG Plugin API v1.
It adapts the `jmcomic` dependency inside the Plugin Host to provide resource discovery, source
metadata, and materialized page images through ComicAPNG-owned data-transfer objects.

After materialization, the common source bridge creates an ordinary editable document. This module
uses the common editor, document model, APNG encoder, and ZIP archive format. The core application
continues to provide local import, editing, reading, and export through those shared components.
