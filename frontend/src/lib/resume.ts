import { API_BASE, ApiError, api, authHeaders, networkError } from "@/lib/api";
import type { ResumeOut } from "@/types";

/** Mirrors MAX_UPLOAD_MB on the server (default 5). The server is the real gate; this just saves a round trip. */
export const MAX_RESUME_MB = 5;

export function validateResumeFile(file: File): string | null {
  const isPdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!isPdf) return "Please choose a PDF file.";
  if (file.size === 0) return "That file is empty.";
  if (file.size > MAX_RESUME_MB * 1024 * 1024) return `The file is larger than ${MAX_RESUME_MB} MB.`;
  return null;
}

/** POST /resume with upload progress (fetch cannot report upload progress, so this uses XMLHttpRequest). */
export function uploadResume(file: File, onProgress: (percent: number) => void, signal?: AbortSignal): Promise<ResumeOut> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/resume`);
    for (const [k, v] of Object.entries(authHeaders())) xhr.setRequestHeader(k, v);
    xhr.setRequestHeader("Accept", "application/json");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(Math.round((e.loaded / e.total) * 100));
    xhr.onerror = () => reject(networkError());
    xhr.ontimeout = () => reject(networkError());
    xhr.onabort = () => reject(new DOMException("Aborted", "AbortError"));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* not JSON */
      }
      if (xhr.status >= 200 && xhr.status < 300) return resolve(body as ResumeOut);
      const e = (body as { error?: { code?: string; message?: string; request_id?: string } } | null)?.error;
      const retry = Number(xhr.getResponseHeader("Retry-After"));
      reject(
        new ApiError(xhr.status, e?.code ?? "http_error", e?.message ?? "Upload failed.", e?.request_id, retry > 0 ? retry : undefined),
      );
    };
    signal?.addEventListener("abort", () => xhr.abort(), { once: true });
    xhr.timeout = 60_000;
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export const getResume = (id: string) => api.get<ResumeOut>(`/resume/${id}`);
export const deleteResume = (id: string) => api.delete(`/resume/${id}`);
