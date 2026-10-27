import { useState } from "react";

/** Type-to-search user picker: input + suggestions + chips. `value` is an array of user ids. */
export default function AssigneePicker({ users, value, onChange }) {
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
