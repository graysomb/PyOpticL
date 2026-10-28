# Crystal holder and separate bracket

```python
from PyOpticL import lab_catalog, machined_baseplate
from PyOpticL.layout import Layout

layout = Layout('Crystal assembly')
holder = layout.add(lab_catalog.create('crystal_holder', 'Crystal'), (0, 0, 12.7), 0)
plate, machining = machined_baseplate.add(layout)
layout.recompute()
```

`crystal_holder` contains all six unchanged solids from the supplied
`Crystal holder.step`, a separate fabricated bracket, four holder screws and flat
washers, two plate screws, and two locating pins. `crystal_holder_bare` returns
the original six-part assembly; `crystal_bracket` returns the new bracket alone.
These definitions accept no geometry overrides. In the schematic editor, choose
**Crystal holder**, with **Crystal holder + support bracket** or **bare**.
Bounds, packing and Python export use the same complete part definition.

## Source datums

The crystal is 4 × 27.4 × 1 mm in source coordinates, centered at (0, 0, 3.5).
Source +Y, its long axis, becomes component +X; source +Z remains upright.
Component origin and optical datum are at the crystal center. Input/output
datums are X=-13.7/+13.7 mm. The source plate underside is Z=-3.5 mm.
The source's original clips and spacers retain their relative positions.
Its clip fasteners are not present in the supplied STEP and are not inferred.

The uploaded bytes are pinned by SHA-256 in `source_references.json` and bundled
in `catalog_data/sources`. Runtime rebuilds do not need Downloads or the sibling
Data directory. `crystal_holder_reference.json` records source solid identities,
volumes, normalization, measured holes and the new bracket's dimensions.

## Bracket and fastening

The bracket is 44 × 50 × 9.2 mm, placing the optical axis 12.7 mm above its
baseplate seating face. It remains a separate removable part. The original
holder is neither modified nor fused into the baseplate.

All four original through holes attach the holder to the bracket. Their
asymmetric pattern is measured from the supplied STEP:

| Source XY (mm) | Component XY (mm) | Source bore | Washer seat, source Z | Holder screw |
|---|---|---|---|---|
| (-8.5, -10.5) | (-10.5, 8.5) | Ø2, through 5 mm, conical Ø4 mouth | 5 mm, plate top | M1.6 × 10 |
| (-8.5, 10.5) | (10.5, 8.5) | Ø2, through 5 mm, conical Ø4 mouth | 5 mm, plate top | M1.6 × 10 |
| (8.5, -10) | (-10, -8.5) | Ø2.2, through 3 mm, beneath lateral clip slot | 5 mm, clip top | M1.6 × 10 |
| (8.5, 10.5) | (10.5, -8.5) | Ø2, through 3 mm, conical Ø4 mouth | 3 mm, lower plate shelf | M1.6 × 8 |

The STEP establishes no thread standard. These four nominal M1.6 screws pass
through the existing bores into **new** M1.6 × 0.35 bracket taps. Four
Ø5/Ø1.8 × 0.5 mm flat washers seat on the corresponding plate or clip surface.
The slotted-corner screw also retains the lateral clip. The shorter screw
matches the lower shelf. All four have 4.5 mm nominal bracket engagement.
Bracket tap-drills are Ø1.25 × 6 mm straight depth, with 118° tips and 5 mm
nominal usable thread.

Two M4 × 12 mm plate screws sit outside the holder at component (0, ±20) mm.
Bracket clearances are Ø4.5 mm, counterbored Ø7.5 × 4.4 mm from the top.
Nominal plate engagement is 7.2 mm. Holder and plate screw heads are accessible
from above. Fastener shapes are smooth nominal envelopes; manufacturer-specific
head details and manufactured fit remain unverified.

Two Ø2 × 5 mm locating pins sit at (±15, -18) mm. Bracket receiving bores are
Ø2.05 × 2 mm upward from its underside, followed by 118° tips. Each pin enters
the plate 4.445 mm and projects 0.555 mm into the bracket.

## Drilling contract

The bracket's `ComponentContract.holes` describes eight **component** holes: four
M1.6 taps, two M4 clearance/counterbores, and two locating bores. Its mounting
frames and thread interfaces are separate from its mating plate operations.

`baseplate_profile()` and `drill()` produce exactly four **baseplate** bores:

| Feature | Position (component XY, mm) | Baseplate operation |
|---|---|---|
| plate_1 / plate_2 | (0, -20) / (0, 20) | M4 × 0.7; Ø3.3 tap drill, 10 mm straight depth, 8 mm usable thread |
| pin_1 / pin_2 | (-15, -18) / (15, -18) | Ø2.01 × 4.445 mm straight depth, 118° tip |

All four start on component Z=-12.7 and point downward. Pin fit uses the existing
catalog convention: Ø2.0066–2.02184 mm, depth +0.0508/-0 mm. No holder tap is
propagated into the baseplate. Both ordinary `Baseplate` drilling and
`machined_baseplate.add()` use the shared attachment implementation, including
nested translations, yaw and recomputation.

## Optical representation

The assembly provides an identity ray interface through the crystal center,
with a rectangular 4 × 1 mm aperture. Both ends of the 27.4 mm crystal must
clear the ray center; the schematic constrains axial incidence. Wavelength,
power, direction and polarization pass through unchanged. This supports CAD
layout; it does not model refractive index, SHG/SPDC conversion, phase matching,
or material optical path. The STEP label “DC Crystal” does not establish its
material. Temperature, heater, sensor and thermal isolation are outside the
requested scope.

## Example and checks

```bash
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python examples/crystal_holder.py
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python tests/catalog/freecad_crystal_acceptance.py -v
python -m unittest discover -s tests -p 'test_schematic_crystal.py' -v
```

Use Python 3.10 or newer for portable schematic tests. The example exports
`artifacts/crystal_holder.FCStd`, the assembly STEP, `crystal_bracket.step`,
baseplate machining JSON, component contracts, and a BOM. The static native
document reopens without Python proxies or source-file access. The Python
example rebuilds the editable assembly.
