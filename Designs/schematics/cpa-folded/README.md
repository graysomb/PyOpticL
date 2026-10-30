# Folded CPA variant

This independent version folds both dispersive stages. The
stretcher uses one grating and one 1-inch, 500 mm lens four times. With its axis at
12.7 mm, the lens receives the beam at 15.525 mm and returns it at 9.875 mm. A D-shaped
pickoff sends the lower beam through VA100 to the end retroreflector, which
returns the complete path to the launching coupler.

Both systems sit along the same front edge of the shared plate. Their couplers
are at (500,-300) mm and (770,-300) mm, 270 mm apart. The stretcher grating is
at (950,-75) mm, beside the compressor. Its input hardware and grating-to-lens
spacing remain fixed.
Edit `STRETCHER_GRATING_X_MM` and `STRETCHER_INPUT_Y_MM` to reposition it.
The default packed plate is 1395 × 435 mm; its footprint is regenerated around
the assemblies.

An additional 1-inch mirror (`ST_Bend`, POLARIS-K1VS2) turns the long stretcher
leg by 90° after the lens. The axial lengths are 325 mm from lens to bend and
175 mm from bend to the existing 1-inch `ST_Fold` end mirror, totaling 500 mm.
The end mirror faces the folded axis and returns both passes through the same
bend mirror and lens. The added mirror is shared across four off-axis visits;
the lens still receives upper, lower, lower and upper encounters. The complete
finite chief-ray path remains 3540.031922 mm. Edit
`STRETCHER_LENS_TO_BEND_MM` and `STRETCHER_BEND_ANGLE_DEG` to change the fold;
the remaining leg length is derived from the unchanged 500 mm lens-to-end span.

The compressor uses one grating four times and two HRS1015-P01 roof assemblies:

```
grating 1 → horizontal roof → grating 2 → vertical roof
          → grating 3 → same horizontal roof → grating 4 → D pickoff → SHG
```

The numbered grating encounters share one physical grating. The horizontal roof
uses a 9.538700743 mm separation, reversed on its second encounter. The vertical roof
lowers the beam by 5.65 mm, giving grating hit heights of 15.525, 15.525, 9.875 and 9.875 mm.
The grating is centered between the two lateral spots. Its four spots lie at
±7.7 mm along the face and ±2.825 mm vertically, centering each quadrant of the
30.8 × 11.3 mm clear aperture. Both folded stages share the 5.65 mm vertical
separation. The compressor’s nominal 430 mm fold plane places the horizontal roof entrance 417.3 mm from the first grating hit;
actual ray lengths also include the finite roof path and lateral walkoff.

The compressor input leg is at Y=-300 mm. CP_M1 is a centered half-inch circular
mirror in POLARIS-K05VS2 at (320,-300,15.525) mm. The vertical roof entrance is at
Y=-100 mm, between the grating and D pickoff. Its physical axis is shifted 5 mm
in negative local Y (negative world X) from the return ray, so the beam enters
and exits the roof intentionally off axis. The revised 2.54 mm integral stops
are retained. Both straight-through beams clear the roof optic and mount with
1 mm radius probes. A 1-inch PFD10-03-P01 in KM100DL at (320,-220,9.875) mm
selects the lower output for SHG. The horizontal roof is entered through B first;
its 9.538700743 mm separation preserves the quadrant-centered grating spots.
The SHG crystal, dichroic and rear 1550 nm collection hardware retain their
X/Y positions and 9.875 mm height. The two 30 mm SHG lenses are constrained
60 mm apart, with their physical optical centers at X=130 mm and X=70 mm.
The crystal center stays at X=100 mm, exactly 30 mm from each lens. The input
route constrains lens-to-crystal-center distance to 30 mm. The output routes
start at the crystal exit (X=86.3 mm) and constrain its distance to the shared
output lens to 16.3 mm. The folded CAD builder rejects inconsistent lens
spacing, midpoint or wavelength-boundary placement across the schematic files.
`SHG_LENS_SEPARATION_MM` is the shared editable spacing parameter.

The rear 1550 nm receiving leg now runs through `SHG_IR_HWP1` (FBR half-wave
plate) and `SHG_IR_PBS1` (12.7 mm polarizing cube in the library's integral
PBS holder). The transmitted beam continues toward -Y into the existing
`Residual_1550` coupler; the reflected beam exits toward +X as the open
`Pickoff_1550` output. No additional receiving coupler is added to that branch.
Mirror-to-waveplate, waveplate-to-PBS and PBS-to-coupler spacings are
30, 30 and 60 mm, preserving the original 120 mm receiving leg and coupler position.
Edit the `REAR_*` constants to change these distances, the 100 mm pickoff guide,
or the initial 22.5° waveplate fast-axis angle. This angle controls the ideal
polarization split; the exact 1550 nm cube coating remains unselected.

Edit the constants in `generate.py`, then regenerate the schematic JSON and
standalone scripts from the repository root:

```bash
python Designs/schematics/cpa-folded/generate.py
```

Use FreeCAD's bundled Python to build `examples/chirped_pulse_amplification_folded.py`.
It writes `artifacts/chirped_pulse_amplification_folded.FCStd`, hardware and
baseplate STEP files, and separate review, BOM and drilling JSON reports.
The baseline CAD and schematic files are not overwritten.

Both D-shaped mirrors use 1-inch PFD10-03-P01 optics: KM100D for the stretcher
and KM100DL for the compressor. Their optical datums and beam paths are retained.
Each mounting profile includes its M4 screw and two rear-contact locating pins,
22 mm apart, tangent to the fixed base rather than the moving mirror plate.

The plate is 36 mm thick with its top at Z=3 mm and underside at Z=-33 mm. This
contains the deeper 1-inch D-mirror recesses and their 10 mm blind mounting bores.
Raised
input mounts have supported seats, while taller mounts and the
compressor roof supports receive local recesses. Both D-mirror mount recesses
have twice the usual width and length for Allen-key adjuster access, retaining
their original seat depths and screw locations. Each D mirror also has two
plate dowel holes for 2 mm × 5 mm pins tangent to the fixed base rear face:
nominal Ø2.01 mm, 4 mm straight depth, projecting 1 mm above the recess floor.
Drilling coordinates are relative
to the plate: report Z=0 corresponds to assembly Z=3 mm. All distances are provisional.

All three lens-mount recesses are aligned with their lens axes. Each is extended
12 mm along that axis (6 mm at each end), preserving transverse width, seat
depth and attachment-hole positions. The drilling report includes each
rectangle's rotated origin, local dimensions and orientation.

After building, run `python examples/cpa_folded_elevation.py` with matplotlib and
numpy installed to plot the actual native trace. The elevation expands the
vertical scale to show the 5.65 mm separation. The model uses existing ideal
thin-lens behavior, without a detailed aberration or pulse-dispersion calculation.

Run `python examples/cpa_folded_compressor_preview.py` after building to draw the
compressor's ordered roof-return path and four native grating spots.
Run `python examples/cpa_folded_rear_pickoff_preview.py` for the rear 1550 nm
waveplate/PBS/coupler routing and its separate pickoff output.
