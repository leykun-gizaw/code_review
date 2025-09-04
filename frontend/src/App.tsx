import { useState } from "react";
import { RunForm } from "./components/RunForm";
import { RunsTable } from "./components/RunsTable";
import { RunViewer } from "./components/RunViewer";

export default function App() {
  const [currentId, setCurrentId] = useState<number | null>(null);
  return (
    <div className="max-w-7xl mx-auto p-6 space-y-8">
      <div className="space-y-6">
        <RunForm onCreated={(id) => setCurrentId(id)} />
        <RunsTable onSelect={(id) => setCurrentId(id)} />
      </div>
      {currentId && (
        <div className="border-t pt-6">
          <RunViewer id={currentId} />
        </div>
      )}
    </div>
  );
}
