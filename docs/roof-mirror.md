# HRS1015-P01 roof mirror

```python
from PyOpticL import lab_catalog as catalog

bare = catalog.create('HRS1015-P01', 'Purchased roof')
horizontal = catalog.create('roof', 'Sideways return', beam_separation=12.7)
vertical = catalog.create('roof', 'Upward return',
                          orientation='vertical', beam_separation=12.7)
```

Dimensions are millimeters. `orientation` accepts `horizontal` and `vertical`.
Spacing must be finite, positive, and put the nominal central rays inside both
modeled clear rectangles. The present source permits approximately 2.823 to
22.577 mm spacing (strictly inside the aperture). Spacing chooses alignment
datums on an unchanged optic; it is not an actuator or a guaranteed displacement
for arbitrary off-axis rays. Unknown construction parameters fail explicitly.

The component origin and `input`/`optical` frames are the nominal incoming beam
position on the front opening plane; propagation is local +X. The `output`
frame points along -X. Horizontal output is at `(0, -spacing, 0)`; vertical output
is at `(0, 0, spacing)`. Ordinary placement yaw rotates these positions and
directions together. In vertical mode only the optic rolls -90 degrees; the
integral supports, removable clamp, screw and hole axes stay upright.

## Corrected integral supports and M2 clamp

The mounted preset uses the user's corrected designs:

- `HRS1015-AG-Step Copy 1.step`: horizontal roof and slotted rectangular clamp.
- `HRS1015-AG-Step (1).step`: vertical roof and slotted corner clamp.

Both source hashes, measured dimensions, hole locations and solid roles are
recorded in `catalog_data/roof_support_reference.json`. Their native profiles
are committed as editable rational curves and extrusions; runtime rebuilding
does not depend on the files remaining in Downloads. The supplied AG-labelled
optic is used only to verify geometry. The purchased part remains the exact
hash-pinned HRS1015-P01, including all three vendor solids and the existing
optical model. Source AG and purchased P01 envelopes agree geometrically.

The original bolt-on carrier has been replaced. Each design contributes a
38.1 x 38.1 x 12.7 mm stock reference patch with its integral stops, a separate
5.08 mm-thick removable clamp, and one nominal M2 socket-head screw. The
horizontal stop height is 2.54 mm above the patch reference top; vertical stops
are 12.7 mm high. The vertical clamp retains its corner shape and 1.27 mm
relief. There are no roof M4 attachments, dowel pins, acetal pads or carrier
recesses. The support body becomes material in the baseplate.

The only deliberate hole changes from the supplied designs are:

| Feature | Horizontal | Vertical |
|---|---:|---:|
| Clamp attachment thread | M2 x 0.4 | M2 x 0.4 |
| Tap-drill diameter | 1.6 mm | 1.6 mm |
| Straight drill depth | 7.62 mm | 5.08 mm |
| Usable modeled thread | 6.62 mm | 4.08 mm |
| Clamp-slot width | 2.2 mm | 2.2 mm |
| Slot end-center spacing | 5.08 mm | 2.54 mm |
| Nominal screw | M2 x 10 mm | M2 x 8 mm |
| Nominal screw engagement | 4.92 mm | 2.92 mm |

The base holes are tapped, rather than Ø2 mm clearance holes. The 1.6 mm
cutting-tap drill follows the [Haas M2 x 0.4 tap specification](https://www.haascnc.com/haas-tooling/threading/taps/03-1600.html).
The clamp slots are enlarged from the supplied nominal Ø2 mm width for screw
clearance. Each blind tap drill has a 118-degree tip beyond its straight depth.
Threads and screw heads are nominal envelopes, not detailed helical geometry.
Physical fit, torque, holding force, repeatability and manufacturing tolerances
require validation on fabricated parts.

The two supports are reconstructed from measured profiles to a 0.01 mm CAD
comparison tolerance. The vertical source has a small outer-wall trim deviation
below 0.003 mm; nominal extrusion of its measured top profile stays within
that tolerance. Source comparison excludes only the deliberately changed hole
and slot regions and separately checks the purchased optic.

Both ordinary `Baseplate` and `MachinedBaseplate` union the selected support
body into stock and then cut its one M2 hole. Holes are recut after fusion so
stock cannot refill the clamp hole or a neighboring component's bores. The
removable clamp, screw and purchased optic remain separate. Integration uses
the support's `baseplate_integration()` declaration; it has no bolt-on
`baseplate_profile()`. The support contract describes one M2 tap drill, and
the clamp contract one clearance slot. Contract schema v1 is unchanged.

Integrated support rows in the BOM have `integrated_into='baseplate'` and
`separate_part=False`. The static assembly and hardware STEP contain the
support material only in the plate, avoiding duplicate solids. Distinct Lab
part identifiers distinguish the horizontal and vertical clamps. Their
separate STEP exports contain the corrected M2 clearance slots.

## Datums, native height and direct union

The source optic center is Z=0, the reference plate top Z=-12.7 mm and the
reference stock bottom Z=-25.4 mm. `catalog.native_height(roof)` measures input
height above that reference top, rather than above the stock patch bottom.

| Orientation | Native input | Native output | Reference patch top for 12.7 mm input |
|---|---:|---:|---:|
| Horizontal | 12.7 | 12.7 | 0 |
| Vertical, spacing s | 12.7 - s/2 | 12.7 + s/2 | s/2 |
| Vertical, default s=12.7 | 6.35 | 19.05 | 6.35 |

At native placement, the patch reference top coincides with the plate top.
The demo retains 12.7 mm input height for both roofs: horizontal supports rise
from the plate surface, while the vertical patch forms a 6.35 mm integral
pedestal. Its output is 25.4 mm high. No separate spacer or bracket is added.

The selected patch must join the blank, fit within its lateral stock bounds,
and stay above the stock bottom. Its optic seating plane cannot be buried
below the plate top. Non-upright integration and insufficient stock are
rejected. The ordinary plate requires the user to position the support within
its footprint; `MachinedBaseplate` computes a surrounding blank as usual.
Existing purchased-mount and fixed-iris attachment profiles remain unchanged.

## Purchased optic source

The exact official HRS1015-P01 STEP and drawing **TTN048987-E0W revision B**
are hash-pinned in the existing CAD cache. The optic has three valid source
solids and volume 7951.62842695 mm³; nominal dimensions are
25.4 x 25.4 x 18.7 mm, including the 6 mm backing. Chamfers reduce actual
native forward extent to 18.5232233 mm. No source solid is modified or fused
into the plate. The assembly source and static exports preserve the purchased
optic as one BOM item.

Normalization maps native `(0,18.7,0)` to the roof front center and rotates
+90 degrees about Z. The nominal roof edge is at `(12.7,0,0)`, parallel to Z
before the selected optic roll. The corrected support files already contain
the corresponding orientations, so their structures are normalized without
rolling them a second time. At runtime only the vendor optic requires its
pinned cache; the custom support and clamp are native geometry.

## Explicit optical passage and OPL

The entrance, both finite reflective planes and exit are separate interactions.
Facet bounds are tested in their own transformed coordinates. The optical
clear region is a **centered rectangle covering 80% of each measured trimmed
facet dimension**. This is a conservative modeling assumption; the vendor
drawing states greater than 80% clear aperture but does not define its exact
boundary. Rays entering the projected body envelope that cannot complete two
valid reflections terminate at the entrance. Rays outside that envelope do
not interact. This is central-ray clipping, without a diffraction model.

For normal input, the three internal legs have lengths `(12.7-s/2, s,
12.7-s/2)`, totaling **25.4 mm**, independent of valid nominal spacing. For
general direction d and unit roof-edge axis e, two ideal perpendicular
reflections give `d_out = -d + 2(d·e)e`. A direction component along the roof
edge is preserved; arbitrary 3D rays need not return antiparallel.

```python
result = beam.measure_component_pass(vertical, refractive_index=1.0)
# World-coordinate entry_mm, exit_mm, reflection_points_mm,
# outgoing_direction; segment_lengths_mm, geometric_length_mm,
# optical_path_length_mm and the specified homogeneous refractive_index.
```

Optional `beam_index` selects a beam; zero-based `pass_index` selects a completed
pass. Missing/blocked passes and invalid indices or refractive indices raise
`ValueError`. Length comes from actual traced segments, not nominal spacing.
The cavity is air: no fused-silica optical thickness is added. The supplied
homogeneous refractive index scales reported OPL only. Existing ideal mirror
power/Jones behavior and Gaussian propagation are retained; silver coating
phase, dispersion and diffraction are not modeled.

Interface metadata (`name`, `role`, `output_boundary`) distinguishes internal
continuations from completed output. Existing interfaces default to completed
output behavior. `after_object=roof`, `measure_properties()` and
`get_output_indices()` operate on the exiting ray. Measurement positions and
directions are expressed in the beam path frame; pass geometry is in world
coordinates. Internal segment metadata persists in the FreeCAD properties.

## Rebuild and verification

From the repository root on this Mac:

```bash
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python tests/catalog/freecad_roof_acceptance.py -v
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. /Applications/FreeCAD.app/Contents/Resources/bin/python examples/roof_mirror.py
```

`examples/roof_mirror.py` exposes `build(output=None, plate_thickness=30.0)` and
returns the static document and verification report. Placements, spacing, input
height, wavelength, waist and power are editable. The default scene contains
both corrected supports in one plate, two 1550 nm paths, 12.7 mm input height,
0.2 mm waist radius and 1 mW per input. Each source/receiver lies 50 mm from
the front plane: five traced legs and 125.4 mm complete path per roof.

Exports under `artifacts/roof_mirror*` include static FreeCAD, hardware STEP
(without beams), separate baseplate STEP, separate horizontal/vertical clamp
STEPs, machining/BOM JSON, and concise Markdown/JSON verification reports.
Source documents remain open for editing. The default plate is 85 x 170 x
30 mm below Z=0, with two integral support sets, two M2 taps and no carrier
pockets. Raised features reach Z=19.05 mm, so the minimum bounding billet
is **85 x 170 x 49.05 mm**. The machining JSON and BOM report the slab
and complete stock envelope separately.
The hardware assembly has 11 valid solids; each purchased roof retains three.

Verification on 2026-10-26 with FreeCAD 1.1.4's bundled Python:

| Suite | Passing tests |
|---|---:|
| Standard-Python catalog/download/contracts | 7 |
| Existing FreeCAD catalog | 10 |
| Existing baseplate | 4 |
| Existing fixed iris | 10 |
| Existing vendor batch | 8 |
| Existing all-components baseplate | 8 |
| Corrected roof acceptance | 17 |
| **Total** | **64** |

The existing `tests/beam_test.py` smoke fixture also runs successfully. Roof
acceptance verifies both supplied designs, their source hashes and geometry,
M2 tap/slot adaptation, direct union in both plate workflows, nested transforms,
recompute, instance isolation and preservation of a neighboring iris's bores.
It also checks finite two-bounce optics, spacing, oblique/skew rays, seam and
aperture misses, Gaussian/Jones propagation, translation delay, opposite-port
double passage, downstream placement and cache-independent static exports.

Clamps and optics have no volumetric plate interference. The only accepted
screw overlap is within each M2 thread annulus. At the default plate thickness,
minimum remaining stock beneath a drill tip is approximately 21.8993 mm.
FreeCAD and STEP roundtrip checks preserve valid solids, bounds and volume.
The saved review requires neither Python proxies nor the CAD cache. No
purchasing or complete translation-stage delay module is included.
