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

  // kits
  listKits: () => request("/kits"),
  getKit: (id) => request(`/kits/${id}`),

  // jobs
  createJob: (payload) => request("/jobs", { method: "POST", body: payload }),
  listJobs: () => request("/jobs"),
  getJob: (publicId) => request(`/jobs/${publicId}`),
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
  // multipart
  const partSize = init.part_size;
  const parts = [];
  for (let i = 0; i < init.part_urls.length; i++) {
    const start = i * partSize;
    const chunk = file.slice(start, Math.min(start + partSize, file.size));
    const etag = await putWithProgress(init.part_urls[i], chunk, (f) =>
      onProgress((i + f) / init.part_urls.length)
    );
    parts.push({ part_number: i + 1, etag: etag.replaceAll('"', "") });
  }
  await api.completeUpload(init.key, init.upload_id, parts);
  onProgress(1);
  return init.key;
}

function putWithProgress(url, blob, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () =>
      xhr.status >= 200 && xhr.status < 300
        ? resolve(xhr.getResponseHeader("ETag") || "")
        : reject(new Error(`upload failed: ${xhr.status}`));
    xhr.onerror = () => reject(new Error("network error during upload"));
    xhr.send(blob);
  });
}
