import { useEffect, useRef, useState } from "react";
import { api } from "../api/client.js";

/**
 * The claim codes just issued — the only time they exist.
 *
 * Only a fingerprint of each code is stored, so this card cannot be rebuilt. If it is dismissed
 * or the page is left before the codes are saved, the only way back is issuing new ones, which
 * kills any sticker already printed. Hence: downloading is the primary action, dismissing asks
 * first, and leaving the page warns.
 */
export default function ClaimCodesCard({ rows, onDismiss }) {
  const [downloaded, setDownloaded] = useState(false);
  const [confirmDismiss, setConfirmDismiss] = useState(false);
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);
  const ref = useRef(null);

  // Bring it into view: the form above it is a whole 96-well plate tall.
  useEffect(() => {
    ref.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, []);

  // The browser's own guard against closing the tab on unsaved codes.
  useEffect(() => {
    if (downloaded) return;
    const warn = (e) => { e.preventDefault(); e.returnValue = ""; };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [downloaded]);

  if (!rows?.length) return null;

  const download = async () => {
    setBusy(true); setErr(null);
    try {
      await api.downloadKitStickers(rows);
      setDownloaded(true);
    } catch (e) {
      setErr(e.message);
    } finally {
      setBusy(false);
    }
  };

  const copyAll = () => {
    const text = rows.map((r) => `${r.kit_code}\t${r.claim_code}`).join("\n");
    navigator.clipboard?.writeText(text);
  };

  return (
    <section ref={ref} className={`card claim-codes-card${downloaded ? "" : " warn-sticky"}`}>
      <div className="row">
        <b>
          {rows.length === 1 ? "Claim code" : `${rows.length} claim codes`} — shown only once
        </b>
        <span className="spacer" />
        {confirmDismiss ? (
          <span className="confirm-inline">
            Close without saving? These codes cannot be shown again.
            <button className="danger" onClick={onDismiss}>Close anyway</button>
            <button className="secondary" onClick={() => setConfirmDismiss(false)}>Keep open</button>
          </span>
        ) : (
          <button
            className="secondary"
            onClick={() => (downloaded ? onDismiss() : setConfirmDismiss(true))}
          >
            {downloaded ? "Close" : "Dismiss"}
          </button>
        )}
      </div>

      <p className="muted small">
        Ship each code with its kit — whoever receives it redeems the code to unlock the kit, with
        no admin step. We keep only a fingerprint, so this list cannot be recovered later.
      </p>

      <div className="row">
        <button onClick={download} disabled={busy}>
          {busy ? "Preparing…" : "⭳ Download for printing (.xlsx)"}
        </button>
        <button className="secondary" onClick={copyAll}>Copy all</button>
        {downloaded && <span className="ok small">✓ downloaded</span>}
      </div>
      {err && <p className="error">{err}</p>}

      <table className="table">
        <tbody>
          {rows.map((r) => (
            <tr key={r.kit_code}>
              <td>{r.kit_code}</td>
              <td className="mono"><b>{r.claim_code}</b></td>
              <td>
                <button
                  type="button"
                  className="linkish"
                  onClick={() => navigator.clipboard?.writeText(r.claim_code)}
                >
                  copy
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}
