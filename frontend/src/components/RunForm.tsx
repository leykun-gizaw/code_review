import { useState } from "react";
import { createRun } from "../api";

interface Props {
  onCreated(id: number): void;
}

export function RunForm({ onCreated }: Props) {
  const [email, setEmail] = useState("");
  const [repo, setRepo] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!email || !repo) {
      setError("Email and repository URL required");
      return;
    }
    try {
      setLoading(true);
      const { id } = await createRun(email, repo);
      onCreated(id);
    } catch (err: any) {
      setError(err.message || "Failed");
    } finally {
      setLoading(false);
      setEmail("");
      setRepo("");
    }
  }

  return (
    <form
      onSubmit={submit}
      className="flex flex-wrap gap-4 bg-white shadow-sm border border-slate-200 rounded-lg p-4"
    >
      <div className="flex flex-col min-w-[240px] flex-1">
        <label className="text-sm font-medium mb-1">Email</label>
        <input
          className="px-3 py-2 rounded-md border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="user@example.com"
        />
      </div>
      <div className="flex flex-col min-w-[260px] flex-1">
        <label className="text-sm font-medium mb-1">GitHub URL</label>
        <input
          className="px-3 py-2 rounded-md border border-slate-300 focus:outline-none focus:ring-2 focus:ring-blue-500"
          value={repo}
          onChange={(e) => setRepo(e.target.value)}
          placeholder="https://github.com/owner/repo.git"
        />
      </div>
      <div className="flex items-end">
        <button
          disabled={loading}
          className="h-[42px] inline-flex items-center px-5 rounded-md font-semibold bg-blue-600 text-white hover:bg-blue-500 disabled:opacity-60 disabled:cursor-not-allowed transition"
        >
          {loading ? "Submitting..." : "Submit"}
        </button>
      </div>
      {error && (
        <p className="basis-full text-sm font-medium text-red-600">{error}</p>
      )}
    </form>
  );
}
