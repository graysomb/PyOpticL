# Folded CPA variant

This independent version retains the baseline compressor and SHG routes. The
stretcher uses one grating and one 1-inch, 500 mm lens four times. With its axis at
12.7 mm, the lens receives the beam at 14.7 mm and returns it at 10.7 mm. A D-shaped
pickoff sends the lower beam through VA100 to the end retroreflector, which
returns the complete path to the launching coupler.

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
input mounts have supported seats, while taller mounts and the unchanged
compressor roof support receive local recesses. All distances are provisional.

After building, run `python examples/cpa_folded_elevation.py` with matplotlib and
numpy installed to plot the actual native trace. The elevation expands the
vertical scale to show the 4 mm separation. The model uses existing ideal
thin-lens behavior, without a detailed aberration or pulse-dispersion calculation.
