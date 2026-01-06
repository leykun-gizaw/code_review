import { useState, useEffect } from "react";
import { RunForm } from "./components/RunForm";
import { RunsTable } from "./components/RunsTable";
import { RunViewer } from "./components/RunViewer";
import { getAvailableCohorts } from "./api";

export default function App() {
  const [currentId, setCurrentId] = useState<number | null>(null);
  const [currentCohortId, setCurrentCohortId] = useState<string | null>(null);
  const [cohorts, setCohorts] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getAvailableCohorts()
      .then((data) => {
        if (active) {
          setCohorts(data);
          setLoading(false);
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
  }, []);

  const response = { cohorts, loading, error };
  console.log(currentCohortId);

  return (
    <div className="h-screen w-screen flex overflow-hidden text-slate-800">
      {/* Left Pane */}
      <div className="w-[48%] min-w-[520px] max-w-[920px] border-r border-slate-200 flex flex-col bg-slate-50/40">
        <div className="p-4 border-b bg-white/80 backdrop-blur">
          <h1 className="text-lg font-semibold tracking-tight">
            Repository Analyzer
          </h1>
        </div>
        <div className="p-4 space-y-4 overflow-y-auto custom-scroll">
          <RunForm onCreated={(id) => setCurrentId(id)} />
          <div className="flex items-center space-x-2">
            <label htmlFor="cohort-filter" className="text-sm font-medium">
              Filter by Cohort:
            </label>
            <select
              id="cohort-filter"
              className="border border-slate-300 rounded-md px-4 py-1 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              value={currentCohortId || "All Cohorts"}
              onChange={(e) =>
                setCurrentCohortId(e.target.value ? e.target.value : null)
              }
            >
              <option value="All Cohorts">All Cohorts</option>
              {response?.cohorts?.map((c: { id: string; name: string }) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>

          <RunsTable
            onSelect={(id) => setCurrentId(id)}
            currentCohortId={currentCohortId}
            currentId={currentId}
          />
        </div>
      </div>
      {/* Right Pane */}
      <div className="p-6 flex-1 flex flex-col bg-white">
        {currentId ? (
          <RunViewer id={currentId} />
        ) : (
          <div className="h-full w-full flex items-center justify-center text-slate-400 select-none">
            <div className="text-center space-y-2">
              <p className="text-sm">Select a run to view analysis & scores</p>
              <p className="text-xs">(Create or choose one on the left)</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
