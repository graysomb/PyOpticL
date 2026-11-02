"""Plot the rear 1550 nm pickoff from the exported native CAD trace."""
import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

ROOT = Path(__file__).resolve().parents[1]


def main():
    stem = ROOT / "artifacts/chirped_pulse_amplification_folded"
    report = json.loads(stem.with_suffix(".review.json").read_text())
    document = json.loads((ROOT / "Designs/schematics/cpa-folded/residual-1550.pyopticl-schematic.json").read_text())
    poses = document["layout"]["poses"]
    angle = next(n["parameters"]["fast_axis_angle"] for n in document["nodes"]
                 if n["id"] == "SHG_IR_HWP1")
    fig, ax = plt.subplots(figsize=(10, 8), facecolor="#f6f8fa")
    for segment in report["routes"]["residual-1550"]["trace"]:
        if segment["start_component"] not in ("SHG_IR_M1", "SHG_IR_HWP1", "SHG_IR_PBS1",
                                               "SHG_IR_Pickoff_M1", "SHG_IR_Pickoff_L1"):
            continue
        a, b = segment["start_mm"], segment["end_mm"]
        color = "#a65b18" if segment["end_component"] in (
            "SHG_IR_Pickoff_M1", "SHG_IR_Pickoff_L1", "Pickoff_1550") else "#c14b28"
        ax.plot([a[0], b[0]], [a[1], b[1]], color=color, lw=2.2)
        ax.annotate("", xy=((a[0]+3*b[0])/4, (a[1]+3*b[1])/4),
                    xytext=((3*a[0]+b[0])/4, (3*a[1]+b[1])/4),
                    arrowprops=dict(arrowstyle="->", color=color, lw=2))
    x, y = poses["SHG_IR_PBS1"][:2]
    ax.add_patch(Rectangle((x-6.35, y-6.35), 12.7, 12.7,
                           facecolor="#bbc7df", edgecolor="#536773"))
    for ref, label, offset in (
        ("SHG_IR_M1", "Rear 1550 nm mirror", (15, 10)),
        ("SHG_IR_HWP1", f"Half-wave plate · {angle:g}°", (15, 0)),
        ("SHG_IR_PBS1", "Polarizing beam splitter", (15, -22)),
        ("Residual_1550", "1550 nm receiving coupler", (25, -10)),
        ("SHG_IR_Pickoff_M1", "½-inch mirror", (15, -15)),
        ("SHG_IR_Pickoff_L1", "f = 30 mm lens", (15, 0)),
        ("Pickoff_1550", "Newport 818-BB-30", (-100, 20)),
    ):
        p = poses[ref]
        ax.plot(p[0], p[1], "o", color="#163c54", ms=5)
        ax.annotate(label, xy=p[:2], xytext=offset, textcoords="offset points",
                    fontsize=11, color="#163c54")
    for a, b in (("SHG_IR_M1", "SHG_IR_HWP1"),
                 ("SHG_IR_HWP1", "SHG_IR_PBS1"),
                 ("SHG_IR_PBS1", "Residual_1550")):
        ya, yb = poses[a][1], poses[b][1]
        ax.annotate("", xy=(x-20, ya), xytext=(x-20, yb),
                    arrowprops=dict(arrowstyle="<->", color="#829ba8"))
        ax.text(x-24, (ya+yb)/2, f"{abs(ya-yb):g} mm", ha="right", va="center", fontsize=10)
    lx, ly = poses["SHG_IR_Pickoff_L1"][:2]
    dy = poses["Pickoff_1550"][1]
    ax.annotate("", xy=(lx-20, ly), xytext=(lx-20, dy),
                arrowprops=dict(arrowstyle="<->", color="#829ba8"))
    ax.text(lx-25, (ly+dy)/2, f"{dy-ly:g} mm", ha="right", va="center", fontsize=10)
    ax.set(xlim=(x-65, lx+105), ylim=(poses["Residual_1550"][1]-30, dy+50),
           xlabel="X (mm)", ylabel="Y (mm)", aspect="equal")
    ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Rear 1550 nm · adjustable pickoff", fontsize=18, color="#18384b")
    fig.text(.1, .04, "Native center rays · editable waveplate angle and spacings\nTransmitted → receiving coupler; reflected → mirror → lens → photodetector",
             fontsize=11, color="#536773")
    fig.tight_layout(rect=(0, .1, 1, .94))
    fig.savefig(stem.with_name(stem.name + "_rear_pickoff.png"), dpi=160)


if __name__ == "__main__":
    main()
