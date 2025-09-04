-- Single table schema for analysis & scoring with caching of AI raw responses

CREATE TABLE IF NOT EXISTS analysis_runs (
    id SERIAL PRIMARY KEY,
    email TEXT NOT NULL,
    github_url TEXT NOT NULL,
    -- provenance / traceability
    commit_hash TEXT,
    branch_name TEXT,
    analysis_started_at TIMESTAMPTZ,
    analyzer_tool_version TEXT,
    scorer_tool_version TEXT,
    -- analyzer outputs
    analyzer_md TEXT,
    analyzer_json JSONB,
    -- scorer outputs
    final_scorer_md TEXT,
    final_scorer_json JSONB,
    overall_score NUMERIC(4,2),
    -- cached AI raw responses
    analyzer_ai_cache JSONB,
    scorer_ai_cache JSONB,
    status TEXT NOT NULL DEFAULT 'PENDING', -- PENDING | RUNNING | DONE | ERROR
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_analysis_runs_email ON analysis_runs(email);
CREATE INDEX IF NOT EXISTS idx_analysis_runs_github ON analysis_runs(github_url);
