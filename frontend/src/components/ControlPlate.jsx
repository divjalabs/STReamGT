import { useState, useRef, useEffect } from "react";

// 96-well control layout, shown transposed like SampleTable: 8 columns A–H, 12 rows 12→1.
const LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H"];
const NUMBERS = Array.from({ length: 12 }, (_, i) => i + 1);
const DISPLAY_NUMBERS = NUMBERS.slice().reverse();

// Control types (kind) + colour, matching the run report.
export const CONTROL_KINDS = [
  { key: "positive", label: "Positive", abbr: "Pos", color: "#16a34a" },
  { key: "sequencing", label: "Sequencing (blank)", abbr: "Seq", color: "#dc2626" },
  { key: "pcr", label: "PCR", abbr: "PCR", color: "#f59e0b" },
  { key: "extraction", label: "Extraction", abbr: "Ext", color: "#7c3aed" },
];
export const KIND_META = Object.fromEntries(CONTROL_KINDS.map((k) => [k.key, k]));

// Short token used in auto-generated names — must match the backend (enums.ControlKind.name_token).
const NAME_TOKEN = { positive: "pos", sequencing: "blank", pcr: "pcr", extraction: "ext", negative: "blank" };
const KIND_ORDER = Object.fromEntries(CONTROL_KINDS.map((k, i) => [k.key, i]));

let seq = 1;
const mkRow = (pos, kind, name = "") => ({ uid: seq++, pos, kind, name });

// Sort key: letter first, then number (A1, A2, … A12, B1, …) so A1 comes before H1.
const posKey = (p) => {
  const m = /^([A-H])(\d+)$/i.exec((p || "").trim());
  return m ? m[1].toUpperCase().charCodeAt(0) * 100 + parseInt(m[2], 10) : 99999;
};

/** name shown/sent for a control — explicit, else auto `{kitCode}_{token}_{pos}`. */
export function resolveControlName(kitCode, c) {
  return (c.name || "").trim() || `${(kitCode || "KIT").trim()}_${NAME_TOKEN[c.kind] || c.kind}_${c.pos}`;
}

/** Editable control layout: a type "brush" + a 96-well plate (click to paint) and a list view. */
export default function ControlPlate({ value, onChange, kitCode }) {
  const rows = value || [];
  const [brush, setBrush] = useState("sequencing");
  const [view, setView] = useState("plate");
  const [sortBy, setSortBy] = useState("position");
  const byPos = {};
  rows.forEach((r) => { byPos[r.pos] = r; });

  // click-and-drag painting: mousedown decides paint-vs-erase, mouseenter repeats it while held.
  const dragMode = useRef(null);
  useEffect(() => {
    const up = () => { dragMode.current = null; };
    window.addEventListener("mouseup", up);
    return () => window.removeEventListener("mouseup", up);
  }, []);
  const applyCell = (pos, mode) => onChange((prev) => {
    const cur = prev || [];
    if (mode === "erase") return cur.filter((r) => r.pos !== pos);
    const ex = cur.find((r) => r.pos === pos);
    return ex ? cur.map((r) => (r.pos === pos ? { ...r, kind: brush } : r)) : [...cur, mkRow(pos, brush)];
  });
  const onCellDown = (pos) => {
    const ex = byPos[pos];
    dragMode.current = ex && ex.kind === brush ? "erase" : "paint";   // click same type again = erase
    applyCell(pos, dragMode.current);
  };
  const onCellEnter = (pos) => { if (dragMode.current) applyCell(pos, dragMode.current); };

  const setRow = (uid, patch) =>
    onChange(rows.map((r) => (r.uid === uid ? { ...r, ...patch } : r)));
  const removeRow = (uid) => onChange(rows.filter((r) => r.uid !== uid));
  const listRows = rows.slice().sort((a, b) =>
    sortBy === "type"
      ? (KIND_ORDER[a.kind] - KIND_ORDER[b.kind]) || (posKey(a.pos) - posKey(b.pos))
      : posKey(a.pos) - posKey(b.pos));

  return (
    <div>
      <div className="row" style={{ flexWrap: "wrap", gap: ".5rem", alignItems: "center" }}>
        <div className="tabs">
          <button type="button" className={view === "plate" ? "active" : ""} onClick={() => setView("plate")}>Plate</button>
          <button type="button" className={view === "list" ? "active" : ""} onClick={() => setView("list")}>List</button>
        </div>
        <span className="spacer" />
        <span className="muted small">{rows.length} control{rows.length === 1 ? "" : "s"}</span>
        {rows.length > 0 && (
          <button type="button" className="link" onClick={() => { if (confirm("Clear all controls?")) onChange([]); }}>Clear</button>
        )}
      </div>

      {view === "plate" && (
        <div className="control-brush">
          {CONTROL_KINDS.map((k) => (
            <button type="button" key={k.key}
                    className={`brush-btn ${brush === k.key ? "on" : ""}`}
                    style={{ "--c": k.color }}
                    onClick={() => setBrush(k.key)}>
              <span className="brush-dot" style={{ background: k.color }} /> {k.label}
            </button>
          ))}
          <span className="muted small">— pick a type, then click or drag across wells (click a painted well again to clear)</span>
        </div>
      )}

      {view === "list" && rows.length > 0 && (
        <label className="inline-label" style={{ margin: ".3rem 0" }}>Sort by
          <select value={sortBy} onChange={(e) => setSortBy(e.target.value)}>
            <option value="position">Position</option>
            <option value="type">Type</option>
          </select>
        </label>
      )}

      {view === "plate" ? (
        <div className="plate-wrap">
          <table className="plate-grid control-grid">
            <thead><tr><th></th>{LETTERS.map((l) => <th key={l}>{l}</th>)}</tr></thead>
            <tbody>
              {DISPLAY_NUMBERS.map((num) => (
                <tr key={num}>
                  <th>{num}</th>
                  {LETTERS.map((letter) => {
                    const pos = `${letter}${num}`;
                    const c = byPos[pos];
                    const meta = c ? KIND_META[c.kind] : null;
                    return (
                      <td key={pos}>
                        <button type="button" className="control-cell"
                                title={c ? resolveControlName(kitCode, c) : pos}
                                style={meta ? { background: meta.color, color: "#fff", borderColor: meta.color } : undefined}
                                onMouseDown={(e) => { e.preventDefault(); onCellDown(pos); }}
                                onMouseEnter={() => onCellEnter(pos)}>
                          {meta ? meta.abbr : ""}
                        </button>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <table className="table">
          <thead><tr><th>Position</th><th>Type</th><th>Name</th><th></th></tr></thead>
          <tbody>
            {listRows.length === 0 ? (
              <tr><td colSpan={4} className="muted">No controls yet — add them on the Plate tab.</td></tr>
            ) : listRows.map((r) => (
              <tr key={r.uid}>
                <td className="mono">{r.pos}</td>
                <td>
                  <select value={r.kind} onChange={(e) => setRow(r.uid, { kind: e.target.value })}>
                    {CONTROL_KINDS.map((k) => <option key={k.key} value={k.key}>{k.label}</option>)}
                  </select>
                </td>
                <td>
                  <input value={r.name} placeholder={resolveControlName(kitCode, r)}
                         onChange={(e) => setRow(r.uid, { name: e.target.value })} />
                </td>
                <td><button type="button" className="link" onClick={() => removeRow(r.uid)}>×</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
