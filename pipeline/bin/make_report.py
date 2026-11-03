#!/usr/bin/env python3
"""Generate interactive HTML result reports for a kit run.

Produces two self-contained HTML files from the merged pipeline outputs:
  {kit}_report.html            - read-attrition funnel, reads/alleles per locus & replicate,
                                 plate read-count heatmaps with +/- controls marked (Plotly).
  {kit}_consensus_report.html  - per-sample consensus "fishbone" plots (matplotlib).

Ports the logic from the R drafts (Genotype_stat.Rmd, PlotNGSGenotype.R) to Python. Robust to
empty/missing inputs: writes a valid HTML with a note rather than crashing.
"""
import argparse
import base64
import io
import json
import logging
import re
import sys

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from plotly.offline import get_plotlyjs

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.backends.backend_pdf import PdfPages  # noqa: E402

log = logging.getLogger("make_report")
ROWS = ["A", "B", "C", "D", "E", "F", "G", "H"]  # 8 plate rows


def setup_logging(log_path):
    for h in list(log.handlers):
        log.removeHandler(h)
    log.setLevel(logging.INFO)
    log.propagate = False
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    for handler in (logging.FileHandler(log_path, mode="w"), logging.StreamHandler(sys.stderr)):
        handler.setFormatter(fmt)
        log.addHandler(handler)


def read_table(path, sep="\t"):
    """Read a delimited table; return an empty DataFrame if missing/empty."""
    if not path:
        return pd.DataFrame()
    try:
        return pd.read_csv(path, sep=sep)
    except (FileNotFoundError, pd.errors.EmptyDataError, OSError):
        return pd.DataFrame()


def _is_true(series):
    return series.astype(str).str.upper() == "TRUE"


def _frag(fig):
    """Plotly figure -> HTML fragment (plotly.js is inlined once in <head>, so exclude it here)."""
    return fig.to_html(full_html=False, include_plotlyjs=False, default_height="470px")


def _well_row_col(position):
    # Position is a column-major 1..96 well index: 1->A1, 2->B1, ..., 8->H1, 9->A2, ...
    p = int(position) - 1
    return ROWS[p % 8], (p // 8) + 1


# Control types + a colour per type for the plate marks / controls section.
CONTROL_TYPES = {"positive", "sequencing", "pcr", "extraction", "negative"}
CONTROL_TYPE_COLORS = {
    "positive": "#16a34a",     # green
    "sequencing": "#dc2626",   # red (blank / sequencing negative)
    "pcr": "#f59e0b",          # amber
    "extraction": "#7c3aed",   # violet
    "negative": "#dc2626",     # legacy
}


def _control_type_of(df):
    """Lowercased control_type Series ('' for samples), robust to a missing column."""
    if "control_type" in df.columns:
        return df["control_type"].fillna("").astype(str).str.strip().str.lower()
    return pd.Series([""] * len(df), index=df.index)


def _is_control_series(df):
    return _control_type_of(df).isin(CONTROL_TYPES)


def read_ngsfilter_control_types(path):
    """Map base Sample_Name -> control_type, parsed from the ngsfilter 'control' column.

    The ngsfilter (from make_ngsfilter.py) is the authoritative control source; positions.txt /
    genotypes.txt often lack a control_type column. Its 'sample' field is NAME__POSITION__PPn and
    its 'control' field encodes 'type=control;control_type=X;' for control wells.
    """
    df = read_table(path, sep=",")
    out = {}
    if not df.empty and {"sample", "control"} <= set(df.columns):
        for s, c in zip(df["sample"], df["control"]):
            m = re.search(r"control_type=([^;]+)", str(c))
            if m and m.group(1).strip().lower() in CONTROL_TYPES:
                out[str(s).rsplit("__", 2)[0]] = m.group(1).strip().lower()
    return out


# ---------------- Section 1: read-attrition funnel ----------------

def funnel_section(reads_summary, expected):
    if reads_summary.empty:
        return "<p class='muted'>No reads summary available.</p>"
    row = reads_summary.iloc[0]
    steps = [("reads_sequenced", "Produced"),
             ("reads_paired_filtered", "Paired / aligned"),
             ("reads_pass_ngsfilter", "Assigned to samples")]
    labels = [lab for col, lab in steps if col in reads_summary.columns]
    values = [int(row[col]) for col, _ in steps if col in reads_summary.columns]
    if not values:
        return "<p class='muted'>Reads summary has no expected columns.</p>"

    produced = values[0] or 1
    text = [f"{v:,}<br>{100 * v / produced:.1f}%" for v in values]
    fig = go.Figure(go.Bar(x=labels, y=values, text=text, textposition="outside",
                           marker_color=["#2563eb", "#0891b2", "#059669"][:len(values)]))
    if expected:
        fig.add_hline(y=expected, line_dash="dash", line_color="#dc2626",
                      annotation_text=f"expected {expected:,}", annotation_position="top left")
    fig.update_layout(title="Reads retained at each step",
                      yaxis_title="Number of reads (single-direction)", showlegend=False, margin=dict(t=50))
    html = _frag(fig)

    rows = ["<table class='tbl'><tr><th>Step</th><th>Reads</th><th>% of produced</th><th>% discarded vs previous</th></tr>"]
    prev = None
    for label, v in zip(labels, values):
        drop = "" if prev is None else f"{100 * (prev - v) / prev:.1f}%"
        rows.append(f"<tr><td>{label}</td><td>{v:,}</td><td>{100 * v / produced:.1f}%</td><td>{drop}</td></tr>")
        prev = v
    html += "".join(rows) + "</table>"
    return html


def _fmt_num(v):
    try:
        return f"{float(v):g}"
    except (TypeError, ValueError):
        return "" if v is None else str(v)


def thresholds_section(thresholds):
    """Per-locus effective thresholds (progressive_threshold derives them from each locus's reads)."""
    if thresholds.empty or "Marker" not in thresholds.columns:
        return "<p class='muted'>No per-locus thresholds recorded for this run.</p>"
    df = thresholds.drop_duplicates("Marker").sort_values("Marker")
    intro = ("<p class='muted'>The read-count thresholds actually applied to each locus. With progressive "
             "thresholding these are derived from the locus's own reads: <b>discard</b> = 1.5 × the loudest "
             "negative control; <b>low-allele flag</b> = the 5th percentile of retained reads "
             "(str/snp per locus type).</p>")
    rows = "".join(
        f"<tr><td>{r.Marker}</td><td>{getattr(r, 'locus_type', '')}</td>"
        f"<td style='text-align:right'>{_fmt_num(getattr(r, 'discard_threshold', None))}</td>"
        f"<td style='text-align:right'>{_fmt_num(getattr(r, 'low_allele_flag_threshold', None))}</td></tr>"
        for r in df.itertuples())
    return (intro + "<table style='border-collapse:collapse;margin-top:.5rem' border='1' cellpadding='4'>"
            "<thead><tr><th>Locus</th><th>Type</th><th>discard_threshold</th>"
            "<th>low_allele_flag_threshold</th></tr></thead>"
            f"<tbody>{rows}</tbody></table>")


# ---------------- Section 2: reads and alleles per locus / replicate ----------------

def per_locus_section(genotypes):
    if genotypes.empty:
        return "<p class='muted'>No genotypes available.</p>"
    g = genotypes.copy()
    g = g[~_is_control_series(g)]           # controls are excluded from locus/replicate counts
    if g.empty:
        return "<p class='muted'>No non-control genotypes available.</p>"
    g["called_b"] = _is_true(g["called"])

    per_marker = g.groupby("Marker").agg(
        reads=("Read_Count", "sum"), sequences=("Sequence", "nunique"),
        called_alleles=("called_b", "sum")).reset_index().sort_values("Marker")

    fig = go.Figure(go.Bar(x=per_marker["Marker"], y=per_marker["reads"], marker_color="#2563eb"))
    fig.update_layout(title="Reads per locus", yaxis_title="reads", xaxis_title="locus", margin=dict(t=50))
    html = _frag(fig)

    # Total called alleles first: grouped bars follow trace order, so this one sits on the left of
    # each pair. Colours stay with their meaning (green = called, cyan = unique), not with position.
    fig2 = go.Figure()
    fig2.add_bar(name="total called alleles", x=per_marker["Marker"],
                 y=per_marker["called_alleles"], marker_color="#059669")
    fig2.add_bar(name="unique alleles", x=per_marker["Marker"],
                 y=per_marker["sequences"], marker_color="#0891b2")
    fig2.update_layout(title="Allelic diversity per locus", barmode="group",
                       xaxis_title="locus", yaxis_title="alleles", margin=dict(t=50))
    html += _frag(fig2)

    per_plate = g.groupby("Plate").agg(reads=("Read_Count", "sum"),
                                       called_alleles=("called_b", "sum")).reset_index()
    per_plate["Plate"] = per_plate["Plate"].astype(str)
    fig3 = go.Figure()
    fig3.add_bar(name="reads", x=per_plate["Plate"], y=per_plate["reads"], marker_color="#2563eb", visible=True)
    fig3.add_bar(name="called alleles", x=per_plate["Plate"], y=per_plate["called_alleles"],
                 marker_color="#059669", visible=False)
    fig3.update_layout(
        title=dict(text="Per replicate (plate)", x=0, xanchor="left", y=0.97, yanchor="top"),
        xaxis_title="plate (PP)", yaxis_title="reads", showlegend=False,
        margin=dict(t=110),
        updatemenus=[dict(type="buttons", direction="right", showactive=True,
            x=1, xanchor="right", y=1.22, yanchor="top", pad=dict(t=2, b=2),
            buttons=[
                dict(label="Reads", method="update",
                     args=[{"visible": [True, False]}, {"yaxis": {"title": "reads"}}]),
                dict(label="Called alleles", method="update",
                     args=[{"visible": [False, True]}, {"yaxis": {"title": "called alleles"}}]),
            ])])
    html += _frag(fig3)
    return html


# ---------------- Section 3: plate read-count heatmaps with controls ----------------

SAMPLE_COLOR = "#2563eb"          # same blue as "Reads per locus"
BUBBLE_MIN, BUBBLE_MAX = 6, 30    # marker diameter in px


def _bubble_size(reads, top):
    """Diameter for a read count, scaled so AREA is proportional to reads.

    Perceived quantity follows area, so the radius goes as sqrt(): a linear radius would make the
    loudest well look about four times bigger than it is. Wells with no reads are drawn separately.
    """
    if not top or reads <= 0:
        return BUBBLE_MIN
    return BUBBLE_MIN + (BUBBLE_MAX - BUBBLE_MIN) * (float(reads) / float(top)) ** 0.5


def _nice_round(v):
    """The largest "round" number at or below v, stepping 1 / 2.5 / 5 per decade.

    So a locus topping out at 13,516 reads gets a scale of 10,000 / 2,500 / 500 rather than
    13,516 / 3,379 / 844 — a legend is for reading off, and nobody reads off 3,379.
    """
    if v <= 0:
        return 0
    import math
    decade = 10 ** math.floor(math.log10(v))
    for step in (10, 5, 2.5, 1):
        cand = step * decade
        if cand <= v:
            return int(cand) if cand >= 1 else cand
    return int(decade)


def _scale_legend(top):
    """Three reference circles explaining the sizes, as its own labelled trace.

    Rebuilt per locus because the sizes are rescaled per locus — a circle means nothing without
    the key beside it. The labels are rounded down to readable numbers, and the circle drawn is
    the size that number earns, so what you see is what you can measure against.
    """
    if not top:
        return None
    vals = []
    for raw in (top, top / 4, top / 16):
        v = _nice_round(raw)
        if v > 0 and v not in vals:          # a low-yield locus can collapse these into one
            vals.append(v)
    if not vals:
        return None
    return go.Scatter(
        x=list(range(1, len(vals) + 1)), y=[1] * len(vals), mode="markers+text",
        text=[f"{v:,}" for v in vals], textposition="bottom center",
        textfont=dict(size=10), showlegend=False, hoverinfo="skip",
        marker=dict(size=[_bubble_size(v, top) for v in vals], color=SAMPLE_COLOR,
                    opacity=0.85, line=dict(width=0)))


def _plate_figure(plates, layout_by, reads_by, ctrl_by):
    """Interactive Plotly figure for one locus: every primer plate as an 8x12 grid of circles
    whose AREA is the read count. Samples blue, controls in their type colour, wells that produced
    nothing as a hollow grey ring. Names and counts are on hover only. Sizes are rescaled to this
    locus's loudest well, with a scale strip underneath. Returns a Figure (rendered client-side)."""
    from collections import defaultdict
    ncol = 2 if len(plates) > 1 else 1
    nrow = (len(plates) + ncol - 1) // ncol
    top = max([v for v in reads_by.values() if v], default=0)

    # The scale sits on top, spanning the full width, so it is read before the plates rather
    # than found after them.
    specs = ([[{"colspan": ncol}] + [None] * (ncol - 1)]
             + [[{} for _ in range(ncol)] for _ in range(nrow)])
    titles = ["scale"] + [f"PP{p}" for p in plates]
    fig = make_subplots(rows=nrow + 1, cols=ncol, specs=specs, subplot_titles=titles,
                        row_heights=[0.3] + [1] * nrow,
                        horizontal_spacing=0.06, vertical_spacing=max(0.07, 0.18 / nrow))
    for idx, plate in enumerate(plates):
        r, c = idx // ncol + 2, idx % ncol + 1
        # One trace per control type plus one for samples, so each keeps its own colour; empty
        # wells go in their own trace because a size cannot express "nothing".
        groups = defaultdict(lambda: ([], [], [], []))   # key -> xs, ys, sizes, hover
        for pos in range(1, 97):
            name = layout_by.get((plate, pos))
            if name is None:
                continue                      # no such well in this run's layout
            rr, cc = _well_row_col(pos)
            reads = reads_by.get((plate, pos), 0)
            ctype = ctrl_by.get((plate, pos), "")
            key = ctype if ctype in CONTROL_TYPES else ("sample" if reads else "empty")
            label = f"{name}<br>{reads:,} reads" if reads else f"{name}<br>no reads"
            if ctype in CONTROL_TYPES:
                label = f"{name}<br>{ctype} control<br>{reads:,} reads"
            xs, ys, sz, hv = groups[key]
            xs.append(cc); ys.append(rr); sz.append(_bubble_size(reads, top)); hv.append(label)
        for key, (xs, ys, sz, hv) in groups.items():
            if key == "empty":
                marker = dict(size=BUBBLE_MIN, color="rgba(0,0,0,0)",
                              line=dict(width=1, color="#cbd5e1"))
            else:
                marker = dict(size=sz, opacity=0.85, line=dict(width=0),
                              color=SAMPLE_COLOR if key == "sample"
                              else CONTROL_TYPE_COLORS.get(key, "#64748b"))
            fig.add_trace(go.Scatter(
                x=xs, y=ys, mode="markers", showlegend=False, hovertext=hv,
                hovertemplate="%{hovertext}<extra></extra>", marker=marker), row=r, col=c)

    legend = _scale_legend(top)
    if legend is not None:
        fig.add_trace(legend, row=1, col=1)
        fig.update_xaxes(visible=False, range=[0.4, 4], row=1, col=1)
        fig.update_yaxes(visible=False, range=[0.5, 1.6], row=1, col=1)

    for idx in range(len(plates)):
        r, c = idx // ncol + 2, idx % ncol + 1
        fig.update_xaxes(side="top", dtick=1, tickfont=dict(size=10),
                         range=[0.5, 12.5], row=r, col=c)
        fig.update_yaxes(autorange="reversed", categoryorder="array", categoryarray=ROWS,
                         tickfont=dict(size=10), row=r, col=c)
    # Subplot titles are annotations sitting right on the subplot's top edge, which is also where
    # the position axis lives — so PP5 and the column numbers landed on top of each other.
    for ann in fig.layout.annotations:
        ann.update(yshift=16)
    fig.update_layout(height=340 * nrow + 150, margin=dict(t=50, l=20, r=10, b=10),
                      plot_bgcolor="#f9fafb", font=dict(size=11))
    return fig


def plate_heatmap_section(genotypes, positions, negative_name):
    if positions.empty and genotypes.empty:
        return "<p class='muted'>No data for plate heatmaps.</p>"

    # reads per (marker, plate, position); sample layout per (marker, plate, position)
    reads_by = {}
    if not genotypes.empty:
        gg = genotypes.groupby(["Marker", "Plate", "Position"])["Read_Count"].sum().reset_index()
        for _, r in gg.iterrows():
            reads_by[(str(r["Marker"]), str(r["Plate"]), int(r["Position"]))] = int(r["Read_Count"])
    layout = positions if not positions.empty else genotypes.drop_duplicates(["Marker", "Plate", "Position"])
    layout_by = {}
    for _, r in layout.iterrows():
        layout_by[(str(r["Marker"]), str(r["Plate"]), int(r["Position"]))] = str(r["Sample_Name"])

    # control type per well (plate, position) — a well's type is the same across loci.
    ctrl_by = {}
    lct = _control_type_of(layout)
    for (_, r), ctype in zip(layout.iterrows(), lct):
        if ctype in CONTROL_TYPES:
            ctrl_by[(str(r["Plate"]), int(r["Position"]))] = ctype
    if not ctrl_by:   # back-compat: no control column → fall back to the negative_name substring
        neg = (negative_name or "").lower()
        if neg:
            for (m, pl, pos), name in layout_by.items():
                if neg in name.lower():
                    ctrl_by[(pl, pos)] = "sequencing"

    markers = sorted({k[0] for k in layout_by} | {k[0] for k in reads_by})
    options, figs_json = [], []

    def add(label, plates, lb, rb):
        options.append(f"<option value='{len(options)}'>{label}</option>")
        figs_json.append(_plate_figure(plates, lb, rb, ctrl_by).to_json())

    # "All loci" first: reads summed across every locus per well (well layout is shared across loci).
    all_layout = {(pl, pos): layout_by[(m, pl, pos)] for (m, pl, pos) in layout_by}
    all_reads = {}
    for (m, pl, pos), rc in reads_by.items():
        all_reads[(pl, pos)] = all_reads.get((pl, pos), 0) + rc
    all_plates = sorted({k[0] for k in all_layout} | {k[0] for k in all_reads}, key=lambda p: (len(p), p))
    if all_plates:
        add("All loci (Σ reads)", all_plates, all_layout, all_reads)

    for marker in markers:
        plates = sorted({k[1] for k in layout_by if k[0] == marker} | {k[1] for k in reads_by if k[0] == marker},
                        key=lambda p: (len(p), p))
        if not plates:
            continue
        lb = {(pl, pos): layout_by[(marker, pl, pos)] for (m, pl, pos) in layout_by if m == marker}
        rb = {(pl, pos): reads_by[(marker, pl, pos)] for (m, pl, pos) in reads_by if m == marker}
        add(marker, plates, lb, rb)
    if not options:
        return "<p class='muted'>No plate/marker data.</p>"
    log.info("plate heatmaps: %d loci", len(options))

    legend = " ".join(
        f"<span style='color:{c}'>●</span> {t}" for t, c in CONTROL_TYPE_COLORS.items()
        if t != "negative")
    intro = ("<p class='muted'>Each primer plate (PP) as an 8×12 grid. <b>Circle area is the read "
             f"count</b> — the scale underneath gives the numbers. <span style='color:{SAMPLE_COLOR}'>●</span> "
             "sample; controls in their own colour: " + legend +
             "; a hollow ring is a well that produced no reads. Sizes are rescaled to the loudest "
             "well of the locus you are viewing, so pick a locus and hover a circle for its name "
             "and exact count.</p>")
    select = ("<label>Locus: <select onchange='showPlate(this.value)' style='font-size:1rem;padding:.3rem'>"
              + "".join(options) + "</select></label>")
    script = ("<script>var PLATE_FIGS=[" + ",".join(figs_json) + "];"
              "function showPlate(i){var f=PLATE_FIGS[i];"
              "Plotly.react('plate-plot',f.data,f.layout,{responsive:true});}"
              "document.addEventListener('DOMContentLoaded',function(){showPlate(0);});</script>")
    return intro + select + "<div id='plate-plot' style='min-height:520px'></div>" + script


# ---------------- Section 4: per-sample consensus plots (matplotlib) ----------------

def consensus_report_html(kit_id, genotypes, reference, consensus):
    if genotypes.empty:
        return _wrap_html(f"{kit_id} — consensus plots", "<h1>Consensus plots</h1><p>No genotypes to plot.</p>")
    g = genotypes.copy()
    g["flagged"] = g["flag"].fillna("").astype(str).replace("nan", "") != ""
    if not reference.empty:
        g = g.merge(reference[["Marker", "Sequence", "AlleleName"]], on=["Marker", "Sequence"], how="left")
    cons = consensus.rename(columns={"Sample": "Sample_Name", "Mrkr": "Marker"}) if not consensus.empty else pd.DataFrame()

    items = []  # (sample, png_b64, pdf_b64) — PNG for fast inline preview, PDF for download
    all_pdf = io.BytesIO()
    with PdfPages(all_pdf) as pdf_all:
        for sample, sd in g.groupby("Sample_Name"):
            markers = sorted(sd["Marker"].unique())
            ncol = min(4, max(1, len(markers)))
            nrow = (len(markers) + ncol - 1) // ncol
            fig, axes = plt.subplots(nrow, ncol, figsize=(4 * ncol, 3 * nrow), squeeze=False)
            for ax in axes.flat:
                ax.axis("off")
            for idx, marker in enumerate(markers):
                ax = axes[idx // ncol][idx % ncol]
                ax.axis("on")
                md = sd[sd["Marker"] == marker]
                for _, grp in md.groupby("TagCombo"):
                    grp = grp.sort_values("length")
                    ax.plot(grp["length"], grp["Read_Count"], color="orange", alpha=0.5, linewidth=0.8)
                ax.scatter(md["length"], md["Read_Count"],
                           c=["#dc2626" if f else "#111827" for f in md["flagged"]], s=18, zorder=3)
                title = marker
                if not cons.empty:
                    cr = cons[(cons["Sample_Name"] == sample) & (cons["Marker"] == marker)]
                    if not cr.empty:
                        a1, a2 = str(cr.iloc[0].get("Al1", "")), str(cr.iloc[0].get("Al2", ""))
                        title = f"{marker}: {a1}/{a2}".replace("nan", "").rstrip("/")
                ax.set_title(title, fontsize=8, color="#b91c1c")
                ax.tick_params(labelsize=6)
            fig.suptitle(f"Sample: {sample}", fontsize=11)
            fig.tight_layout(rect=[0, 0, 1, 0.97])
            png = io.BytesIO(); fig.savefig(png, format="png", dpi=110)
            pdf = io.BytesIO(); fig.savefig(pdf, format="pdf")
            pdf_all.savefig(fig)  # one page per sample in the combined PDF
            plt.close(fig)
            items.append((str(sample), base64.b64encode(png.getvalue()).decode(),
                          base64.b64encode(pdf.getvalue()).decode()))
    log.info("consensus plots: %d samples", len(items))
    if not items:
        return _wrap_html(f"{kit_id} — consensus plots", "<h1>Consensus plots</h1><p>No samples.</p>")
    all_pdf_b64 = base64.b64encode(all_pdf.getvalue()).decode()

    # one sample shown at a time; typeable selector; PDF download of the current sample or all samples.
    dopts = "".join(f"<option value=\"{s}\"></option>" for s, _, _ in items)
    divs = "".join(
        f"<div id='samp-{i}' class='sampfig' style='display:{'block' if i == 0 else 'none'}'>"
        f"<p><a class='dl' download='{kit_id}_{s}_consensus.pdf' "
        f"href='data:application/pdf;base64,{pdfb}'>⬇ Download {s} plot (PDF)</a></p>"
        f"<img src='data:image/png;base64,{pngb}' style='max-width:100%'></div>"
        for i, (s, pngb, pdfb) in enumerate(items))
    idx_map = json.dumps({s: i for i, (s, _, _) in enumerate(items)})
    selector = ("<label>Sample: <input list='samplelist' placeholder='type or pick a sample…' "
                "oninput='showSample(this.value)' autocomplete='off' "
                "style='font-size:1rem;padding:.35rem;min-width:260px'>"
                f"<datalist id='samplelist'>{dopts}</datalist></label>")
    all_dl = (f"<a class='dl' download='{kit_id}_consensus_plots.pdf' "
              f"href='data:application/pdf;base64,{all_pdf_b64}'>⬇ Download all samples (PDF)</a>")
    script = ("<script>var SAMP=" + idx_map + ";function showSample(v){if(!(v in SAMP))return;"
              "document.querySelectorAll('.sampfig').forEach(function(e){e.style.display='none'});"
              "document.getElementById('samp-'+SAMP[v]).style.display='block';}</script>")
    body = ("<h1>Consensus genotype plots</h1>"
            "<p class='muted'>Read count vs allele length; orange lines = replicates, red points = "
            "flagged. Title shows the consensus alleles. Pick a sample to view; download the current "
            "sample or all samples as PDF.</p>"
            + "<p>" + selector + " &nbsp; " + all_dl + "</p>" + divs + script)
    return _wrap_html(f"{kit_id} — consensus plots", body)


# ---------------- assembly ----------------

_STYLE = """<style>body{font:15px system-ui,sans-serif;margin:1.5rem;color:#1c2430;max-width:1100px}
h1{font-size:1.5rem}h2{margin-top:2rem;border-bottom:1px solid #e2e5ea;padding-bottom:.3rem}
h3{margin-top:1.4rem}.muted{color:#6b7280}.tbl{border-collapse:collapse;margin:.6rem 0}
.tbl th,.tbl td{border:1px solid #e2e5ea;padding:.3rem .6rem;text-align:left;font-size:.9rem}
.tbl th{background:#f0f2f5}
.dl{display:inline-block;background:#eef2ff;color:#2563eb;padding:.35rem .7rem;border-radius:6px;text-decoration:none;font-weight:500}
.dl:hover{background:#dfe6ff}</style>"""


def _wrap_html(title, body, plotlyjs=None):
    head = _STYLE + (f"<script>{plotlyjs}</script>" if plotlyjs else "")
    return (f"<!doctype html><html><head><meta charset='utf-8'><title>{title}</title>{head}</head>"
            f"<body>{body}</body></html>")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--kit_id", required=True)
    ap.add_argument("--reads_summary")
    ap.add_argument("--genotypes")
    ap.add_argument("--positions")
    ap.add_argument("--frequency")
    ap.add_argument("--consensus")
    ap.add_argument("--reference_alleles")
    ap.add_argument("--ngsfilter")
    ap.add_argument("--parameters_file_path", default="/usr/local/bin/parameters.json")
    ap.add_argument("--thresholds")
    ap.add_argument("--expected_reads", type=int, default=None)
    args = ap.parse_args()
    setup_logging(f"{args.kit_id}_report.log")
    log.info("Building report for kit %s", args.kit_id)

    negative_name = "blank"
    try:
        with open(args.parameters_file_path) as f:
            negative_name = json.load(f).get("negative_name", "blank")
    except (OSError, json.JSONDecodeError):
        log.info("parameters.json unreadable; defaulting negative_name='blank'")

    reads_summary = read_table(args.reads_summary, sep=",")
    genotypes = read_table(args.genotypes)
    positions = read_table(args.positions)
    consensus = read_table(args.consensus)
    reference = read_table(args.reference_alleles)
    thresholds = read_table(args.thresholds, sep=",")

    # Control types come from the ngsfilter (positions/genotypes lack a control_type column). Enrich
    # both frames once so every _control_type_of() consumer (plate heatmap, controls table, per-locus
    # exclusion) picks them up.
    name_ctypes = read_ngsfilter_control_types(args.ngsfilter)
    if name_ctypes:
        for df in (genotypes, positions):
            if not df.empty and "Sample_Name" in df.columns:
                df["control_type"] = df["Sample_Name"].map(name_ctypes).fillna("")
        log.info("ngsfilter control types: %d control samples", len(name_ctypes))

    body = (
        f"<h1>{args.kit_id} — run report</h1>"
        f"<h2>Read attrition</h2>{funnel_section(reads_summary, args.expected_reads)}"
        f"<h2>Reads and alleles per locus / replicate assigned to alleles</h2>{per_locus_section(genotypes)}"
        f"<h2>Thresholds used per locus</h2>{thresholds_section(thresholds)}"
        f"<h2>Plate read counts</h2>{plate_heatmap_section(genotypes, positions, negative_name)}"
    )
    out_main = f"{args.kit_id}_report.html"
    with open(out_main, "w") as f:
        f.write(_wrap_html(f"{args.kit_id} — run report", body, plotlyjs=get_plotlyjs()))
    log.info("wrote %s", out_main)

    out_cons = f"{args.kit_id}_consensus_report.html"
    with open(out_cons, "w") as f:
        f.write(consensus_report_html(args.kit_id, genotypes, reference, consensus))
    log.info("wrote %s", out_cons)


if __name__ == "__main__":
    main()
