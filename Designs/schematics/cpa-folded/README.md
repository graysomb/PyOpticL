# Folded CPA variant

This independent version folds both dispersive stages. The
stretcher uses one grating and one 1-inch, 500 mm lens four times. With its axis at
12.7 mm, the lens receives the beam at 15.525 mm and returns it at 9.875 mm. A D-shaped
pickoff sends the lower beam through VA100 to the end retroreflector, which
returns the complete path to the launching coupler.

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

The compressor input leg is at Y=-300 mm and the vertical roof entrance at
Y=-400 mm. The horizontal roof is entered through B first, putting the
intermediate corridor on the side that clears the final pickoff. A half-inch
PFD05-03-P01 in KM05DL replaces the final mirror, with its interaction at
(320,-220,9.875) mm. CP_M1 also uses PFD05-03-P01 in KM05DL, with a −5.3 mm
in-plane offset along local Y and a 0.5 mm edge datum. Its interaction remains
(320,-300,15.525) mm. The off-center input D mirror and left-handed final
pickoff clear the intermediate bypasses. The SHG/output chain retains its X/Y positions at
the new 9.875 mm height, including the rear 1550 nm collection mirror and coupler.

Edit the constants in `generate.py`, then regenerate the schematic JSON and
standalone scripts from the repository root:

```bash
python Designs/schematics/cpa-folded/generate.py
```

Use FreeCAD's bundled Python to build `examples/chirped_pulse_amplification_folded.py`.
It writes `artifacts/chirped_pulse_amplification_folded.FCStd`, hardware and
baseplate STEP files, and separate review, BOM and drilling JSON reports.
The baseline CAD and schematic files are not overwritten.

The plate is 33 mm thick with its top at Z=3 mm and underside at Z=-30 mm. Raised
input mounts have supported seats, while taller mounts and the
compressor roof supports receive local recesses. Drilling coordinates are relative
to the plate: report Z=0 corresponds to assembly Z=3 mm. All distances are provisional.

After building, run `python examples/cpa_folded_elevation.py` with matplotlib and
numpy installed to plot the actual native trace. The elevation expands the
vertical scale to show the 5.65 mm separation. The model uses existing ideal
thin-lens behavior, without a detailed aberration or pulse-dispersion calculation.

Run `python examples/cpa_folded_compressor_preview.py` after building to draw the
compressor's ordered roof-return path and four native grating spots.
