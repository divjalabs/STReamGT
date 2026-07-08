import { Fragment, useEffect, useState } from "react";
import { api } from "../../api/client.js";

export default function AdminPanels() {
  const [panels, setPanels] = useState([]);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const [f, setF] = useState({ code: "", species_common: "", species_latin: "", description: "", file: null });

  const [openId, setOpenId] = useState(null);      // expanded panel (primers shown)
  const [detail, setDetail] = useState(null);      // fetched PanelOut for openId
  const [editId, setEditId] = useState(null);      // panel being renamed
  const [edit, setEdit] = useState({});

  const load = () => api.listPanels().then(setPanels).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);

  const view = async (p) => {
    if (openId === p.id) { setOpenId(null); setDetail(null); return; }
    setOpenId(p.id); setDetail(null);
    try { setDetail(await api.getPanel(p.id)); } catch (e) { setErr(e.message); }
  };

  const download = async (id) => {
    try { const { url } = await api.downloadPanel(id); window.open(url, "_blank"); }
    catch (e) { setErr(e.message); }
  };

  const startEdit = (p) => {
    setEditId(p.id);
    setEdit({ species_common: p.species_common || "", species_latin: p.species_latin || "" });
  };
  const saveEdit = async (id) => {
    try { await api.updatePanel(id, edit); setEditId(null); load(); }
    catch (e) { setErr(e.message); }
  };
  const remove = async (p) => {
    if (!confirm(`Delete panel ${p.code}?`)) return;
    try { await api.deletePanel(p.id); load(); } catch (e) { setErr(e.message); }
  };

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    if (!f.file) return setErr("Choose a primers CSV.");
    setBusy(true);
    try {
      const form = new FormData();
      form.append("code", f.code);
      if (f.species_common) form.append("species_common", f.species_common);
      if (f.species_latin) form.append("species_latin", f.species_latin);
      if (f.description) form.append("description", f.description);
      form.append("primers_csv", f.file);
      await api.createPanel(form);
      setF({ code: "", species_common: "", species_latin: "", description: "", file: null });
      e.target.reset();
      load();
    } catch (e) { setErr(e.message); } finally { setBusy(false); }
  };

  return (
    <div className="container">
      <h1>Primer panels (admin)</h1>
      {err && <p className="error">{err}</p>}

      <section className="card">
        <h2>Add a panel</h2>
        <form onSubmit={submit}>
          <label>Code<input value={f.code} onChange={(e) => setF({ ...f, code: e.target.value })} required placeholder="e.g. UA_primers" /></label>
          <label>Species (common)<input value={f.species_common} onChange={(e) => setF({ ...f, species_common: e.target.value })} placeholder="brown bear" /></label>
          <label>Species (latin)<input value={f.species_latin} onChange={(e) => setF({ ...f, species_latin: e.target.value })} placeholder="Ursus arctos" /></label>
          <label>Description<input value={f.description} onChange={(e) => setF({ ...f, description: e.target.value })} /></label>
          <label>Primers CSV<input type="file" accept=".csv" onChange={(e) => setF({ ...f, file: e.target.files[0] })} /></label>
          <button type="submit" disabled={busy}>{busy ? "Uploading…" : "Add panel"}</button>
        </form>
      </section>

      <h2>Catalog <span className="muted">({panels.length})</span></h2>
      <table className="table">
        <thead><tr><th>Code</th><th>Species</th><th>Markers</th><th></th></tr></thead>
        <tbody>
          {panels.map((p) => (
            <Fragment key={p.id}>
              <tr>
                <td><a href="#" onClick={(e) => { e.preventDefault(); view(p); }}>{p.code}</a></td>
                <td>
                  {editId === p.id ? (
                    <span className="row">
                      <input value={edit.species_common} onChange={(e) => setEdit({ ...edit, species_common: e.target.value })} placeholder="common" />
                      <input value={edit.species_latin} onChange={(e) => setEdit({ ...edit, species_latin: e.target.value })} placeholder="latin" />
                    </span>
                  ) : (
                    <>{p.species_common || "—"} <i className="muted">{p.species_latin || ""}</i></>
                  )}
                </td>
                <td className="muted">{p.primer_count}</td>
                <td>
                  {editId === p.id ? (
                    <>
                      <button className="secondary" onClick={() => saveEdit(p.id)}>Save</button>{" "}
                      <button className="link" onClick={() => setEditId(null)}>cancel</button>
                    </>
                  ) : (
                    <>
                      <button className="secondary" onClick={() => view(p)}>{openId === p.id ? "hide" : "view"}</button>{" "}
                      <button className="secondary" onClick={() => download(p.id)}>download</button>{" "}
                      <button className="secondary" onClick={() => startEdit(p)}>rename</button>{" "}
                      <button className="link" onClick={() => remove(p)}>delete</button>
                    </>
                  )}
                </td>
              </tr>
              {openId === p.id && (
                <tr>
                  <td colSpan={4}>
                    {!detail ? <span className="muted">loading markers…</span> : (
                      <table className="table">
                        <thead><tr><th>Locus</th><th>Type</th><th>Forward</th><th>Reverse</th><th>Motif/Seq</th></tr></thead>
                        <tbody>
                          {detail.primers.map((m) => (
                            <tr key={m.id}>
                              <td>{m.locus}</td><td>{m.type}</td>
                              <td className="muted">{m.primer_f}</td><td className="muted">{m.primer_r}</td>
                              <td className="muted">{m.motif || m.sequence || "—"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
