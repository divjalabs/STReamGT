import { Link } from "react-router-dom";
import { useAuth } from "../auth.jsx";

export default function Home() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";

  return (
    <div className="container">
      <div className="banner">
        <h2>Welcome to STReamGT</h2>
        <p className="muted">
          Upload your kit’s FASTQ data, run genotyping, and download your results and QC
          reports. New here? Start with the guides.
        </p>
        <p className="row" style={{ gap: "1rem" }}>
          <Link to="/manuals/user">User Guide</Link>
          {isAdmin && <Link to="/manuals/admin">Admin Guide</Link>}
        </p>
      </div>

      <div className="row" style={{ gap: "1rem", flexWrap: "wrap" }}>
        <Link to="/submit"><button>New analysis</button></Link>
        <Link to="/jobs"><button className="secondary">My analyses</button></Link>
        <Link to="/kits"><button className="secondary">My kits</button></Link>
      </div>
    </div>
  );
}
