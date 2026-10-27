# LightSmyth transmission grating and MK05S assembly

The native-height grating preset combines the Coherent LightSmyth **1336552**
(Edmund **16-876**, T-1000C-31.8x12.3-94), an imperial Thorlabs **MK05S**, and a removable
baseplate adapter. The glass seats directly in MK05S and is retained by its
existing nylon-tipped lock. Dimensions use millimeters; wavelength uses nanometers;
angles use degrees. This is a single-grating component, not a compressor model.

```python
from PyOpticL import lab_catalog

mount = lab_catalog.create('MK05S', 'Purchased mount')
optic = lab_catalog.create('LightSmyth-1336552', 'Purchased grating', order=1)
grating = lab_catalog.create('grating', 'G1', mount='MK05S',
    design_wavelength=1550., incidence_angle=49.9, order=1)
print(lab_catalog.grating_angles())
print(lab_catalog.native_height(grating))  # 20.5061 mm
```

The bare optic's origin is its front-surface center. Local +X points into the
substrate, +Y across its grooves, and +Z along the short edge and grooves. The
mounted preset's origin is the same point, with its **nominal incoming ray along
+X**. It rotates all mechanical and optical parts by the specified incidence
angle about Z. Place the preset with the ordinary layout API, or use
`BeamPath.add()` to seat its optical interface on an incoming beam. No physical
articulation or adjustment controls are implemented.

The `output` contract frame describes the nominal design-wavelength direction.
Actual downstream placement must use traced output, for example:

```python
receiver = beam.add(receiver_component, beam_index=1, rotation=0,
                    distance=50, after_object=grating)
output = beam.measure_properties(grating)
indices = beam.get_output_indices(grating)  # [1] for a completed passage
```

## Source evidence and native geometry

The exact [MK05S product downloads](https://www.thorlabs.com/item/MK05S) are
pinned in `catalog_data/assets/MK05S.*.json`. The engineering drawing is
**TTN193112-E0W, revision A**. STEP declares inches; FreeCAD imports millimeters.
Independent measurements and normalization are in `catalog_data/grating_reference.json`.
The original STEP, drawing, and LightSmyth datasheet are versioned in
`PyOpticL/catalog_data/sources`; rebuilding and source checks work offline.
The datasheet is indexed by `source_references.json`.

| Source | SHA-256 |
|---|---|
| MK05S STEP | `530ed2a20d8d81be649e457a1a6e0c4c82868f2f22b730888abcb0fdb34697fe` |
| MK05S drawing | `34d7563801a1f24fe51cc29921e4a08b800cdc3df6ed8a8abe82b4875791bb09` |
| Coherent T-1000C datasheet | `77e76a42ec86007f0c56e64a051347a46f7641e45a8f35595c1641836eb21e2e` |

All **25 MK05S solids**, their volumes, dimensions, and relative placements are
preserved. Its measured envelope is approximately 20.2184 x 21.1836 x 16.1178 mm.
The grating is a nominal parametric **31.8 x 12.3 x 0.95 mm** fused-silica envelope,
with **30.8 x 11.3 mm** clear aperture. No exact grating STEP was supplied or
used; its geometry has documented dimensional provenance, not an exact-CAD claim.
The [manufacturer datasheet](https://www.coherent.com/content/dam/coherent/site/en/resources/datasheet/optics/diffraction-grating-t-1000c-series-ds.pdf)
and [selected distributor specification](https://www.edmundoptics.com/p/ii-vi-lightsmytht-1525---1565nm-1000-groovesmm-318-x-123mm-transmission-diffraction-grating/44712/)
identify the groove direction, thickness, operating band, and aperture.

The grating seats directly against the native pocket's bottom and right edge.
In source STEP coordinates its bounds are X = -25.45...6.35 mm,
Y = -6.35...5.95 mm and Z = -3.015...-2.065 mm. The front-center optical datum
is therefore (-9.55, -0.2, -2.065) mm. The glass thickness is centered at
Z = -2.54 mm, under the existing nylon-tipped locking screw. Both support
contact and absence of glass/mount interference are checked against the original
25 vendor solids. The MK05S holds the optic directly; only the plate adapter
is fabricated.

The reference-pose nylon lock is **0.55875 mm** above the glass top edge and must
advance during installation. The source assembly is not articulated. Direct
mounting is the user's selected arrangement; the 0.95 mm grating is below the
published 2.54 mm minimum optic thickness. The model verifies nominal geometric
seating and beam clearance, while physical retention, clamp force and
manufactured fit remain unvalidated. No extra optic holder is inserted.

## Plate adapter and drilling contract

The **40 x 50 x 10 mm** aluminum adapter centers under the selected bottom
MK05S mounting hole. Its underside counterbore accepts a **4-40 UNC x 3/8 inch**
nominal cap screw. The 9.525 mm shaft passes 6.5 mm of adapter stock, engaging
the mount by **3.025 mm**, including the modeled 0.254 mm entrance chamfer.
Straight thread engagement is **2.771 mm**; the screw does not project into the
internal cavity. Install
this screw before attaching the adapter to the plate. The imperial mount is
not interchangeable with the M3-threaded MK05S/M.
The vendor bore has a curved exit: its conservative cylindrical extent is
3.5865 mm, and its farthest trimmed surface reaches 3.80948 mm. Both are
recorded separately. Twenty-millimeter-long, Ø2 mm approach envelopes verify
access to both tip/tilt hexes and the nylon lock.

All following XY coordinates are relative to that mounting screw, in the
unrotated adapter's normal/across-groove axes:

| Feature | XY, mm | Component geometry | Mating plate operation |
|---|---|---|---|
| Two plate screws | `(0, -20)`, `(0, 20)` | Ø4.5 through, Ø7.5 counterbore 4.4 deep | M4 x 0.7, Ø3.3 tap drill, 10 straight depth, 8 thread depth |
| Two locating pins | `(14, -5)`, `(14, 5)` | Ø2.05, 2 straight blind depth from underside | Ø2.01, 4.445 straight blind depth |
| MK05S attachment | `(0, 0)` | Ø3.1 through, Ø5.5 underside counterbore 3.5 deep | None |

Blind bores have 118 degree drill tips. Plate pin limits remain
**2.0066–2.02184 mm** diameter, **+0.0508/-0 mm** straight depth, and **0.555 mm**
nominal projection for Ø2 x 5 mm pins. M4 x 12 mm plate screws engage 6.4 mm of
the mating plate. Only the adapter exposes `baseplate_profile()` and `drill()`:
exactly **two tapped operations plus two dowel operations**. Its own five-hole
contract is distinct from these four plate operations. The MK05S attachment clearance never drills the plate. Contract serialization remains version 1.

The optical center is **10.5061 mm above the MK05S seating face**, and
**20.5061 mm above the adapter bottom**. Both native and assembly heights are
recorded. The demo sits directly on the plate top. Existing recess placement
can accommodate another chosen beam plane; the preset introduces no common
height policy or automatic spacers.

## Diffraction convention and accuracy

`grating_angles(wavelength_nm=1550., incidence_angle_deg=49.9, order=1,
grooves_per_mm=1000.)` returns the incidence, diffraction, and beam-deflection
angles, period in millimeters, wavelength, and selected order. With its sign
convention:

```text
sin(alpha) + sin(beta) = m * wavelength_nm * 1e-6 * grooves_per_mm
beam deflection = alpha + beta
```

At 1550 nm this gives **alpha = 49.9°, beta = 51.7279483°**, and a **101.6279483°**
turn of the propagating beam. Equal angles would instead be 50.8050326°; the
default deliberately uses the vendor's nominal 49.9° AOI. Zeroth order has
beta = -alpha and travels straight ahead.

`beam_path.TransmissionGrating` applies the actual wavelength and incident
direction. For surface normal `n`, unit across-groove vector `u`, and normalized
incident direction `d`, it calculates:

```text
t = d - (d dot n)*n + m*wavelength_mm*grooves_per_mm*u
d_out = t + sign(d dot n)*sqrt(1 - t dot t)*n
```

The groove-parallel component is conserved, including skew incidence. Local
rectangle bounds remain correct after roll, yaw, translation, and nested
placement. Substrate-border hits terminate; rays outside the physical rectangle
miss the component. Grazing and nonpropagating selected orders produce no
output. Nonfinite/nonpositive wavelength or density, noninteger order, invalid
angles, and impossible nominal configurations are rejected. Design wavelength
defines nominal alignment, while actual rays retain their own wavelengths.

This is an **ideal single-order, thin-interface ray model in air**. Preserved
power is a convention, not a claim of 100% physical diffraction efficiency.
Jones states undergo minimal-rotation transport into the outgoing transverse
basis. Scalar Gaussian free-space propagation is retained; anamorphic beam
reshaping, substrate lateral displacement/OPL, coating response, diffraction
patterns, and polarization-dependent efficiency are outside the model. The
manufacturer efficiency band is 1525–1565 nm; geometric calculations outside
that band do not establish optical performance.

## Rebuild and review

```bash
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. \
  /Applications/FreeCAD.app/Contents/Resources/bin/python examples/grating.py
PYTHONPATH=/Applications/FreeCAD.app/Contents/Resources/lib:. \
  /Applications/FreeCAD.app/Contents/Resources/bin/python tests/catalog/freecad_grating_acceptance.py
```

`examples/grating.py` exposes `build(output=None, plate_thickness=30.)`, returning
the static review document and verification report. Wavelength, incidence,
order, waist, power, placement, and yaw are editable example constants. It traces
50 mm before and 50 mm after the grating, with a 0.2 mm waist and illustrative
1 mW power at the native assembly height. The receiver uses traced output.

Generated, gitignored review files under `artifacts/grating*` include the static
FreeCAD document, 33-solid hardware STEP assembly, separate one-solid baseplate,
adapter STEP file, machining JSON, BOM, verification,
and a concise report. The editable source stays open. Saved static geometry
reopens without the source-asset cache. The demo verifies beam envelopes,
thread-annulus-only interference, two pins, all four plate bores, stock under
drill tips, repeated recomputation, and export/reopen integrity.

Automated verification on 2026-10-26 with FreeCAD 1.1.4 passed **82 tests**:
18 grating acceptance, 7 standard catalog/asset/contract, 10 catalog, 4 baseplate,
10 iris, 8 vendor batch, 17 roof, and 8 all-components tests. The existing beam
smoke test also passed. The grating suite includes source hashes and independent
solid/placement recovery, direct glass-to-MK05S seating, aperture corners and edge
rejection, wavelength dispersion, skew-ray momentum, reciprocity, zeroth order,
Jones/Gaussian transport, nested transforms, physical cuts in both baseplate
workflows, isolation, stock rejection, contracts/BOMs, and static export/reopen.
