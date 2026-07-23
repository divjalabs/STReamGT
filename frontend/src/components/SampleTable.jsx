import { useEffect, useState } from "react";
import { KIND_META } from "./ControlPlate.jsx";

// 96-well plate shown transposed: 12 rows (numbers) down, 8 columns (A..H) across.
const LETTERS = ["A", "B", "C", "D", "E", "F", "G", "H"]; // columns
const NUMBERS = Array.from({ length: 12 }, (_, i) => i + 1); // 1..12
const DISPLAY_NUMBERS = NUMBERS.slice().reverse();          // rows shown 12 (top) → 1 (bottom)

// Plate loading order (down each column): A1,B1,..,H1, A2,B2,..,H2, ... — used to auto-fill list positions.
const WELLS = NUMBERS.flatMap((n) => LETTERS.map((l) => `${l}${n}`));
export const TOTAL_WELLS = WELLS.length; // 96

let seq = 1;
const mkRow = (pos = "", name = "") => ({ uid: seq++, pos, name });

/** Serialize rows to `position,name,control_type` text the backend parses.
 * control_type is looked up from `controlsByPos` (POS -> {kind,name}); empty for samples. */
export function rowsToSampleText(rows, controlsByPos = {}) {
  return (rows || [])
    .filter((r) => r.pos.trim() && r.name.trim())
    .map((r) => {
      const ct = controlsByPos[r.pos.trim().toUpperCase()]?.kind || "";
      return `${r.pos.trim()},${r.name.trim()},${ct}`;
    })
    .join("\n");
}

/** Warnings for the submit plate: duplicate names + defined control wells that were changed/cleared. */
export function controlPlateWarnings(rows, controlsByPos = {}) {
  const warns = [];
  const filled = (rows || []).filter((r) => r.pos.trim() && r.name.trim());
  const counts = {};
  filled.forEach((r) => { const n = r.name.trim(); counts[n] = (counts[n] || 0) + 1; });
  Object.entries(counts).filter(([, c]) => c > 1).forEach(([n]) =>
    warns.push(`Name "${n}" is used in more than one well.`));
  Object.entries(controlsByPos).forEach(([pos, c]) => {
    const row = (rows || []).find((r) => r.pos.trim().toUpperCase() === pos);
    if (!row || !row.name.trim()) warns.push(`Control well ${pos} (${c.kind}) is empty — expected "${c.name}".`);
    else if (row.name.trim() !== c.name)
      warns.push(`Well ${pos} is "${row.name.trim()}" but is a defined ${c.kind} control ("${c.name}").`);
  });
  return warns;
}

// Rank a position by plate order (A1,B1,..,H1,A2,..); unknown/non-standard positions sort last.
const posRank = (p) => {
  const i = WELLS.indexOf(p.trim().toUpperCase());
  return i === -1 ? WELLS.length : i;
};
/** Drop blank rows and order by position (A1 → H12) — used when entering List view. */
function sortByPosition(rows) {
  return (rows || [])
    .filter((r) => r.pos.trim() || r.name.trim())
    .slice()
    .sort((a, b) => posRank(a.pos) - posRank(b.pos));
}

/** Count distinct standard plate wells (A1..H12) that have a sample name. */
export function filledWellCount(rows) {
  const set = new Set();
  (rows || []).forEach((r) => {
    const p = r.pos.trim().toUpperCase();
    if (r.name.trim() && WELLS.includes(p)) set.add(p);
  });
  return set.size;
}

/** Give named rows that lack a position the next free well, in plate order. */
function autoFillPositions(rows) {
  const used = new Set(rows.map((r) => r.pos.trim().toUpperCase()).filter(Boolean));
  let wi = 0;
  return rows.map((r) => {
    if (r.pos.trim() || !r.name.trim()) return r; // already positioned, or empty → leave
    while (wi < WELLS.length && used.has(WELLS[wi])) wi++;
    if (wi >= WELLS.length) return r; // plate full
    const pos = WELLS[wi++];
    used.add(pos);
    return { ...r, pos };
  });
}

/** Editable sample table with two interchangeable views: plate grid (12×8) or a list. */
export default function SampleTable({ value, onChange, controls = {} }) {
  const [view, setView] = useState("plate");
  const rows = value || [];
  const commitList = (next) => onChange(autoFillPositions(next));

  // In list view, always keep one trailing blank row to type/paste into.
  useEffect(() => {
    if (view !== "list") return;
    const last = rows[rows.length - 1];
    if ((!last || last.pos.trim() || last.name.trim()) && rows.length < TOTAL_WELLS) {
      onChange([...rows, mkRow()]);
    }
  }, [view, rows]);

  // --- plate (lookup by well id) ---
  const byPos = {};
  rows.forEach((r) => { if (r.pos) byPos[r.pos.trim().toUpperCase()] = r; });

  const setWell = (pos, name) => {
    const existing = rows.find((r) => r.pos.trim().toUpperCase() === pos);
    if (name.trim()) {
      onChange(existing
        ? rows.map((r) => (r === existing ? { ...r, name } : r))
        : [...rows, mkRow(pos, name)]);
    } else {
      onChange(existing ? rows.filter((r) => r !== existing) : rows);
    }
  };

  const pastePlate = (e, startRow, startCol) => {
    const text = e.clipboardData.getData("text");
    if (!text.includes("\n") && !text.includes("\t")) return; // single value → normal typing
    e.preventDefault();
    const grid = text.replace(/\r/g, "").split("\n").map((l) => l.split(/\t|,/));
    const next = [...rows];
    const upsert = (pos, name) => {
      const i = next.findIndex((r) => r.pos.trim().toUpperCase() === pos);
      if (name.trim()) { if (i >= 0) next[i] = { ...next[i], name }; else next.push(mkRow(pos, name)); }
      else if (i >= 0) next.splice(i, 1);
    };
    grid.forEach((line, r) =>
      line.forEach((val, c) => {
        const num = DISPLAY_NUMBERS[startRow + r], letter = LETTERS[startCol + c];
        if (num !== undefined && letter !== undefined) upsert(`${letter}${num}`, val.trim());
      })
    );
    onChange(next);
  };

  // --- list ---
  const setRow = (u, patch) => commitList(rows.map((r) => (r.uid === u ? { ...r, ...patch } : r)));
  const removeRow = (u) => commitList(rows.filter((r) => r.uid !== u));

  // Cell-anchored paste: a single column pastes down; two columns fill both. Grows rows as needed.
  const pasteList = (e, rowIndex, colIndex) => {
    const text = e.clipboardData.getData("text");
    if (!text.includes("\n") && !text.includes("\t") && !text.includes(",")) return;
    e.preventDefault();
    const lines = text.replace(/\r/g, "").split("\n");
    while (lines.length && lines[lines.length - 1].trim() === "") lines.pop();
    const next = rows.map((r) => ({ ...r }));
    const ensure = (i) => { while (next.length <= i) next.push(mkRow()); };
    lines.forEach((line, li) => {
      line.split(/\t|,/).forEach((val, ci) => {
        const field = colIndex + ci === 0 ? "pos" : colIndex + ci === 1 ? "name" : null;
        if (!field) return;
        const ri = rowIndex + li;
        if (ri >= TOTAL_WELLS) return; // never exceed 96 rows in the list
        ensure(ri);
        next[ri][field] = val.trim();
      });
    });
    commitList(next.slice(0, TOTAL_WELLS));
  };

  const hasData = rows.some((r) => r.pos.trim() || r.name.trim());
  const filled = filledWellCount(rows);
  const clearAll = () => { if (confirm("Clear all samples?")) onChange([]); };

  return (
    <div>
      <div className="row">
        <div className="tabs">
          <button type="button" className={view === "plate" ? "active" : ""} onClick={() => setView("plate")}>Plate (96-well)</button>
          <button type="button" className={view === "list" ? "active" : ""} onClick={() => { if (view !== "list") { const s = sortByPosition(rows); onChange(s.length < TOTAL_WELLS ? [...s, mkRow()] : s); } setView("list"); }}>List</button>
        </div>
        <span className="spacer" />
        <span className={`well-count ${filled === TOTAL_WELLS ? "ok" : ""}`}>{filled} / {TOTAL_WELLS} wells</span>
        {hasData && <button type="button" className="link" onClick={clearAll}>Clear all</button>}
      </div>

      {view === "plate" ? (
        <>
          <div className="plate-wrap">
            <table className="plate-grid">
              <thead><tr><th></th>{LETTERS.map((l) => <th key={l}>{l}</th>)}</tr></thead>
              <tbody>
                {DISPLAY_NUMBERS.map((num, rIdx) => (
                  <tr key={num}>
                    <th>{num}</th>
                    {LETTERS.map((letter, cIdx) => {
                      const pos = `${letter}${num}`;
                      const ctrl = controls[pos];
                      const meta = ctrl ? KIND_META[ctrl.kind] : null;
                      return (
                        <td key={pos}>
                          <input
                            className={ctrl ? "control-well" : undefined}
                            style={meta ? { borderColor: meta.color, boxShadow: `inset 0 -3px 0 ${meta.color}` } : undefined}
                            value={byPos[pos]?.name || ""}
                            onChange={(e) => setWell(pos, e.target.value)}
                            onPaste={(e) => pastePlate(e, rIdx, cIdx)}
                            title={ctrl ? `${pos} — ${ctrl.kind} control (${ctrl.name})` : pos}
                          />
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="muted">Paste a 12×8 block from Excel, or type into wells. Empty wells are ignored.</p>
        </>
      ) : (
        <>
          <table className="table">
            <thead><tr><th>Position</th><th>Sample name</th><th></th></tr></thead>
            <tbody>
              {rows.map((r, idx) => (
                <tr key={r.uid}>
                  <td><input value={r.pos} placeholder="A1" onChange={(e) => setRow(r.uid, { pos: e.target.value })} onPaste={(e) => pasteList(e, idx, 0)} /></td>
                  <td><input value={r.name} placeholder="sample name" onChange={(e) => setRow(r.uid, { name: e.target.value })} onPaste={(e) => pasteList(e, idx, 1)} /></td>
                  <td>{rows.length > 1 && <button type="button" className="link" onClick={() => removeRow(r.uid)}>×</button>}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <p className="muted">Type or paste sample names — positions auto-fill (A1, B1, … H1, A2, …); edit a position to override.</p>
        </>
      )}
    </div>
  );
}
