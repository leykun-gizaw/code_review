# Analysis Frontend (React + Vite + TypeScript)

Minimal dashboard to:

- Create an analysis run (email + GitHub repo URL)
- Enqueue async analysis/scoring job
- Poll status and display analyzer / scorer markdown outputs + overall score

## Quick Start

1. Install deps

```bash
npm install
```

2. (Optional) Configure API base (defaults to http://localhost:5000). Create `.env`:

```
VITE_API_BASE=http://localhost:5000
```

3. Run dev server

```bash
npm run dev
```

4. Open the printed local URL (typically http://localhost:5173).

## File Overview

- `src/api.ts` REST helpers (createRun, enqueueRun, getRun)
- `src/components/RunForm.tsx` form to create + enqueue
- `src/components/RunViewer.tsx` polling status + output panels
- `src/App.tsx` composition
- `src/main.tsx` bootstrap

## Notes

- Simple in-memory polling (2.5s interval) until status DONE or ERROR.
- Analyzer / scorer markdown shown verbatim (no rendering of Markdown into HTML).
- Add security (auth) & validation in API before exposing publicly.

## Next Enhancements (Suggested)

- Add run list / history table
- Syntax highlight or Markdown render
- Abort / re-run buttons
- Dark/light theme toggle
- WebSocket or Server-Sent Events instead of polling
