import { useEffect, useMemo, useState } from "react";

export const num = (v, d = 2) => (v === null || v === undefined ? "—" : Number(v).toFixed(d));

// MisBase "Browse Consensus" acceptance thresholds (stblSettings) — green = pass, red = fail.
const T = { REPLICATES: 2, SUCCESS: 10, QI: 0.1, ALLELE_HET: 2, ALLELE_HOMO: 3 };
const passClass = (v, thr) =>
  v === null || v === undefined ? "" : v >= thr ? "cell-pass" : "cell-fail";

// One editable allele cell (Al1..Al4). Disabled when the row is locked.
export function AlleleCell({ value, locked, onSave }) {
  const [v, setV] = useState(value ?? "");
  useEffect(() => setV(value ?? ""), [value]);
  const commit = () => { if ((v || "") !== (value ?? "")) onSave(v || null); };
  return (
    <input
      className="allele-cell" value={v} disabled={locked}
      onChange={(e) => setV(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => { if (e.key === "Enter") e.target.blur(); }}
    />
  );
}

// Consensus genotype table. Lock is the first column; a synthetic top "Sex" row is bound to the
// sample's genetic sex (same control as the info-panel Sex menu). Al3/Al4 columns hide when empty.
export function ConsensusTable({ rows, onEdit, onToggleLock, sex, onSetSex, sexMarker }) {
  const showAl3 = rows.some((c) => c.allele3);
  const showAl4 = rows.some((c) => c.allele4);
  const alleleCols = [1, 2, ...(showAl3 ? [3] : []), ...(showAl4 ? [4] : [])];

  return (
    <div className="table-scroll">
      <table className="table consensus-table">
        <thead>
          <tr>
            <th></th><th>Marker</th>
            <th>Al1</th><th>Al2</th>{showAl3 && <th>Al3</th>}{showAl4 && <th>Al4</th>}
            <th>N.Al1</th><th>N.Al2</th><th>Unconfirmed</th>
            <th>NAmp</th><th>OK</th><th>Succ%</th><th>QI</th><th>ADO</th><th>FalseAl</th><th>Src</th>
          </tr>
        </thead>
        <tbody>
          {onSetSex && (
            <tr className="sex-row">
              <td></td>
              <td className="sex-marker">{sexMarker || "Sex"} <span className="muted small">(sex)</span></td>
              <td colSpan={alleleCols.length + 10}>
                <select className="sex-select" value={sex ?? "unknown"}
                        onChange={(e) => onSetSex(e.target.value)}>
                  <option value="unknown">unknown</option>
                  <option value="male">male ♂</option>
                  <option value="female">female ♀</option>
                </select>
              </td>
            </tr>
          )}
          {rows.map((c) => {
            const homo = !c.allele2;
            return (
              <tr key={c.id} className={`${c.is_locked ? "locked-row" : ""} ${c.marker === sexMarker ? "is-sex" : ""}`}>
                <td>
                  <button className="lockbtn-icon" title={c.is_locked ? "Unlock" : "Lock"}
                          onClick={() => onToggleLock(c)}>{c.is_locked ? "🔒" : "🔓"}</button>
                </td>
                <td className="marker-cell">{c.marker}{c.is_edited ? " ✎" : ""}</td>
                {alleleCols.map((i) => (
                  <td key={i}>
                    <AlleleCell value={c[`allele${i}`]} locked={c.is_locked}
                      onSave={(val) => onEdit(c.id, { [`allele${i}`]: val })} />
                  </td>
                ))}
                <td className={passClass(c.n_obs_a1, homo ? T.ALLELE_HOMO : T.ALLELE_HET)}>{c.n_obs_a1 ?? "—"}</td>
                <td className={c.allele2 ? passClass(c.n_obs_a2, T.ALLELE_HET) : ""}>{c.allele2 ? (c.n_obs_a2 ?? "—") : ""}</td>
                <td className="muted unconf">{c.unconfirmed_alleles || "—"}</td>
                <td className={passClass(c.n_amp, T.REPLICATES)}>{c.n_amp ?? "—"}</td>
                <td className={passClass(c.n_amp_ok, T.REPLICATES)}>{c.n_amp_ok ?? "—"}</td>
                <td className={passClass(c.success_rate, T.SUCCESS)}>{num(c.success_rate, 1)}</td>
                <td className={passClass(c.quality_index, T.QI)}>{num(c.quality_index)}</td>
                <td>{c.ado ?? "—"}</td><td>{c.false_alleles ?? "—"}</td>
                <td className="muted src">{c.source}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// Replicate observations, grouped/sorted by marker → position → allele; headers sortable; no bars.
const SORTABLE = { marker: "marker", plate: "plate", position: "position", allele: "allele_name", read_count: "read_count" };
export function ReplicateTable({ rows }) {
  const [sort, setSort] = useState({ key: "marker", dir: 1 });

  const val = (r, k) => {
    if (k === "read_count") return r.read_count ?? -1;
    if (k === "position") return r.position ?? -1;
    return (r[k] ?? "").toString();
  };
  const cmp = (a, b, k, dir) => {
    const av = val(a, k), bv = val(b, k);
    return (av < bv ? -1 : av > bv ? 1 : 0) * dir;
  };
  const sorted = useMemo(() => {
    const k = SORTABLE[sort.key] || "marker";
    return [...rows].sort((a, b) =>
      cmp(a, b, k, sort.dir)
      || cmp(a, b, "marker", 1) || cmp(a, b, "position", 1) || cmp(a, b, "allele_name", 1));
  }, [rows, sort]);

  const th = (key, label) => (
    <th className="sortable" onClick={() => setSort((s) => ({ key, dir: s.key === key ? -s.dir : 1 }))}>
      {label}{sort.key === key ? (sort.dir === 1 ? " ▲" : " ▼") : ""}
    </th>
  );

  return (
    <div className="table-scroll">
      <table className="table">
        <thead>
          <tr>
            {th("marker", "Marker")}{th("plate", "Plate")}{th("position", "Pos")}
            {th("allele", "Allele")}{th("read_count", "Reads")}<th>Flag</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={i} className={r.flag ? "flagged" : ""}>
              <td>{r.marker}</td><td>{r.plate || "—"}</td><td>{r.position ?? "—"}</td>
              <td>{r.allele_name || "—"}</td>
              <td className="reads-n">{r.read_count ?? "—"}</td>
              <td className="muted">{r.flag || ""}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
