import os
import yaml
import subprocess
import time
import json
import hashlib
from datetime import datetime
from threading import Lock
from dotenv import load_dotenv
from google import genai

ANALYZER_TOOL_VERSION = "analyzer-0.1.0"

load_dotenv()

# --- AI Configuration ---
# The script reads the API key from your environment variables for security.
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
client = None
if GOOGLE_API_KEY:
    try:
        client = genai.Client(api_key=GOOGLE_API_KEY)
        print("✅ Gemini API configured successfully.")
    except Exception as e:
        print(f"⚠️  Gemini API init failed: {e}")
else:
    print("⚠️  GOOGLE_API_KEY not set; AI checks will fail.")


# --- Rate Limiter & Caching Layer -------------------------------------------------
class RateLimiter:
    """Simple token bucket / sliding window hybrid to cap calls per minute.

    Environment variable AI_MAX_CALLS_PER_MINUTE (default 6) controls throughput.
    """

    def __init__(self, max_per_minute: int):
        self.max_per_minute = max_per_minute
        self.calls = []  # timestamps
        self.lock = Lock()

    def acquire(self):
        with self.lock:
            now = time.time()
            one_minute_ago = now - 60
            # drop old timestamps
            self.calls = [t for t in self.calls if t > one_minute_ago]
            if len(self.calls) >= self.max_per_minute:
                sleep_for = 60 - (now - self.calls[0]) + 0.1
                if sleep_for > 0:
                    print(
                        f"  - ⏳ RateLimiter sleeping {sleep_for:.1f}s to respect quota..."
                    )
                    time.sleep(sleep_for)
            # record call
            self.calls.append(time.time())


AI_MAX_CALLS_PER_MINUTE = int(os.getenv("AI_MAX_CALLS_PER_MINUTE", "6"))
_rate_limiter = RateLimiter(AI_MAX_CALLS_PER_MINUTE)

_cache_lock = Lock()
_cache_path = os.getenv("AI_CACHE_FILE", ".ai_cache.json")
try:
    if os.path.exists(_cache_path):
        with open(_cache_path, "r") as _f:
            _ai_cache = json.load(_f)
    else:
        _ai_cache = {}
except Exception:
    _ai_cache = {}


def _hash_prompt(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8", errors="ignore")).hexdigest()


def _save_cache():
    try:
        with _cache_lock:
            with open(_cache_path, "w") as f:
                json.dump(_ai_cache, f)
    except Exception:
        pass  # non-critical


def generate_ai_content(prompt: str):
    """Central AI call with caching, rate limiting, and robust retries.

    Returns tuple (success: bool, answer: str)
    """
    key = _hash_prompt(prompt)
    with _cache_lock:
        if key in _ai_cache:
            return True, _ai_cache[key]

    max_attempts = 5
    base_delay = 2
    for attempt in range(1, max_attempts + 1):
        _rate_limiter.acquire()
        try:
            if client is None:
                raise RuntimeError("AI client not configured (missing GOOGLE_API_KEY)")
            response = client.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
            )
            answer = (response.text or "").strip()
            with _cache_lock:
                _ai_cache[key] = answer
            _save_cache()
            return True, answer
        except Exception as e:  # Retry logic
            error_message = str(e).lower()
            retryable = any(
                k in error_message
                for k in ["429", "rate", "unavail", "overload", "timeout", "503"]
            )
            if retryable and attempt < max_attempts:
                delay = base_delay * (2 ** (attempt - 1))
                # jitter
                delay += min(3, 0.25 * delay)
                print(
                    f"  - ⚠️  AI call retry {attempt}/{max_attempts-1} after {delay:.1f}s ({e})"
                )
                time.sleep(delay)
                continue
            return False, f"FAILED: AI call error after {attempt} attempt(s): {e}"
    # Fallback (should not reach)
    return False, "FAILED: Unknown AI execution path (no response)"


# -------------------------------------------------------------------------------
# -------------------------

AI_SCORE_MAP = {"PASS": 1.0, "PARTIAL": 0.5, "FAIL": 0.0}


def run_ai_check(check, repo_path):
    """Run an AI-based check and return (status, details_list, score).

    status: PASS | PARTIAL | FAIL
    score:  1.0  | 0.5     | 0.0  (only ai_check supports PARTIAL)
    """
    prompt_template = check.get("prompt", "")
    details = []

    # Git log context
    if check.get("context_source") == "git_log":
        try:
            process = subprocess.run(
                [
                    "git",
                    "-C",
                    repo_path,
                    "log",
                    "--oneline",
                    "--graph",
                    "-n",
                    str(check.get("git_log_depth", 25)),
                ],
                capture_output=True,
                text=True,
                check=True,
                encoding="utf-8",
            )
            context = process.stdout or "(no commits)"
        except Exception as e:
            return (
                "FAIL",
                [f"  - FAILED: Could not retrieve git history. Error: {e}"],
                0.0,
            )
        prompt = prompt_template.format(context=context, file_path=None)

    # File context
    elif "files_to_analyze" in check:
        consolidated_context = ""
        missing = []
        for filename in check["files_to_analyze"]:
            file_path = find_file_in_repo(filename, repo_path)
            if not file_path:
                missing.append(filename)
                continue
            try:
                with open(file_path, "r", errors="ignore") as f:
                    content = f.read()
                max_file_len = int(check.get("per_file_char_limit", 8000))
                if len(content) > max_file_len:
                    content = content[:max_file_len] + "\n... (truncated)"
                consolidated_context += f"\n\n--- FILE: {file_path} ---\n{content}"
            except Exception as e:
                consolidated_context += (
                    f"\n\n--- FILE: {file_path} (read error: {e}) ---\n"
                )
        if not consolidated_context:
            return (
                "FAIL",
                ["  - FAILED: None of the target files for analysis were found."],
                0.0,
            )
        global_cap = int(check.get("total_context_char_limit", 30000))
        if len(consolidated_context) > global_cap:
            consolidated_context = (
                consolidated_context[:global_cap]
                + "\n... (context truncated due to length)"
            )
        prompt = prompt_template.format(
            context=consolidated_context, file_path="multiple files"
        )
        if missing:
            details.append(f"  - INFO: Missing files skipped: {', '.join(missing)}")
    else:
        return (
            "FAIL",
            [
                "  - FAILED: AI check misconfigured (needs 'context_source' or 'files_to_analyze')."
            ],
            0.0,
        )

    print("  - 🤖 Sending context to AI (with caching & rate limiting)...")
    ok, answer = generate_ai_content(prompt)
    prefix = "  - "
    if not ok:
        return "FAIL", details + [prefix + answer], 0.0

    # Parse first token for PASS / PARTIAL / FAIL
    first_line = answer.strip().splitlines()[0] if answer.strip() else ""
    token = first_line.split(None, 1)[0].upper() if first_line else "FAIL"
    if token not in AI_SCORE_MAP:
        # If rubric not yet updated to output PARTIAL, fall back:
        if token.startswith("PASS"):
            token = "PASS"
        elif token.startswith("FAIL"):
            token = "FAIL"
        else:
            token = "FAIL"
    score = AI_SCORE_MAP[token]
    return token, details + [prefix + answer], score


def find_file_in_repo(filename, repo_path):
    """Recursively finds the first occurrence of a file in the repository."""
    for root, _, files in os.walk(repo_path):
        if filename in files:
            return os.path.join(root, filename)
    return None


def run_file_exists_check(check, repo_path):
    """Checks if a single file or one of multiple possible files exists."""
    recursive = bool(check.get("recursive"))  # optional flag enabling deep search
    max_depth = int(check.get("max_depth", 2))  # default depth limit when recursive

    def _recursive_search(target_names):
        """Return (found: bool, relative_path or None).

        Constraints:
        - Searches by basename only.
        - Ignores any directory named '.venv'.
        - Prunes traversal beyond `max_depth` levels below repo root.
        """
        basenames = {os.path.basename(p) for p in target_names}
        root_depth = repo_path.rstrip(os.sep).count(os.sep)
        for root, dirs, files in os.walk(repo_path):
            # Current depth (root depth = 0)
            current_depth = root.rstrip(os.sep).count(os.sep) - root_depth
            # Prune directories in-place: remove '.venv' and those that would exceed max_depth
            if current_depth >= max_depth:
                # No need to descend further from here
                dirs[:] = []
            else:
                dirs[:] = [
                    d for d in dirs if d != ".venv"  # ignore virtual env folders
                ]
            intersect = basenames.intersection(files)
            if intersect:
                chosen = sorted(intersect)[0]
                rel_path = os.path.relpath(os.path.join(root, chosen), repo_path)
                return True, rel_path
        return False, None

    if "path" in check:
        raw = check["path"]
        path_to_check = os.path.join(repo_path, raw)
        if os.path.exists(path_to_check):
            return True, [f"  - PASSED: '{raw}' found."]
        if recursive:
            found, rel = _recursive_search([raw])
            if found:
                return True, [
                    f"  - PASSED: Found '{os.path.basename(raw)}' at '{rel}' via recursive search.",
                    f"  - INFO: Original expected path '{raw}' not present at root.",
                ]
        return False, [
            f"  - FAILED: '{raw}' does not exist"
            + (" anywhere in repo." if recursive else "."),
        ]

    elif "paths" in check:
        # First pass: direct matches
        for path_option in check["paths"]:
            if os.path.exists(os.path.join(repo_path, path_option)):
                return True, [
                    f"  - PASSED: Found required dependency file ('{path_option}')."
                ]
        # Second pass: recursive if enabled
        if recursive:
            found, rel = _recursive_search(check["paths"])
            if found:
                rel_display = rel or "(unknown)"
                base_display = os.path.basename(rel_display)
                return True, [
                    f"  - PASSED: Found one of required files ('{base_display}') at '{rel_display}' via recursive search.",
                    "  - INFO: None matched at provided top-level paths.",
                ]
        or_string = "' or '".join(check["paths"])
        return False, [
            f"  - FAILED: Could not find '{or_string}'"
            + (" (recursive search also failed)." if recursive else "."),
        ]

    return False, ["  - FAILED: Check is misconfigured (needs 'path' or 'paths')."]


def run_git_commit_count_check(check, repo_path):
    """Checks if the repository has a minimum number of commits."""
    try:
        command = ["git", "-C", repo_path, "rev-list", "--count", "HEAD"]
        process = subprocess.run(
            command, capture_output=True, text=True, check=True, encoding="utf-8"
        )
        commit_count = int(process.stdout.strip())

        min_commits = check["min_commits"]
        if commit_count >= min_commits:
            return True, [
                f"  - PASSED: Found {commit_count} commits (minimum was {min_commits})."
            ]
        else:
            return False, [
                f"  - FAILED: Found only {commit_count} commits (minimum is {min_commits})."
            ]
    except (subprocess.CalledProcessError, FileNotFoundError, ValueError) as e:
        return False, [
            f"  - FAILED: Could not run git command. Is git installed and is this a git repo? Error: {e}"
        ]


def run_analyzer(repo_path: str, rubric_path: str = "rubric.yaml"):
    """Run analysis programmatically.

    Returns (md_report_str, json_obj, ai_cache_dict, total_passed, total_checks).
    """
    if not os.path.isdir(repo_path):
        raise ValueError("Repository path invalid")
    try:
        with open(rubric_path, "r", encoding="utf-8") as f:
            rubric = yaml.safe_load(f)
    except FileNotFoundError:
        raise FileNotFoundError("rubric.yaml not found")

    results = []  # collect dicts
    total_passed = 0
    total_partial = 0

    for check in rubric["checks"]:
        ctype = check.get("type")
        title = check.get("name", "Unnamed Check")

        if ctype == "ai_check":
            status, details, score = run_ai_check(check, repo_path)
            passed_bool = status == "PASS"
            partial_bool = status == "PARTIAL"
            if passed_bool:
                total_passed += 1
            elif partial_bool:
                total_partial += 1
            results.append(
                {
                    "name": title,
                    "type": ctype,
                    "status": status,
                    "score": score,
                    "details": [d.strip() for d in details],
                }
            )
        elif ctype == "file_exists":
            passed, details = run_file_exists_check(check, repo_path)
            score = 1.0 if passed else 0.0
            if passed:
                total_passed += 1
            results.append(
                {
                    "name": title,
                    "type": ctype,
                    "status": "PASS" if passed else "FAIL",
                    "score": score,
                    "details": [d.strip() for d in details],
                }
            )
        elif ctype == "git_commit_count":
            passed, details = run_git_commit_count_check(check, repo_path)
            score = 1.0 if passed else 0.0
            if passed:
                total_passed += 1
            results.append(
                {
                    "name": title,
                    "type": ctype,
                    "status": "PASS" if passed else "FAIL",
                    "score": score,
                    "details": [d.strip() for d in details],
                }
            )
        else:
            results.append(
                {
                    "name": title,
                    "type": ctype,
                    "status": "FAIL",
                    "score": 0.0,
                    "details": [f"FAILED: Unknown check type '{ctype}'."],
                }
            )

    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    # Markdown report
    lines = [
        "# Analysis Report",
        f"Generated: {timestamp}",
        f"Total: {len(results)} | Pass: {total_passed} | Partial: {total_partial} | Fail: {len(results)-total_passed-total_partial}",
        "---",
    ]
    for r in results:
        lines.append(f"## [{r['status']}] {r['name']}")
        for d in r["details"]:
            content = d.lstrip()
            if not content.startswith("- "):
                content = content.replace("  - ", "", 1)
            lines.append(f"- {content.strip()}")
        lines.append("")
    md_report = "\n".join(lines) + "\n"

    # JSON summary
    total_points = sum(1.0 for _ in results)  # each check weight =1 for now
    earned_points = sum(r["score"] for r in results)
    json_obj = {
        "generated_at": timestamp,
        "summary": {
            "total_checks": len(results),
            "passed": total_passed,
            "partial": total_partial,
            "failed": len(results) - total_passed - total_partial,
            "total_points": total_points,
            "earned_points": earned_points,
            "percent": (
                round((earned_points / total_points) * 100, 2) if total_points else 0.0
            ),
        },
        "checks": results,
    }
    return md_report, json_obj, _ai_cache, total_passed, len(results)


def main():
    repo_path = input("Enter the full path to the cloned repository: ")
    try:
        md_report, json_obj, _cache, total_passed, total_checks = run_analyzer(
            repo_path
        )
    except Exception as e:
        print(f"❌ ERROR: {e}")
        return
    md_path = os.getenv("REPORT_MD_PATH", "analysis_report.md")
    json_path = os.getenv("REPORT_JSON_PATH", "analysis_report.json")
    try:
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_report)
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_obj, f, indent=2)
        print(f"Saved {md_path}, {json_path}")
        print(f"Summary: {total_passed}/{total_checks} passed.")
    except Exception as e:
        print(f"⚠️  Could not write report files: {e}")


if __name__ == "__main__":
    main()
