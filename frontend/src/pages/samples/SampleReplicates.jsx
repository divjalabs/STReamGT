import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../../api/client.js";
import { ReplicateTable } from "../../components/consensus.jsx";

// Standalone (pop-out) replicate-observation table for one sample.
export default function SampleReplicates() {
  const { id } = useParams();
  const [rows, setRows] = useState(null);
  const [label, setLabel] = useState("");
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.getSample(id).then((s) => setLabel(`${s.name} · ${s.system_code}`)).catch(() => {});
    api.getSampleReplicates(id).then(setRows).catch((e) => setErr(e.message));
  }, [id]);

  return (
    <div className="sample-fullwidth">
      <p><Link to={`/samples/${id}`}>← Sample</Link></p>
      <h1>Replicate observations <span className="muted">· {label}</span></h1>
      {err && <p className="error">{err}</p>}
      {!rows ? <p>Loading…</p> : rows.length === 0
        ? <p className="muted">No replicate observations.</p>
        : <ReplicateTable rows={rows} />}
    </div>
  );
}
