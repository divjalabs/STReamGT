import { useEffect, useState } from "react";
import { api } from "../../api/client.js";
import ControlPlate from "../../components/ControlPlate.jsx";

const STATUSES = ["sent", "received", "analysed", "reanalyse"];
const STATUS_CLASS = { analysed: "ok", reanalyse: "warn", received: "", sent: "muted" };

/** Type-to-search user picker: input + suggestions + chips. `value` is an array of user ids. */
function AssigneePicker({ users, value, onChange }) {
  const [q, setQ] = useState("");
  const emailFor = (id) => users.find((u) => u.id === id)?.email || `#${id}`;
  const matches = q.trim()
    ? users.filter((u) => !value.includes(u.id) && u.email.toLowerCase().includes(q.toLowerCase())).slice(0, 6)
    : [];
  return (
    <div>
      <div className="chips">
        {value.map((id) => (
          <span key={id} className="chip on">
            {emailFor(id)}
            <button type="button" className="chip-x" onClick={() => onChange(value.filter((x) => x !== id))}>×</button>
          </span>
        ))}
      </div>
      <div className="typeahead">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="type a username to add…" />
        {matches.length > 0 && (
          <ul className="suggestions">
            {matches.map((u) => (
              <li key={u.id} onClick={() => { onChange([...value, u.id]); setQ(""); }}>
                {u.email}{u.role === "admin" ? " (admin)" : ""}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

export default function AdminKits() {
  const [kits, setKits] = useState([]);
  const [panels, setPanels] = useState([]);
  const [layout, setLayout] = useState(null);
  const [users, setUsers] = useState([]);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  // create form
  const [codes, setCodes] = useState("");
  const [panelId, setPanelId] = useState("");
  const [tags, setTags] = useState([]);
  const [controlPattern, setControlPattern] = useState("blank");
  const [controls, setControls] = useState([]);        // [{uid, pos, kind, name}]
  const [templates, setTemplates] = useState([]);
  const [assignees, setAssignees] = useState([]);
  const [description, setDescription] = useState("");

  // claim codes shown once after create / regenerate
  const [newCodes, setNewCodes] = useState([]);

  // row editing
  const [editId, setEditId] = useState(null);
  const [edit, setEdit] = useState({ status: "sent", description: "", assigned_user_ids: [] });

  const load = () => api.listKits().then(setKits).catch((e) => setErr(e.message));
  useEffect(() => {
    load();
    api.listPanels().then(setPanels).catch((e) => setErr(e.message));
    api.getTagLayout().then(setLayout).catch((e) => setErr(e.message));
    api.listUsers().then(setUsers).catch((e) => setErr(e.message));
    api.listControlTemplates().then(setTemplates).catch(() => {});
  }, []);

  let tplSeq = 0;
  const applyTemplate = (id) => {
    const tpl = templates.find((t) => String(t.id) === String(id));
    if (!tpl) return;
    setControls((tpl.positions || []).map((p) => ({
      uid: `t${tplSeq++}`, pos: p.position, kind: p.kind, name: p.name || "",
    })));
  };
  const saveTemplate = async () => {
    if (controls.length === 0) return setErr("Add some control positions before saving a template.");
    const name = prompt("Template name:");
    if (!name || !name.trim()) return;
    try {
      const tpl = await api.createControlTemplate({
        name: name.trim(),
        positions: controls.map((c) => ({
          kind: c.kind, position: c.pos, ...(c.name?.trim() ? { name: c.name.trim() } : {}),
        })),
      });
      setTemplates((ts) => [...ts, tpl].sort((a, b) => a.name.localeCompare(b.name)));
    } catch (e) { setErr(e.message); }
  };

  const emailFor = (id) => users.find((u) => u.id === id)?.email || `#${id}`;
  const toggleTag = (name) => setTags(tags.includes(name) ? tags.filter((t) => t !== name) : [...tags, name]);

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    const codeList = codes.split(/[\s,]+/).map((c) => c.trim()).filter(Boolean);
    if (codeList.length === 0) return setErr("Enter at least one kit code.");
    if (!panelId) return setErr("Choose a primer panel.");
    if (tags.length === 0) return setErr("Select at least one tag column.");
    setBusy(true);
    const controlsPayload = [];
    if (controlPattern.trim())
      controlsPayload.push({ name_pattern: controlPattern.trim(), kind: "sequencing" });
    for (const c of controls)
      controlsPayload.push({ kind: c.kind, position: c.pos, name: c.name?.trim() || null });
    const base = {
      panel_id: Number(panelId),
      selected_tags: tags,
      controls: controlsPayload,
      assigned_user_ids: assignees,
      description: description || null,
    };
    const failed = [];
    const created = [];
    for (const code of codeList) {
      try { const k = await api.createKit({ kit_code: code, ...base }); created.push(k); }
      catch (e) { failed.push(`${code}: ${e.message}`); }
    }
    setBusy(false);
    setNewCodes(created.map((k) => ({ kit_code: k.kit_code, claim_code: k.claim_code })));
    if (failed.length) setErr("Some kits failed — " + failed.join(" | "));
    else { setCodes(""); setPanelId(""); setTags([]); setAssignees([]); setDescription(""); setControls([]); }
    load();
  };

  const regenCode = async (id) => {
    try { const k = await api.regenerateClaimCode(id); setNewCodes([{ kit_code: k.kit_code, claim_code: k.claim_code }]); }
    catch (e) { setErr(e.message); }
  };

  const startEdit = (k) => {
    setEditId(k.id);
    setEdit({ status: k.status, description: "", assigned_user_ids: [...k.assigned_user_ids] });
  };
  const saveEdit = async (id) => {
    try { await api.updateKit(id, edit); setEditId(null); load(); } catch (e) { setErr(e.message); }
  };
  const remove = async (id) => {
    if (!confirm("Delete this kit?")) return;
    try { await api.deleteKit(id); load(); } catch (e) { setErr(e.message); }
  };

  return (
    <div className="container">
      <h1>Kits (admin)</h1>
      {err && <p className="error">{err}</p>}

      <section className="card">
        <h2>Register kit(s)</h2>
        <form onSubmit={submit}>
          <label>Kit code(s) <span className="muted">— one or more, comma or space separated (all share the fields below)</span>
            <input value={codes} onChange={(e) => setCodes(e.target.value)} required placeholder="DIVJA240, DIVJA241, DIVJA242" />
          </label>
          <label>Primer panel (species)
            <select value={panelId} onChange={(e) => setPanelId(e.target.value)} required>
              <option value="">— choose a panel —</option>
              {panels.map((p) => (
                <option key={p.id} value={p.id}>{p.code}{p.species_common ? ` — ${p.species_common}` : ""}</option>
              ))}
            </select>
          </label>
          <fieldset>
            <legend>Tag columns</legend>
            {!layout ? <p className="muted">loading…</p> : (
              <div className="chips">
                {layout.column_names.map((name) => (
                  <label key={name} className={`chip ${tags.includes(name) ? "on" : ""}`}>
                    <input type="checkbox" checked={tags.includes(name)} onChange={() => toggleTag(name)} />{name}
                  </label>
                ))}
              </div>
            )}
          </fieldset>
          <label>Negative control name pattern
            <input value={controlPattern} onChange={(e) => setControlPattern(e.target.value)} placeholder="blank" />
          </label>
          <fieldset>
            <legend>Control positions</legend>
            <div className="row" style={{ flexWrap: "wrap", gap: ".5rem", alignItems: "center" }}>
              <label className="inline-label">Apply template
                <select defaultValue="" onChange={(e) => { applyTemplate(e.target.value); e.target.value = ""; }}>
                  <option value="">— choose —</option>
                  {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                </select>
              </label>
              <button type="button" className="secondary" onClick={saveTemplate}>Save positions as template</button>
              <span className="muted small">Names auto-generate as {"{kit}_{type}_{well}"} unless set.</span>
            </div>
            <ControlPlate value={controls} onChange={setControls} kitCode={codes.split(/[\s,]+/)[0] || "KIT"} />
          </fieldset>
          <fieldset>
            <legend>Assign to users</legend>
            <AssigneePicker users={users} value={assignees} onChange={setAssignees} />
          </fieldset>
          <label>Description (optional)
            <input value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <button type="submit" disabled={busy}>{busy ? "Registering…" : "Register kit(s)"}</button>
        </form>
      </section>

      {newCodes.length > 0 && (
        <section className="card claim-codes-card">
          <div className="row">
            <b>Claim code{newCodes.length > 1 ? "s" : ""} — copy now, shown only once</b>
            <span className="spacer" />
            <button type="button" className="link" onClick={() => setNewCodes([])}>dismiss</button>
          </div>
          <p className="muted small">Ship each code with its kit. The buyer redeems it to unlock the kit — no admin step.</p>
          <table className="table">
            <tbody>
              {newCodes.map((c) => (
                <tr key={c.kit_code}>
                  <td>{c.kit_code}</td>
                  <td className="mono"><b>{c.claim_code}</b></td>
                  <td><button type="button" className="linkish" onClick={() => navigator.clipboard?.writeText(c.claim_code)}>copy</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <h2>All kits <span className="muted">({kits.length})</span></h2>
      <table className="table">
        <thead>
          <tr><th>Kit</th><th>Species</th><th>Tags</th><th>Assigned to</th><th>Claimed by</th><th>Status</th><th></th></tr>
        </thead>
        <tbody>
          {kits.map((k) => editId === k.id ? (
            <tr key={k.id}>
              <td>{k.kit_code}</td>
              <td>{k.species || "—"}</td>
              <td className="muted">{k.tag_columns.map((t) => t.name).join(", ")}</td>
              <td><AssigneePicker users={users} value={edit.assigned_user_ids}
                    onChange={(v) => setEdit({ ...edit, assigned_user_ids: v })} /></td>
              <td className="muted">{k.claimed_by_email || "—"}</td>
              <td>
                <select value={edit.status} onChange={(e) => setEdit({ ...edit, status: e.target.value })}>
                  {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
              </td>
              <td>
                <button className="secondary" onClick={() => saveEdit(k.id)}>Save</button>{" "}
                <button className="link" onClick={() => setEditId(null)}>cancel</button>
              </td>
            </tr>
          ) : (
            <tr key={k.id}>
              <td>{k.kit_code}</td>
              <td>{k.species || "—"}</td>
              <td className="muted">{k.tag_columns.map((t) => t.name).join(", ")}</td>
              <td className="muted">{k.assigned_user_ids.map(emailFor).join(", ") || "—"}</td>
              <td className="muted">{k.claimed_by_email || "unclaimed"}</td>
              <td><span className={`badge ${STATUS_CLASS[k.status] || ""}`}>{k.status}</span></td>
              <td>
                <button className="secondary" onClick={() => startEdit(k)}>edit</button>{" "}
                <button className="linkish" onClick={() => regenCode(k.id)}>code</button>{" "}
                <button className="link" onClick={() => remove(k.id)}>delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
