// One consensus "fishbone" plot for a marker: X = allele length, Y = read count.
// Dashed polyline per PCR replicate. Points: black dot = allele, red = flagged, square = stutter.
// Allele names are labelled near the tallest point of each distinct allele (lengths can collide).
export function GenotypePlot({ plot, width = 300, height = 210, subtitle }) {
  const pad = { l: 42, r: 18, t: subtitle ? 34 : 24, b: 26 };
  const pts = plot.points || [];
  const xs = pts.map((p) => p.length);
  const ys = pts.map((p) => p.reads);
  const xmin = xs.length ? Math.min(...xs) : 0;
  const xmax = xs.length ? Math.max(...xs) : 1;
  const ymax = Math.max(1, ...ys);
  // inset the domain so extreme points (and their labels) don't sit on / over the axes
  const xgap = Math.max((xmax - xmin) * 0.18, 1);
  const dmin = xmin - xgap, dmax = xmax + xgap;
  const xr = dmax - dmin || 1;
  const px = (x) => pad.l + ((x - dmin) / xr) * (width - pad.l - pad.r);
  const py = (y) => height - pad.b - (y / ymax) * (height - pad.t - pad.b);

  // one label per distinct allele, placed at its tallest observation
  const byName = {};
  for (const p of pts) {
    if (!p.allele_name) continue;
    if (!byName[p.allele_name] || p.reads > byName[p.allele_name].reads) byName[p.allele_name] = p;
  }

  return (
    <figure className="gplot">
      <svg viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img"
           aria-label={`Genotype plot ${plot.title}`}>
        <text x={width / 2} y={14} textAnchor="middle" className="gplot-title">{plot.title}</text>
        {subtitle && <text x={width / 2} y={27} textAnchor="middle" className="gplot-subtitle">{subtitle}</text>}
        {/* axes */}
        <line x1={pad.l} y1={pad.t} x2={pad.l} y2={height - pad.b} className="gplot-axis" />
        <line x1={pad.l} y1={height - pad.b} x2={width - pad.r} y2={height - pad.b} className="gplot-axis" />
        <text x={4} y={pad.t + 4} className="gplot-tick">{ymax}</text>
        <text x={4} y={height - pad.b} className="gplot-tick">0</text>
        <text x={px(xmin)} y={height - 6} textAnchor="middle" className="gplot-tick">{xmin}</text>
        <text x={px(xmax)} y={height - 6} textAnchor="middle" className="gplot-tick">{xmax}</text>
        {/* replicate polylines (dashed) */}
        {(plot.lines || []).map((line, i) => (
          <polyline key={i} className="gplot-line"
                    points={line.map(([x, y]) => `${px(x)},${py(y)}`).join(" ")} />
        ))}
        {/* observed alleles: square = stutter, circle otherwise; red = flagged, black = normal */}
        {pts.map((p, i) => {
          const cx = px(p.length), cy = py(p.reads);
          const cls = `gplot-pt${p.flagged ? " flagged" : ""}`;
          const tip = `${p.allele_name ?? "?"} · ${p.length} bp · ${p.reads} reads${p.stutter ? " · stutter" : ""}${p.flagged ? " · flagged" : ""}`;
          return p.stutter ? (
            <rect key={i} x={cx - 3} y={cy - 3} width={6} height={6} className={cls}>
              <title>{tip}</title>
            </rect>
          ) : (
            <circle key={i} cx={cx} cy={cy} r={3.2} className={cls}><title>{tip}</title></circle>
          );
        })}
        {/* allele-name labels (anchor leftward near the right edge so they don't overflow) */}
        {Object.values(byName).map((p, i) => {
          const x = px(p.length);
          const right = x > pad.l + (width - pad.l - pad.r) * 0.72;
          return (
            <text key={i} x={x + (right ? -5 : 5)} y={py(p.reads) - 4}
                  textAnchor={right ? "end" : "start"} className="gplot-label">{p.allele_name}</text>
          );
        })}
        {!pts.length && (
          <text x={width / 2} y={height / 2} textAnchor="middle" className="gplot-tick">no called alleles</text>
        )}
      </svg>
    </figure>
  );
}
