# Reference measurements and verification

Measurements were taken from the supplied lab STEP files and exact Thorlabs STEP/drawing downloads before defining the corresponding nominal geometry. Machine-readable records and source hashes are in `PyOpticL/catalog_data/reference_measurements.json`; each vendor manifest pins its STEP or PDF independently. All comparisons use **0.01 mm and 0.01°**, not manufacturing tolerances.

## Vendor references

| Part | Official drawing document | Drawing revision | Measured native datums (mm) |
|---|---|---|---|
| POLARIS-K05VS2 | POLARIS-K05VS2-E0W | C | Optic contact plane Z=2.159; mounting face Y=-12.7; post-hole axis at X=0, Z=8.96484066 |
| F260FC-1550 | 7524-E0W | D | Barrel front Z=9.5504; axis X=Y=0; FC/PC end Z=-14.1732 |
| AD1109F | 13080-E0W | B | M11 seating shoulder Z=0.762; SM05 shoulder Z=-3.937; nose end Z=-7.112 |
| KA05TA | KA05TA-E0W | A | Bore axis X=9.09394, Y=14.67817; front seat Z=2.39919; base Y=1.97817; post-hole axial coordinate Z=18.68338 |
| ELL16 | ELL16-E0W | A | Optical axis native Y; cage mounting plane Y=-8.64876292; four hole axes at X/Z=±15 |
| XR25C | XR25C-E0W | E | Base Y=-7.112; payload Y=15.888; native translation axis X; payload height 23 |

Source pages: [POLARIS-K05VS2](https://www.thorlabs.com/item/POLARIS-K05VS2), [F260FC-1550](https://www.thorlabs.com/item/F260FC-1550), [AD1109F](https://www.thorlabs.com/item/AD1109F), [KA05TA](https://www.thorlabs.com/item/KA05TA), [ELL16](https://www.thorlabs.com/item/ELL16), [XR25C](https://www.thorlabs.com/item/XR25C).

The optical collimator reference is a barrel-front datum, not a claimed lens principal plane. Vendor cylinder origins are not necessarily their end faces: axial projections were used for hole-center comparisons. Hole records distinguish drawing thread standards from modeled bore diameters. XR25C records all 22 payload-hole axes and their 1/4-20 specification. Mounting slots and partial holes should be interpreted through their reference profiles, not replaced by arbitrary circular holes.

Normalization maps vendor coordinates to component coordinates while retaining original source bytes. Optics face local +X. ELL16's mounting face is placed at holder X=10; the holder wall ends at X=13. The XR25C payload frame is local Z=23. DOF ranges remain unknown instead of inferring symmetric travel from total-travel marketing specifications.

## Legacy KA05TA coupling chain

The [collimator compatibility table](https://www.thorlabs.com/fixed-focus-collimation-packages-fcpc-connectors?tabName=Overview) and exact drawings identify F260FC-1550 → AD1109F → KA05TA. The first mate is external/internal M11 × 0.5; the second is external/internal SM05 (0.535-40). The adapter's M9 thread is not used.

The user selected **the end of the M11 thread** as the nominal placement datum. Vendor STEP plane Z=6.5532 is 2.9972 mm behind the collimator front at Z=9.5504. The AD1109F opening is aligned with that thread-end plane. The model does not bottom the collimator against the adapter's inner shoulder; its 6.35 mm threaded depth is not used as the insertion distance.

With the collimator front at assembly X=0, the adapter opening is X=-2.9972 and its SM05 shoulder is X=8.0518. KA05TA's front is X=8.0518. The contract records the user-selected nominal convention and its measured CAD datum.

The SM05 section is 3.175 mm long and its shoulder is seated against the mount. A direct solid-pair check of the initially installed front retaining ring found 58.885 mm³ interference with the adapter, so that ring is removed and retained as an unused included BOM item. The rear ring remains installed. Internal adjusters are not split into moving bodies.

At the delivered thread-end placement, individual-solid boolean checks report **0 mm³ overlap and no unresolved operations** for collimator/adapter, collimator/mount and adapter/mount. Results are recorded in `coupling_interference.json`; `tools/check_catalog_interference.py` reproduces the check. Checking individual solids is necessary because a compound-level result can hide an internal accessory collision.

FC/APC is rejected as an equivalent FC/PC connector. Nominal geometry and mechanical interface standards are checked separately from optical suitability, coupling efficiency, tightening torque and physical installation access.

## Displacement PBS support (current catalog revision 2)

The source is `Data/Displacement setup/Displacement Mount Assembly.step`, center object `Body`. Its SHA-256 and independent datums are pinned in `displacement_pbs_reference.json`. The upper seat provides the local pattern; equivalent seats occur elsewhere on that center piece.

- Seating plane Z=44.45 mm, register tops Z=49.5 mm (5.05 mm high).
- Register contact planes X=7.08 and Y=1.98056105 mm. A 12.7 mm cube seated against them has center (0.73, -4.36943895, 50.8). This is the nominal assembled optical reference, derived from those contact planes.
- Three relief trenches immediately ahead of the registers: two straight, one joined corner. Width 0.8 mm; depth 1 mm; 0.2 mm edge rounds. Straight trench length 9.5 mm.
- Comparison patch: origin (-16,-17,25.4), size (28.5,24.5,24.6) mm. These are extraction boundaries within the integral center piece, not a new bolt-on support design. The patch preserves the plastic-clamp attachment bore at (-12.942,-13.04143895): Ø2.5 mm, 9 mm straight blind depth from Z=44.45, drill tip Z=34.69892423. The STEP does not establish a thread designation. No standalone base fastening or replacement plastic clamp geometry is inferred.
- Geometry uses boxes, a polygonal corner pocket, extrusions and 0.2 mm fillets. `tools/verify_displacement_pbs.py` checks the original source hash and independently imports and trims its Body before comparing surfaces. Results are in `displacement_pbs_verification.json`; threshold 0.01 mm.
- The existing generic cube optical interfaces and fixed DOF description are unchanged. Legacy HOM support/clamp definitions remain available but are no longer selected by `create("pbs", ...)`.

## HOM custom parts (legacy PBS; current rotation holder)

The source assembly labels are `PBSClipBottom`, `Body`, and `Part 1` (ELL16 holder). The reconstruction stores rational sketch curves rather than opaque reference solids. Thicknesses, extrusions, holes and rounded upright edges are constructed parametrically.

- PBS seat: global Z=44.45; cube center Z=50.8; raised seating pads end at Z=47.45.
- PBS clamp: 5 mm extrusion, bottom Z=44.45; diagonal 3 mm slot retained.
- PBS clamp tap drill: center (-14.52157288, 9.52157288), Ø2.5, straight depth 5 mm, drill tip ending at Z=38.69892. Thread specification M3 × 0.5.
- PBS support comparison region: box from (-25,-15,25.4) with dimensions (40,40,24.6). This is a patch of the integral base and carries no invented standalone attachment holes.
- ELL16 holder: base Z=25.4, 7 mm thick; upright Y=-28.1 to -25.1; optical center (0,-38.1,50.8). Cage slots centered at X=±15, Z=35.8/65.8; base mounting slots X=±25.25; locating features X=-10,0,10 at Y=-38.1.

Bidirectional sampled surface checks against independently imported solids:

| Part | Samples | Maximum sampled deviation |
|---|---:|---:|
| PBS clamp | 560 | 1.02 × 10⁻¹³ mm |
| PBS support patch | 635 | 4.23 × 10⁻⁶ mm |
| ELL16 holder | 512 | 1.79 × 10⁻⁸ mm |

These are sampled comparisons, not a proof of the full continuous Hausdorff distance. The source uses spline surfaces even for planar/extruded features; integrated volume differs slightly after analytic reconstruction (notably about 2.96 mm³ on the 10,431 mm³ rotation holder). Surface locations, seats and hole/slot datums are the acceptance measures. Raw results are in `hom_verification.json`.

Generic M3 × 8 and 4-40 × 3/16-inch screws are explicit nominal fastening selections, not recovered vendor part numbers. Their nominal engagement is respectively 3 mm and 1.7625 mm. Manufacturer-specific head geometry and procurement selection remain unverified. External baseplate attachment hardware is not included.

## SPDC support decision

**Not verified compatible; excluded from the coupling preset.** The pinned `OutMount_BeamPathR_Machine (1).step` has a measured row at X=11.56, Y=-18.6 through -167.4 on 12.4 mm spacing, top Z=25.4, with Ø5.1054 modeled bores. KA05TA's mounting clearance is Ø4.6228 for #8/M4. The STEP alone does not establish a suitable thread, bolt, washer or adapter stack. The matching beam-line labels in the SPDC assembly are optical paths, not coupling supports. No unsupported compatibility claim is made from those labels or approximate diameters.

## Verification boundary

The current regression run passed 39 tests: 7 standard-Python tests and 32 FreeCAD integration tests across catalog, baseplate, fixed-iris and batch suites. It checks FreeCAD construction, pinned solids, independently measured vendor hole axes, nominal frames, DOF transforms, read-only summaries, metadata inertness, repeat recomputation, instance isolation and an existing mirror/interfaces/drill workflow. Downloader tests cover malformed files, hash changes, identity errors, both vendor-domain handlers and dynamic-page fallback. Skills pass the skill validator; their known-chain and mismatch logic is exercised through the connection API.

No physical motion, motor control, optical coupling-efficiency test, complete sweep of the historic example scripts, or physical assembly test is claimed. OptoSigma MHV source solids and their exact part identities are now checked by batch acceptance, in addition to downloader fixtures. The SPDC fastening stack and manufacturer-specific external fasteners remain open procurement/installation qualification items. The coupling nominal placement follows the explicitly selected thread-end convention.


## Direct baseplate attachment

`baseplate_interfaces.json` pins the mounting profiles to the existing vendor
STEP and drawing hashes. Both POLARIS-K05VS2 and KA05TA mounting faces lie
12.7 mm below their optical axes. Native POLARIS attachment axes are
(0,-12.7,8.96484065558) for the #8/M4 clearance hole and X=-5,+5 at the same
Y/Z for alignment pins. The +5 feature is a slot: its cylindrical ends have
X=4.50457 and 5.49543, radius 1.00457 mm. The mating plate uses its centerline,
not two separate holes for those end arcs. The prior contract recorded only
the round feature; the slot is now included.

POLARIS drawing C specifies 2 × 5 mm DIN 7-m6 / ISO 2338 pins and mating holes
Ø0.0790–0.0796 in, 0.175 +0.002/-0 in deep. Plate values are explicit mm
conversions, distinct from the mount's 1.905 mm blind pin pockets. KA05TA's
selected bottom clearance-hole axis is (9.09394,1.97817,18.68338). Its other
mounting hole is on the orthogonal side face; no dowel pattern is documented.

Stock-size and recess decisions use tight `optimalBoundingBox()` bounds rather
than loose spline bounds. For example, the POLARIS imported compound's ordinary
box extends below the actual mounting face; that alone is not evidence of a
physical projection requiring a pocket. The native planar mounting faces and
actual plate/mount solid intersection checks establish flush seating.

## Vendor mount batch, 2026-10-26

`batch_measurements.json` records the eight independently imported source solid
counts, volumes, native optical datums, selected mounting faces, cylindrical
axes, slot end arcs and STEP/drawing hashes. `normalization.json` records the
corresponding working transforms. `batch_mounting_profiles.json` selects the
component interfaces and mating plate dimensions. No source solids are scaled
or drilled. The MHV asset identities are verified by the product labels and
STEP archive members, despite misleading legacy URL slugs containing
“front-loading”. These are **MHV-12.7L-R and MHV-25.4L-R**, not VMHV.

| Part | Drawing revision | Native height, mm | Source solids |
|---|---|---:|---:|
| POLARIS-L05G | B | 12.7 | 1 |
| POLARIS-L1G | E | 19.05 | 1 |
| POLARIS-K1VS2 | B | 25.4 | 26 |
| MHV-12.7L-R | MHV family E2505 | 12.7 | 9 |
| MHV-25.4L-R | MHV family E2505 | 25.4 | 7 |
| FBR | A | 14.3002 | 7 |
| VA100 | M | 17.78 | 46 |
| POLARIS-K05T6 | G | 12.7 | 31 |

K1VS2's optical datum is the measured optic installation stop, not the compound's
front bounding box. Front-loading optics are displaced relative to that stop
by their thickness; MHV rear-loading optics seat with their reflecting face at
the selected ledge. The MHV-12.7L-R moving plate has small source pose noise,
producing approximately 0.00036 mm³ contact overlap with the nominal mirror,
within the 0.01 mm/0.01° comparison threshold. This source geometry is preserved.

FBR has included Ø3.175 mm pins, not the lab's usual 2 mm pins. Its working
retaining-ring solid is translated to the chosen waveplate face without changing
its dimensions; the cached source remains untouched. The custom 3.20 mm receiving
bore choice is clearance geometry, with no vendor fit tolerance claimed.

VA100's selected 8-32 UNC attachment is 6.35 mm deep. Its 9.652 × 50.8 mm
seating footprint drives the 37 × 56.8 × 10 mm bracket. The independently checked
assembly height is 27.78 mm. Its source mechanical opening is 5.8928 mm; blade
motion cannot be represented by translating the two blade solids alone without
housing collisions. Width 0–6 mm therefore configures only the ideal optical
slit, with the reference mechanical pose explicitly retained in the contract.

The new default coupling uses K05T6's independently measured source solid 25 as
the removed front POLARIS-SM05RR; rear solid 26 remains. The AD1109F shoulder
seats at X=8.0518 mm. Collimator/adapter and collimator/mount overlaps are zero.
Adapter/mount overlap is approximately 4.08248 mm³, confined to the simplified
SM05 engagement envelopes, radius 6.4516–6.795 mm and X=8.0518–11.2268 mm.
Acceptance rejects any overlap outside that annulus. This is a nominal thread
compatibility and envelope check; thread phase, torque and physical assembly
are unresolved fit evidence. The older zero-overlap report above applies only
to explicit KA05TA assemblies.

See [batch verification](component-batch-verification.md) and
[the catalog API](lab-catalog.md) for tests, native heights and drilling selections.
