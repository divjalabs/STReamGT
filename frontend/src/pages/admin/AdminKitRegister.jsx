import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import ControlPlate from "../../components/ControlPlate.jsx";
import AssigneePicker from "../../components/AssigneePicker.jsx";

export default function AdminKitRegister() {
  const [panels, setPanels] = useState([]);
  const [layout, setLayout] = useState(null);
  const [users, setUsers] = useState([]);
  const [templates, setTemplates] = useState([]);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  // create form
  const [codes, setCodes] = useState("");
  const [panelId, setPanelId] = useState("");
  const [tags, setTags] = useState([]);
  const [controlPattern, setControlPattern] = useState("blank");
  const [controls, setControls] = useState([]);        // [{uid, pos, kind, name}]
  const [assignees, setAssignees] = useState([]);
  const [description, setDescription] = useState("");

  // claim codes shown once after create / regenerate
  const [newCodes, setNewCodes] = useState([]);

  useEffect(() => {
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
  };

  return (
    <div className="container">
      <div className="row">
        <h1>Register kit(s)</h1>
        <span className="spacer" />
        <Link to="/admin/kits" className="link">← Back to kits</Link>
      </div>
      {err && <p className="error">{err}</p>}

      <section className="card">
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
          <p><Link to="/admin/kits" className="link">← Back to kits</Link></p>
        </section>
      )}
    </div>
  );
}
