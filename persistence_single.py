import os
import json
import psycopg
from contextlib import contextmanager
from typing import Optional, Dict, Any

DATABASE_URL = os.getenv("DATABASE_URL")

DB_KW = dict(
    dbname=os.getenv("POSTGRES_DB", "analysis_db"),
    user=os.getenv("POSTGRES_USER", "analysis_user"),
    password=os.getenv("POSTGRES_PASSWORD", "change_me"),
    host=os.getenv("POSTGRES_HOST", "localhost"),
    port=os.getenv("POSTGRES_PORT", "5432"),
)


@contextmanager
def get_conn():
    if DATABASE_URL:
        with psycopg.connect(DATABASE_URL) as conn:  # type: ignore[arg-type]
            yield conn
    else:
        with psycopg.connect(**DB_KW) as conn:  # type: ignore[arg-type]
            yield conn


def init_db(sql_path: str = "init.sql"):
    with open(sql_path, "r", encoding="utf-8") as f:
        ddl = f.read()
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(ddl)  # type: ignore[arg-type]
        conn.commit()


def create_run(email: str, github_url: str) -> int:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(
            """INSERT INTO analysis_runs (email, github_url) VALUES (%s, %s) RETURNING id""",
            (email, github_url),
        )
        row = cur.fetchone()
        if not row:
            raise RuntimeError("Failed to insert run (no id returned)")
        run_id = row[0]
        conn.commit()
        return run_id


def update_run_metadata(run_id: int, **fields):
    if not fields:
        return
    cols = []
    values = []
    for k, v in fields.items():
        cols.append(f"{k}=%s")
        values.append(v)
    values.append(run_id)
    sql = f"UPDATE analysis_runs SET {', '.join(cols)}, updated_at=NOW() WHERE id=%s"
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute(sql, values)
        conn.commit()


def get_run(run_id: int) -> Optional[Dict[str, Any]]:
    with get_conn() as conn, conn.cursor() as cur:
        cur.execute("SELECT * FROM analysis_runs WHERE id=%s", (run_id,))
        row = cur.fetchone()
        if not row:
            return None
        cols = [desc.name for desc in cur.description]  # type: ignore[attr-defined]
        return dict(zip(cols, row))


def store_analyzer_outputs(
    run_id: int,
    md: str,
    json_obj: Dict[str, Any],
    ai_cache: Dict[str, Any],
    commit_hash: str,
    branch_name: str,
    tool_version: str,
):
    update_run_metadata(
        run_id,
        analyzer_md=md,
        analyzer_json=json.dumps(json_obj),
        analyzer_ai_cache=json.dumps(ai_cache),
        commit_hash=commit_hash,
        branch_name=branch_name,
        analysis_started_at=json_obj.get("generated_at"),
        analyzer_tool_version=tool_version,
        status="ANALYZED",
    )


def store_scorer_outputs(
    run_id: int,
    md: str,
    json_obj: Dict[str, Any],
    ai_cache: Dict[str, Any],
    overall_score: float,
    tool_version: str,
):
    update_run_metadata(
        run_id,
        final_scorer_md=md,
        final_scorer_json=json.dumps(json_obj),
        scorer_ai_cache=json.dumps(ai_cache),
        overall_score=overall_score,
        scorer_tool_version=tool_version,
        status="DONE",
    )
