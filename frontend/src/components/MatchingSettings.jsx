import { useEffect, useState } from "react";

// Editable matching-threshold form. Used both on the population match page (Save settings) and in
// the animal page's "Rerun matching" dialog (Run rematch). onSave receives the edited settings.
export function MatchingSettingsForm({ settings, onSave, busy, saveLabel = "Save settings", title = "Matching settings" }) {
  const [s, setS] = useState(settings);
  useEffect(() => setS(settings), [settings]);
  const set = (k, v) => setS((p) => ({ ...p, [k]: v }));
  const numField = (k, label) => (
    <label className="field">
      <span>{label}</span>
      <input type="number" step="any" value={s[k]} onChange={(e) => set(k, Number(e.target.value))} />
    </label>
  );
  return (
    <div className="card settings-card">
      {title && <h3>{title}</h3>}
      <div className="fields">
        {numField("min_shared_loci", "Min shared loci")}
        <label className="field">
          <span>Mismatch metric</span>
          <select value={s.mismatch_metric} onChange={(e) => set("mismatch_metric", e.target.value)}>
            <option value="decomposed">decomposed (ADO/IC)</option>
            <option value="flat">flat (Tm)</option>
          </select>
        </label>
        <label className="field check">
          <input type="checkbox" checked={s.use_pi_gate} onChange={(e) => set("use_pi_gate", e.target.checked)} />
          <span>Use PI/PIsib gate</span>
        </label>
        {s.mismatch_metric === "flat" ? (
          <>{numField("tm_possible", "Tm possible")}{numField("tm_reliable", "Tm reliable")}</>
        ) : (
          <>
            {numField("max_ado_mm_match", "Max ADO (possible)")}
            {numField("max_total_mm_match", "Max total IC (possible)")}
            {numField("reliable_max_ado_mm", "Max ADO (reliable)")}
            {numField("reliable_max_total", "Max total IC (reliable)")}
          </>
        )}
      </div>
      <button onClick={() => onSave(s)} disabled={busy}>{saveLabel}</button>
    </div>
  );
}
