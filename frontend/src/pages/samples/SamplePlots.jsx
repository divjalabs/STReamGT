import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import { GenotypePlot } from "../../components/GenotypePlot.jsx";

// Standalone (pop-out) consensus genotype plots for one sample.
export default function SamplePlots() {
  const { id } = useParams();
  const [plots, setPlots] = useState(null);
  const [sample, setSample] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.getSample(id).then(setSample).catch(() => {});
    api.getSamplePlotData(id, []).then(setPlots).catch((e) => setErr(e.message));
  }, [id]);

  const sexMarker = sample?.sex_marker;
  return (
    <div className="sample-fullwidth">
      <p><Link to={`/samples/${id}`}>← Sample</Link></p>
      <h1>Consensus genotype plots {sample && <span className="muted">· {sample.name} · {sample.system_code}</span>}</h1>
      <p className="muted small">Dashed lines = replicates · black = allele · red = flagged · square = stutter.</p>
      {err && <p className="error">{err}</p>}
      {!plots ? <p>Loading…</p> : plots.length === 0 ? <p className="muted">No plot data.</p> : (
        <div className="plot-grid">
          {plots.map((p) => (
            <GenotypePlot key={p.marker} plot={p}
              subtitle={p.marker === sexMarker ? `sex: ${sample?.sex ?? "unknown"}` : undefined} />
          ))}
        </div>
      )}
    </div>
  );
}
