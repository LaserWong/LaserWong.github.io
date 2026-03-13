from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "arxiv_daily_cornell_config.json"
USER_AGENT = "Mozilla/5.0 (compatible; ArxivDailyKimGroup/1.0)"
OPENAI_RESPONSES_ENDPOINT = "https://api.openai.com/v1/responses"
DEFAULT_OPENAI_MODEL = "gpt-5-codex"
DEFAULT_OPENAI_MAX_OUTPUT_TOKENS = 220
DEFAULT_OPENAI_TIMEOUT_SECONDS = 90
DEFAULT_OPENAI_REASONING_EFFORT = "low"
CATEGORY_ORDER = ["cond-mat", "quant-ph", "cs"]
BUCKET_ORDER = [
    "AI for Physics",
    "Quantum Computation / Simulation",
    "Quantum Information",
    "CMT Theory / Computation",
]
TYPE_ORDER = ["Theory", "Numerical", "Theory + Numerical", "Experiment"]
HIGHLIGHT_ORDER = ["AI for Physics", "Quantum Advantage", "Quantum Error Correction"]
PHYSICS_CROSSLIST_PREFIXES = ("quant-ph", "cond-mat", "physics.")
CS_AI_SUBJECT_CODES = {"cs.AI", "cs.LG", "cs.CL", "cs.CV", "cs.NE", "stat.ML"}

AI_KEYWORDS = {"artificial intelligence", "machine learning", "deep learning", "neural network", "neural quantum state", "neural quantum states", "quantum neural network", "quantum neural networks", "born machine", "born machines", "graph neural network", "large language model", "foundation model", "reinforcement learning", "diffusion model", "bayesian optimization", "surrogate model", "neural operator", "physics-informed", "inverse design"}
PHYSICS_TARGET_KEYWORDS = {"condensed matter", "materials science", "quantum physics", "quantum state", "quantum many-body", "many-body", "many body", "hamiltonian", "wavefunction", "phase transition", "band structure", "fermion", "boson", "spin", "superconduct", "cold atom", "ion trap", "trapped ion", "superconducting qubit", "topological matter", "phase-field", "thin film", "complex oxide", "alloy", "electrochemistry", "corrosion", "solidification", "grain boundary"}
QUANTUM_COMPUTATION_KEYWORDS = {"quantum computation", "quantum computing", "quantum algorithm", "quantum algorithms", "quantum circuit", "quantum circuits", "quantum compiler", "quantum processor", "fault-tolerant", "fault tolerant", "logical qubit", "resource estimate", "qubit", "qubits"}
QUANTUM_SIMULATION_KEYWORDS = {"quantum simulation", "quantum simulator", "digital quantum simulation", "analog quantum simulation", "analog simulator"}
QUANTUM_ADVANTAGE_KEYWORDS = {"quantum advantage", "quantum supremacy", "beyond classical", "exponential speedup"}
QEC_KEYWORDS = {"quantum error correction", "error correction", "surface code", "stabilizer code", "logical qubit", "fault-tolerant", "fault tolerant"}
QUANTUM_INFORMATION_KEYWORDS = {"quantum information", "entanglement", "teleportation", "quantum communication", "nonlocality", "bell inequality", "resource theory", "quantum sensing", "quantum metrology", "state tomography", "process tomography", "entropic"}
CMT_KEYWORDS = {"condensed matter", "many-body", "many body", "strongly correlated", "superconduct", "topological", "spin liquid", "hubbard", "moir", "quantum geometry", "flat band", "hall", "fermion", "boson", "magnon", "lattice", "phase transition", "kitaev"}
NUMERIC_KEYWORDS = {"numerical", "simulation", "simulations", "monte carlo", "tensor network", "tensor-network", "dmrg", "exact diagonalization", "density functional", "dft", "ab initio", "first-principles", "first principles", "variational", "optimization", "solver", "computed", "computational", "benchmark"}
THEORY_KEYWORDS = {"theory", "field theory", "effective theory", "analytical", "analytic", "model", "models", "symmetry", "topology", "renormalization", "renormalisation", "proof", "bound", "classification", "equation", "hamiltonian"}
EXPERIMENTAL_PLATFORM_KEYWORDS = {"cold atom", "cold atoms", "ultracold", "bose-einstein condensate", "optical lattice", "ion trap", "ion traps", "trapped ion", "trapped ions", "superconducting qubit", "superconducting qubits", "superconducting circuit", "superconducting circuits", "transmon", "fluxonium", "neutral atom", "neutral atoms", "rydberg"}
EXPERIMENTAL_SIGNAL_KEYWORDS = {"experiment", "experimental", "demonstration", "measurement", "measured", "implemented", "implementation", "realized", "realised", "observed", "observation", "device", "hardware", "calibration", "fabrication"}


def log(message: str) -> None:
    print(message, flush=True)


def load_config() -> dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def fetch_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize(text: str) -> str:
    return text.lower().replace("–", "-").replace("—", "-").replace("’", "'")


def contains_any(text: str, keywords: set[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def subject_codes(subject_text: str) -> list[str]:
    return re.findall(r"\(([A-Za-z0-9_.-]+)\)", subject_text)


def select_featured_authors(authors: list[str], max_total: int) -> list[str]:
    if len(authors) <= max_total:
        return authors
    return authors[:3] + authors[-3:]


OPENAI_SYSTEM_PROMPT = (
    "You are an expert editor preparing a Kim Group daily arXiv digest for advanced physics readers. "
    "Use only the provided title, subjects, comments, and abstract. "
    "Write compact, factual English without hype."
)
SUMMARY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "what_done": {"type": "string"},
        "results": {"type": "string"},
        "significance": {"type": "string"},
    },
    "required": ["what_done", "results", "significance"],
}


def post_json(url: str, payload: dict[str, Any], headers: dict[str, str], timeout: int = 60) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, **headers},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def split_english_sentences(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return []
    return [piece.strip() for piece in re.split(r"(?<=[.!?])\s+", normalized) if piece.strip()]


def trim_to_words(text: str, max_words: int) -> str:
    words = clean_space(text).split()
    if len(words) <= max_words:
        return " ".join(words)
    return " ".join(words[:max_words]).rstrip(",;:-")


def ensure_sentence(text: str) -> str:
    cleaned = clean_space(text)
    cleaned = re.sub(r"^[123][.):]\s*", "", cleaned)
    cleaned = cleaned.strip('"\' ')
    cleaned = cleaned.rstrip(" .!?")
    if not cleaned:
        return ""
    return f"{cleaned}."


def build_local_summary(title: str, abstract: str) -> str:
    sentences = split_english_sentences(abstract)
    first = sentences[0] if sentences else f"This paper studies {title}."
    result_keywords = {
        "show", "shows", "demonstrate", "demonstrates", "find", "finds", "obtain", "obtains",
        "achieve", "achieves", "benchmark", "benchmarks", "outperform", "outperforms", "improve",
        "improves", "reveal", "reveals", "indicate", "indicates", "matches", "speedup", "scaling",
    }
    significance_keywords = {
        "suggest", "suggests", "enable", "enables", "provide", "provides", "route", "routes",
        "implication", "implications", "future", "scalable", "opens", "open", "broader", "meaning",
        "significance", "application", "applications", "useful",
    }
    result = next((sentence for sentence in sentences[1:] if any(keyword in normalize(sentence) for keyword in result_keywords)), sentences[1] if len(sentences) > 1 else "The main result is a concrete performance, accuracy, or scaling improvement over existing approaches.")
    significance = next((sentence for sentence in reversed(sentences) if any(keyword in normalize(sentence) for keyword in significance_keywords)), sentences[-1] if len(sentences) > 2 else "The broader significance is a clearer route toward scalable methods, sharper benchmarks, or better physical understanding.")
    parts = [
        ensure_sentence(trim_to_words(first, 38)),
        ensure_sentence(trim_to_words(result, 42)),
        ensure_sentence(trim_to_words(significance, 38)),
    ]
    return "\n".join(f"{index}. {sentence}" for index, sentence in enumerate(parts, start=1) if sentence)


def merge_usage_totals(target: dict[str, int], source: dict[str, Any]) -> None:
    input_tokens = int(source.get("input_tokens", source.get("prompt_tokens", 0)) or 0)
    output_tokens = int(source.get("output_tokens", source.get("completion_tokens", 0)) or 0)
    total_tokens = int(source.get("total_tokens", input_tokens + output_tokens) or 0)
    target["input_tokens"] += input_tokens
    target["output_tokens"] += output_tokens
    target["total_tokens"] += total_tokens


def build_openai_prompt(paper: dict[str, Any]) -> str:
    comments = paper["comments"] or "None"
    subjects = paper["subjects"] or "None"
    return (
        "Summarize this arXiv paper in exactly three English sentences for a physics audience.\n"
        "Sentence 1: what the paper does.\n"
        "Sentence 2: the main result or performance/physics finding.\n"
        "Sentence 3: why it matters or what it enables.\n"
        "Requirements:\n"
        "- Stay faithful to the provided metadata and abstract only.\n"
        "- Do not use bullet points, hedging boilerplate, or generic hype.\n"
        "- Keep the total length around 90-120 words.\n"
        "- Prefer concrete verbs and concrete technical content.\n\n"
        f"Title: {paper['title']}\n"
        f"Subjects: {subjects}\n"
        f"Comments: {comments}\n"
        f"Abstract: {paper['abstract']}"
    )


def extract_json_object(text: str) -> dict[str, Any] | None:
    stripped = text.strip()
    if not stripped:
        return None
    candidates = [stripped]
    match = re.search(r"\{.*\}", stripped, flags=re.S)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    return None


def extract_response_text(response: dict[str, Any]) -> str:
    output_text = response.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            text = content.get("text") if isinstance(content, dict) else None
            if isinstance(text, str) and text.strip():
                return text.strip()
    return ""


def format_openai_summary(payload: dict[str, Any]) -> str | None:
    caps = [("what_done", 38), ("results", 42), ("significance", 38)]
    parts: list[str] = []
    for key, max_words in caps:
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            return None
        sentence = ensure_sentence(trim_to_words(value, max_words))
        if not sentence:
            return None
        parts.append(sentence)
    return "\n".join(f"{index}. {sentence}" for index, sentence in enumerate(parts, start=1))


def summarize_with_openai(
    paper: dict[str, Any],
    cache: dict[str, str | None],
    api_key: str,
    model: str,
    max_output_tokens: int,
    timeout_seconds: int,
    reasoning_effort: str,
) -> tuple[str | None, dict[str, int], str]:
    usage = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    if not api_key:
        return None, usage, "no_key"
    cache_key = json.dumps(
        {
            "title": paper["title"],
            "subjects": paper["subjects"],
            "comments": paper["comments"],
            "abstract": paper["abstract"],
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    if cache_key in cache:
        return cache[cache_key], usage, "cached"
    payload = {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": OPENAI_SYSTEM_PROMPT}]},
            {"role": "user", "content": [{"type": "input_text", "text": build_openai_prompt(paper)}]},
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "cornell_arxiv_summary",
                "strict": True,
                "schema": SUMMARY_SCHEMA,
            }
        },
        "max_output_tokens": max_output_tokens,
        "reasoning": {"effort": reasoning_effort},
    }
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    for attempt in range(3):
        try:
            response = post_json(OPENAI_RESPONSES_ENDPOINT, payload, headers=headers, timeout=timeout_seconds)
            merge_usage_totals(usage, response.get("usage") or {})
            parsed_payload = response.get("output_parsed")
            if isinstance(parsed_payload, dict):
                summary = format_openai_summary(parsed_payload)
                cache[cache_key] = summary
                if summary:
                    return summary, usage, "ok"
                return None, usage, "parse_failure"
            text = extract_response_text(response)
            parsed_payload = extract_json_object(text)
            if parsed_payload is None:
                cache[cache_key] = None
                return None, usage, "parse_failure"
            summary = format_openai_summary(parsed_payload)
            cache[cache_key] = summary
            if summary:
                return summary, usage, "ok"
            return None, usage, "parse_failure"
        except urllib.error.HTTPError as exc:
            if exc.code in {408, 429, 500, 502, 503, 504} and attempt < 2:
                time.sleep(2 ** attempt)
                continue
            cache[cache_key] = None
            return None, usage, f"http_{exc.code}"
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
            if attempt < 2:
                time.sleep(2 ** attempt)
                continue
            cache[cache_key] = None
            return None, usage, "request_failure"
    cache[cache_key] = None
    return None, usage, "request_failure"


def parse_new_submissions(category: str, html_text: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    dl = soup.select_one("dl#articles")
    if dl is None:
        raise ValueError(f"Could not find article list for {category}")
    first_section = dl.find("h3")
    if first_section is None:
        raise ValueError(f"Could not find section header for {category}")

    papers: list[dict[str, Any]] = []
    current = first_section.find_next_sibling()
    while current is not None and current.name != "h3":
        if current.name == "dt":
            link = current.find("a", title="Abstract")
            dd = current.find_next_sibling("dd")
            if link is None or dd is None:
                current = current.find_next_sibling()
                continue
            title_el = dd.select_one(".list-title")
            abstract_el = dd.select_one("p.mathjax")
            if title_el is None or abstract_el is None:
                current = current.find_next_sibling()
                continue
            paper_id = link.get_text(" ", strip=True).replace("arXiv:", "")
            authors = [clean_space(item.get_text(" ", strip=True)) for item in dd.select(".list-authors a")]
            subjects_el = dd.select_one(".list-subjects")
            comments_el = dd.select_one(".list-comments")
            primary_el = dd.select_one(".primary-subject")
            title = clean_space(title_el.get_text(" ", strip=True).replace("Title:", ""))
            abstract = clean_space(abstract_el.get_text(" ", strip=True))
            subjects = clean_space(subjects_el.get_text(" ", strip=True).replace("Subjects:", "")) if subjects_el else ""
            comments = clean_space(comments_el.get_text(" ", strip=True).replace("Comments:", "")) if comments_el else ""
            primary_subject = clean_space(primary_el.get_text(" ", strip=True)) if primary_el else ""
            papers.append(
                {
                    "id": paper_id,
                    "category": category,
                    "title": title,
                    "authors": authors,
                    "abstract": abstract,
                    "subjects": subjects,
                    "subject_codes": subject_codes(subjects),
                    "primary_subject": primary_subject,
                    "comments": comments,
                    "url": f"https://arxiv.org/abs/{paper_id}",
                    "topic_text": normalize(" ".join([title, abstract, comments])),
                    "search_text": normalize(" ".join([title, " ".join(authors), abstract, subjects, comments])),
                }
            )
        current = current.find_next_sibling()
    return papers


def has_physics_crosslist(paper: dict[str, Any]) -> bool:
    return any(code.startswith(PHYSICS_CROSSLIST_PREFIXES) for code in paper["subject_codes"] if not code.startswith("cs."))


def has_ai_subject_code(paper: dict[str, Any]) -> bool:
    return any(code in CS_AI_SUBJECT_CODES for code in paper["subject_codes"])


def is_ai_for_physics(paper: dict[str, Any]) -> bool:
    text = paper["topic_text"]
    return contains_any(text, AI_KEYWORDS) and contains_any(text, PHYSICS_TARGET_KEYWORDS)


def is_quantum_advantage(paper: dict[str, Any]) -> bool:
    return contains_any(paper["topic_text"], QUANTUM_ADVANTAGE_KEYWORDS)


def is_quantum_error_correction(paper: dict[str, Any]) -> bool:
    return contains_any(paper["topic_text"], QEC_KEYWORDS)


def is_quantum_computation(paper: dict[str, Any]) -> bool:
    text = paper["topic_text"]
    return contains_any(text, QUANTUM_COMPUTATION_KEYWORDS) or contains_any(text, QUANTUM_SIMULATION_KEYWORDS) or is_quantum_advantage(paper) or is_quantum_error_correction(paper)


def is_quantum_information(paper: dict[str, Any]) -> bool:
    return contains_any(paper["topic_text"], QUANTUM_INFORMATION_KEYWORDS) or is_quantum_error_correction(paper)


def is_target_experiment(paper: dict[str, Any]) -> bool:
    text = paper["topic_text"]
    return contains_any(text, EXPERIMENTAL_PLATFORM_KEYWORDS) and contains_any(text, EXPERIMENTAL_SIGNAL_KEYWORDS)


def should_include(paper: dict[str, Any]) -> bool:
    text = paper["topic_text"]
    search_text = paper["search_text"]
    if contains_any(text, {"remembering", "memorial", "tribute", "obituary", "in honor of"}):
        return False
    if paper["category"] == "cs":
        ai_for_physics = is_ai_for_physics(paper)
        quantum_comp = is_quantum_computation(paper)
        if not (ai_for_physics or quantum_comp):
            return False
        if ai_for_physics:
            return has_physics_crosslist(paper)
        return has_physics_crosslist(paper) or contains_any(search_text, {"quantum computing", "quantum computation", "quantum error correction", "quantum advantage", "fault-tolerant", "fault tolerant", "qubit"})
    if is_ai_for_physics(paper) or is_quantum_computation(paper) or is_quantum_information(paper) or is_target_experiment(paper):
        return True
    if paper["category"] == "cond-mat":
        return contains_any(search_text, CMT_KEYWORDS | THEORY_KEYWORDS | NUMERIC_KEYWORDS)
    if paper["category"] == "quant-ph":
        return contains_any(search_text, QUANTUM_INFORMATION_KEYWORDS | QUANTUM_COMPUTATION_KEYWORDS | QUANTUM_SIMULATION_KEYWORDS | THEORY_KEYWORDS | NUMERIC_KEYWORDS)
    return False


def infer_type(paper: dict[str, Any]) -> str:
    text = paper["topic_text"]
    if is_target_experiment(paper):
        return "Experiment"
    has_numeric = contains_any(text, NUMERIC_KEYWORDS)
    has_theory = contains_any(text, THEORY_KEYWORDS) or not has_numeric
    if has_numeric and has_theory:
        return "Theory + Numerical"
    if has_numeric:
        return "Numerical"
    return "Theory"


def infer_bucket(paper: dict[str, Any]) -> str:
    if is_ai_for_physics(paper):
        return "AI for Physics"
    if is_quantum_computation(paper):
        return "Quantum Computation / Simulation"
    if is_quantum_information(paper) or is_target_experiment(paper) or paper["category"] == "quant-ph":
        return "Quantum Information"
    return "CMT Theory / Computation"


def infer_highlights(paper: dict[str, Any]) -> list[str]:
    highlights: list[str] = []
    if is_ai_for_physics(paper):
        highlights.append("AI for Physics")
    if is_quantum_advantage(paper):
        highlights.append("Quantum Advantage")
    if is_quantum_error_correction(paper):
        highlights.append("Quantum Error Correction")
    return highlights


def author_note(author_count: int, shown_count: int) -> str:
    if author_count == 0:
        return "No author list found"
    if author_count > shown_count:
        return f"Showing the first 3 and last 3 of {author_count} authors"
    suffix = "s" if author_count != 1 else ""
    return f"{author_count} author{suffix}"


def paper_id_number(paper_id: str) -> int:
    return int(paper_id.replace(".", ""))


def sort_key(paper: dict[str, Any]) -> tuple[Any, ...]:
    bucket_rank = BUCKET_ORDER.index(paper["bucket"])
    highlight_rank = tuple(0 if label in paper["highlights"] else 1 for label in HIGHLIGHT_ORDER)
    type_rank_map = {"Theory + Numerical": 0, "Theory": 1, "Numerical": 2, "Experiment": 3}
    if paper["bucket"] == "Quantum Information":
        type_rank_map = {"Experiment": 0, "Theory + Numerical": 1, "Theory": 2, "Numerical": 3}
    category_rank = CATEGORY_ORDER.index(paper["category"])
    return (bucket_rank, highlight_rank, type_rank_map.get(paper["type"], 99), category_rank, -paper_id_number(paper["id"]))


def enrich_papers(
    papers: list[dict[str, Any]],
    max_featured_authors: int,
    enable_openai_summary: bool,
    openai_api_key: str,
    openai_model: str,
    openai_max_output_tokens: int,
    openai_timeout_seconds: int,
    openai_reasoning_effort: str,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    summary_cache: dict[str, str | None] = {}
    usage = {
        "calls": 0,
        "successes": 0,
        "fallbacks": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "parse_failures": 0,
        "request_failures": 0,
    }
    selected = [paper for paper in papers if should_include(paper)]
    enriched: list[dict[str, Any]] = []
    total = len(selected)
    for index, paper in enumerate(selected, start=1):
        log(f"      -> paper {index}/{total}: {paper['category']} {paper['id']}")
        featured = select_featured_authors(paper["authors"], max_featured_authors)
        if enable_openai_summary and openai_api_key:
            usage["calls"] += 1
            summary, usage_delta, status = summarize_with_openai(
                paper=paper,
                cache=summary_cache,
                api_key=openai_api_key,
                model=openai_model,
                max_output_tokens=openai_max_output_tokens,
                timeout_seconds=openai_timeout_seconds,
                reasoning_effort=openai_reasoning_effort,
            )
            merge_usage_totals(usage, usage_delta)
            if summary:
                usage["successes"] += 1
            elif status == "parse_failure":
                usage["parse_failures"] += 1
            elif status not in {"cached", "no_key"}:
                usage["request_failures"] += 1
                usage["fallbacks"] += 1
        prepared = {
            "id": paper["id"],
            "category": paper["category"],
            "title": paper["title"],
            "authors": paper["authors"],
            "featured_authors": featured,
            "author_count": len(paper["authors"]),
            "author_note": author_note(len(paper["authors"]), len(featured)),
            "abstract": paper["abstract"],
            "subjects": paper["subjects"],
            "primary_subject": paper["primary_subject"],
            "comments": paper["comments"],
            "url": paper["url"],
            "type": infer_type(paper),
            "bucket": infer_bucket(paper),
            "highlights": infer_highlights(paper),
        }
        prepared["sort_key"] = sort_key(prepared)
        enriched.append(prepared)
    enriched.sort(key=lambda item: item["sort_key"])
    for paper in enriched:
        paper.pop("sort_key", None)
    return enriched, usage

def stats_cards(papers: list[dict[str, Any]]) -> list[tuple[str, int]]:
    bucket_counts = {bucket: 0 for bucket in BUCKET_ORDER}
    for paper in papers:
        bucket_counts[paper["bucket"]] += 1
    cards = [("Selected papers", len(papers))]
    cards.extend((bucket, bucket_counts[bucket]) for bucket in BUCKET_ORDER)
    cards.append(("Highlighted", sum(1 for paper in papers if paper["highlights"])))
    return cards




def build_daily_html(date_str: str, papers: list[dict[str, Any]]) -> str:
    papers_json = json.dumps(papers, ensure_ascii=False)
    cards_html = "".join(
        f'<article class="stat"><div class="label">{label}</div><div class="value">{value}</div></article>'
        for label, value in stats_cards(papers)
    )
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kim Group arXiv Daily - __DATE__</title>
  <style>
    :root { --bg:#f4efe7; --panel:#fffdf9; --text:#281f18; --muted:#67584d; --line:rgba(61,46,32,.14); --accent:#8d402e; --accent2:#1d5b66; --ai:#9a4d12; --qc:#6e4db5; --qi:#236d5c; --cmt:#7a3c2f; --exp:#2e6f3f; --radius:20px; }
    * { box-sizing:border-box; }
    body { margin:0; min-height:100vh; color:var(--text); font-family:"Aptos","Segoe UI",Arial,sans-serif; background:linear-gradient(180deg,#fbf7f0 0%,#f4efe7 45%,#efe5d8 100%); }
    .shell { width:min(1340px,calc(100% - 32px)); margin:0 auto; padding:28px 0 64px; }
    .hero, .controls, .paper { border:1px solid var(--line); background:rgba(255,252,247,.92); box-shadow:0 12px 28px rgba(54,32,16,.07); }
    .hero { padding:28px; border-radius:28px; }
    .eyebrow { display:inline-flex; padding:8px 12px; border-radius:999px; font-size:12px; letter-spacing:.08em; text-transform:uppercase; color:var(--muted); background:#fff; border:1px solid var(--line); }
    h1 { margin:16px 0 10px; font-family:Georgia,"Times New Roman",serif; font-size:clamp(34px,5vw,56px); line-height:1.03; letter-spacing:-.03em; }
    .hero p { margin:0; max-width:980px; color:var(--muted); line-height:1.7; }
    .stats { display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:14px; margin-top:22px; }
    .stat { padding:16px; border-radius:18px; background:rgba(255,255,255,.8); border:1px solid var(--line); }
    .label { color:var(--muted); font-size:12px; text-transform:uppercase; letter-spacing:.05em; }
    .value { font-size:26px; font-weight:700; }
    .controls { position:sticky; top:12px; z-index:2; margin-top:22px; padding:16px; border-radius:22px; transition:padding .18s ease, transform .18s ease, top .18s ease, box-shadow .18s ease; }
    .controls.compact { top:6px; padding:10px 12px; transform:translateY(-6px); box-shadow:0 8px 18px rgba(54,32,16,.08); }
    .control-grid { display:grid; grid-template-columns:minmax(280px,1.2fr) minmax(0,1.1fr) minmax(0,1fr) minmax(0,1fr); gap:12px 14px; align-items:start; transition:gap .18s ease; }
    .controls.compact .control-grid { gap:8px 10px; }
    .field { display:flex; flex-direction:column; gap:10px; }
    .field label { font-size:12px; font-weight:700; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }
    .controls.compact .field label { font-size:11px; }
    .search-field { grid-column:1; grid-row:1; }
    .category-field { grid-column:1; grid-row:2; }
    .bucket-field { grid-column:2 / 4; grid-row:1; }
    .type-field { grid-column:4; grid-row:1; }
    .highlight-field { grid-column:2 / 5; grid-row:2; transition:opacity .18s ease, max-height .18s ease; }
    .controls.compact .highlight-field { opacity:0; max-height:0; overflow:hidden; }
    .search { width:100%; padding:12px 14px; border-radius:14px; border:1px solid var(--line); background:#fff; font:inherit; color:var(--text); transition:padding .18s ease; }
    .controls.compact .search { padding:8px 10px; }
    .chip-row { display:flex; flex-wrap:wrap; gap:8px; }
    .chip { border:1px solid var(--line); background:#fff; padding:8px 11px; border-radius:999px; font:inherit; cursor:pointer; transition:padding .18s ease; }
    .controls.compact .chip { padding:6px 9px; }
    .chip.active { border-color:rgba(141,64,46,.34); background:rgba(141,64,46,.12); color:#5b2418; }
    .meta-row { display:flex; justify-content:space-between; align-items:center; gap:16px; margin-top:10px; color:var(--muted); font-size:14px; }
    .paper-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(360px,1fr)); gap:18px; margin-top:22px; }
    .paper { display:flex; flex-direction:column; gap:14px; padding:22px; border-radius:var(--radius); }
    .paper-top { display:flex; flex-wrap:wrap; gap:8px; }
    .tag { display:inline-flex; padding:6px 10px; border-radius:999px; font-size:12px; font-weight:700; border:1px solid transparent; }
    .category { background:rgba(45,36,29,.08); }
    .bucket-ai { background:rgba(154,77,18,.12); color:var(--ai); border-color:rgba(154,77,18,.18); }
    .bucket-qc { background:rgba(110,77,181,.12); color:var(--qc); border-color:rgba(110,77,181,.18); }
    .bucket-qi { background:rgba(35,109,92,.12); color:var(--qi); border-color:rgba(35,109,92,.18); }
    .bucket-cmt { background:rgba(122,60,47,.12); color:var(--cmt); border-color:rgba(122,60,47,.18); }
    .type-exp { background:rgba(46,111,63,.12); color:var(--exp); border-color:rgba(46,111,63,.18); }
    .type { background:rgba(0,0,0,.05); }
    .highlight { background:rgba(29,91,102,.12); color:var(--accent2); border-color:rgba(29,91,102,.18); }
    .id { color:var(--muted); font-size:13px; }
    .paper h2 { margin:0; font-family:Georgia,"Times New Roman",serif; font-size:24px; line-height:1.24; }
    .paper h2 a { color:inherit; text-decoration:none; }
    .paper h2 a:hover { color:var(--accent); }
    .authors, .subjects, .comments { color:var(--muted); font-size:14px; line-height:1.6; }
    .authors strong, .subjects strong, .comments strong { color:var(--text); }
    details { border:1px solid var(--line); border-radius:14px; padding:10px 12px; background:rgba(255,255,255,.72); }
    details summary { cursor:pointer; color:var(--accent2); font-weight:700; list-style:none; }
    details summary::-webkit-details-marker { display:none; }
    details p { margin:10px 0 0; color:var(--muted); line-height:1.72; font-size:14px; }
    footer { margin-top:auto; display:flex; justify-content:flex-end; align-items:center; gap:12px; color:var(--muted); font-size:13px; }
    footer a { color:var(--accent); font-weight:700; text-decoration:none; }
    .empty { display:none; margin-top:24px; padding:28px; text-align:center; color:var(--muted); border:1px dashed var(--line); border-radius:22px; background:rgba(255,255,255,.7); }
    @media (max-width:1040px) {
      .control-grid { grid-template-columns:1fr 1fr; }
      .search-field, .category-field, .bucket-field, .type-field, .highlight-field { grid-column:auto; grid-row:auto; }
      .controls { position:static; }
    }
    @media (max-width:720px) { .control-grid { grid-template-columns:1fr; } }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="eyebrow">Kim Group arXiv Daily &middot; __DATE__</div>
      <h1>AI, Quantum, and CMT arXiv Digest</h1>
      <p>This local digest scans <code>cond-mat</code>, <code>quant-ph</code>, and <code>cs</code> new submissions. The ranking prioritizes AI for physics, then quantum computation and simulation, then quantum information, and finally condensed-matter theory and computation. Each card keeps the core metadata visible and hides the full abstract inside a compact disclosure panel.</p>
      <div class="stats">__STATS_HTML__</div>
    </section>
    <section class="controls" id="controls">
      <div class="control-grid">
        <div class="field search-field"><label for="search">Search</label><input class="search" id="search" type="search" placeholder="Search title, authors, abstract, subjects, comments, or arXiv id"></div>
        <div class="field category-field"><label>Category</label><div class="chip-row" id="category-filters"></div></div>
        <div class="field bucket-field"><label>Bucket</label><div class="chip-row" id="bucket-filters"></div></div>
        <div class="field type-field"><label>Type</label><div class="chip-row" id="type-filters"></div></div>
        <div class="field highlight-field"><label>Highlights</label><div class="chip-row" id="highlight-filters"></div></div>
      </div>
      <div class="meta-row"><div id="result-count">Loading...</div><div><a href="../index.html">Archive</a></div></div>
    </section>
    <section class="paper-grid" id="paper-grid"></section>
    <section class="empty" id="empty-state">No papers match the current search and filters.</section>
  </div>
  <script>
    const papers = __PAPERS_JSON__;
    const categoryOrder = ["cond-mat", "quant-ph", "cs"];
    const bucketOrder = ["AI for Physics", "Quantum Computation / Simulation", "Quantum Information", "CMT Theory / Computation"];
    const typeOrder = ["Theory", "Numerical", "Theory + Numerical", "Experiment"];
    const highlightOrder = ["AI for Physics", "Quantum Advantage", "Quantum Error Correction"];
    const state = { search: "", categories: new Set(categoryOrder), buckets: new Set(bucketOrder), types: new Set(typeOrder), highlights: new Set() };
    const gridEl = document.getElementById("paper-grid");
    const resultCountEl = document.getElementById("result-count");
    const emptyStateEl = document.getElementById("empty-state");
    const searchEl = document.getElementById("search");
    const controlsEl = document.getElementById("controls");
    function escapeHtml(value) { return String(value ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;").replace(/'/g,"&#39;"); }
    function bucketClass(bucket) { if (bucket === "AI for Physics") return "bucket-ai"; if (bucket === "Quantum Computation / Simulation") return "bucket-qc"; if (bucket === "Quantum Information") return "bucket-qi"; return "bucket-cmt"; }
    function typeClass(type) { return type === "Experiment" ? "type-exp" : "type"; }
    function renderChips(containerId, values, selectedSet, onToggle) { const container = document.getElementById(containerId); container.innerHTML = values.map((value) => `<button class="chip ${selectedSet.has(value) ? "active" : ""}" type="button" data-value="${escapeHtml(value)}">${escapeHtml(value)}</button>`).join(""); container.querySelectorAll(".chip").forEach((button) => button.addEventListener("click", () => onToggle(button.dataset.value))); }
    function toggleRequiredSet(set, value) { if (set.has(value)) { if (set.size > 1) set.delete(value); } else { set.add(value); } }
    function toggleOptionalSet(set, value) { if (set.has(value)) set.delete(value); else set.add(value); }
    function matches(paper) {
      const highlightMatch = state.highlights.size === 0 || (paper.highlights || []).some((tag) => state.highlights.has(tag));
      const haystack = [paper.id, paper.category, paper.bucket, paper.type, paper.title, paper.subjects, paper.comments, paper.abstract, ...(paper.authors || [])].join(" ").toLowerCase();
      return state.categories.has(paper.category) && state.buckets.has(paper.bucket) && state.types.has(paper.type) && highlightMatch && haystack.includes(state.search);
    }
    function renderPapers() {
      const filtered = papers.filter(matches);
      resultCountEl.textContent = `Showing ${filtered.length} of ${papers.length} papers`;
      emptyStateEl.style.display = filtered.length ? "none" : "block";
      gridEl.innerHTML = filtered.map((paper) => {
        const safeUrl = escapeHtml(paper.url);
        const highlights = (paper.highlights || []).map((tag) => `<span class="tag highlight">${escapeHtml(tag)}</span>`).join("");
        const subjects = paper.subjects ? `<div class="subjects"><strong>Subjects:</strong> ${escapeHtml(paper.subjects)}</div>` : "";
        const comments = paper.comments ? `<div class="comments"><strong>Comments:</strong> ${escapeHtml(paper.comments)}</div>` : "";
        return `<article class="paper"><div class="paper-top"><span class="tag category">${escapeHtml(paper.category)}</span><span class="tag ${bucketClass(paper.bucket)}">${escapeHtml(paper.bucket)}</span><span class="tag ${typeClass(paper.type)}">${escapeHtml(paper.type)}</span>${highlights}</div><div class="id">arXiv:${escapeHtml(paper.id)}</div><h2><a href="${safeUrl}" target="_blank" rel="noreferrer">${escapeHtml(paper.title)}</a></h2><div class="authors"><strong>Authors:</strong> ${escapeHtml((paper.featured_authors || []).join(", ") || "Not available")}</div><div class="comments">${escapeHtml(paper.author_note || "")}</div>${subjects}${comments}<details><summary>Abstract</summary><p>${escapeHtml(paper.abstract)}</p></details><footer><a href="${safeUrl}" target="_blank" rel="noreferrer">Open arXiv</a></footer></article>`;
      }).join("");
    }
    function rerenderFilters() {
      renderChips("category-filters", categoryOrder, state.categories, (value) => { toggleRequiredSet(state.categories, value); rerenderFilters(); renderPapers(); });
      renderChips("bucket-filters", bucketOrder, state.buckets, (value) => { toggleRequiredSet(state.buckets, value); rerenderFilters(); renderPapers(); });
      renderChips("type-filters", typeOrder, state.types, (value) => { toggleRequiredSet(state.types, value); rerenderFilters(); renderPapers(); });
      renderChips("highlight-filters", highlightOrder, state.highlights, (value) => { toggleOptionalSet(state.highlights, value); rerenderFilters(); renderPapers(); });
    }
    function updateControlsCompact() { controlsEl.classList.toggle("compact", window.scrollY > 160); }
    searchEl.addEventListener("input", (event) => { state.search = event.target.value.trim().toLowerCase(); renderPapers(); });
    window.addEventListener("scroll", updateControlsCompact, { passive: true });
    rerenderFilters();
    renderPapers();
    updateControlsCompact();
  </script>
</body>
</html>
"""
    return template.replace("__DATE__", date_str).replace("__PAPERS_JSON__", papers_json).replace("__STATS_HTML__", cards_html)


def build_archive_html(entries: list[dict[str, Any]]) -> str:
    cards = "\n".join(f'<article class="card"><h2><a href="./{entry["date"]}/index.html">{entry["date"]}</a></h2><p>{entry["count"]} papers · categories: {", ".join(entry["categories"])}.</p></article>' for entry in entries) or "<p>No digests have been generated yet.</p>"
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Kim Group arXiv Daily Archive</title><style>body{{margin:0;font-family:"Aptos","Segoe UI",Arial,sans-serif;background:#f4efe7;color:#281f18}}.shell{{width:min(960px,calc(100% - 32px));margin:0 auto;padding:32px 0 56px}}.hero{{padding:28px;border-radius:28px;background:rgba(255,255,255,.88);border:1px solid rgba(61,46,32,.14)}}h1{{margin:0 0 8px;font-size:40px}}p{{color:#67584d;line-height:1.7}}.grid{{display:grid;gap:16px;margin-top:24px}}.card{{padding:18px 20px;border-radius:22px;background:rgba(255,255,255,.9);border:1px solid rgba(61,46,32,.14)}}.card h2{{margin:0 0 10px;font-size:22px}}.card a{{color:#8d402e;text-decoration:none}}.actions{{margin-top:18px;display:flex;gap:14px;flex-wrap:wrap}}.button{{display:inline-block;padding:10px 14px;border-radius:999px;background:#8d402e;color:white;text-decoration:none}}</style></head><body><div class="shell"><section class="hero"><h1>Kim Group arXiv Daily Archive</h1><p>Companion archive for the Kim Group selection. This track prioritizes AI for physics, quantum computation, quantum information, and condensed-matter theory / computation.</p><div class="actions"><a class="button" href="./latest.html">Open latest digest</a></div></section><section class="grid">{cards}</section></div></body></html>"""


def write_archive(output_root: Path) -> None:
    entries: list[dict[str, Any]] = []
    for date_dir in sorted((item for item in output_root.iterdir() if item.is_dir()), reverse=True):
        papers_path = date_dir / "papers.json"
        if not papers_path.exists():
            continue
        papers = json.loads(papers_path.read_text(encoding="utf-8-sig"))
        categories = sorted({paper["category"] for paper in papers})
        entries.append({"date": date_dir.name, "count": len(papers), "categories": categories})
    (output_root / "index.html").write_text(build_archive_html(entries), encoding="utf-8-sig")
    if entries:
        latest_target = f"./{entries[0]['date']}/index.html"
        latest_html = f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta http-equiv=\"refresh\" content=\"0; url={latest_target}\"><title>Latest Kim Group arXiv Daily</title></head><body><script>window.location.replace('{latest_target}');</script><p><a href=\"{latest_target}\">Open latest digest</a></p></body></html>"
        (output_root / "latest.html").write_text(latest_html, encoding="utf-8-sig")



def generate(date_str: str | None = None) -> Path:
    config = load_config()
    categories = config.get("categories", CATEGORY_ORDER)
    max_featured_authors = int(config.get("max_featured_authors", 6))
    enable_openai_summary = bool(config.get("enable_openai_summary", False))
    openai_api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    openai_model = str(config.get("openai_model", DEFAULT_OPENAI_MODEL))
    openai_max_output_tokens = int(config.get("openai_max_output_tokens", DEFAULT_OPENAI_MAX_OUTPUT_TOKENS))
    openai_timeout_seconds = int(config.get("openai_timeout_seconds", DEFAULT_OPENAI_TIMEOUT_SECONDS))
    openai_reasoning_effort = str(config.get("openai_reasoning_effort", DEFAULT_OPENAI_REASONING_EFFORT))
    date_value = dt.date.fromisoformat(date_str) if date_str else dt.date.today()
    output_root = ROOT / config.get("output_root", "output")
    output_root.mkdir(parents=True, exist_ok=True)
    day_dir = output_root / date_value.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)

    log(f"[1/6] Preparing digest for {date_value.isoformat()}")
    fetched: list[dict[str, Any]] = []
    for index, category in enumerate(categories, start=1):
        log(f"[2/6] Fetching category {index}/{len(categories)}: {category}")
        html_text = fetch_text(f"https://arxiv.org/list/{category}/new")
        category_papers = parse_new_submissions(category, html_text)
        fetched.extend(category_papers)
        log(f"      collected {len(category_papers)} submissions from {category}")

    log(f"[3/6] Filtering and ranking {len(fetched)} submissions")
    summary_mode = "codex" if enable_openai_summary and openai_api_key else "local fallback"
    log(f"[4/6] Enriching papers (summary={summary_mode})")
    papers, usage = enrich_papers(
        papers=fetched,
        max_featured_authors=max_featured_authors,
        enable_openai_summary=enable_openai_summary,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        openai_max_output_tokens=openai_max_output_tokens,
        openai_timeout_seconds=openai_timeout_seconds,
        openai_reasoning_effort=openai_reasoning_effort,
    )
    log(f"      kept {len(papers)} papers")
    for bucket in BUCKET_ORDER:
        log(f"      {bucket}: {sum(1 for paper in papers if paper['bucket'] == bucket)}")
    if enable_openai_summary:
        log(
            "      [usage] Codex "
            f"calls={usage['calls']} "
            f"successes={usage['successes']} "
            f"fallbacks={usage['fallbacks']} "
            f"input_tokens={usage['input_tokens']} "
            f"output_tokens={usage['output_tokens']} "
            f"total_tokens={usage['total_tokens']} "
            f"parse_failures={usage['parse_failures']} "
            f"request_failures={usage['request_failures']}"
        )

    log(f"[5/6] Writing files into {day_dir}")
    (day_dir / "papers.json").write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    (day_dir / "index.html").write_text(build_daily_html(date_value.isoformat(), papers), encoding="utf-8-sig")

    log("[6/6] Updating archive pages")
    write_archive(output_root)
    output_path = day_dir / "index.html"
    log(f"[done] Report ready: {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate the Kim Group arXiv daily digest.")
    parser.add_argument("--date", help="Target date in YYYY-MM-DD. Defaults to today.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        output_path = generate(date_str=args.date)
    except Exception as exc:
        print(f"Generation failed: {exc}", file=sys.stderr)
        return 1
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
