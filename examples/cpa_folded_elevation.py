"""Plot the actual native folded-stretcher trace from its review JSON.

Run with a Python containing numpy and matplotlib after building the folded CAD.
The vertical scale is deliberately expanded to show the path separation.
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "artifacts/chirped_pulse_amplification_folded.review.json"


def render(report=REPORT, output=None):
    report = Path(report)
    data = json.loads(report.read_text())
    trace = data["routes"]["stretcher"]["trace"]
    lens = np.array(next(s["end_mm"] for s in trace if s["end_component"] == "ST_L2"))
    fold = np.array(next(s["end_mm"] for s in trace if s["end_component"] == "ST_Fold"))
    bend_segment = next((s for s in trace if s["end_component"] == "ST_Bend"), None)
    bend = np.array(bend_segment["end_mm"]) if bend_segment else None
    gx = -np.linalg.norm(
        np.array(next(s["end_mm"] for s in trace if s["end_component"] == "ST_G2"))[:2]
        - lens[:2]
    )
    bx = np.linalg.norm(bend[:2] - lens[:2]) if bend is not None else None
    fx = (
        bx + np.linalg.norm(fold[:2] - bend[:2])
        if bend is not None
        else np.linalg.norm(fold[:2] - lens[:2])
    )
    axial = {"ST_G2": gx, "ST_L2": 0.0, "ST_Fold": fx}
    if bend is not None:
        axial["ST_Bend"] = bx
    optical = set(axial)
    forward = [
        s
        for s in trace
        if s["start_component"] in optical and s["end_component"] in optical
    ][: 6 if bend is not None else 4]
    hits = [s["end_mm"][2] for s in trace if s["end_component"] == "ST_L2"]
    upper, lower = max(hits), min(hits)
    center = fold[2]

    fig, ax = plt.subplots(figsize=(13, 6.8), facecolor="#f7f9fb")
    ax.set_facecolor("#f7f9fb")
    colors = (
        ("#b65c00", "#bc3a26", "#bc3a26", "#27794e", "#27794e", "#176cb4")
        if bend is not None
        else ("#b65c00", "#bc3a26", "#27794e", "#176cb4")
    )
    for segment, color in zip(forward, colors):
        a, b = np.array(segment["start_mm"]), np.array(segment["end_mm"])
        x = np.array(
            [axial[segment["start_component"]], axial[segment["end_component"]]]
        )
        z = np.array([a[2], b[2]])
        ax.plot(x, z, lw=2.6, color=color)
        p, q = 0.43, 0.57
        ax.annotate(
            "",
            xy=(x[0] + q * (x[1] - x[0]), z[0] + q * (z[1] - z[0])),
            xytext=(x[0] + p * (x[1] - x[0]), z[0] + p * (z[1] - z[0])),
            arrowprops=dict(arrowstyle="-|>", color=color, lw=2, mutation_scale=15),
        )
    ax.axhline(center, color="#83919d", ls="--", lw=1)
    ax.plot([0, 0], [lower - 1, upper + 1], color="#4b8fba", lw=7, alpha=0.5)
    ax.plot([gx, gx], [lower - 0.6, upper + 0.6], color="#314f60", lw=5)
    ax.plot([fx, fx], [lower - 1, upper + 1], color="#46535e", lw=5)
    if bx is not None:
        ax.axvline(bx, color="#46535e", ls=":", lw=1.5)
    ax.scatter([0] * 4, hits, s=40, color="#163c54", zorder=5)
    ax.annotate(
        "",
        xy=(-35, upper),
        xytext=(-35, lower),
        ha="center",
        va="center",
        arrowprops=dict(arrowstyle="<->", color="#536773"),
        fontsize=12,
        color="#163c54",
    )
    ax.text(
        -35,
        center,
        f"{upper - lower:g} mm",
        ha="center",
        va="center",
        bbox=dict(facecolor="#f7f9fb", edgecolor="none", pad=3),
        color="#163c54",
        fontsize=12,
    )
    ax.annotate(
        "",
        xy=(fx, upper + 0.8),
        xytext=(0, upper + 0.8),
        arrowprops=dict(arrowstyle="<->", color="#718594"),
    )
    ax.text(
        fx / 2, upper + 1.02, f"{fx:g} mm axial distance", ha="center", color="#536773"
    )
    labels = [
        (gx, "Grating"),
        (0, "1-inch lens\nf = 500 mm"),
        (fx, "1-inch end mirror"),
    ]
    if bx is not None:
        labels.append((bx, "1-inch bend mirror\n90° turn in plan"))
    for x, label in labels:
        ax.text(
            x, lower - 1.35, label, ha="center", va="top", fontsize=11, color="#163c54"
        )
    ax.text(17, upper + 0.12, f"Upper pass: {upper:g} mm", color=colors[1], fontsize=11)
    ax.text(17, lower - 0.4, f"Lower pass: {lower:g} mm", color=colors[3], fontsize=11)
    ax.text(
        fx * 0.68,
        center + 0.18,
        f"Lens axis: {center:g} mm",
        color="#536773",
        fontsize=10,
    )
    ax.set(
        xlim=(gx - 30, fx + 40),
        ylim=(lower - 2.1, upper + 1.6),
        xlabel="Unfolded axial distance from lens toward end mirror (mm)",
        ylabel="Height above original datum (mm)",
    )
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", alpha=0.16)
    fig.suptitle(
        "Folded stretcher · native CAD ray trace",
        x=0.08,
        ha="left",
        fontsize=20,
        color="#163c54",
        weight="bold",
    )
    fig.text(
        0.08,
        0.9,
        (
            "Upper beam → lens → bend mirror → end mirror → bend mirror → lens → lower beam"
            if bend is not None
            else "Upper beam → lens → midpoint mirror → same lens → lower beam"
        ),
        fontsize=12,
        color="#536773",
    )
    fig.text(
        0.08,
        0.065,
        "Lower beam → same grating → D pickoff → VA100 → retroreflector; the full path then retraces.",
        fontsize=10,
        color="#536773",
    )
    fig.text(
        0.08,
        0.03,
        "Vertical scale expanded. Lens hits: upper, lower, lower, upper. Ideal thin-lens model; center rays only.",
        fontsize=10,
        color="#536773",
    )
    fig.subplots_adjust(top=0.83, bottom=0.19, left=0.08, right=0.96)
    output = Path(
        output
        or report.with_name(report.stem.removesuffix(".review") + "_elevation.png")
    )
    fig.savefig(output, dpi=180, facecolor=fig.get_facecolor())
    plt.close(fig)
    return output


if __name__ == "__main__":
    print(render())
