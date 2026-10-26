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

Supported preset IDs: `mirror`, `coupling`, `pbs`, `rotation`, `translation`,
`iris`, `slit`, `roof`. Purchased mounts are also available directly through
`create(part_number, label)` for every part in the native-height table below.
These return ordinary reusable `Component` objects with `VendorPart` definitions.
Unknown parameters fail explicitly. Dimensions use mm.

```python
lens_mount = lab_catalog.create('POLARIS-L1G', 'Lens mount')
mirror = lab_catalog.create('mirror', 'M1', mount='MHV-25.4L-R', thickness=3)
waveplate = lab_catalog.create('rotation', 'HWP', mount='FBR',
                              thickness=1, retardance=0.5, fast_axis_angle=45)
slit = lab_catalog.create('slit', 'Entrance slit', slit_width=1.0)
coupler = lab_catalog.create('coupling', 'Output')  # POLARIS-K05T6
legacy = lab_catalog.create('coupling', 'Legacy output', mount='KA05TA')
```

Mirror defaults remain POLARIS-K05VS2, Ø12.7 × 3 mm. Select POLARIS-K1VS2,
MHV-12.7L-R or MHV-25.4L-R to derive optic diameter and front/rear seating from
the selected mount. MHV parts are the rear-loading family, not VMHV.
Rotation defaults to ELL16 with its HOM holder. FBR uses the same generic
half-inch waveplate and Jones behavior without that holder; thickness must be
positive and no greater than 4 mm. `retardance` is in waves and
`fast_axis_angle` is in degrees. Iris accepts `aperture_diameter` (default 0.5).
Changing optic thickness changes the nominal assembly and requires fit checking.

Contracts are immutable dataclasses with versioned JSON serialization. Frames are directly component-local, in millimeters and fixed XYZ degrees. Optical frames use local +X along the beam; seating/interface frames use local +Z for the outward normal, and hole frames use local +Z for the hole axis. DOF axes are unit vectors in their named frame. `limits=None` means unknown; it never means zero travel. DOFs describe capabilities and affected parts, not exact pivots. `report_dofs(component, relative_to=layout)` expresses axes in the requested layout without changing any placements. FreeCAD shows read-only `AvailableDOFs` and `ComponentContract` properties.

Commercial thread designations are explicit and independent of the global metric/imperial preference. Fastener CAD uses nominal clearance envelopes, with thread specifications in metadata. Generic fasteners are labeled as such, not assigned fabricated manufacturer part numbers.

## Assemblies and scope

| ID | Contents | DOFs |
|---|---|---|
| mirror | Generic Ø12.7 × 3 mm mirror; POLARIS-K05VS2 | Tip, tilt |
| coupling | F260FC-1550; AD1109F; POLARIS-K05T6 (KA05TA optional); supplied rings accounted for | Tip, tilt, axial translation |
| pbs | Generic 12.7 mm PBS; displacement center-piece support patch with register relief trenches | Fixed |
| rotation | Generic Ø12.7 mm waveplate; ELL16/HOM holder or FBR | Optical-axis rotation |
| translation | XR25C, nominal payload attachment frame | Stage-axis translation |
| iris | Fabricated fixed aperture plate; two round dowel mounting holes | Fixed |
| slit | VA100 variable slit; fabricated 10 mm support; three nominal screws | Slit width (optical parameter) |
| roof | HRS1015-P01; integral baseplate supports and removable M2 clamp | Fixed; horizontal/vertical construction orientation |

The [roof mirror](roof-mirror.md) supports both horizontal and upward vertical
returns, with configurable nominal `beam_separation` (default 12.7 mm).
`create('HRS1015-P01', label, ...)` returns the purchased optic alone;
`create('roof', label, ...)` includes its integral support design, removable clamp and M2 screw. Both use explicit
finite reflections and separate input/output datums. Native input
heights above the source plate reference are 12.7 mm horizontally and 6.35 mm
vertically at default spacing. The supplied support bodies are unioned into
the baseplate, with one M2 x 0.4 clamp tap each.
`BeamPath.measure_component_pass()` reports the actual front-to-front path and
OPL; its nominal air path is 25.4 mm. Rebuild both integral orientations with
`examples/roof_mirror.py`.

The PBS support is an explicitly bounded patch of the displacement mount’s main center piece, not a newly qualified stand-alone bolt-on holder. Baseplates, fibers, cables, controllers and stage payloads remain separate. BOM mounting-hardware requirements identify plate screws and pins; VA100 also includes nominal screw geometry. No optical coupling-efficiency model is inferred from the mechanical collimator model.

The coupling uses the user-selected thread-end datum: the F260FC-1550 M11 thread-end plane aligns with the AD1109F opening, 2.9972 mm behind the collimator front. This is a measured nominal placement convention, not a claim of bottoming against the internal shoulder.

The coupling preset removes the front **POLARIS-SM05RR** from K05T6, retaining
the rear ring. The BOM records the removed ring as an unused included accessory.
The explicit KA05TA option removes its own front SM05KRR. Solid indices and
mounting patterns are measured independently for each mount. The AD1109F shoulder
sits at assembly X=8.0518 mm; the established collimator insertion is unchanged.
K05T6 and AD1109F simplified SM05 envelopes overlap about 4.0825 mm³ within the
thread engagement annulus (radius 6.4516–6.795 mm, X=8.0518–11.2268 mm).
Acceptance excludes interference outside this region. Physical thread phase,
torque and engagement under load remain unverified.

## Native heights and VA100 support

Heights are measured from the selected mounting face to the optical datum.
There is no common-height constraint or compensating spacer.

| Purchased part | Native height (mm) | Assembly height on plate (mm) | Plate operations |
|---|---:|---:|---|
| POLARIS-L05G | 12.7 | 12.7 | 1 M4 + 2 dowel bores |
| POLARIS-L1G | 19.05 | 19.05 | 1 M4 + 2 dowel bores |
| POLARIS-K1VS2 | 25.4 | 25.4 | 1 M4 + 2 dowel bores |
| MHV-12.7L-R | 12.7 | 12.7 | 2 M4 + 2 dowel bores |
| MHV-25.4L-R | 25.4 | 25.4 | 3 M4 + 2 dowel bores |
| FBR | 14.3002 | 14.3002 | 2 receiving bores for included Ø3.175 mm pins |
| VA100 | 17.78 | 27.78 with bracket | 2 M4; central slit screw ends in VA100 |
| POLARIS-K05T6 | 12.7 | 12.7 | 1 M4 + 2 dowel bores |

FBR's measured 14.3002 mm corresponds to the drawing's rounded 14.3 mm.
Its included SM05RR is positioned against the selected optic in a static working
copy. Its 3.20 mm × 5 mm plate bores are a custom nominal clearance selection;
the source drawing supplies no receiving-hole fit tolerance. Its pins remain
purchased solids, rather than being described as holes in the component contract.

`slit_width` accepts finite values from 0 to 6 mm, including fully closed.
The ideal interface clips along component-local Z, rotating with the component,
inside the existing finite entrance field. It transmits or terminates ray
centers without diffraction or Gaussian clipping calculations. Supplier VA100
CAD remains at its reference opening, measured as 5.8928 mm; `slit_width` changes
only the optical interface. Blade/linkage motion is not modeled. Bare
`create('VA100', label)` returns the purchased reference part without a bracket
or configured optical interface; use `create('slit', ...)` for the assembly.

`VA100Bracket` reuses `Surface_Adapter`: thickness 10 mm, footprint 37 × 56.8 mm,
providing at least 3 mm around the 9.652 × 50.8 mm measured seating footprint.
Two M4 clearance holes are 25 mm apart along X, with accessible top counterbores.
An underside counterbore accepts a nominal 8-32 × 3/8-inch screw into the VA100's
6.35 mm-deep 8-32 attachment. Install this screw before attaching the bracket to
the plate. Nominal engagement is 3.925 mm. Two M4 × 12 mm plate screws provide
6.4 mm engagement. The bracket contract describes three clearance holes; its
plate drilling footprint contains only the two M4 tap drills. Assembly contracts
record both native and bracket mounting faces; the review report records the
17.78 mm component height, 10 mm support and 27.78 mm total separately.

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
This demonstrates nominal alignment, not fiber coupling efficiency. The example now includes a machined baseplate with four M4 threaded mounting holes and eight 2 mm pin holes. The saved
native document includes the hardware, traced beam solids, contracts and BOM,
and reopens without the vendor asset cache; the Python example rebuilds the
live PyOpticL layout for editing.


## Integral machined baseplates

`lab_catalog.native_height(component)` derives the optical height from the selected
mounting face, including real bracket thickness. Place each component at its own
height above plate top Z=0, then call
`plate, machining = machined_baseplate.add(layout)` before recomputing. The plate
top is layout Z=0; thickness defaults to 12.7 mm and margin to 15 mm. Stock bounds
round outward to a 5 mm grid. The two-mirror example produces a 320 × 180 mm plate.

The selected mounting face sits directly on the plate. If its datum lies below
Z=0, a rectangular clearance pocket is machined down to that face; insufficient
remaining stock fails explicitly. A face above Z=0 is rejected rather than given
a spacer. The two-mirror example uses 12.7 mm mounts and requires no pockets. Side-facing KA05TA mounting holes are an
alternative mounting orientation and do not become holes in a horizontal plate.

Mounting coordinates are transformed from the pinned vendor CAD datums.
`baseplate_interfaces.json` and `batch_mounting_profiles.json` record independently
checked attachment patterns and drawing hashes. Shared `attachments.operations()`
builds both ordinary baseplate drill footprints and machined-plate operations,
including nested assembly placements. The plate uses explicit M4 × 0.7 threads in the
vendor's #8/M4 clearance holes: Ø3.3 mm tap drills, 10 mm straight drill depth,
8 mm nominal usable thread depth, with 118° drill tips. Thread helices are not
modeled; the thread designation is recorded in the read-only `MachiningPlan`.
The plate holes are threaded, while the purchased mount holes remain clearance
holes. Exact screw length/head selection is not yet included in the example BOM.

The original POLARIS-K05VS2 profile gets both pins: native X=-5 mm (round feature) and X=+5 mm
(slotted feature). The mating plate has two round Ø2.01 mm holes, 4.445 mm deep,
for 2 × 5 mm pins, following drawing revision C notes 1–2. Permitted diameter
range is 2.0066–2.02184 mm; depth tolerance is +0.0508/-0 mm. A pin projects
0.555 mm above the plate, within the mount's 1.905 mm blind depth. KA05TA has no
documented mating dowel pattern, so no pin holes are invented for it.

The batch profiles retain each part's own pin-hole recommendation. K05T6 uses
4.699 ±0.127 mm straight depth and Ø2.00914–2.02184 mm plate bores; its two
2 × 5 mm pins project 0.301 mm nominally. L05G and L1G use Ø2.002–2.008 mm
bores, with depths 4.699 and 4.318 mm respectively, each ±0.127 mm. K1VS2
uses 4.445 ±0.0508 mm depth and Ø2.00914–2.02184 mm bores. MHV profiles use
the compatible nominal 2 × 5 mm convention with 0.555 mm projection, explicitly
identified as a custom mating-plate selection rather than a vendor fit guarantee.
No holes are added to purchased geometry. `ComponentContract.holes` describes
component holes; machining operations describe distinct mating plate bores.

Machining plans include `optical_heights_mm` per mounting object and
`native_optical_heights_mm` for the selected support datum. The legacy scalar
`optical_height_mm` remains a number for uniform-height layouts and is `null`
for mixed heights. Contract serialization remains unchanged.

The displacement PBS support is fused into the plate as one solid. Its existing
clamp bore is recut after fusion so that the plate stock does not fill it. No
holder-attachment holes are added. `machining.integrated_names` identifies the
source support features for omission when exporting an assembly or BOM; the live
features are hidden where a GUI is present. `examples/integral_pbs_plate.py` writes a separate fused PBS demonstration,
exporting just the plate/support solid and the optic. The two-mirror example contains no PBS. ELL16 and translation baseplate attachments remain unsupported; FBR has its
own selected receiving-pin profile.

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

## Batch review and acceptance

Run `examples/component_batch.py` with FreeCAD's Python to generate eight native-height
samples, individual drilled plates (25 operations), contracts and BOMs in one
static `artifacts/component_batch.FCStd` review document. The companion
`component_batch.step` preserves solid geometry; `component_batch.report.json`
includes source measurements, heights, machining plans, BOMs and fit qualifications.
The saved document reopens without proxy classes or cache access. Rebuild the
editable source layout through the example script.

Run `tests/catalog/freecad_component_batch_acceptance.py` for source hashes,
valid solids, seats, reflection, FBR Jones behavior, slit width/orientation,
thread-envelope qualification, retaining-ring disposition, both plate workflows,
nested rotations/translations, recomputation and isolation. Existing catalog,
baseplate and fixed-iris suites remain regression requirements. See
[the batch verification report](component-batch-verification.md) for delivered results.


## One recessed plate with all new components

`examples/all_components_baseplate.py` builds a continuous folded path through
both lens mounts, the fixed iris, all three new mirror mounts, FBR and VA100,
with K05T6 input/output couplers. Every optical datum is **12.7 mm above the
unrecessed plate top**. Purchased parts retain their native dimensions and
mounting heights; the mounting surfaces are lowered into the plate.

```python
from examples.all_components_baseplate import build
review, report = build()  # 30 mm plate stock
# Optional output path and thickness, in millimeters:
# review, report = build('/absolute/path/demo.FCStd', plate_thickness=30.0)
```

The nominal stock is 395 × 255 × 30 mm, with 20 mm margins and 0.25 mm pocket
clearance. Recess depths are FBR 1.6002 mm, L1G 6.35 mm, K1VS2 and MHV-25.4L-R
12.7 mm, and the VA100 bracket 15.08 mm. There are no extra height-compensating
risers; VA100 retains its existing 10 mm bracket. The deepest drill leaves
3.9286 mm of stock. Insufficient stock fails before any export.

The 1550 nm trace has nine segments, three reflections and 760 mm total length.
The generic 2 mm-thick lenses use focal lengths 100 and 150 mm; they are ideal
thin lenses with cylindrical CAD envelopes, not selected vendor optics.
The iris diameter and slit width default to 2 mm. FBR carries a 1 mm half-wave
plate with its fast axis at 22.5°, producing linear 45° polarization in the
existing Jones model. Input waist radius 0.2 mm and power 1 mW are illustrative;
no fiber efficiency, diffraction or Gaussian clipping-loss model is implied.

Edit `PLACEMENTS` and the optical constants in the example; update
`EXPECTED_ROUTE` and the default-layout checks when changing the route or its
footprint. The height assignment and recess generation reuse existing component
contracts and `MachinedBaseplate`; this example adds no global placement solver.

Outputs are `artifacts/all_components_baseplate.FCStd`, hardware-only `.step`,
`all_components_baseplate_baseplate.step`, `.machining.json`, `.bom.json`,
`.report.json` and `.report.md`. The review has ten component groups, a drilled
plate, sixteen external nominal Ø2 × 5 mm pins and nine beam solids. FBR's two
supplied pins remain in its vendor compound. Thirty machining operations comprise
twelve M4 tap drills and eighteen pin bores. VA100 includes its nominal screws;
the other ten M4 mounting screws remain BOM requirements with installation
lengths unselected. Vendor `mounting_hardware` annotations are requirements,
not additional inventory quantities.

The editable source document remains open after `build()`. The static review
reopens without Python proxies or cache access; its groups retain contracts and
BOMs. In a GUI session the beam is red (false color for infrared). Headless
exports also retain intended colors as `DisplayColor` metadata. The hardware
STEP excludes the optical-only receiver and beam geometry.

The report carries forward VA100's fixed mechanical reference pose, qualified
SM05 thread-envelope overlap, FBR's custom receiving-bore selection, and the
small MHV source pose deviation. Recesses are nominal rectangular clearances;
no CAM/tool-access or physical manufacturing-fit certification is inferred.

```bash
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python examples/all_components_baseplate.py
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python tests/catalog/freecad_all_components_baseplate_acceptance.py
```
