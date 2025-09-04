import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
// GitHub-flavored markdown (tables, strikethrough, task lists)
import remarkGfm from "remark-gfm";
import { getRun, enqueueRun, RunRow } from "../api";

interface Props {
  id: number;
}

export function RunViewer({ id }: Props) {
  const [data, setData] = useState<RunRow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"analyzer" | "scorer">("analyzer");

  useEffect(() => {
    let active = true;
    async function poll() {
      try {
        const row = await getRun(id);
        if (!active) return;
        setData(row);
        if (row.status !== "DONE" && row.status !== "ERROR") {
          setTimeout(poll, 2500);
        }
      } catch (e: any) {
        if (active) setError(e.message || "Fetch failed");
      }
    }
    poll();
    return () => {
      active = false;
    };
  }, [id]);

  if (error)
    return (
      <div className="border border-red-200 bg-red-50 text-red-700 p-3 rounded">
        Error: {error}
      </div>
    );
  if (!data)
    return (
      <div className="border border-slate-200 bg-white p-3 rounded shadow-sm">
        Loading run #{id}...
      </div>
    );

  return (
    <div className="grid gap-6 md:grid-cols-4">
      <div className="md:col-span-1 space-y-3">
        <div className="bg-white rounded-lg border border-slate-200 p-4 shadow-sm">
          <h2 className="text-base font-semibold mb-2">Run #{data.id}</h2>
          <Meta label="Status" value={<StatusBadge status={data.status} />} />
          <Meta label="Email" value={data.email} />
          <Meta
            label="Repository"
            value={
              <a
                className="text-blue-600 underline"
                href={data.github_url}
                target="_blank"
                rel="noreferrer"
              >
                Open Repo
              </a>
            }
          />
          {data.commit_hash && (
            <Meta label="Commit" value={data.commit_hash.slice(0, 10)} />
          )}
          {data.branch_name && <Meta label="Branch" value={data.branch_name} />}
          {data.overall_score != null && (
            <Meta label="Overall Score" value={data.overall_score} />
          )}
          {(data.status === "PENDING" || data.status === "ERROR") && (
            <button
              onClick={() => enqueueRun(id)}
              className="mt-3 w-full inline-flex justify-center items-center rounded-md bg-blue-600 text-white px-3 py-2 text-sm font-medium hover:bg-blue-500"
            >
              Enqueue
            </button>
          )}
        </div>
      </div>
      <div className="md:col-span-3 space-y-4">
        <div>
          <div className="flex border-b border-slate-200 mb-4 gap-4 text-sm">
            <button
              onClick={() => setTab("analyzer")}
              className={`pb-2 -mb-px border-b-2 ${
                tab === "analyzer"
                  ? "border-blue-600 text-blue-700 font-medium"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              Analyzer
            </button>
            <button
              onClick={() => setTab("scorer")}
              className={`pb-2 -mb-px border-b-2 ${
                tab === "scorer"
                  ? "border-blue-600 text-blue-700 font-medium"
                  : "border-transparent text-slate-500 hover:text-slate-700"
              }`}
            >
              Scorer
            </button>
          </div>
          {tab === "analyzer" ? (
            <MarkdownBlock
              content={data.analyzer_md}
              emptyLabel="Analyzer output not ready yet."
            />
          ) : (
            <MarkdownBlock
              content={data.final_scorer_md}
              emptyLabel="Scorer output not ready yet."
            />
          )}
        </div>
        <div>
          <h3 className="text-sm font-semibold tracking-wide uppercase text-slate-600 mb-2">
            Summary Table
          </h3>
          {renderSummaryTable(data)}
        </div>
      </div>
    </div>
  );
}

function Meta({ label, value }: { label: string; value: any }) {
  return (
    <p className="text-sm flex justify-between gap-2">
      <span className="text-slate-500">{label}</span>
      <span className="font-medium text-slate-800 text-right break-all">
        {value}
      </span>
    </p>
  );
}

function MarkdownBlock({
  content,
  emptyLabel,
}: {
  content: any;
  emptyLabel: string;
}) {
  if (!content) {
    return (
      <div className="p-4 border border-dashed border-slate-300 rounded-md text-sm text-slate-500">
        {emptyLabel}
      </div>
    );
  }
  return (
    <div className="p-4 border border-slate-200 bg-white rounded-md overflow-auto text-sm leading-relaxed text-slate-800 max-h-[540px] markdown-content">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          code({ node, inline: _inline, className, children, ..._props }: any) {
            const isInline = _inline as boolean;
            const lang = /language-/.test(className || "")
              ? className
              : undefined;
            if (isInline) {
              return (
                <code className="px-1 py-0.5 rounded bg-slate-100 text-[0.85em]">
                  {children}
                </code>
              );
            }
            return (
              <pre className="bg-slate-900 text-slate-100 p-3 rounded-md overflow-auto text-xs mb-3">
                <code className={lang}>{children}</code>
              </pre>
            );
          },
          h1: ({ children, ...p }) => (
            <h1 className="text-xl font-semibold mt-2 mb-3" {...p}>
              {children}
            </h1>
          ),
          h2: ({ children, ...p }) => (
            <h2 className="text-lg font-semibold mt-4 mb-2" {...p}>
              {children}
            </h2>
          ),
          h3: ({ children, ...p }) => (
            <h3 className="text-base font-semibold mt-4 mb-2" {...p}>
              {children}
            </h3>
          ),
          ul: ({ children, ...p }) => (
            <ul className="list-disc ml-5 mb-3 space-y-1" {...p}>
              {children}
            </ul>
          ),
          ol: ({ children, ...p }) => (
            <ol className="list-decimal ml-5 mb-3 space-y-1" {...p}>
              {children}
            </ol>
          ),
          p: ({ children, ...p }) => (
            <p className="mb-3" {...p}>
              {children}
            </p>
          ),
          table: ({ children, ...p }) => (
            <table className="mb-4 border border-slate-300 text-sm" {...p}>
              {children}
            </table>
          ),
          thead: ({ children, ...p }) => (
            <thead className="bg-slate-100" {...p}>
              {children}
            </thead>
          ),
          th: ({ children, ...p }) => (
            <th className="border border-slate-300 px-2 py-1 text-left" {...p}>
              {children}
            </th>
          ),
          td: ({ children, ...p }) => (
            <td className="border border-slate-300 px-2 py-1 align-top" {...p}>
              {children}
            </td>
          ),
        }}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    PENDING: "bg-slate-400",
    RUNNING: "bg-blue-500",
    ANALYZED: "bg-purple-500",
    DONE: "bg-green-600",
    ERROR: "bg-red-600",
  };
  return (
    <span
      className={`inline-flex items-center h-5 px-2 rounded text-xs font-semibold text-white ${
        map[status] || "bg-slate-500"
      }`}
    >
      {status}
    </span>
  );
}

function renderSummaryTable(row: RunRow) {
  // Basic high-level summary derived from presence of outputs
  const items = [
    {
      key: "Analyzer",
      present: !!row.analyzer_md,
      note: row.analyzer_md ? "Generated" : "Pending",
    },
    {
      key: "Scorer",
      present: !!row.final_scorer_md,
      note: row.final_scorer_md ? "Generated" : "Pending",
    },
    {
      key: "Overall Score",
      present: row.overall_score != null,
      note: row.overall_score != null ? row.overall_score : "—",
    },
  ];
  return (
    <div className="overflow-x-auto bg-white border border-slate-200 rounded-md">
      <table className="min-w-full text-sm">
        <thead className="bg-slate-50 text-slate-600">
          <tr>
            <th className="text-left font-semibold px-3 py-2">Item</th>
            <th className="text-left font-semibold px-3 py-2">Status</th>
            <th className="text-left font-semibold px-3 py-2">Detail</th>
          </tr>
        </thead>
        <tbody>
          {items.map((i) => (
            <tr key={i.key} className="border-t border-slate-100">
              <td className="px-3 py-2 font-medium text-slate-800">{i.key}</td>
              <td className="px-3 py-2">
                {i.present ? (
                  <span className="text-green-600 font-medium">Ready</span>
                ) : (
                  <span className="text-slate-400">Pending</span>
                )}
              </td>
              <td className="px-3 py-2 text-slate-600">{i.note}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
