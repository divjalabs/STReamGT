import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import ClaimCodesCard from "../../components/ClaimCodesCard.jsx";
import AssigneePicker from "../../components/AssigneePicker.jsx";

const STATUSES = ["sent", "received", "analysed", "reanalyse"];
const STATUS_CLASS = { analysed: "ok", reanalyse: "warn", received: "", sent: "muted" };

export default function AdminKits() {
  const [kits, setKits] = useState([]);
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState(null);

  // claim codes shown once after regenerate
  const [newCodes, setNewCodes] = useState([]);

  // row editing
  // Sorting is client-side: the whole list is already loaded, and a lab's kit count stays in
  // the hundreds.
  const [sort, setSort] = useState({ key: "kit_code", dir: "asc" });
  const [exporting, setExporting] = useState(false);
  const [sheeting, setSheeting] = useState(false);
  const [purge, setPurge] = useState(null);   // {kit, impact, typed, busy} — the danger zone
  const [note, setNote] = useState(null);
  const [editId, setEditId] = useState(null);
  const [edit, setEdit] = useState({ status: "sent", assigned_user_ids: [] });

  const load = () => api.listKits().then(setKits).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    api.listUsers().then(setUsers).catch((e) => setErr(e.message));
  }, []);

  const exportKits = async () => {
    setExporting(true); setErr(null);
    try {
      // Without claim codes, deliberately — this is the file that gets emailed around.
      await api.downloadKitExport();
    } catch (e) {
      setErr(e.message);
    } finally {
      setExporting(false);
    }
  };

  // Reprints the codes for every kit nobody has claimed yet, for when the sheet from
  // registration was lost. Claiming a kit drops it from this sheet.
  const stickerSheet = async () => {
    setSheeting(true); setErr(null);
    try {
      await api.downloadKitStickerSheet();
    } catch (e) {
      setErr(e.message);
    } finally {
      setSheeting(false);
    }
  };

  const SORT_VALUE = {
    kit_code: (k) => k.kit_code || "",
    species: (k) => k.species || "",
    tags: (k) => k.tag_columns.map((t) => t.name).join(","),
    claimed_by_email: (k) => k.claimed_by_email || "",
    status: (k) => k.status || "",
  };

  const sorted = [...(kits || [])].sort((a, b) => {
    const get = SORT_VALUE[sort.key] || SORT_VALUE.kit_code;
    // numeric:true so Bearplex_261029_9 sorts before _10 rather than after it.
    const cmp = String(get(a)).localeCompare(String(get(b)), undefined, { numeric: true });
    return sort.dir === "asc" ? cmp : -cmp;
  });

  const sortBy = (key) =>
    setSort((s) => ({ key, dir: s.key === key && s.dir === "asc" ? "desc" : "asc" }));

  const Th = ({ label, k }) => (
    <th>
      <button type="button" className="linkish" onClick={() => sortBy(k)}>
        {label}{sort.key === k ? (sort.dir === "asc" ? " ▲" : " ▼") : ""}
      </button>
    </th>
  );

  const emailFor = (id) => users.find((u) => u.id === id)?.email || `#${id}`;

  const regenCode = async (id) => {
    try {
      const k = await api.regenerateClaimCode(id);
      setNewCodes((prev) => [
        ...prev.filter((c) => c.kit_code !== k.kit_code),
        { kit_code: k.kit_code, claim_code: k.claim_code, species: k.species,
          panel: k.panel?.code, registered: new Date().toISOString().slice(0, 10) },
      ]);
    }
    catch (e) { setErr(e.message); }
  };

  // Hand a kit back so the right person can claim it. The endpoint clears claimed_by and the
  // access grant but leaves the code's hash alone, so the sticker already on the box still works.
  const release = async (k) => {
    setErr(null);
    if (!confirm(
      `Release ${k.claimed_by_email}'s claim on ${k.kit_code}? They lose access to it. `
      + `The code on its sticker still works, so the right person can claim it.`
    )) return;
    try { await api.revokeClaim(k.id); load(); } catch (e) { setErr(e.message); }
  };

  const startEdit = (k) => {
    setEditId(k.id);
    // Don't send `description` at all — this form doesn't edit it, and sending "" wiped it.
    setEdit({ status: k.status, assigned_user_ids: [...k.assigned_user_ids] });
  };
  const saveEdit = async (id) => {
    try { await api.updateKit(id, edit); setEditId(null); load(); } catch (e) { setErr(e.message); }
  };
  const remove = async (k) => {
    setErr(null);
    if (!confirm(`Delete kit ${k.kit_code}?`)) return;
    try { await api.deleteKit(k.id); load(); }
    catch (e) {
      // The refusal already explains itself; offer the way through rather than a dead end.
      setErr(e.message);
      if (e.status === 409) openPurge(k);
    }
  };

  // The danger zone: deleting a kit together with the genotypes it produced. Nothing is shown
  // until the server has said what would go, and the button needs the kit code typed.
  const openPurge = async (k) => {
    setPurge({ kit: k, impact: null, typed: "", busy: false });
    try {
      setPurge((pg) => ({ ...pg, impact: "loading" }));
      const impact = await api.kitDeletionImpact(k.id);
      setPurge((pg) => (pg && pg.kit.id === k.id ? { ...pg, impact } : pg));
    } catch (e) {
      setErr(e.message);
      setPurge(null);
    }
  };

  const doPurge = async () => {
    setPurge((pg) => ({ ...pg, busy: true }));
    setErr(null);
    try {
      const out = await api.deleteKitEverything(purge.kit.id, purge.kit.kit_code);
      setPurge(null);
      setNote(`Deleted ${out.kit_code}: ${out.samples} sample(s), ${out.jobs} analysis(es), `
              + `${out.objects_deleted} file(s), ${(out.bytes_freed / 1e6).toFixed(1)} MB freed.`);
      load();
    } catch (e) {
      setErr(e.message);
      setPurge((pg) => (pg ? { ...pg, busy: false } : pg));
    }
  };

  return (
    <div className="container">
      <div className="row">
        <h1>Kits (admin)</h1>
        <span className="spacer" />
        <button className="secondary" onClick={exportKits} disabled={exporting}>
          {exporting ? "Preparing…" : "⭳ Export kits (.xlsx)"}
        </button>{" "}
        <button className="secondary" onClick={stickerSheet} disabled={sheeting}
                title="Claim codes for every kit nobody has claimed yet">
          {sheeting ? "Preparing…" : "⭳ Sticker sheet (.xlsx)"}
        </button>{" "}
        <Link to="/admin/kits/new"><button>＋ Register kit(s)</button></Link>
      </div>
      {err && <p className="error">{err}</p>}
      {note && <p className="ok">{note}</p>}

      {purge && (
        <section className="card danger-box">
          <h2>Delete {purge.kit.kit_code} and everything it produced</h2>
          {purge.impact === "loading" || purge.impact === null ? (
            <p className="muted">Working out what this would remove…</p>
          ) : (
            <>
              <p>This permanently deletes:</p>
              <ul>
                <li><b>{purge.impact.samples}</b> sample(s), with{" "}
                  <b>{purge.impact.consensus_genotypes}</b> consensus genotype(s) and{" "}
                  <b>{purge.impact.replicate_observations}</b> replicate observation(s)</li>
                <li><b>{purge.impact.jobs}</b> analysis run(s) and{" "}
                  <b>{purge.impact.result_files}</b> result file(s)</li>
                {purge.impact.has_stored_reads && <li>the kit's stored FASTQ pair</li>}
              </ul>
              {purge.impact.populations_whose_matching_is_cleared.length > 0 && (
                <p className="warn">
                  Matching is per population, so the animals in{" "}
                  <b>{purge.impact.populations_whose_matching_is_cleared.join(", ")}</b>{" "}
                  will be cleared and need matching again — including animals built from other
                  kits' samples in the same population.
                </p>
              )}
              <p className="muted small">
                There is no undo. The nightly database dump is the only way back.
              </p>
              <label>Type <b>{purge.kit.kit_code}</b> to confirm
                <input value={purge.typed} autoFocus
                       onChange={(e) => setPurge({ ...purge, typed: e.target.value })} />
              </label>
              <div className="row">
                <button className="danger" disabled={purge.busy || purge.typed !== purge.kit.kit_code}
                        onClick={doPurge}>
                  {purge.busy ? "Deleting…" : "Delete everything"}
                </button>{" "}
                <button className="secondary" disabled={purge.busy}
                        onClick={() => setPurge(null)}>Cancel</button>
              </div>
            </>
          )}
        </section>
      )}

      <ClaimCodesCard rows={newCodes} onDismiss={() => setNewCodes([])} />

      <h2>All kits <span className="muted">({kits.length})</span></h2>
      <table className="table">
        <thead>
          <tr>
            <Th label="Kit" k="kit_code" />
            <Th label="Species" k="species" />
            <Th label="Tags" k="tags" />
            <Th label="Claimed by" k="claimed_by_email" />
            <Th label="Status" k="status" />
            <th></th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((k) => editId === k.id ? (
            <tr key={k.id}>
              <td>{k.kit_code}</td>
              <td>{k.species || "—"}</td>
              <td className="muted">{k.tag_columns.map((t) => t.name).join(", ")}</td>
              <td className="muted">{k.claimed_by_email || "—"}</td>
              <td>
                <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
                  {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </td>
              <td className="muted small">
                <AssigneePicker users={users} value={edit.assigned_user_ids}
                  onChange={(v) => setEdit({ ...edit, assigned_user_ids: v })} />
              </td>
              <td>
                <button className="secondary" onClick={() => saveEdit(k.id)}>Save</button>{" "}
                <button className="link" onClick={() => setEditId(null)}>cancel</button>
              </td>
            </tr>
          ) : (
            <tr key={k.id}>
              <td>
                {k.kit_code}
                {k.description && <div className="muted small">{k.description}</div>}
              </td>
              <td>{k.species || "—"}</td>
              <td className="muted">{k.tag_columns.map((t) => t.name).join(", ")}</td>
              <td className="muted">{k.claimed_by_email || "unclaimed"}</td>
              <td><span className={`badge ${STATUS_CLASS[k.status] || ""}`}>{k.status}</span></td>
              <td>
                <button className="secondary" onClick={() => startEdit(k)}>edit</button>{" "}
                <button className="linkish" onClick={() => regenCode(k.id)}>code</button>{" "}
                {k.claimed_by_email && (
                  <>
                    <button className="linkish" onClick={() => release(k)}>release</button>{" "}
                  </>
                )}
                <button className="link" onClick={() => remove(k)}>delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
