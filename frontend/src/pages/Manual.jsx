import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeSlug from "rehype-slug";
import { MANUALS } from "../config/manuals.js";

// Drop a leading YAML front-matter block (--- ... ---) so it isn't rendered as content.
function stripFrontMatter(md) {
  return md.replace(/^\s*---\r?\n[\s\S]*?\r?\n---\r?\n/, "");
}

// Render links: in-app paths (/manuals/…) via react-router; everything else opens a new tab.
function MdLink({ href = "", children, ...props }) {
  if (href.startsWith("/")) {
    return <Link to={href} {...props}>{children}</Link>;
  }
  const external = /^https?:\/\//.test(href);
  return (
    <a href={href} {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})} {...props}>
      {children}
    </a>
  );
}

export default function Manual() {
  const { slug } = useParams();
  const manual = MANUALS[slug];
  const [text, setText] = useState(null);
  const [err, setErr] = useState(null);

  useEffect(() => {
    if (!manual) return;
    setText(null);
    setErr(null);
    fetch(manual.raw)
      .then((res) => {
        if (!res.ok) throw new Error(`Could not load the manual (HTTP ${res.status}).`);
        return res.text();
      })
      .then((md) => setText(stripFrontMatter(md)))
      .catch((e) => setErr(e.message));
  }, [manual, slug]);

  if (!manual) {
    return (
      <div className="container">
        <p className="error">Unknown manual “{slug}”.</p>
        <Link to="/">← Back</Link>
      </div>
    );
  }

  return (
    <div className="container">
      <div className="row">
        <h1>{manual.title}</h1>
        <span className="spacer" />
        <Link to="/">← Home</Link>
      </div>
      {err && <p className="error">{err}</p>}
      {!text && !err && <p>Loading…</p>}
      {text && (
        <div className="markdown-body">
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            rehypePlugins={[rehypeSlug]}
            components={{ a: MdLink }}
          >
            {text}
          </ReactMarkdown>
        </div>
      )}
    </div>
  );
}
