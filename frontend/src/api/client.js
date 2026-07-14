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
  requestReanalysis: (publicId, reason) =>
    request(`/jobs/${publicId}/request-reanalysis`, { method: "POST", body: { reason } }),
  getResults: (publicId) => request(`/jobs/${publicId}/results`),

  // uploads
  initUpload: (filename, size, purpose) =>
    request("/jobs/uploads", { method: "POST", body: { filename, size, purpose } }),
  completeUpload: (key, uploadId, parts) =>
    request("/jobs/uploads/complete", {
      method: "POST",
      body: { key, upload_id: uploadId, parts },
    }),
};

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
