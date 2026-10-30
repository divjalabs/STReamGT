import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api/client.js";
import ControlPlate from "../../components/ControlPlate.jsx";
import ClaimCodesCard from "../../components/ClaimCodesCard.jsx";

export default function AdminKitRegister() {
  const [panels, setPanels] = useState([]);
  const [layout, setLayout] = useState(null);
  const [templates, setTemplates] = useState([]);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  // create form
  // "generate": the server names the kits <panel>_<YYMMDD>_<NN>; "enter": type your own codes,
  // kept for one-offs and codes that have to match an external numbering scheme.
  const [mode, setMode] = useState("generate");
  const [count, setCount] = useState(10);
  const [codes, setCodes] = useState("");
  const [panelId, setPanelId] = useState("");
  const [tags, setTags] = useState([]);
  const [controlPattern, setControlPattern] = useState("blank");
  const [controls, setControls] = useState([]);        // [{uid, pos, kind, name}]
  const [showControls, setShowControls] = useState(false);
  const [selectedTpl, setSelectedTpl] = useState("");
  const [description, setDescription] = useState("");

  // claim codes for the batch just registered
  const [newCodes, setNewCodes] = useState([]);

  useEffect(() => {
    api.listPanels().then(setPanels).catch((e) => setErr(e.message));
    api.getTagLayout().then(setLayout).catch((e) => setErr(e.message));
    api.listControlTemplates().then(setTemplates).catch(() => {});
  }, []);

  // A ref, not a module-level `let`: that reset on every render, so applying a second template
  // could mint uids the first one had already used.
  const tplSeq = useRef(0);
  const applyTemplate = () => {
    const tpl = templates.find((t) => String(t.id) === String(selectedTpl));
    if (!tpl) return setErr("Choose a template to apply.");
    setErr(null);
    setControls((tpl.positions || []).map((p) => ({
      uid: `t${tplSeq.current++}`, pos: p.position, kind: p.kind, name: p.name || "",
    })));
    setShowControls(true);   // never apply a layout the page is hiding
  };
  const deleteTemplate = async () => {
    const tpl = templates.find((t) => String(t.id) === String(selectedTpl));
    if (!tpl) return setErr("Choose a template to delete.");
    // Deleting a template never touches kits already registered: the wells are copied onto each
    // kit at registration, so this only removes the saved shortcut.
    if (!confirm(`Delete the template "${tpl.name}"? Kits already registered keep their wells.`))
      return;
    try {
      await api.deleteControlTemplate(tpl.id);
      setTemplates((ts) => ts.filter((t) => t.id !== tpl.id));
      setSelectedTpl("");
      setErr(null);
    } catch (e) { setErr(e.message); }
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

  // Mirrors the server's format (services/kit_codes.py); for preview only — the real numbering
  // continues from whatever already exists for that panel today.
  const panelCode = panels.find((p) => String(p.id) === String(panelId))?.code;
  const codePreview = panelCode
    ? `${panelCode}_${new Date().toISOString().slice(2, 10).replace(/-/g, "")}_01`
    : "";

  const toggleTag = (name) => setTags(tags.includes(name) ? tags.filter((t) => t !== name) : [...tags, name]);

  const submit = async (e) => {
    e.preventDefault();
    setErr(null);
    const codeList = codes.split(/[\s,]+/).map((c) => c.trim()).filter(Boolean);
    if (mode === "enter" && codeList.length === 0) return setErr("Enter at least one kit code.");
    if (mode === "generate" && (!count || count < 1))
      return setErr("How many kits should be registered?");
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
      description: description || null,
    };
    const reset = () => {
      setCodes(""); setPanelId(""); setTags([]); setDescription("");
      setControls([]);
    };

    if (mode === "generate") {
      // One request, one transaction: a half-created batch would leave the printed sheet
      // disagreeing with what actually exists.
      try {
        const batch = await api.createKitBatch({ count: Number(count), ...base });
        setNewCodes(batch.kits);
        reset();
      } catch (e) {
        setErr(e.message);
      } finally {
        setBusy(false);
      }
      return;
    }

    const failed = [];
    const created = [];
    for (const code of codeList) {
      try { const k = await api.createKit({ kit_code: code, ...base }); created.push(k); }
      catch (e) { failed.push(`${code}: ${e.message}`); }
    }
    setBusy(false);
    setNewCodes(created.map((k) => ({ kit_code: k.kit_code, claim_code: k.claim_code })));
    if (failed.length) setErr("Some kits failed — " + failed.join(" | "));
    else reset();
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
          <div className="tabs">
            <button type="button" className={mode === "generate" ? "active" : ""}
                    onClick={() => setMode("generate")}>Generate codes</button>
            <button type="button" className={mode === "enter" ? "active" : ""}
                    onClick={() => setMode("enter")}>Enter my own</button>
          </div>

          {mode === "generate" ? (
            <label>How many kits?
              <input type="number" min="1" max="200" value={count}
                     onChange={(e) => setCount(e.target.value)} required style={{ maxWidth: "8rem" }} />
              <span className="muted small">
                {" "}Named after the panel and today's date — e.g. {codePreview}
              </span>
            </label>
          ) : (
            <label>Kit code(s) <span className="muted">— one or more, comma or space separated (all share the fields below)</span>
              <input value={codes} onChange={(e) => setCodes(e.target.value)} required placeholder="DIVJA240, DIVJA241, DIVJA242" />
            </label>
          )}
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
            {/* Collapsed by default: the plate is the tallest thing on the page, and most
                batches reuse whatever the last one used. Hiding it changes nothing about what
                is submitted — the count in the legend says what is still selected. */}
            <legend>
              <button type="button" className="linkish" onClick={() => setShowControls((v) => !v)}>
                {showControls ? "▾" : "▸"} Control positions
              </button>
              <span className="muted small">
                {" "}— {controls.length === 0 ? "none" : `${controls.length} well${controls.length === 1 ? "" : "s"}`}
              </span>
            </legend>
            {showControls && (
              <>
                <div className="row" style={{ flexWrap: "wrap", gap: ".5rem", alignItems: "center" }}>
                  <label className="inline-label">Saved template
                    <select value={selectedTpl} onChange={(e) => setSelectedTpl(e.target.value)}>
                      <option value="">— choose —</option>
                      {templates.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
                    </select>
                  </label>
                  <button type="button" className="secondary" onClick={applyTemplate}>Apply</button>
                  <button type="button" className="secondary" onClick={deleteTemplate}>Delete</button>
                  <button type="button" className="secondary" onClick={saveTemplate}>Save positions as template</button>
                  <span className="muted small">Names auto-generate as {"{kit}_{type}_{well}"} unless set.</span>
                </div>
                <ControlPlate value={controls} onChange={setControls} kitCode={mode === "generate" ? (codePreview || "KIT") : (codes.split(/[\s,]+/)[0] || "KIT")} />
              </>
            )}
          </fieldset>
          <label>Description (optional)
            <input value={description} onChange={(e) => setDescription(e.target.value)} />
          </label>
          <button type="submit" disabled={busy}>{busy ? "Registering…" : "Register kit(s)"}</button>
        </form>
      </section>

      {newCodes.length > 0 && (
        <ClaimCodesCard rows={newCodes} onDismiss={() => setNewCodes([])} />
      )}
    </div>
  );
}
