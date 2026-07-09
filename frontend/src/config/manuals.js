// Manuals are fetched live from the public GitHub repo at render time, so editing a
// manual only requires committing to docs/ on GitHub — no app rebuild/redeploy.
// (GitHub's raw CDN caches ~5 min, so edits appear within a few minutes.)
//
// DOCS_REF is the branch/tag the app reads manuals from. Defaults to "main" (the repo's
// mainline, where the docs live). Override at build/dev time with VITE_DOCS_REF to preview
// docs on another branch, e.g.
//   VITE_DOCS_REF=my-docs-branch npm run dev
// Changing the ref needs a rebuild; changing manual *content* on that ref does not.
export const DOCS_REF = import.meta.env.VITE_DOCS_REF || "main";

const RAW = `https://raw.githubusercontent.com/divjalabs/STReamGT/${DOCS_REF}/docs`;

export const MANUALS = {
  user: {
    title: "User Guide",
    raw: `${RAW}/user-manual.md`,
  },
  admin: {
    title: "Admin Guide",
    raw: `${RAW}/admin-manual.md`,
    adminOnly: true,
  },
};
