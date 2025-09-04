import os
import threading
import queue
import tempfile
import subprocess
import shutil
from flask import Flask, request, jsonify
from persistence_single import (
    init_db,
    create_run,
    get_run,
    store_analyzer_outputs,
    store_scorer_outputs,
    update_run_metadata,
)
from analyzer import run_analyzer, ANALYZER_TOOL_VERSION
from final_scorer import run_final_scorer, SCORER_TOOL_VERSION

app = Flask(__name__)
JOB_QUEUE: "queue.Queue[int]" = queue.Queue()

WORKER_STARTED = False


def clone_repo(github_url: str, dest: str):
    subprocess.run(["git", "clone", "--depth", "50", github_url, dest], check=True)


def worker_loop():
    while True:
        run_id = JOB_QUEUE.get()
        if run_id is None:
            break
        run_row = get_run(run_id)
        if not run_row:
            continue
        if run_row.get("status") not in ("PENDING", "ERROR"):
            continue
        update_run_metadata(run_id, status="RUNNING")
        repo_url = run_row["github_url"]
        tmpdir = tempfile.mkdtemp(prefix=f"run_{run_id}_")
        try:
            clone_repo(repo_url, tmpdir)
            # capture branch + commit
            branch = subprocess.check_output(
                ["git", "-C", tmpdir, "rev-parse", "--abbrev-ref", "HEAD"], text=True
            ).strip()
            commit = subprocess.check_output(
                ["git", "-C", tmpdir, "rev-parse", "HEAD"], text=True
            ).strip()
            # Run analyzer unless already present
            if not run_row.get("analyzer_md"):
                md, js, ai_cache, passed, total = run_analyzer(tmpdir)
                store_analyzer_outputs(
                    run_id,
                    md,
                    js,
                    ai_cache,
                    commit_hash=commit,
                    branch_name=branch,
                    tool_version=ANALYZER_TOOL_VERSION,
                )
                run_row = get_run(run_id) or run_row
            # Run scorer unless already present
            if not run_row.get("final_scorer_md"):
                analyzer_json = run_row.get("analyzer_json")
                if analyzer_json:
                    md_s, js_s, ai_cache_s, overall = run_final_scorer(
                        analyzer_json, is_json=True
                    )
                    store_scorer_outputs(
                        run_id,
                        md_s,
                        js_s,
                        ai_cache_s,
                        overall_score=overall,
                        tool_version=SCORER_TOOL_VERSION,
                    )
            update_run_metadata(run_id, status="DONE")
        except Exception as e:
            update_run_metadata(run_id, status="ERROR", scorer_tool_version=str(e))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
        JOB_QUEUE.task_done()


def ensure_worker():
    global WORKER_STARTED
    if not WORKER_STARTED:
        t = threading.Thread(target=worker_loop, daemon=True)
        t.start()
        WORKER_STARTED = True


@app.route("/runs", methods=["POST"])
def create_run_endpoint():
    data = request.get_json(force=True)
    email = data.get("email")
    github_url = data.get("github_url")
    if not email or not github_url:
        return jsonify({"error": "email and github_url required"}), 400
    run_id = create_run(email, github_url)
    return jsonify({"id": run_id, "status": "PENDING"}), 201


@app.route("/runs/<int:run_id>", methods=["GET"])
def get_run_endpoint(run_id: int):
    row = get_run(run_id)
    if not row:
        return jsonify({"error": "not found"}), 404
    return jsonify(row)


@app.route("/runs/<int:run_id>/enqueue", methods=["POST"])
def enqueue_run(run_id: int):
    row = get_run(run_id)
    if not row:
        return jsonify({"error": "not found"}), 404
    ensure_worker()
    JOB_QUEUE.put(run_id)
    return jsonify({"queued": True, "id": run_id})


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("API_PORT", "5000")))
