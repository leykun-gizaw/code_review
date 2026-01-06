import { useState } from "react";
import { RunForm } from "./components/RunForm";
import { RunsTable } from "./components/RunsTable";
import { RunViewer } from "./components/RunViewer";

export default function App() {
  const [currentId, setCurrentId] = useState<number | null>(null);
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
          <RunsTable
            onSelect={(id) => setCurrentId(id)}
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
