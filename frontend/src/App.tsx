import { useState } from "react";
import { RunForm } from "./components/RunForm";
import { RunViewer } from "./components/RunViewer";

export default function App() {
  const [currentId, setCurrentId] = useState<number | null>(null);
  return (
    <div style={{ display: "grid", gap: "1.5rem" }}>
      <RunForm onCreated={(id) => setCurrentId(id)} />
      {currentId && <RunViewer id={currentId} />}
    </div>
  );
}
