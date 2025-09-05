import os
import threading
import queue
import tempfile
import subprocess
import shutil
import logging
import traceback
import json
from datetime import datetime
from flask import Flask, request, jsonify
from persistence_single import (
    init_db,
    create_run,
    get_run,
    list_runs,
    store_analyzer_outputs,
    store_scorer_outputs,
    update_run_metadata,
)
from analyzer import run_analyzer, ANALYZER_TOOL_VERSION
from final_scorer import run_final_scorer, SCORER_TOOL_VERSION
from flask_cors import CORS
from ai_keys import get_next_key

app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# --- Logging Configuration ----------------------------------------------------
ERROR_LOG_PATH = os.getenv("ERROR_LOG_PATH", "error.log")
_log_dir = os.path.dirname(ERROR_LOG_PATH)
if _log_dir and not os.path.exists(_log_dir):
    try:
        os.makedirs(_log_dir, exist_ok=True)
    except Exception:
        # fallback to current directory if directory creation fails
        ERROR_LOG_PATH = "error.log"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logger = logging.getLogger("api")
logger.setLevel(LOG_LEVEL)

# Avoid duplicate handlers if module reloaded
if not any(
    isinstance(h, logging.FileHandler)
    and getattr(h, "baseFilename", "") == os.path.abspath(ERROR_LOG_PATH)
    for h in logger.handlers
):
    file_handler = logging.FileHandler(ERROR_LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(file_handler)

if not any(isinstance(h, logging.StreamHandler) for h in logger.handlers):
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    )
    logger.addHandler(stream_handler)

logger.info(
    f"Using error log file: {os.path.abspath(ERROR_LOG_PATH)} (level={LOG_LEVEL})"
)
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
            # Pick API key for this run (one key per repo run)
            key_label, api_key = get_next_key()
            update_run_metadata(run_id, status="RUNNING", api_key_label=key_label)

            clone_repo(repo_url, tmpdir)
            # capture branch + commit
            branch = subprocess.check_output(
                ["git", "-C", tmpdir, "rev-parse", "--abbrev-ref", "HEAD"], text=True
            ).strip()
            commit = subprocess.check_output(
                ["git", "-C", tmpdir, "rev-parse", "HEAD"], text=True
            ).strip()
            # Run analyzer unless already present
            json_obj = None
            if not run_row.get("analyzer_md"):
                md_report, json_obj, cache, total_passed, total_checks = run_analyzer(
                    tmpdir,
                    api_key=api_key,
                )
                store_analyzer_outputs(
                    run_id,
                    md_report,
                    json_obj,
                    cache,
                    commit,
                    branch,
                    ANALYZER_TOOL_VERSION,
                )
                run_row = get_run(run_id) or run_row
            else:
                # Parse stored analyzer JSON so scorer invocation uniform
                try:
                    stored = run_row.get("analyzer_json")
                    if stored:
                        json_obj = json.loads(stored)
                except Exception:
                    json_obj = None
            # Run scorer unless already present
            if not run_row.get("final_scorer_md") and json_obj is not None:
                scorer_md, scorer_json, scorer_cache, overall = run_final_scorer(
                    json_obj,
                    is_json=True,
                    api_key=api_key,
                )
                store_scorer_outputs(
                    run_id,
                    scorer_md,
                    scorer_json,
                    scorer_cache,
                    overall,
                    SCORER_TOOL_VERSION,
                )
            update_run_metadata(run_id, status="DONE")
        except Exception as e:
            tb = traceback.format_exc(limit=20)
            msg = f"Worker failure run_id={run_id} repo={repo_url} error={e}\n{tb}"
            logger.error(msg)
            # Fallback direct append in case handlers failed
            try:
                with open(ERROR_LOG_PATH, "a", encoding="utf-8") as _ef:
                    _ef.write(f"{datetime.utcnow().isoformat()}Z {msg}\n")
            except Exception:
                pass
            update_run_metadata(
                run_id, status="ERROR", scorer_tool_version=str(e)[:240]
            )
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


@app.route("/runs", methods=["GET"])
def list_runs_endpoint():
    try:
        limit = int(request.args.get("limit", "100"))
    except ValueError:
        limit = 100
    data = list_runs(limit=limit)
    return jsonify(data)


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
