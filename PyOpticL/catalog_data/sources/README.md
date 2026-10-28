# Versioned CAD sources

This directory contains the original bytes required to build and independently
verify the lab catalog from a Git checkout. These are ordinary Git files, not
Git LFS pointers. No download, home-directory cache, sibling `Data/` directory,
or original `Downloads/` file is required.

Files use `objects/<sha256>/source.step` or `source.pdf`. The existing
`cache_path` manifest field is the relative object key in this directory; its
name is retained for schema-1 compatibility. Identical source bytes are stored
once. `.gitattributes` preserves their bytes across platforms and treats CAD
changes as binary diffs.

- `../assets/*.json`: 44 vendor STEP/drawing records covering 22 parts.
- `../source_references.json`: 10 original CAD/document references, including
  the iris, HOM, displacement PBS, corrected roof supports, and grating datasheet.
- Combined: 54 records referencing 53 files, 211,366,914 bytes (about 211 MB
  before Git compression). The largest file is about 35 MB.

Source hashes, original vendor filenames, URLs, revisions, measurements, and
normalization remain in their existing records. Historical source names in
those records are provenance, not paths that a rebuild must find elsewhere.
Original geometry is unchanged; custom components still rebuild from Python
and the versioned parametric profiles.

Verify every source without accessing the cache or network:

```bash
python3 -m PyOpticL.vendor_cad verify --all
```

Resolution uses these versioned bytes first and fails on a hash mismatch. A
missing file may fall back to the old `~/.cache/pyopticl/cad` store (or
`PYOPTICL_CAD_CACHE`) for backward compatibility. `verify --all` requires the
repository copy of every file and never accepts that fallback. An explicit
`resolve(..., root=...)` or CLI `verify --cache ...` checks that particular store.

New `register`/`download` acquisitions write here by default, so Git can track
the source along with its manifest. `--cache` or `PYOPTICL_CAD_CACHE` can select
an external acquisition store. Before committing a catalog addition, verify
and add its source object and manifest together. Never repin existing records
to changed bytes without rechecking their CAD datums.

Generated assemblies, STEP exports, and verification BREP intermediates remain
rebuildable artifacts under `artifacts/` or a selected output directory.
