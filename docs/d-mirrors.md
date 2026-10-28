# D-shaped pickoff mirrors and left/right-handed holders

The catalog includes the exact Thorlabs purchased mirror and holder geometry:

| Holder | Matching protected-silver mirror | Diameter | Circle-center height | Default beam-datum height | Plate attachment |
|---|---|---:|---:|---:|---|
| [KM05DR](https://www.thorlabs.com/item/KM05DR) | [PFD05-03-P01](https://www.thorlabs.com/item/PFD05-03-P01) | 12.7 mm | 17.526 mm | 16.526 mm | One 8-32 stud |
| [KM05DL](https://www.thorlabs.com/item/KM05DL) (left) | [PFD05-03-P01](https://www.thorlabs.com/item/PFD05-03-P01) | 12.7 mm | 17.526 mm | 16.526 mm | One 8-32 stud |
| [KM100D](https://www.thorlabs.com/item/KM100D) | [PFD10-03-P01](https://www.thorlabs.com/item/PFD10-03-P01) | 25.4 mm | 32.004 mm | 31.004 mm | One M4 cap screw |
| [KM100DL](https://www.thorlabs.com/item/KM100DL) (left) | [PFD10-03-P01](https://www.thorlabs.com/item/PFD10-03-P01) | 25.4 mm | 32.004 mm | 31.004 mm | One M4 cap screw |

Both mirrors are **6 mm thick**, including their original 30-degree rear relief
and edge bevels. The `03` in their part numbers does not specify 3 mm thickness.
No custom holder or height-compensating spacer is introduced.

```python
from PyOpticL import lab_catalog

small = lab_catalog.create('d_mirror', 'Half-inch pickoff', mount='KM05DR')
large = lab_catalog.create('d_mirror', 'One-inch pickoff', mount='KM100D', edge_distance=1.0)

left_small = lab_catalog.create('d_mirror', 'Left half-inch', mount='KM05DL')
left_large = lab_catalog.create('d_mirror', 'Left one-inch', mount='KM100DL')

# Existing mirror selection also accepts all four holders.
large = lab_catalog.create('mirror', 'Pickoff', mount='KM100D')

# Reusable purchased parts, without assembling a pair:
holder = lab_catalog.create('KM05DR', 'Holder')
mirror = lab_catalog.create('PFD05-03-P01', 'Mirror')

height = lab_catalog.native_height(small)
```

The default pair is KM05DR/PFD05-03-P01. Bare optics also accept `edge_distance`. An optional `optic=` selects the exact
mirror explicitly and must match its holder. Exact purchased mirrors have fixed
dimensions; the `mirror` alias accepts `thickness=6` and rejects other thicknesses.
The selected mounting face is the bottom face. The alternate side attachment is
described in the component contract but is excluded from the plate footprint.

## Optical datum and pickoff behavior

Local +X is the outward reflective normal. The substrate extends from X=-6 to 0.
The straight edge runs along Y, at Z=`edge_distance`; the open half faces +Z. The component
origin is `edge_distance` below the straight edge, default 1 mm, inside the reflective
area. The default leaves 1 mm between the ray center and the pickoff edge; the
example separately verifies its 45-degree approach/return envelopes.
`edge_distance` must be greater than 0.1 mm and less than the clear radius;
changing it selects a beam datum without changing any purchased dimensions.
The circle center itself lies on the straight edge,
so it is recorded as a separate datum rather than used as the default beam hit.
The table gives both native heights to make this distinction explicit.

The finite interface checks hits in the optic's own coordinate frame, including
roll, yaw, translation and nested placement. A ray in the missing half or outside
the substrate has no interaction and continues. A hit inside the modeled clear
aperture reflects through the existing `Reflection` implementation. Hits on the
remaining substrate border terminate. Backside and grazing rays are excluded.

The drawing specifies clear aperture greater than 90% of the diameter and a
0.1 mm maximum straight-edge bevel. The model conservatively uses the intersection
of the 90%-diameter semicircle and a region 0.1 mm below the straight edge.
This is an ideal single-sided reflection: Gaussian propagation, power and Jones
behavior follow the existing ideal mirror. P01 coating efficiency/phase,
edge diffraction, finite-beam clipping fractions, and general mechanical ray
occlusion are not modeled. The example separately checks illustrative Ø0.5 mm
approach/return envelopes against each holder.

The assembly owns the optical interaction, so `BeamPath.add(..., after_object=...)`,
`measure_properties()` and `get_output_indices()` work with the complete pair.
The purchased optic remains its own BOM item and has no duplicate ray interface.

## Source geometry and seating

All six STEP files and engineering drawings are hash-pinned in `catalog_data/assets`
and stored as original bytes in `catalog_data/sources`. Independent measurements,
source solid counts/volumes/bounds, and fit choices are in `d_mirror_reference.json`.
Drawings are **21737-E0W revision A**, **TTN099623-E0W revision A**,
**15651-E0W revision C**, and **15656-E0W revision C**, plus left-hand drawings
**TTN098184-E0W revision A** (KM05DL) and **TTN010108-E0W revision B** (KM100DL).

- KM100D and KM100DL sources each contain 23 solids, including an example optic
  explicitly labeled
  "optic not included" by the drawing. Working holder geometry excludes that
  reference solid (index 22); the exact PFD10-03-P01 replaces it in the assembly.
- KM05DR and KM05DL each retain all 26 hardware solids. In each mounted pair, the two
  nylon-tipped screws retract 0.44375 mm along their axes to contact the rear S2
  surface of the purchased 6 mm mirror. KM05DR is rear loaded: coated S1 faces
  native +Z through the retaining lip at Z=14.6558 mm; rear S2 is at Z=8.6558 mm.
  KM05DL uses its own front lip at native Z=2.032 mm, rear S2 at Z=-3.968 mm,
  and clamp solids 15/16, also retracting 0.44375 mm. Its semicircle opens along
  native -X, so its upright normalization is a 90-degree Y rotation and its
  bottom mounting face is native X=15.6464 mm. Their dimensions and original
  source pose/bytes are unchanged.
- PFD05 imports as one valid solid. PFD10 is supplied as one valid, closed shell;
  it is promoted to a solid using its eight unchanged faces. No sewing, healing,
  or remodeling is applied. This conversion is explicitly enabled for that asset.
- KM100D/KM100DL seat on their rear support planes. KM100DL S1 faces native
  -Z at Z=-6.35 mm, with its rear seat at -0.35 mm. KM05DR/KM05DL seat against their
  front retaining lips, with nylon screws contacting the rear surface. All four pairs have no material
  overlap with the holder or nylon clamp tips. Source compounds are protected
  from neighboring automatic drilling.

## Plate contract and hardware

None of these holders has locating dowels. Each exposes exactly **one tapped operation**
through the shared attachment builder, in ordinary `Baseplate` and
`MachinedBaseplate`. Component holes remain distinct from these plate bores.

- KM05DR/KM05DL use their actual **8-32 UNC** bottom tap. The selected plate bore is
  Ø3.4544 mm (#29), 10 mm straight depth, with 8 mm nominal thread depth and a
  118-degree tip. A nominal 8-32 x 1/4-inch double-ended stud engages the holder
  and plate by 3.175 mm each. This is an installation selection; it is not a
  vendor-specified plate connection or a dowel registration scheme.
- KM100D/KM100DL use their existing Ø4.7625 mm clearance hole and Ø7.9375 mm counterbore.
  The plate uses the existing M4 profile: Ø3.3 x 10 mm tap drill, 8 mm nominal
  thread depth and a 118-degree tip. A selected M4 x 12 mm cap screw spans the
  measured 4.318 mm clearance section, giving 7.682 mm nominal plate engagement.
  Thorlabs supplies imperial/metric mounting screws; their supplied lengths
  have not been verified. The selected screw is recorded as a BOM requirement.
- Each KM100D/KM100DL removable knob protrudes 0.635 mm below the mounting face. A separate
  conservative rectangular plate relief is 0.885 mm deep, allowing 0.25 mm extra
  clearance. Both plate workflows consume the same profile box. The optical
  datum and seating height remain unchanged. It is reported as a pocket, not an
  attachment operation. KM100DL uses independently measured source knob solid
  21 and its own relief coordinates; KM100D uses source solid 6.

Screws/stud are BOM requirements rather than extra nominal solids in the review
STEP. Clamp-force, preload, thread phase, manufacturing fit and physical retention
are separate from the nominal CAD fit checks.

## Demo and verification

```bash
python3 -m PyOpticL.vendor_cad verify --all
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python tests/catalog/freecad_d_mirror_acceptance.py
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python examples/d_mirrors.py
```

The example uses one flat 30 mm baseplate with all four pairs at their native beam
datum heights. Four independent 1550 nm paths each travel 50 mm to the mirror,
reflect by 90 degrees, and travel 40 mm to an optical-only receiver.
Right-hand samples return toward +Y and left-hand samples toward -Y.
Each input has illustrative waist radius 0.2 mm and power 1 mW.

Outputs under `artifacts/d_mirrors*` include the static FreeCAD assembly, purchased
geometry/baseplate STEP assembly, separate baseplate STEP, machining JSON, BOM,
and verification report. Generated outputs remain rebuildable ignored artifacts;
original vendor sources and the rebuilding code are tracked in Git.

The expanded acceptance suite checks all four holder selections, original source
hashes and solids, native heights, front-facing coated surfaces, opposite arm
handedness, clamp seating, selectable edge distance, both plate workflows with
nested transforms, recomputation, instance isolation, and export/reopen integrity.
The four-pair review contains four tapped attachment bores and two knob reliefs.
The small mounts retain their 8-32 threads; no extra dowel holes are introduced.
Detailed local results are in `artifacts/d_mirrors.verification.json`.

Verified 2026-10-28: 67 tests passed across D-mirror, catalog, baseplate, vendor-batch,
fixed-iris, and schematic checks. One Qt inspector test was skipped because that
GUI runtime was unavailable. All 54 original-source records verified locally; the
D-mirror, baseplate, vendor-batch, and iris suites passed with cache/network access
disabled. STEP roundtrip preserved 101 valid solids.
