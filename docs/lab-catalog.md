# Lab component catalog

The catalog extends the existing `Component` definition protocol. `definition.contract()` is optional. Existing `shape()`, `drill()`, `interfaces()`, `subcomponents()`, `mount_definition`, and `mount_offset` continue to work. No motion simulation, adjustment controls, kinematic solver, or motor commands are introduced.

```python
from PyOpticL import lab_catalog
mirror = lab_catalog.create('mirror', 'M1', thickness=3)
coupler = lab_catalog.create('coupling', 'Fiber input')
mirror.recompute()
coupler.recompute()
print(coupler.contract().to_dict())
print(lab_catalog.report_dofs(coupler))  # world axes
print(lab_catalog.bom(coupler))
```

Supported IDs: `mirror`, `coupling`, `pbs`, `rotation`, `translation`. Rotation accepts `thickness` (default 1 mm) and `retardance` (default half-wave); these describe a generic half-inch waveplate, not a selected vendor optic. Mirror diameter is 12.7 mm and default thickness is 3 mm. Other unknown parameters fail explicitly. Changing optic thickness changes the nominal assembly configuration and may require fit revalidation.

Contracts are immutable dataclasses with versioned JSON serialization. Frames are directly component-local, in millimeters and fixed XYZ degrees. Optical frames use local +X along the beam; seating/interface frames use local +Z for the outward normal, and hole frames use local +Z for the hole axis. DOF axes are unit vectors in their named frame. `limits=None` means unknown; it never means zero travel. DOFs describe capabilities and affected parts, not exact pivots. `report_dofs(component, relative_to=layout)` expresses axes in the requested layout without changing any placements. FreeCAD shows read-only `AvailableDOFs` and `ComponentContract` properties.

Commercial thread designations are explicit and independent of the global metric/imperial preference. Fastener CAD uses nominal clearance envelopes, with thread specifications in metadata. Generic fasteners are labeled as such, not assigned fabricated manufacturer part numbers.

## Assemblies and scope

| ID | Contents | DOFs |
|---|---|---|
| mirror | Generic Ø12.7 × 3 mm mirror; POLARIS-K05VS2 | Tip, tilt |
| coupling | F260FC-1550; AD1109F; KA05TA; supplied rings accounted for | Tip, tilt, axial translation |
| pbs | Generic 12.7 mm PBS; HOM integral support patch; removable clamp; generic M3 screw | Fixed |
| rotation | Generic Ø12.7 mm waveplate; ELL16; HOM holder; four generic cage screws | Optical-axis rotation |
| translation | XR25C, nominal payload attachment frame | Stage-axis translation |

The PBS support is an explicitly bounded patch of the original integral base, not a newly qualified stand-alone bolt-on holder. External baseplates, fibers, cables, controllers, payloads, and their installation hardware are outside the five presets. No optical coupling-efficiency model is inferred from the mechanical collimator model.

The coupling uses the user-selected thread-end datum: the F260FC-1550 M11 thread-end plane aligns with the AD1109F opening, 2.9972 mm behind the collimator front. This is a measured nominal placement convention, not a claim of bottoming against the internal shoulder.

The coupling preset removes the **front SM05KRR** from the installed KA05TA solid compound. The BOM retains it as an unused included accessory; the rear ring remains in its vendor position. Vendor adjusters and internal hardware remain static compounds, not articulated bodies. `bom()` lists separately instantiated optics, mounts, adapters, supports and external fasteners, and records included rings without requiring a second purchase.

## Assets and acquisition

Runtime assets are in `~/.cache/pyopticl/cad`, or `PYOPTICL_CAD_CACHE`. Git contains hash manifests, normalization transforms, reference measurements and parametric sketch profiles. Missing or changed cache objects fail before geometry is used; the catalog never silently fetches a different revision. Original STEP solids remain untouched in the cache. Normalization is in `PyOpticL/catalog_data/normalization.json`.

```bash
python -m PyOpticL.vendor_cad discover --vendor thorlabs --part KA05TA --product-url https://www.thorlabs.com/item/KA05TA
python -m PyOpticL.vendor_cad register --vendor thorlabs --part KA05TA --product-url https://www.thorlabs.com/item/KA05TA --file /absolute/path/KA05TA-Step.step --kind step --manifest /absolute/path/new-revision.json
python -m PyOpticL.vendor_cad verify --manifest PyOpticL/catalog_data/assets/KA05TA.step.json
```

Use `download --asset-url OFFICIAL_URL` for explicit file links, `--kind pdf` for drawings, and `--document-id` for a page-confirmed opaque filename. Thorlabs and OptoSigma official domains are supported. Dynamic pages return `browser_required`; download through their public UI, then register. Acquisition validates file contents, stores SHA-256 and retrieval time, and refuses replacing a manifest with a different asset hash. CAD import and dimensional checks remain separate from file validation. STEP revision is unknown unless explicitly identified; a drawing revision is not automatically the STEP revision.

Versioned skills are in `skills/vendor-optics-cad` and `skills/thorlabs-connect-parts`, with discoverable installed copies in `~/.codex/skills`. Their scope is exact assets and documented connections, not optical suitability or motion control.

## Demonstration and validation

Run `examples/lab_catalog_demo.py` in FreeCAD or its bundled Python. It writes `artifacts/lab_catalog.FCStd`, an ordinary static document that reopens without Python proxy classes or access to the asset cache. It includes component metadata and assembly BOM properties.

On this Mac, the tested commands are:

```bash
python3 -m unittest discover -s tests/catalog -p 'test_*.py' -v
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python tests/catalog/freecad_acceptance.py
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python examples/lab_catalog_demo.py
```

For independent custom-holder regression, run `tools/extract_hom_references.py` with the original HOM STEP and an output directory, then pass that directory to `tools/verify_hom_profiles.py`. The extractor checks the lab source hash before using labels to identify parts. Reference solids are validation inputs only; generated geometry uses editable rational sketch curves and extrusions.

See [the measurement report](reference-measurements.md) for precise evidence, comparison thresholds and remaining limitations. Do not treat this catalog as a manufacturing-tolerance or optical-performance certification.
