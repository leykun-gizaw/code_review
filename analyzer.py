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

load_dotenv()

# --- AI Configuration ---
# The script reads the API key from your environment variables for security.
try:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY environment variable not set.")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
    client = genai.Client(api_key=GOOGLE_API_KEY)
    print("✅ Gemini API configured successfully.")
except (ValueError, Exception) as e:
    raise RuntimeError(f"🔴 CRITICAL: Could not configure Gemini API. {e}")


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


def find_file_in_repo(filename, repo_path):
    """Recursively finds the first occurrence of a file in the repository."""
    for root, _, files in os.walk(repo_path):
        if filename in files:
            return os.path.join(root, filename)
    return None


def run_ai_check(check, repo_path):
    """Gathers context, builds prompt, delegates to generate_ai_content.

    Refactored to centralize retry/rate-limit/caching logic.
    """

    prompt_template = check.get("prompt", "")

    # Context: Git log
    details = []
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
            return False, [f"  - FAILED: Could not retrieve git history. Error: {e}"]
        prompt = prompt_template.format(context=context, file_path=None)

    # Context: Files
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
                # Lightweight truncation per file to avoid single huge context
                max_file_len = int(check.get("per_file_char_limit", 8000))
                if len(content) > max_file_len:
                    content = content[:max_file_len] + "\n... (truncated)"
                consolidated_context += f"\n\n--- FILE: {file_path} ---\n{content}"
            except Exception as e:
                consolidated_context += (
                    f"\n\n--- FILE: {file_path} (read error: {e}) ---\n"
                )
        if not consolidated_context:
            return False, [
                "  - FAILED: None of the target files for analysis were found."
            ]
        # Global cap
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
        return False, [
            "  - FAILED: AI check misconfigured (needs 'context_source' or 'files_to_analyze')."
        ]

    print("  - 🤖 Sending context to AI (with caching & rate limiting)...")
    ok, answer = generate_ai_content(prompt)
    prefix = "  - "
    if ok:
        if answer.upper().startswith("PASS"):
            return True, details + [prefix + answer]
        return False, details + [prefix + answer]
    return False, details + [prefix + answer]


def run_file_exists_check(check, repo_path):
    """Checks if a single file or one of multiple possible files exists."""
    if "path" in check:
        path_to_check = os.path.join(repo_path, check["path"])
        if os.path.exists(path_to_check):
            return True, [f"  - PASSED: '{check['path']}' found."]
        else:
            return False, [f"  - FAILED: '{check['path']}' does not exist."]

    elif "paths" in check:
        for path_option in check["paths"]:
            if os.path.exists(os.path.join(repo_path, path_option)):
                return True, [
                    f"  - PASSED: Found required dependency file ('{path_option}')."
                ]

        or_string = "' or '".join(check["paths"])
        return False, [f"  - FAILED: Could not find '{or_string}'."]

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


def main():
    """Main function to load the rubric and orchestrate the analysis."""
    print("--- 🚀 Custom Code Analyzer ---")
    try:
        with open("rubric.yaml", "r") as f:
            rubric = yaml.safe_load(f)
    except FileNotFoundError:
        print(
            "❌ ERROR: rubric.yaml not found! Please create it in the same directory."
        )
        return

    repo_path = input("Enter the full path to the cloned repository: ")
    if not os.path.isdir(repo_path):
        print("❌ ERROR: The provided path is not a valid directory.")
        return

    print("\n--- 🔬 Starting Analysis ---")
    all_results = {}
    total_passed = 0

    check_functions = {
        "ai_check": run_ai_check,
        "file_exists": run_file_exists_check,
        "git_commit_count": run_git_commit_count_check,
    }

    for i, check in enumerate(rubric["checks"], 1):
        check_type = check.get("type")
        title = f"{check.get('name', 'Unnamed Check')}"
        print(f"\n▶ Running: {title}")

        if check_type in check_functions:
            passed, details = check_functions[check_type](check, repo_path)
            if passed:
                total_passed += 1
            all_results[title] = (passed, details)
        else:
            all_results[title] = (
                False,
                [f"  - FAILED: Unknown check type '{check_type}'."],
            )

    print("\n\n✅ --- Final Analysis Report --- ✅")
    for title, (passed_status, details) in all_results.items():
        status = "PASSED" if passed_status else "FAILED"
        print(f"\n[{status}] {title}")
        for detail in details:
            print(detail)

    print("\n\n--- 📊 Summary ---")
    print(f"{total_passed} out of {len(rubric['checks'])} checks passed.")
    print("--------------------")

    # --- Persist report to disk ---
    try:
        md_path = os.getenv("REPORT_MD_PATH", "analysis_report.md")
        json_path = os.getenv("REPORT_JSON_PATH", "analysis_report.json")
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

        # Build Markdown
        lines = []
        lines.append(f"# Analysis Report\n")
        lines.append(f"Generated: {timestamp}\n")
        lines.append(
            f"Total: {len(rubric['checks'])} | Passed: {total_passed} | Failed: {len(rubric['checks']) - total_passed}\n"
        )
        lines.append("---\n")
        for title, (passed_status, details) in all_results.items():
            state = "PASS" if passed_status else "FAIL"
            lines.append(f"## [{state}] {title}\n")
            for d in details:
                # Normalize bullet formatting
                content = d.lstrip()
                if not content.startswith("- "):
                    content = content.replace("  - ", "", 1)
                lines.append(f"- {content.strip()}")
            lines.append("")
        with open(md_path, "w", encoding="utf-8") as f_md:
            f_md.write("\n".join(lines))

        # Build JSON
        json_obj = {
            "generated_at": timestamp,
            "summary": {
                "total_checks": len(rubric["checks"]),
                "passed": total_passed,
                "failed": len(rubric["checks"]) - total_passed,
            },
            "checks": [
                {
                    "name": title,
                    "status": "PASSED" if passed else "FAILED",
                    "details": [d.strip() for d in details],
                }
                for title, (passed, details) in all_results.items()
            ],
        }
        with open(json_path, "w", encoding="utf-8") as f_json:
            json.dump(json_obj, f_json, indent=2)
        print(f"\n📝 Reports saved: {md_path}, {json_path}")
    except Exception as e:
        print(f"⚠️  Could not write report files: {e}")


if __name__ == "__main__":
    main()
