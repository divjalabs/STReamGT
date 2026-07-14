import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api, uploadFile } from "../api/client.js";
import SampleTable, { rowsToSampleText, filledWellCount, TOTAL_WELLS } from "../components/SampleTable.jsx";

let batchSeq = 1;
const newBatch = () => ({
  uid: batchSeq++,
  name: "",
  sampleMode: "upload", // "upload" | "table"
  sampleFile: null,
  sampleRows: [],
  selectedTags: [],
});

export default function Submit() {
  const nav = useNavigate();
  const [kits, setKits] = useState([]);
  const [kitId, setKitId] = useState("");
  const [fastqMode, setFastqMode] = useState("upload"); // "upload" | "ref"
  const [fq1, setFq1] = useState({ file: null, ref: "", pct: 0 });
  const [fq2, setFq2] = useState({ file: null, ref: "", pct: 0 });
  const [expectedReads, setExpectedReads] = useState(10000000);
  const [batches, setBatches] = useState([newBatch()]);
  const [jobs, setJobs] = useState([]);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  useEffect(() => {
    api.listKits().then(setKits).catch((e) => setErr(e.message));
    api.listJobs().then(setJobs).catch(() => {});
  }, []);

  const kit = kits.find((k) => String(k.id) === String(kitId));
  // A kit may have only one job in flight; block resubmission until it finishes.
  const TERMINAL = ["succeeded", "failed"];
  const kitBusy = !!kit && jobs.some((j) => j.kit_id === kit.id && !TERMINAL.includes(j.status));

  // When a kit is picked, tick all of its tag columns in the FIRST batch only; later
  // batches start empty (each PP column can belong to just one batch — see cross-check below).
  useEffect(() => {
    if (!kit) return;
    const all = kit.tag_columns.map((t) => t.name);
    setBatches((bs) => bs.map((b, i) => ({ ...b, selectedTags: i === 0 ? all : [] })));
  }, [kitId]);

  const setBatch = (uid, patch) =>
    setBatches((bs) => bs.map((b) => (b.uid === uid ? { ...b, ...patch } : b)));
  const toggleTag = (uid, name) =>
    setBatches((bs) =>
      bs.map((b) =>
        b.uid === uid
          ? {
              ...b,
              selectedTags: b.selectedTags.includes(name)
                ? b.selectedTags.filter((t) => t !== name)
                : [...b.selectedTags, name],
            }
          : b
      )
    );

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    if (!kit) return setErr("Choose a kit.");
    if (kit.status === "analysed")
      return setErr("This kit has already been analysed. Contact an admin to re-enable it (reanalyse).");
    if (kitBusy)
      return setErr("A job for this kit is already running. Wait for it to finish before submitting again.");
    setBusy(true);
    try {
      // 1. FASTQ: upload or reference.
      let fastq_source = "upload";
      let fastq1_ref, fastq2_ref;
      if (fastqMode === "upload") {
        if (!fq1.file || !fq2.file) throw new Error("Upload both FASTQ files.");
        fastq1_ref = await uploadFile(fq1.file, "fastq", (p) => setFq1((s) => ({ ...s, pct: p })));
        fastq2_ref = await uploadFile(fq2.file, "fastq", (p) => setFq2((s) => ({ ...s, pct: p })));
      } else {
        if (!fq1.ref || !fq2.ref) throw new Error("Provide both FASTQ paths/links.");
        fastq_source = fq1.ref.startsWith("http") ? "link" : "server";
        fastq1_ref = fq1.ref;
        fastq2_ref = fq2.ref;
      }

      // 2. Batches: upload sample sheets or send pasted text.
      const outBatches = [];
      const seenTags = new Set();
      for (const b of batches) {
        if (!b.name) throw new Error("Every batch needs a name.");
        if (b.selectedTags.length === 0) throw new Error(`Batch ${b.name}: pick at least one tag column.`);
        const dup = b.selectedTags.filter((t) => seenTags.has(t));
        if (dup.length)
          throw new Error(`Batch ${b.name}: PP column(s) ${dup.join(", ")} are already used in another batch.`);
        b.selectedTags.forEach((t) => seenTags.add(t));
        const out = { name: b.name, selected_tags: b.selectedTags };
        if (b.sampleMode === "upload") {
          if (!b.sampleFile) throw new Error(`Batch ${b.name}: upload a sample sheet.`);
          out.sample_sheet_key = await uploadFile(b.sampleFile, "sample");
        } else {
          const n = filledWellCount(b.sampleRows);
          if (n < TOTAL_WELLS) throw new Error(`Batch ${b.name}: all ${TOTAL_WELLS} wells must be filled (currently ${n}).`);
          out.sample_names_text = rowsToSampleText(b.sampleRows);
        }
        outBatches.push(out);
      }

      // 3. Create the job.
      const job = await api.createJob({
        kit_id: kit.id,
        fastq_source,
        fastq1_ref,
        fastq2_ref,
        expected_read_number: Number(expectedReads) || null,
        batches: outBatches,
      });
      nav(`/jobs/${job.public_id}`);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="container">
      <h1>Analyse the data</h1>
      {err && <p className="error">{err}</p>}
      <form onSubmit={submit}>
        <section className="card">
          <label>
            Library (kit) name
            <select value={kitId} onChange={(e) => setKitId(e.target.value)} required>
              <option value="">— choose a kit —</option>
              {kits.map((k) => (
                <option key={k.id} value={k.id}>{k.kit_code}{k.species ? ` (${k.species})` : ""}</option>
              ))}
            </select>
          </label>
          {kit && <p className="muted">Species: <b>{kit.species || "—"}</b> · tag columns: {kit.tag_columns.map((t) => t.name).join(", ")}</p>}
          {kit && kit.status === "analysed" && (
            <p className="error">⚠️ Each kit can be analysed only once. This kit is already analysed — contact an admin to re-enable it (reanalyse).</p>
          )}
          {kit && kitBusy && (
            <p className="error">⚠️ A job for this kit is already running. Wait for it to finish before submitting again.</p>
          )}
        </section>

        <section className="card">
          <h2>FASTQ (one pair per run, shared by all batches)</h2>
          <div className="tabs">
            <button type="button" className={fastqMode === "upload" ? "active" : ""} onClick={() => setFastqMode("upload")}>Upload</button>
            <button type="button" className={fastqMode === "ref" ? "active" : ""} onClick={() => setFastqMode("ref")}>Server path / link</button>
          </div>
          {fastqMode === "upload" ? (
            <>
              <label>fastqF (R1)<input type="file" accept=".gz,.fastq" onChange={(e) => setFq1({ ...fq1, file: e.target.files[0] })} /></label>
              {fq1.pct > 0 && <Progress pct={fq1.pct} />}
              <label>fastqR (R2)<input type="file" accept=".gz,.fastq" onChange={(e) => setFq2({ ...fq2, file: e.target.files[0] })} /></label>
              {fq2.pct > 0 && <Progress pct={fq2.pct} />}
            </>
          ) : (
            <>
              <label>fastqF (R1) path or URL<input value={fq1.ref} onChange={(e) => setFq1({ ...fq1, ref: e.target.value })} placeholder="s3 key / /server/path / https://…" /></label>
              <label>fastqR (R2) path or URL<input value={fq2.ref} onChange={(e) => setFq2({ ...fq2, ref: e.target.value })} /></label>
            </>
          )}
          <label>Expected read number (for QC report)
            <input type="number" value={expectedReads} onChange={(e) => setExpectedReads(e.target.value)} />
          </label>
        </section>

        {batches.map((b, i) => {
          const usedElsewhere = new Set(
            batches.filter((x) => x.uid !== b.uid).flatMap((x) => x.selectedTags)
          );
          return (
          <section className="card" key={b.uid}>
            <div className="row">
              <h2>Sample batch {i + 1}</h2>
              <span className="spacer" />
              {batches.length > 1 && (
                <button type="button" className="link" onClick={() => setBatches((bs) => bs.filter((x) => x.uid !== b.uid))}>remove</button>
              )}
            </div>
            <label>Batch name<input value={b.name} onChange={(e) => setBatch(b.uid, { name: e.target.value })} placeholder="e.g. HRM01" /></label>

            <fieldset>
              <legend>Samples</legend>
              <div className="tabs">
                <button type="button" className={b.sampleMode === "upload" ? "active" : ""} onClick={() => setBatch(b.uid, { sampleMode: "upload" })}>Upload Excel</button>
                <button type="button" className={b.sampleMode === "table" ? "active" : ""} onClick={() => setBatch(b.uid, { sampleMode: "table" })}>Enter samples</button>
              </div>
              {b.sampleMode === "upload" ? (
                <input type="file" accept=".xlsx" onChange={(e) => setBatch(b.uid, { sampleFile: e.target.files[0] })} />
              ) : (
                <SampleTable value={b.sampleRows} onChange={(rows) => setBatch(b.uid, { sampleRows: rows })} />
              )}
            </fieldset>

            <fieldset>
              <legend>Tags (PP columns)</legend>
              {!kit ? (
                <p className="muted">Choose a kit to see its tag columns.</p>
              ) : (
                <>
                  {batches.length > 1 && (
                    <p className="muted">Each PP column belongs to a single batch — columns already used in another batch are disabled here.</p>
                  )}
                  <div className="chips">
                    {kit.tag_columns.map((t) => {
                      const taken = usedElsewhere.has(t.name);
                      return (
                        <label
                          key={t.name}
                          className={`chip ${b.selectedTags.includes(t.name) ? "on" : ""}${taken ? " disabled" : ""}`}
                          title={taken ? "Already assigned to another batch" : undefined}
                        >
                          <input
                            type="checkbox"
                            checked={b.selectedTags.includes(t.name)}
                            disabled={taken}
                            onChange={() => toggleTag(b.uid, t.name)}
                          />
                          {t.name}
                        </label>
                      );
                    })}
                  </div>
                </>
              )}
            </fieldset>
          </section>
          );
        })}

        <button type="button" className="secondary" onClick={() => setBatches((bs) => [...bs, newBatch()])}>+ add another sample batch</button>

        <div className="submit-bar">
          <button type="submit" disabled={busy || kit?.status === "analysed" || kitBusy}>{busy ? "Submitting…" : "Submit analysis"}</button>
        </div>
      </form>
    </div>
  );
}

function Progress({ pct }) {
  return (
    <div className="progress"><div style={{ width: `${Math.round(pct * 100)}%` }} /></div>
  );
}
