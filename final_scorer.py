import os
import sys
import yaml
import json
import re
import time
import hashlib
from datetime import datetime
from threading import Lock
from dotenv import load_dotenv
from google import genai

load_dotenv()

# Configuration
RUBRIC_PATH = os.getenv("FINAL_SCORE_RUBRIC", "final_score_rubric.yaml")
OVERRIDES_PATH = os.getenv("FINAL_SCORE_OVERRIDES", "final_score_overrides.json")
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")
OUTPUT_MD = os.getenv("FINAL_SCORE_MD", "final_scores.md")
OUTPUT_JSON = os.getenv("FINAL_SCORE_JSON", "final_scores.json")
STRICT = True  # Fail fast if parsing fails
VERBOSE = os.getenv("FINAL_SCORER_VERBOSE", "1") == "1"
MAX_ANALYZER_CHARS = int(os.getenv("FINAL_SCORER_MAX_ANALYZER_CHARS", "35000"))
CACHE_PATH = os.getenv("FINAL_SCORER_CACHE", ".final_score_cache.json")
RETRY_ATTEMPTS = int(os.getenv("FINAL_SCORER_RETRIES", "4"))
BASE_DELAY = float(os.getenv("FINAL_SCORER_BASE_DELAY", "2"))
RATE_LIMIT_SECONDS = float(
    os.getenv("FINAL_SCORER_MIN_INTERVAL", "1.0")
)  # min gap between AI calls
DO_SUMMARY = os.getenv("FINAL_SCORER_SUMMARY", "1") != "0"

_last_call_time = 0.0
_cache_lock = Lock()
try:
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "r", encoding="utf-8") as _cf:
            _resp_cache = json.load(_cf)
    else:
        _resp_cache = {}
except Exception:
    _resp_cache = {}

SCORE_PATTERN = re.compile(r"SCORE:\s*([0-1](?:\.\d)?)", re.IGNORECASE)
JUST_PATTERN = re.compile(r"JUSTIFICATION:\s*(.+)", re.IGNORECASE | re.DOTALL)

# Allowed discrete increments 0.0 .. 1.0 step 0.1
ALLOWED_SCORES = {f"{i/10:.1f}" for i in range(0, 11)}


def read_rubric():
    with open(RUBRIC_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["criteria"]


def load_overrides():
    if os.path.exists(OVERRIDES_PATH):
        try:
            with open(OVERRIDES_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def parse_ai_response(raw: str):
    score_match = SCORE_PATTERN.search(raw)
    just_match = JUST_PATTERN.search(raw)
    if not score_match:
        raise ValueError(f"Could not parse SCORE from: {raw[:120]}...")
    score_str = score_match.group(1)
    if score_str not in ALLOWED_SCORES:
        raise ValueError(f"Score {score_str} not allowed (must be 0.0..1.0 step 0.1)")
    score = float(score_str)
    justification = just_match.group(1).strip() if just_match else "(no justification)"
    # Trim justification first line only (avoid huge repeats); keep up to 350 chars
    if len(justification) > 350:
        justification = justification[:347] + "..."
    return score, justification


def _hash_key(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()


def safe_ai_call(client, model: str, prompt: str):
    global _last_call_time
    cache_key = _hash_key(model + "\n" + prompt)
    with _cache_lock:
        if cache_key in _resp_cache:
            if VERBOSE:
                print(f"  - (cache hit)")
            return _resp_cache[cache_key]
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        # simple rate limiting gap
        gap = time.time() - _last_call_time
        if gap < RATE_LIMIT_SECONDS:
            time.sleep(RATE_LIMIT_SECONDS - gap)
        try:
            if VERBOSE:
                print(f"  - AI request attempt {attempt}/{RETRY_ATTEMPTS}...")
            resp = client.models.generate_content(model=model, contents=prompt)
            _last_call_time = time.time()
            text = (resp.text or "").strip()
            with _cache_lock:
                _resp_cache[cache_key] = text
                try:
                    with open(CACHE_PATH, "w", encoding="utf-8") as _cf:
                        json.dump(_resp_cache, _cf)
                except Exception:
                    pass
            return text
        except Exception as e:
            err = str(e).lower()
            retryable = any(
                k in err
                for k in ["timeout", "rate", "429", "overload", "unavail", "503"]
            )
            if retryable and attempt < RETRY_ATTEMPTS:
                delay = BASE_DELAY * (2 ** (attempt - 1))
                if VERBOSE:
                    print(f"  - Retryable error: {e} (sleep {delay:.1f}s)")
                time.sleep(delay)
                continue
            raise


def main():
    # Expect first argument: path to analyzer output file (markdown, json, or raw text)
    if len(sys.argv) < 2:
        print("Usage: python final_scorer.py <analyzer_output_file>")
        print(
            "Tip: Run 'python analyzer.py > analyzer_output.txt' then 'python final_scorer.py analyzer_output.txt'"
        )
        sys.exit(1)

    input_path = sys.argv[1]
    if input_path == "-":
        analyzer_output = sys.stdin.read()
    else:
        if not os.path.exists(input_path):
            print(f"Analyzer output file not found: {input_path}")
            sys.exit(1)
        with open(input_path, "r", encoding="utf-8", errors="ignore") as f_in:
            analyzer_output = f_in.read()

    # Truncate overly large analyzer output to keep prompt manageable
    if len(analyzer_output) > MAX_ANALYZER_CHARS:
        if VERBOSE:
            print(
                f"Truncating analyzer output from {len(analyzer_output)} to {MAX_ANALYZER_CHARS} chars"
            )
        analyzer_output = analyzer_output[:MAX_ANALYZER_CHARS] + "\n... (truncated)"

    if not analyzer_output.strip():
        print("Analyzer output file is empty.")
        sys.exit(1)

    try:
        criteria = read_rubric()
    except FileNotFoundError:
        print(f"Rubric file not found: {RUBRIC_PATH}")
        sys.exit(1)

    overrides = load_overrides()

    # Init AI client
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("Missing GOOGLE_API_KEY env var.")
        sys.exit(1)
    client = genai.Client(api_key=api_key)

    results = []
    total_weight = 0.0
    weighted_sum = 0.0

    for item in criteria:
        cid = item["id"]
        name = item.get("name", cid)
        weight = float(item.get("weight", 1))
        total_weight += weight

        # Override path first
        if cid in overrides:
            score = float(overrides[cid])
            just = "(override applied)"
            results.append(
                {
                    "id": cid,
                    "name": name,
                    "score": score,
                    "weight": weight,
                    "justification": just,
                    "source": "override",
                }
            )
            weighted_sum += score * weight
            continue

        prompt = f"""You are a reviewer assigning a numeric score. Follow instructions precisely.\nCriterion Name: {name}\nInstructions:\n{item['prompt']}\n\nAnalyzer Output (possibly truncated):\n----------------\n{analyzer_output}\n----------------\nRules:\n- Choose ONLY one allowed score: 0.0 0.1 0.2 0.3 0.4 0.5 0.6 0.7 0.8 0.9 1.0\n- Output EXACTLY two lines:\nSCORE: <value>\nJUSTIFICATION: <concise>\nIf evidence is weak, choose a conservative score.\n"""
        if VERBOSE:
            print(f"Scoring criterion '{cid}' ({name}) ...")
        try:
            raw = safe_ai_call(client, MODEL, prompt)
            raw_text = str(raw) if raw is not None else ""
            score, just = parse_ai_response(raw_text)
            results.append(
                {
                    "id": cid,
                    "name": name,
                    "score": score,
                    "weight": weight,
                    "justification": just,
                    "raw": raw_text,
                    "source": "ai",
                }
            )
            weighted_sum += score * weight
        except Exception as e:
            if STRICT:
                print(f"Error scoring '{cid}': {e}")
                sys.exit(1)
            else:
                results.append(
                    {
                        "id": cid,
                        "name": name,
                        "score": 0.0,
                        "weight": weight,
                        "justification": f"Parse/AI failure: {e}",
                        "source": "error",
                    }
                )

    overall = weighted_sum / total_weight if total_weight else 0.0

    # Optional overall comment summarizing strengths / improvements
    overall_comment = None
    if DO_SUMMARY:
        try:
            if VERBOSE:
                print("Generating overall review comment ...")
            score_lines = "\n".join(
                [f"- {r['id']}: {r['name']} => {r['score']:.1f}" for r in results]
            )
            summary_prompt = f"""You are an experienced software project reviewer. Produce ONE cohesive overall review comment.\nData available:\n(1) Per-criterion scores (0.0-1.0):\n{score_lines}\nOverall weighted score: {overall:.2f}\n(2) The underlying analyzer output already informed those scores (not repeated here).\nInstructions:\n- Start with a single concise summary sentence capturing overall health.\n- Then provide a short bullet list: Strengths, Risks, Next Steps (each 1-3 bullets).\n- Prioritize actionable technical improvements (security, docs, robustness) over cosmetic.\n- Word limit: 160 words total.\nFormat:\nSummary line\n\nStrengths:\n- ...\nRisks:\n- ...\nNext Steps:\n- ...\nReturn only the comment. Do NOT add extra labels beyond the specified headings.\n"""
            raw_summary = safe_ai_call(client, MODEL, summary_prompt)
            overall_comment = (raw_summary or "").strip()
        except Exception as e:
            overall_comment = f"(Summary generation failed: {e})"

    # Markdown table
    md_lines = []
    md_lines.append(f"# Final Scoring Report\n")
    md_lines.append(
        f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n"
    )
    if overall_comment:
        md_lines.append("\n### Overall Review Comment\n")
        md_lines.append(overall_comment + "\n\n")

    md_lines.append(f"Overall Score: {overall:.2f} (weighted)\n")
    md_lines.append("| ID | Criterion | Score | Weight | Justification | Source |")
    md_lines.append("|----|-----------|-------|--------|---------------|--------|")
    for r in results:
        md_lines.append(
            f"| {r['id']} | {r['name']} | {r['score']:.1f} | {r['weight']:.1f} | {r['justification'].replace('|','/')} | {r['source']} |"
        )

    with open(OUTPUT_MD, "w", encoding="utf-8") as f_md:
        f_md.write("\n".join(md_lines) + "\n")

    out_json = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "overall_score": round(overall, 2),
        "criteria": results,
        "overall_comment": overall_comment,
    }
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f_json:
        json.dump(out_json, f_json, indent=2)

    print(f"Final scoring complete. Overall: {overall:.2f}")
    print(f"Markdown: {OUTPUT_MD} | JSON: {OUTPUT_JSON}")


if __name__ == "__main__":
    main()
