import { useEffect, useState, useRef } from "react";
import { listRuns, enqueueRun, getRun, RunRow } from "../api";
import clsx from "clsx";

interface Props {
  onSelect(id: number): void;
  currentCohortId?: string | null;
  currentId: number | null;
}

export function RunsTable({ onSelect, currentCohortId, currentId }: Props) {
  const [rows, setRows] = useState<RunRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshTick, setRefreshTick] = useState(0);
  const [busy, setBusy] = useState<number | null>(null);
  const autoSelected = useRef(false);

  useEffect(() => {
    let active = true;
    setLoading(true);
    listRuns(200)
      .then((data) => {
        if (active) {
          setRows(data);
          setLoading(false);
          // Auto-select the newest (list assumed sorted desc by created_at/id) once
          if (!autoSelected.current && data.length > 0) {
            onSelect(data[0].id);
            autoSelected.current = true;
          }
        }
      })
      .catch((e) => {
        if (active) {
          setError(e.message || "Fetch failed");
          setLoading(false);
        }
      });
    return () => {
      active = false;
    };
  }, [refreshTick]);

  async function analyze(id: number) {
    try {
      setBusy(id);
      await enqueueRun(id);
      // optimistic status update
      setRows((r) =>
        r.map((x) =>
          x.id === id
            ? {
                ...x,
                status:
                  x.status === "PENDING" || x.status === "ERROR"
                    ? "RUNNING"
                    : x.status,
              }
            : x
        )
      );
      // poll that single row for a short time to refresh score
      setTimeout(async () => {
        try {
          const updated = await getRun(id);
          setRows((r) => r.map((x) => (x.id === id ? updated : x)));
        } catch (_e) {}
      }, 3000);
    } finally {
      setBusy(null);
    }
  }

  if (loading)
    return <div className="text-sm text-slate-500">Loading runs…</div>;
  if (error) return <div className="text-sm text-red-600">Error: {error}</div>;

  return (
    <div className="space-y-2">
      <div className="flex justify-between items-center">
        <h2 className="text-base font-semibold">Runs</h2>
        <button
          onClick={() => setRefreshTick((t) => t + 1)}
          className="text-sm px-3 py-1.5 rounded-md border border-slate-300 bg-white hover:bg-slate-50"
        >
          Refresh
        </button>
      </div>
      <div className="overflow-x-auto border border-slate-200 rounded-md bg-white">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-50 text-slate-600">
            <tr>
              <th className="px-3 py-2 text-left font-medium">ID</th>
              <th className="px-3 py-2 text-left font-medium">Email</th>
              <th className="px-3 py-2 text-left font-medium">Cohort</th>
              <th className="px-3 py-2 text-left font-medium">Repository</th>
              <th className="px-3 py-2 text-left font-medium">Status</th>
              <th className="px-3 py-2 text-left font-medium">Score</th>
              <th className="px-3 py-2 text-left font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rows
              .filter((r) =>
                currentCohortId && currentCohortId !== "All Cohorts"
                  ? r.cohort_id === currentCohortId
                  : true
              )
              .map((r) => (
                <tr
                  key={r.id}
                  className={clsx(
                    "border-t border-slate-100 hover:bg-slate-50",
                    {
                      "bg-slate-100": currentId === r.id,
                    }
                  )}
                >
                  <td className="px-3 py-2 font-medium text-slate-800">
                    <button
                      onClick={() => onSelect(r.id)}
                      className="underline decoration-dotted"
                    >
                      {r.id}
                    </button>
                  </td>
                  <td className="px-3 py-2">{r.email}</td>
                  <td className="px-3 py-2">{r.cohort_name}</td>
                  <td className="px-3 py-2 max-w-[220px] truncate">
                    <a
                      href={r.github_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-blue-500 hover:text-blue-700 underline"
                    >
                      Repo Link
                    </a>
                  </td>
                  <td className="px-3 py-2">{statusBadge(r.status)}</td>
                  <td className="px-3 py-2">
                    {r.overall_score != null ? r.overall_score : "—"}
                  </td>
                  <td className="px-3 py-2 space-x-2 flex">
                    {(r.status === "PENDING" || r.status === "ERROR") && (
                      <button
                        disabled={busy === r.id}
                        onClick={() => analyze(r.id)}
                        className="px-2 py-1 rounded bg-blue-600 text-white text-xs font-semibold disabled:opacity-50"
                      >
                        {busy === r.id ? "…" : "Analyze"}
                      </button>
                    )}
                    <button
                      onClick={() => onSelect(r.id)}
                      className="px-2 py-1 rounded border border-slate-300 text-xs flex-1"
                    >
                      View
                    </button>
                  </td>
                </tr>
              ))}
            {rows.length === 0 && (
              <tr>
                <td
                  colSpan={6}
                  className="px-3 py-6 text-center text-slate-500"
                >
                  No runs yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function statusBadge(status: string) {
  const map: Record<string, string> = {
    PENDING: "bg-slate-400",
    RUNNING: "bg-blue-500",
    ANALYZED: "bg-purple-500",
    DONE: "bg-green-600",
    ERROR: "bg-red-600",
    QUEUED: "bg-yellow-500",
  };
  return (
    <span
      className={`inline-block px-2 py-0.5 rounded text-white text-xs font-semibold ${
        map[status] || "bg-slate-500"
      }`}
    >
      {status}
    </span>
  );
}
