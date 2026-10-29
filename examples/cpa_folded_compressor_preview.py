"""Draw the folded compressor plan and four grating spots from native CAD rays."""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "artifacts/chirped_pulse_amplification_folded.review.json"


def render(report=REPORT, output=None):
    report = Path(report)
    data = json.loads(report.read_text())
    trace = data["routes"]["compressor"]["trace"]
    hits = np.array([s["end_mm"] for s in trace if s["end_component"] == "CP_G1"])
    if hits.shape != (4, 3):
        raise ValueError("Expected four native hits on the shared compressor grating")
    upper, lower = hits[:, 2].max(), hits[:, 2].min()
    colors = ("#82929d", "#bd3c29", "#ba7900", "#268155", "#166eb5")
    background = "#f7f9fb"
    fig, (ax, face) = plt.subplots(
        1,
        2,
        figsize=(15, 8),
        gridspec_kw={"width_ratios": [1.65, 1]},
        facecolor=background,
    )
    for a in (ax, face):
        a.set_facecolor(background)
        a.spines[["top", "right"]].set_visible(False)
    phase = 0
    for segment in trace:
        p, q = np.array(segment["start_mm"]), np.array(segment["end_mm"])
        lower_path = (p[2] + q[2]) / 2 < hits[:, 2].mean() - 0.1
        style = "--" if lower_path else "-"
        ax.plot([p[0], q[0]], [p[1], q[1]], style, color=colors[phase], lw=1.8)
        if np.linalg.norm(q[:2] - p[:2]) > 50:
            start, stop = (0.62, 0.76) if lower_path else (0.28, 0.42)
            a, b = p + start * (q - p), p + stop * (q - p)
            ax.annotate(
                "",
                xy=b[:2],
                xytext=a[:2],
                arrowprops=dict(arrowstyle="-|>", color=colors[phase], lw=1.7),
            )
        if segment["end_component"] == "CP_G1":
            phase += 1

    def entry(ref):
        return next(s["end_mm"][:2] for s in trace if s["end_component"] == ref)

    for ref, label, offset in (
        ("CP_HRoof", "Horizontal roof ×2", (-5, 33)),
        ("CP_VRoof", f"Vertical roof: −{upper-lower:g} mm", (-100, -24)),
        ("CP_G1", "One grating · four passes", (22, 28)),
        ("CP_Pickoff", "D pickoff", (30, 4)),
        ("CP_M1", "Input mirror", (-75, -28)),
        ("SHG_Crystal", f"SHG at {lower:g} mm", (-20, -35)),
    ):
        xy = entry(ref)
        ax.scatter(*xy, s=35, color="#163c54", zorder=8)
        ax.annotate(
            label,
            xy=xy,
            xytext=offset,
            textcoords="offset points",
            fontsize=10,
            color="#163c54",
            bbox=dict(boxstyle="round,pad=.25", fc=background, ec="#c8d2d9"),
            arrowprops=dict(arrowstyle="-", color="#697e8c"),
        )
    source = trace[0]["start_mm"]
    ax.text(
        source[0] + 8,
        source[1] - 3,
        f"Input\n{upper:g} mm",
        fontsize=10,
        color="#536773",
        va="top",
    )
    ax.set(
        xlabel="X (mm)",
        ylabel="Y (mm)",
        xlim=(-150, 570),
        ylim=(-455, 95),
        aspect="equal",
    )
    ax.grid(alpha=0.12)
    ax.set_title(
        "Plan view · native ray segments",
        loc="left",
        fontsize=13,
        color="#163c54",
        pad=15,
    )
    center = hits.mean(axis=0)
    lateral = hits[0] - hits[1]
    lateral[2] = 0
    lateral /= np.linalg.norm(lateral)
    positions = (hits - center) @ lateral
    face.add_patch(
        Rectangle(
            (-15.4, center[2] - 5.65), 30.8, 11.3, fc="#e1ebf1", ec="#8da4b2", lw=1.5
        )
    )
    face.axhline(center[2], color="#8da4b2", lw=1, ls=":")
    face.axvline(0, color="#8da4b2", lw=1, ls=":")
    for i, (position, hit) in enumerate(zip(positions, hits), 1):
        face.scatter(position, hit[2], s=160, color=colors[i], zorder=4)
        face.annotate(
            f"Pass {i}",
            (position, hit[2]),
            xytext=(0, 13 if i < 3 else -23),
            textcoords="offset points",
            ha="center",
            color=colors[i],
            fontsize=11,
            weight="bold",
        )
    face.text(
        0,
        center[2] + 0.35,
        f"Axis: {center[2]:g} mm",
        ha="center",
        color="#536773",
        fontsize=10,
    )
    face.set(
        xlim=(-18, 18),
        ylim=(center[2] - 6.8, center[2] + 6.8),
        xlabel="Position along grating face (mm)",
        ylabel="Height above original datum (mm)",
    )
    face.set_title(
        "Four spots on one grating", loc="left", fontsize=13, color="#163c54", pad=15
    )
    face.text(
        0.5,
        -0.23,
        f"Upper: {upper:g} mm → upper: {upper:g} mm\nLower: {lower:g} mm → lower: {lower:g} mm",
        transform=face.transAxes,
        ha="center",
        va="top",
        fontsize=10,
        color="#536773",
    )
    fig.suptitle(
        "Folded compressor · one grating and two roof mirrors",
        x=0.06,
        ha="left",
        fontsize=20,
        color="#163c54",
        weight="bold",
    )
    fig.text(
        0.06,
        0.9,
        "G1 → horizontal roof → G2 → vertical roof → G3 → horizontal roof → G4 → D pickoff → SHG",
        fontsize=11,
        color="#536773",
    )
    handles = [
        Line2D(
            [0],
            [0],
            color=colors[i],
            lw=2,
            ls="--" if i in (3, 4) else "-",
            label=f"After grating pass {i}",
        )
        for i in range(1, 5)
    ]
    fig.legend(
        handles=handles,
        loc="lower left",
        bbox_to_anchor=(0.06, 0.07),
        ncol=2,
        frameon=False,
        fontsize=10,
    )
    fig.text(
        0.06,
        0.035,
        "Same roof and grating bodies reused. Overlaid return paths use dashed lines; center rays, not a validated beam envelope.",
        fontsize=10,
        color="#536773",
    )
    fig.subplots_adjust(top=0.81, bottom=0.25, left=0.06, right=0.96, wspace=0.32)
    output = Path(
        output
        or report.with_name(report.stem.removesuffix(".review") + "_compressor.png")
    )
    fig.savefig(output, dpi=170, facecolor=background)
    plt.close(fig)
    return output


if __name__ == "__main__":
    print(render())
