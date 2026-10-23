---
name: vendor-optics-cad
description: Locate exact Thorlabs or OptoSigma STEP models and engineering drawings, download or register browser downloads, and verify imported optical hardware against pinned assets in PyOpticL.
---

# Vendor optics CAD

Use exact part numbers, including connector, wavelength and metric suffixes. Find the official product page and confirm the selected variant before downloading. Never substitute a similar part or guess a download filename. Obtain both STEP and engineering drawing when offered.

Find the PyOpticL checkout in the active workspace. Run its downloader from the repository root:

```bash
python -m PyOpticL.vendor_cad discover --vendor thorlabs --part KA05TA --product-url https://www.thorlabs.com/item/KA05TA
```

Use `--vendor optosigma` for OptoSigma. Public links may be absent on dynamic pages; this is an expected `browser_required` result, not evidence that CAD is unavailable. Use the product page's support downloads. Register the downloaded file:

```bash
python -m PyOpticL.vendor_cad register --vendor thorlabs --part KA05TA --product-url https://www.thorlabs.com/item/KA05TA --file /absolute/path/KA05TA-Step.step --kind step --manifest /absolute/path/KA05TA.step.json
```

For an explicit official download URL use `download --asset-url URL` with the same identity options. For opaque vendor filenames add `--document-id` only after confirming the document-to-part association on the page. Record the vendor filename and revision, never infer a revision from the retrieval date. Register the PDF separately using `--kind pdf`. Do not overwrite a pinned manifest on revision changes: create a new revision and reverify datums.

Run `verify --manifest FILE` to check the content and hash. Import STEP with FreeCAD, check units against the drawing, validate solids, and record optical axes, seating planes, hole centers/types/depths and their source. Save independent measurements before implementing geometry. Preserve vendor solids at their nominal position and store normalization transforms separately. Do not split assemblies into moving bodies.

A successful download is not a verified assembly. Distinguish downloaded, imported, datum-verified, and assembly-verified status. Use 0.01 mm and 0.01 degrees for CAD regression, documenting lower-precision exceptions. Keep original assets in the local content-addressed cache and commit provenance/hash manifests, not unreviewed replacements. Report missing drawings, uncertain datums, or insufficient fit evidence explicitly.
