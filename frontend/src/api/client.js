// Thin fetch wrapper + direct-to-S3 upload helpers.

const TOKEN_KEY = "streamgt_token";

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
}

async function request(path, { method = "GET", body, form } = {}) {
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  let payload = body;
  if (form) {
    payload = form; // FormData; let the browser set Content-Type
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, { method, headers, body: payload });
  if (!res.ok) {
    let detail;
    try {
      detail = (await res.json()).detail;
    } catch {
      detail = res.statusText;
    }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  if (res.status === 204) return null;
  return res.json();
}

/** Fetch an authenticated binary endpoint and trigger a browser download. */
async function downloadBlob(path, filename) {
  const headers = {};
  const token = getToken();
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`/api${path}`, { headers });
  if (!res.ok) throw new Error(`Download failed (${res.status})`);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename || "download";
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export const api = {
  // auth
  register: (email, password, organisation) =>
    request("/auth/register", { method: "POST", body: { email, password, organisation } }),
  login: async (email, password) => {
    const form = new URLSearchParams({ username: email, password });
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
      body: form,
    });
    if (!res.ok) throw new Error("Incorrect email or password");
    return res.json();
  },
  me: () => request("/auth/me"),
  forgotPassword: (email) =>
    request("/auth/forgot-password", { method: "POST", body: { email } }),
  resetPassword: (token, newPassword) =>
    request("/auth/reset-password", { method: "POST", body: { token, new_password: newPassword } }),

  // kits
  listKits: () => request("/kits"),
  getKit: (id) => request(`/kits/${id}`),
  createKit: (payload) => request("/kits", { method: "POST", body: payload }),
  updateKit: (id, body) => request(`/kits/${id}`, { method: "PATCH", body }),
  deleteKit: (id) => request(`/kits/${id}`, { method: "DELETE" }),
  getTagLayout: () => request("/kits/tag-layout"),
  downloadKitTemplate: (id, filename) => downloadBlob(`/kits/${id}/control-template.xlsx`, filename),

  // control-position templates (admin)
  listControlTemplates: () => request("/control-templates"),
  createControlTemplate: (payload) => request("/control-templates", { method: "POST", body: payload }),
  deleteControlTemplate: (id) => request(`/control-templates/${id}`, { method: "DELETE" }),

  // panels (admin)
  listPanels: () => request("/panels"),
  getPanel: (id) => request(`/panels/${id}`),
  createPanel: (form) => request("/panels", { method: "POST", form }),
  updatePanel: (id, body) => request(`/panels/${id}`, { method: "PATCH", body }),
  deletePanel: (id) => request(`/panels/${id}`, { method: "DELETE" }),
  downloadPanel: (id) => request(`/panels/${id}/download`),

  // users (admin)
  listUsers: () => request("/users"),
  updateUser: (id, body) => request(`/users/${id}`, { method: "PATCH", body }),

  // jobs
  createJob: (payload) => request("/jobs", { method: "POST", body: payload }),
  listJobs: () => request("/jobs"),
  getJob: (publicId) => request(`/jobs/${publicId}`),
  confirmJob: (publicId, proceed) =>
    request(`/jobs/${publicId}/confirm`, { method: "POST", body: { proceed } }),
  rerunJob: (publicId) => request(`/jobs/${publicId}/rerun`, { method: "POST" }),
  ingestJob: (publicId, body) => request(`/jobs/${publicId}/ingest`, { method: "POST", body }),
  requestReanalysis: (publicId, reason) =>
    request(`/jobs/${publicId}/request-reanalysis`, { method: "POST", body: { reason } }),
  reportJobError: (publicId, note) =>
    request(`/jobs/${publicId}/report-error`, { method: "POST", body: { note } }),
  getResults: (publicId) => request(`/jobs/${publicId}/results`),

  // projects (animal/sample store)
  listProjects: () => request("/projects"),
  getProject: (id) => request(`/projects/${id}`),
  createProject: (payload) => request("/projects", { method: "POST", body: payload }),
  deleteProject: (id) => request(`/projects/${id}`, { method: "DELETE" }),
  shareProject: (id, email, role) =>
    request(`/projects/${id}/share`, { method: "POST", body: { email, role } }),
  listProjectAccess: (id) => request(`/projects/${id}/access`),
  unshareProject: (id, userId) => request(`/projects/${id}/share/${userId}`, { method: "DELETE" }),
  // import / export
  importGenotypes: (id, file) => {
    const fd = new FormData(); fd.append("file", file);
    return request(`/projects/${id}/import/genotypes`, { method: "POST", form: fd });
  },
  importProjectJson: (file) => {
    const fd = new FormData(); fd.append("file", file);
    return request("/projects/import", { method: "POST", form: fd });
  },
  listPopulations: (id) => request(`/projects/${id}/populations`),
  createPopulation: (id, payload) =>
    request(`/projects/${id}/populations`, { method: "POST", body: payload }),
  deletePopulation: (id, popId, { reassign_to, delete_samples } = {}) => {
    const q = new URLSearchParams();
    if (reassign_to != null) q.set("reassign_to", reassign_to);
    if (delete_samples) q.set("delete_samples", "true");
    const qs = q.toString();
    return request(`/projects/${id}/populations/${popId}${qs ? `?${qs}` : ""}`, { method: "DELETE" });
  },
  listStudies: (id) => request(`/projects/${id}/studies`),
  createStudy: (id, payload) =>
    request(`/projects/${id}/studies`, { method: "POST", body: payload }),
  getStudy: (studyId) => request(`/studies/${studyId}`),
  deleteStudy: (studyId) => request(`/studies/${studyId}`, { method: "DELETE" }),
  attachKit: (studyId, kitId) =>
    request(`/studies/${studyId}/kits/${kitId}`, { method: "POST" }),
  detachKit: (studyId, kitId) =>
    request(`/studies/${studyId}/kits/${kitId}`, { method: "DELETE" }),
  listSampleTypes: (id) => request(`/projects/${id}/sample-types`),
  // samples
  getPopulation: (populationId) => request(`/populations/${populationId}`),
  listPopulationSamples: (populationId) => request(`/populations/${populationId}/samples`),
  getSample: (sampleId) => request(`/samples/${sampleId}`),
  patchSample: (sampleId, body) => request(`/samples/${sampleId}`, { method: "PATCH", body }),
  getSampleReplicates: (sampleId) => request(`/samples/${sampleId}/replicates`),
  getSamplePlotData: (sampleId, markers) =>
    request(`/samples/${sampleId}/plot-data${markers && markers.length ? `?markers=${markers.join(",")}` : ""}`),
  listStudySamples: (studyId) => request(`/studies/${studyId}/samples`),
  listKitSamples: (kitId) => request(`/kits/${kitId}/samples`),
  listProjectSamples: (projectId) => request(`/projects/${projectId}/samples`),
  // consensus (M2)
  rerunSampleConsensus: (sampleId) =>
    request(`/samples/${sampleId}/rerun-consensus`, { method: "POST" }),
  rerunPopulationConsensus: (populationId) =>
    request(`/populations/${populationId}/rerun-consensus`, { method: "POST" }),
  editConsensus: (consensusId, body) =>
    request(`/consensus/${consensusId}`, { method: "PATCH", body }),
  lockConsensus: (consensusId) => request(`/consensus/${consensusId}/lock`, { method: "POST" }),
  unlockConsensus: (consensusId) => request(`/consensus/${consensusId}/unlock`, { method: "POST" }),
  // matching (M3)
  rerunMatch: (populationId) =>
    request(`/populations/${populationId}/rerun-match`, { method: "POST" }),
  listSubgroups: (populationId) => request(`/populations/${populationId}/subgroups`),
  getSubgroup: (subgroupId) => request(`/subgroups/${subgroupId}`),
  rematchSubgroup: (subgroupId) => request(`/subgroups/${subgroupId}/rematch`, { method: "POST" }),
  patchSubgroup: (subgroupId, body) => request(`/subgroups/${subgroupId}`, { method: "PATCH", body }),
  listSupergroups: (populationId) => request(`/populations/${populationId}/supergroups`),
  listMatches: (populationId) => request(`/populations/${populationId}/matches`),
  getMatchingSettings: (populationId) => request(`/populations/${populationId}/matching-settings`),
  putMatchingSettings: (populationId, body) =>
    request(`/populations/${populationId}/matching-settings`, { method: "PUT", body }),

  // uploads
  initUpload: (filename, size, purpose) =>
    request("/jobs/uploads", { method: "POST", body: { filename, size, purpose } }),
  completeUpload: (key, uploadId, parts) =>
    request("/jobs/uploads/complete", {
      method: "POST",
      body: { key, upload_id: uploadId, parts },
    }),
};

// Download a project export (auth-gated) and trigger a browser save.
export async function downloadExport(projectId, kind) {
  const token = getToken();
  const res = await fetch(`/api/projects/${projectId}/export/${kind}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    let detail;
    try { detail = (await res.json()).detail; } catch { detail = res.statusText; }
    throw new Error(typeof detail === "string" ? detail : "export failed");
  }
  const blob = await res.blob();
  const cd = res.headers.get("Content-Disposition") || "";
  const m = cd.match(/filename="?([^"]+)"?/);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = m ? m[1] : `${kind}`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

// Upload a File directly to S3. Returns the object key to reference in the job.
// onProgress(fraction) is called 0..1. Requires the bucket's CORS to expose ETag.
export async function uploadFile(file, purpose, onProgress = () => {}) {
  const init = await api.initUpload(file.name, file.size, purpose);
  if (init.method === "put") {
    await putWithProgress(init.put_url, file, onProgress);
    return init.key;
  }
  // multipart — upload parts with limited concurrency to better saturate bandwidth
  const partSize = init.part_size;
  const n = init.part_urls.length;
  const parts = new Array(n);
  const prog = new Array(n).fill(0);
  const report = () => onProgress(prog.reduce((a, b) => a + b, 0) / n);

  const CONCURRENCY = Math.min(6, n); // browsers cap ~6 connections/host — this saturates the link
  let next = 0;
  async function worker() {
    while (next < n) {
      const i = next++;
      const start = i * partSize;
      const chunk = file.slice(start, Math.min(start + partSize, file.size));
      const etag = await putWithProgress(init.part_urls[i], chunk, (f) => {
        prog[i] = f;
        report();
      });
      parts[i] = { part_number: i + 1, etag: etag.replaceAll('"', "") };
    }
  }
  await Promise.all(Array.from({ length: CONCURRENCY }, worker));
  await api.completeUpload(init.key, init.upload_id, parts);
  onProgress(1);
  return init.key;
}

// PUT a blob with progress + automatic retry. A stalled/failed part is retried (with backoff)
// instead of failing the whole upload — essential for reliable large-file uploads.
function putWithProgress(url, blob, onProgress, attempts = 4) {
  return new Promise((resolve, reject) => {
    const tryOnce = (n) => {
      const xhr = new XMLHttpRequest();
      xhr.open("PUT", url);
      xhr.timeout = 120000; // 2 min per part; a genuine stall trips this and retries
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded / e.total);
      };
      const again = (why) => {
        if (n < attempts) setTimeout(() => tryOnce(n + 1), 800 * n);
        else reject(new Error(`upload failed after ${attempts} attempts: ${why}`));
      };
      xhr.onload = () =>
        xhr.status >= 200 && xhr.status < 300
          ? resolve(xhr.getResponseHeader("ETag") || "")
          : again(`status ${xhr.status}`);
      xhr.onerror = () => again("network error");
      xhr.ontimeout = () => again("timeout");
      xhr.send(blob);
    };
    tryOnce(1);
  });
}
