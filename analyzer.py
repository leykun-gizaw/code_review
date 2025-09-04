import os
import yaml
import subprocess
from dotenv import load_dotenv
from google import genai

load_dotenv()

# --- AI Configuration ---
# The script reads the API key from your environment variables for security.
try:
    GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY environment variable not set.")
    client = genai.Client(api_key=GOOGLE_API_KEY)
    print("✅ Gemini API configured successfully.")
except (ValueError, Exception) as e:
    raise RuntimeError(f"🔴 CRITICAL: Could not configure Gemini API. {e}")
# -------------------------


def find_file_in_repo(filename, repo_path):
    """Recursively finds the first occurrence of a file in the repository."""
    for root, _, files in os.walk(repo_path):
        if filename in files:
            return os.path.join(root, filename)
    return None


def run_ai_check(check, repo_path):
    """Gathers context, sends it to the Gemini API, and parses the result."""

    prompt_template = check["prompt"]

    # --- Context Gathering: Git Log ---
    if check.get("context_source") == "git_log":
        try:
            command = [
                "git",
                "-C",
                repo_path,
                "log",
                "--oneline",
                "--graph",
                "-n",
                "25",
            ]
            process = subprocess.run(
                command, capture_output=True, text=True, check=True, encoding="utf-8"
            )
            context = process.stdout
            if not context:
                return False, [
                    "  - FAILED: Git log is empty or this is not a git repository."
                ]
        except Exception as e:
            return False, [f"  - FAILED: Could not retrieve git history. Error: {e}"]

        prompt = prompt_template.format(
            context=context, file_path=None
        )  # file_path is not relevant here

    # --- Context Gathering: File Contents ---
    elif "files_to_analyze" in check:
        all_results = []
        overall_passed = True

        # Consolidate context from all files for a single API call if possible
        consolidated_context = ""

        for filename in check["files_to_analyze"]:
            file_path = find_file_in_repo(filename, repo_path)
            if not file_path:
                all_results.append(f"  - INFO: Could not find '{filename}' to analyze.")
                continue

            with open(file_path, "r", errors="ignore") as f:
                content = f.read()

            consolidated_context += f"\n\n--- CONTENT FROM {file_path} ---\n\n{content}"

        if not consolidated_context:
            return False, [
                "  - FAILED: None of the target files for analysis were found."
            ]

        # Truncate context if it's too long to avoid API errors
        if len(consolidated_context) > 30000:
            consolidated_context = (
                consolidated_context[:30000] + "\n... (context truncated due to length)"
            )

        prompt = prompt_template.format(
            context=consolidated_context, file_path="multiple files"
        )

    else:
        return False, [
            "  - FAILED: AI check is misconfigured in rubric (needs 'context_source' or 'files_to_analyze')."
        ]

    # --- API Call and Response Parsing ---
    try:
        print("  - 🤖 Sending context to AI for analysis... (This may take a moment)")
        response = client.models.generate_content(
            model="gemini-2.5-pro",
            contents=prompt,
        )
        ai_answer = response.text or ""

        if ai_answer.upper().startswith("PASS"):
            return True, [f"  - {ai_answer}"]
        else:
            return False, [f"  - {ai_answer}"]

    except Exception as e:
        return False, [f"  - FAILED: API call failed. Error: {e}"]


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


if __name__ == "__main__":
    main()
