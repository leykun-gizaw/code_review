export interface RunRow {
  id: number;
  email: string;
  github_url: string;
  status: string;
  analyzer_md?: string | null;
  analyzer_json?: any;
  final_scorer_md?: string | null;
  final_scorer_json?: any;
  overall_score?: number | null;
  commit_hash?: string | null;
  branch_name?: string | null;
  created_at?: string;
  updated_at?: string;
}

const API_BASE = import.meta.env.VITE_API_BASE || "http://localhost:5000";

async function jsonFetch<T>(url: string, opts: RequestInit = {}): Promise<T> {
  const r = await fetch(url, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export async function createRun(email: string, github_url: string) {
  return jsonFetch<{ id: number; status: string }>(`${API_BASE}/runs`, {
    method: "POST",
    body: JSON.stringify({ email, github_url }),
  });
}

export async function enqueueRun(id: number) {
  return jsonFetch<{ queued: boolean; id: number }>(
    `${API_BASE}/runs/${id}/enqueue`,
    { method: "POST" }
  );
}

export async function getRun(id: number) {
  return jsonFetch<RunRow>(`${API_BASE}/runs/${id}`);
}
