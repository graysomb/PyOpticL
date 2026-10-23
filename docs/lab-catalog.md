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

Supported IDs: `mirror`, `coupling`, `pbs`, `rotation`, `translation`, `iris`. Rotation accepts `thickness` (default 1 mm) and `retardance` (default half-wave); these describe a generic half-inch waveplate, not a selected vendor optic. Mirror diameter is 12.7 mm and default thickness is 3 mm. Iris accepts `aperture_diameter` (default 0.5 mm). Other unknown parameters fail explicitly. Changing optic thickness changes the nominal assembly configuration and may require fit revalidation.

Contracts are immutable dataclasses with versioned JSON serialization. Frames are directly component-local, in millimeters and fixed XYZ degrees. Optical frames use local +X along the beam; seating/interface frames use local +Z for the outward normal, and hole frames use local +Z for the hole axis. DOF axes are unit vectors in their named frame. `limits=None` means unknown; it never means zero travel. DOFs describe capabilities and affected parts, not exact pivots. `report_dofs(component, relative_to=layout)` expresses axes in the requested layout without changing any placements. FreeCAD shows read-only `AvailableDOFs` and `ComponentContract` properties.

Commercial thread designations are explicit and independent of the global metric/imperial preference. Fastener CAD uses nominal clearance envelopes, with thread specifications in metadata. Generic fasteners are labeled as such, not assigned fabricated manufacturer part numbers.

## Assemblies and scope

| ID | Contents | DOFs |
|---|---|---|
| mirror | Generic Ø12.7 × 3 mm mirror; POLARIS-K05VS2 | Tip, tilt |
| coupling | F260FC-1550; AD1109F; KA05TA; supplied rings accounted for | Tip, tilt, axial translation |
| pbs | Generic 12.7 mm PBS; displacement center-piece support patch with register relief trenches | Fixed |
| rotation | Generic Ø12.7 mm waveplate; ELL16; HOM holder; four generic cage screws | Optical-axis rotation |
| translation | XR25C, nominal payload attachment frame | Stage-axis translation |
| iris | Fabricated fixed aperture plate; two round dowel mounting holes | Fixed |

The PBS support is an explicitly bounded patch of the displacement mount’s main center piece, not a newly qualified stand-alone bolt-on holder. External baseplates, fibers, cables, controllers, payloads, and their installation hardware are outside the component presets. No optical coupling-efficiency model is inferred from the mechanical collimator model.

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

For the current PBS, run `tools/verify_displacement_pbs.py` with `Data/Displacement setup/Displacement Mount Assembly.step`. The preset has four raised registers and three relief trenches; the blind Ø2.5 mm clamp attachment hole is retained. The plastic clamp and screw solids remain omitted because the displacement reference does not include them. The legacy HOM definitions remain available.

For independent legacy HOM custom-holder regression, run `tools/extract_hom_references.py` with the original HOM STEP and an output directory, then pass that directory to `tools/verify_hom_profiles.py`. The extractor checks the lab source hash before using labels to identify parts. Reference solids are validation inputs only; generated geometry uses editable rational sketch curves and extrusions.

See [the measurement report](reference-measurements.md) for precise evidence, comparison thresholds and remaining limitations. Do not treat this catalog as a manufacturing-tolerance or optical-performance certification.

## Two-mirror fiber link example

Run `examples/two_mirror_coupling.py` in FreeCAD (or with its bundled Python and
library path configured) to generate `artifacts/two_mirror_coupling.FCStd`.
It uses two catalog `coupling` assemblies and two catalog `mirror` assemblies.
The input coupler faces +X; the first mirror turns +X to +Y and the second turns
+Y back to +X toward the receiving coupler. Segment lengths are 120, 100 and
120 mm at a common optical height of 12.7 mm above the plate top. Edit `placements` to change the
layout, updating the expected-route checks accordingly.

The example uses PyOpticL's `BeamPath` and the mirror reflection interfaces.
An optical-only `Stop` at the receiving coupler's front datum terminates the
trace; it adds no hardware to the BOM. The 1550 nm beam's 0.75 mm waist radius
and 1 mW power are illustrative inputs, not measured collimator specifications.
This demonstrates nominal alignment, not fiber coupling efficiency. The example now includes a machined baseplate with four M4 threaded mounting holes and four 2 mm pin holes. The saved
native document includes the hardware, traced beam solids, contracts and BOM,
and reopens without the vendor asset cache; the Python example rebuilds the
live PyOpticL layout for editing.


## Integral machined baseplates

`PyOpticL.machined_baseplate.optical_height()` derives the 12.7 mm optical height
from the POLARIS mounting-face datum. Use this height for the layout, then call
`plate, machining = machined_baseplate.add(layout)` before recomputing. The plate
top is layout Z=0; thickness defaults to 12.7 mm and margin to 15 mm. Stock bounds
round outward to a 5 mm grid. The two-mirror example produces a 320 × 180 mm plate.

The selected mounting face sits directly on the plate. If its datum lies below
Z=0, a rectangular clearance pocket is machined down to that face; insufficient
remaining stock fails explicitly. A face above Z=0 is rejected rather than given
a spacer. Current POLARIS and KA05TA mounts both have a 12.7 mm optical height,
so the example requires no pockets. Side-facing KA05TA mounting holes are an
alternative mounting orientation and do not become holes in a horizontal plate.

Mounting coordinates are transformed from the pinned vendor CAD datums.
`baseplate_interfaces.json` records the independently checked attachment
pattern and drawing hashes. The plate uses explicit M4 × 0.7 threads in the
vendor's #8/M4 clearance holes: Ø3.3 mm tap drills, 10 mm straight drill depth,
8 mm nominal usable thread depth, with 118° drill tips. Thread helices are not
modeled; the thread designation is recorded in the read-only `MachiningPlan`.
The plate holes are threaded, while the purchased mount holes remain clearance
holes. Exact screw length/head selection is not yet included in the example BOM.

Each POLARIS mount gets both pins: native X=-5 mm (round feature) and X=+5 mm
(slotted feature). The mating plate has two round Ø2.01 mm holes, 4.445 mm deep,
for 2 × 5 mm pins, following drawing revision C notes 1–2. Permitted diameter
range is 2.0066–2.02184 mm; depth tolerance is +0.0508/-0 mm. A pin projects
0.555 mm above the plate, within the mount's 1.905 mm blind depth. KA05TA has no
documented mating dowel pattern, so no pin holes are invented for it.

The displacement PBS support is fused into the plate as one solid. Its existing
clamp bore is recut after fusion so that the plate stock does not fill it. No
holder-attachment holes are added. `machining.integrated_names` identifies the
source support features for omission when exporting an assembly or BOM; the live
features are hidden where a GUI is present. `examples/integral_pbs_plate.py` writes a separate fused PBS demonstration,
exporting just the plate/support solid and the optic. The two-mirror example contains no PBS. Rotation and translation baseplate attachments are rejected
until their installation profiles are independently verified.

`artifacts/two_mirror_coupling.machining.json` lists all drilling operations,
source hashes and selected threads. No optical-table attachment pattern is added.
Run `tests/catalog/freecad_baseplate_acceptance.py` in FreeCAD's bundled Python
for source-axis, seating, physical bore, recess, recompute and PBS-fusion checks.

## Fixed alignment iris

```python
from PyOpticL import lab_catalog, machined_baseplate
from PyOpticL.layout import Layout

layout = Layout('Iris layout')
iris = layout.add(lab_catalog.create('iris', 'Alignment iris', aperture_diameter=0.5),
                  (0, 0, 12.7), 0)
plate, machining = machined_baseplate.add(layout)
layout.recompute()
```

`lab_catalog.AlignmentIris(aperture_diameter=0.5)` also works as a normal
`Component` definition. Dimensions remain in mm in either unit preference.
The aperture diameter must be finite and strictly between 0 and 20 mm. It is
chosen when constructing the fixed plate; no adjustable blades are modeled.

The parametric body is 20 mm wide, 4 mm thick and 22.7 mm tall, with a flat
bottom and a radius-10 mm semicircular top. Local +X follows the beam, the
aperture center is the component origin, and the bottom is at local Z=-12.7 mm.
In a machined layout with plate top Z=0, place the component at Z=12.7 mm as
above. With an ordinary `library.Baseplate` using its default optical height,
place the iris at beam-plane Z=0; that plate's top is Z=-12.7 mm.

The bottom contains two round Ø2.05 mm holes at local `(0, ±5, -12.7)` mm,
each with 2 mm straight depth followed by a 118° drill tip. The descriptive
`ComponentContract.holes` records exactly these two holes in the iris.
The optical aperture is represented separately by `optical_reference` and a
`Stop` interface. This uses the existing ideal ray-center transmission rule
inside a 20 mm circular stop field; it does not calculate diffraction or
Gaussian power clipping, nor trace the body's full noncircular silhouette.

`drill()` instead returns exactly the **two mating baseplate bores**:
Ø2.01 mm, 4.445 mm straight depth, followed by 118° drill tips. It only drills
objects in the `baseplate` group. The iris itself ignores automatic drilling
from neighbors, including the beam's clearance envelope, to preserve its
aperture and blind holes. No mounting screw or clearance pocket is part of the
iris drilling footprint. `baseplate_profile()` returns a fresh profile using
the existing catalog structure, and both drilling workflows use those dimensions.
`MachinedBaseplate` also supports an iris-only layout and records exactly two
dowel operations for each iris. It retains the existing upright/seating checks.

Use Ø2 × 5 mm DIN 7-m6 / ISO 2338 pins: nominal projection is 0.555 mm above
the plate, within the iris's 2 mm straight blind depth. Plate-hole diameter
limits are 2.0066–2.02184 mm and depth tolerance is +0.0508/-0 mm, following the
existing catalog convention. The bore dimensions do not vary with aperture size.

The design is adapted from `Data/SPDC Mach Zhender V2/IRIS.step`.
`catalog_data/alignment_iris_reference.json` retains its SHA-256 and measured
dimensions. The source has four apertures and a round/slot mounting pattern;
this version has one centered aperture, a shorter body and two round holes.
The hash identifies that reference, not an exact match or a drawing approval
of the modified part. Runtime construction needs neither the STEP nor vendor CAD.

Run `examples/iris_on_baseplate.py` to generate `artifacts/iris_on_baseplate.FCStd`,
an assembly STEP, `alignment_iris.step`, and a machining JSON sidecar. The native
document contains static iris, baseplate and two pin features, plus the mounting
contract and machining plan. It reopens without Python proxies or a CAD cache.
The Python example rebuilds the parametric source layout for editing.

```bash
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python tests/catalog/freecad_iris_acceptance.py
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python examples/iris_on_baseplate.py
```
