from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "arxiv_daily_config.json"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Codex-Arxiv-Daily/1.0"
TRANSLATE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
THEORY_ONLY_CATEGORIES = {"hep-th", "math-ph"}
EXPERIMENTAL_TOPIC_KEYWORDS = {
    "superconducting qubit", "superconducting qubits", "superconducting circuit",
    "superconducting circuits", "superconducting quantum circuit", "superconducting quantum circuits",
    "fluxonium", "transmon", "ion trap", "ion traps", "trapped ion", "trapped ions",
    "cold atom", "cold atoms", "ultracold atom", "ultracold atoms", "neutral atom",
    "neutral atoms", "rydberg atom", "rydberg atoms", "optical lattice",
    "bose-einstein condensate", "bose-einstein condensates"
}
EXPERIMENTAL_TITLE_HINTS = {
    "experiments", "experimental", "experimental demonstration", "demonstration",
    "implementation", "implemented", "measurement", "measurements"
}
EXPERIMENTAL_ACTION_KEYWORDS = {
    "measured performance", "chip-scale", "thermal cycles", "module replacement",
    "hardware and software", "control and measurement", "room temperature and 15 mk"
}
NUMERIC_KEYWORDS = {
    "simulation", "simulations", "numerical", "monte carlo", "molecular dynamics",
    "density functional theory", "dft", "ab initio", "hartree-fock", "finite-size scaling",
    "tensor-network", "tensor network", "time-dependent", "variational", "algorithm",
    "algorithms", "reinforcement learning", "optimization", "optimiz", "sample-based",
    "exact diagonalization", "gpu", "machine-learning", "machine learning", "computed",
    "calculation", "calculations", "solver", "solved", "evaluate", "phase diagram"
}
THEORY_KEYWORDS = {
    "theory", "field theory", "effective theory", "symmetry", "dual", "duality",
    "topological", "phase transition", "critical", "criterion", "proof", "bound",
    "classification", "invariant", "equation", "entanglement", "geometry", "hamiltonian",
    "renormalization", "renormalisation", "partition function", "model", "models",
    "langevin", "polaron", "superfluid", "condensate", "holography", "ads", "cft",
    "swampland", "moduli", "soliton", "string", "gravity", "cluster adjacency",
    "markov", "schrodinger", "rabi", "magic", "coherence", "incoherent operations"
}
INCLUDE_KEYWORDS = THEORY_KEYWORDS | NUMERIC_KEYWORDS | {
    "quantum", "dynamics", "scaling", "universality", "hall effect", "free energy",
    "adiabaticity", "graph states", "error mitigation", "qubit reset", "verification",
    "interacting", "many-body", "free-fermion", "wave packet", "toric code"
}
EXCLUDE_KEYWORDS = {
    "experimental", "experiment", "experimental demonstration", "device", "devices",
    "spectroscopy", "microscopy", "nanoscopy", "measurement", "measurements", "imaging",
    "platform", "review", "strategic review", "introduction to spectroscopy", "autonomous",
    "chip-integrated", "single photons", "biphotons", "conversion", "atomic clocks",
    "telecom", "hardware standardization", "interconnects", "x-ray scattering",
    "laser writing", "transparent ceramics", "nanoscale imaging", "resolving transient",
    "direct laser writing", "micro-scale liquid-metal", "source for", "study of w-l3 edge"
}


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Config file not found: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8-sig"))


def log(message: str) -> None:
    print(message, flush=True)


def fetch_text(url: str, timeout: int = 30) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def parse_new_submissions(category: str, html_text: str) -> list[dict[str, str]]:
    soup = BeautifulSoup(html_text, "html.parser")
    dl = soup.select_one("dl#articles")
    if dl is None:
        raise ValueError(f"Could not find article list for {category}")

    first_section = dl.find("h3")
    if first_section is None:
        raise ValueError(f"Could not find section header for {category}")

    papers: list[dict[str, str]] = []
    current = first_section.find_next_sibling()
    while current is not None and current.name != "h3":
        if current.name == "dt":
            link = current.find("a", title="Abstract")
            dd = current.find_next_sibling("dd")
            if link is None or dd is None:
                current = current.find_next_sibling()
                continue

            paper_id = link.get_text(" ", strip=True).replace("arXiv:", "")
            title_el = dd.select_one(".list-title")
            abstract_el = dd.select_one("p.mathjax")
            if title_el is None or abstract_el is None:
                current = current.find_next_sibling()
                continue

            title = clean_space(title_el.get_text(" ", strip=True).replace("Title:", ""))
            abstract = clean_space(abstract_el.get_text(" ", strip=True))
            papers.append(
                {
                    "id": paper_id,
                    "category": category,
                    "title": title,
                    "abstract": abstract,
                    "url": f"https://arxiv.org/abs/{paper_id}",
                }
            )
        current = current.find_next_sibling()

    return papers


def clean_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def normalize(text: str) -> str:
    lowered = text.lower()
    lowered = lowered.replace("–", "-").replace("—", "-").replace("’", "'")
    return lowered


def contains_any(text: str, keywords: set[str]) -> bool:
    return any(keyword in text for keyword in keywords)


def is_target_experimental_paper(paper: dict[str, str]) -> bool:
    title_text = normalize(paper["title"])
    abstract_text = normalize(paper["abstract"])
    combined_text = f"{title_text} {abstract_text}"
    has_topic = contains_any(combined_text, EXPERIMENTAL_TOPIC_KEYWORDS)
    if not has_topic:
        return False
    has_title_hint = contains_any(title_text, EXPERIMENTAL_TITLE_HINTS)
    has_action_hint = contains_any(abstract_text, EXPERIMENTAL_ACTION_KEYWORDS)
    return has_title_hint or has_action_hint


def infer_type(category: str, text: str, is_experimental: bool = False) -> str:
    if category in THEORY_ONLY_CATEGORIES:
        return "理论"
    if is_experimental:
        return "实验"

    has_numeric = contains_any(text, NUMERIC_KEYWORDS)
    has_theory = contains_any(text, THEORY_KEYWORDS) or not has_numeric
    if has_numeric and has_theory:
        return "理论+数值"
    if has_numeric:
        return "数值"
    return "理论"


def should_include(paper: dict[str, str]) -> bool:
    if paper["category"] in THEORY_ONLY_CATEGORIES:
        return True
    if is_target_experimental_paper(paper):
        return True

    text = normalize(f"{paper['title']} {paper['abstract']}")
    if contains_any(text, EXCLUDE_KEYWORDS):
        return False
    if contains_any(text, INCLUDE_KEYWORDS):
        return True
    return False


def parse_authors(html_text: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html_text, "html.parser")
    author_links = soup.select("div.authors a")
    authors: list[dict[str, Any]] = []
    for link in author_links:
        name = clean_space(link.get_text(" ", strip=True))
        if not name:
            continue
        authors.append({"name": name})
    return authors


def fetch_authors(paper_id: str) -> list[dict[str, Any]]:
    url = f"https://arxiv.org/abs/{paper_id}"
    try:
        html_text = fetch_text(url, timeout=20)
    except (urllib.error.URLError, TimeoutError, ValueError):
        return []
    return parse_authors(html_text)


def select_featured_authors(authors: list[dict[str, Any]], head: int = 3, tail: int = 3) -> list[dict[str, Any]]:
    if len(authors) <= head + tail:
        return authors
    return authors[:head] + authors[-tail:]


def chunk_text_for_translation(text: str, max_chars: int = 1200) -> list[str]:
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]
    if not sentences:
        stripped = text.strip()
        return [stripped] if stripped else []

    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for sentence in sentences:
        addition = len(sentence) + (1 if current else 0)
        if current and current_len + addition > max_chars:
            chunks.append(" ".join(current))
            current = [sentence]
            current_len = len(sentence)
        else:
            current.append(sentence)
            current_len += addition

    if current:
        chunks.append(" ".join(current))
    return chunks


def translate_to_chinese(text: str, cache: dict[str, str | None], enabled: bool) -> str | None:
    if not enabled:
        return None
    if text in cache:
        return cache[text]

    query = urllib.parse.urlencode(
        {
            "client": "gtx",
            "sl": "en",
            "tl": "zh-CN",
            "dt": "t",
            "q": text,
        }
    )
    url = f"{TRANSLATE_ENDPOINT}?{query}"
    try:
        payload = fetch_text(url, timeout=20)
        data = json.loads(payload)
        translated = "".join(chunk[0] for chunk in data[0] if chunk and chunk[0]).strip()
        cache[text] = translated or None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, ValueError):
        cache[text] = None
    return cache[text]


def translate_full_abstract(text: str, cache: dict[str, str | None], enabled: bool) -> str | None:
    chunks = chunk_text_for_translation(text)
    if not chunks:
        return None

    translated_chunks: list[str] = []
    for chunk in chunks:
        translated = translate_to_chinese(chunk, cache, enabled)
        if translated is None:
            return None
        translated_chunks.append(translated.strip())
    return "\n\n".join(translated_chunks)


def fallback_translated_abstract() -> str:
    return "中文摘要自动翻译失败，请展开查看英文原文。"


def enrich_papers(papers: list[dict[str, str]], enable_translation: bool) -> list[dict[str, Any]]:
    cache: dict[str, str | None] = {}
    author_cache: dict[str, list[dict[str, Any]]] = {}
    result: list[dict[str, Any]] = []
    total = len(papers)
    for index, paper in enumerate(papers, start=1):
        log(f"      -> paper {index}/{total}: {paper['category']} {paper['id']}")
        text = normalize(f"{paper['title']} {paper['abstract']}")
        is_experimental = is_target_experimental_paper(paper)
        paper_type = infer_type(paper["category"], text, is_experimental=is_experimental)
        translated_abstract = translate_full_abstract(paper["abstract"], cache, enable_translation)
        if not translated_abstract:
            translated_abstract = fallback_translated_abstract()

        authors = author_cache.get(paper["id"])
        if authors is None:
            authors = fetch_authors(paper["id"])
            author_cache[paper["id"]] = authors
        featured_authors = select_featured_authors(authors)

        result.append(
            {
                **paper,
                "type": paper_type,
                "summary": translated_abstract,
                "authors": authors,
                "featured_authors": featured_authors,
                "author_count": len(authors),
            }
        )
    return result


def build_daily_html(date_str: str, papers: list[dict[str, Any]]) -> str:
    papers_json = json.dumps(papers, ensure_ascii=False)
    template = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>arXiv __DATE__ 理论 / 数值 / 实验论文清单</title>
  <style>
    :root {
      --bg: #f6f1e8;
      --panel: rgba(255, 252, 246, 0.92);
      --text: #2d241d;
      --muted: #6d5d50;
      --line: rgba(69, 49, 32, 0.14);
      --accent: #8f3d2e;
      --accent-2: #1d5f6b;
      --theory: #7c3a2a;
      --numeric: #255b6a;
      --both: #5d4a99;
      --experimental: #2f6b39;
      --shadow: 0 18px 40px rgba(54, 32, 16, 0.12);
      --radius: 22px;
      --ui-font: "Aptos", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      --title-font: "Palatino Linotype", "Noto Serif SC", Georgia, serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--ui-font);
      color: var(--text);
      background: radial-gradient(circle at top left, rgba(255,255,255,0.78), transparent 32%), radial-gradient(circle at 88% 12%, rgba(29,95,107,0.14), transparent 20%), linear-gradient(180deg, #fbf7f0 0%, var(--bg) 42%, #f2e8dc 100%);
      min-height: 100vh;
    }
    .shell { width: min(1220px, calc(100% - 32px)); margin: 0 auto; padding: 28px 0 64px; }
    .hero {
      padding: 30px;
      border: 1px solid var(--line);
      border-radius: 30px;
      background: linear-gradient(135deg, rgba(255,255,255,0.84), rgba(255,248,238,0.72)), linear-gradient(135deg, rgba(143,61,46,0.08), rgba(29,95,107,0.08));
      box-shadow: var(--shadow);
    }
    .eyebrow {
      display: inline-flex; align-items: center; gap: 8px; padding: 8px 12px; border-radius: 999px; background: rgba(255,255,255,0.82); border: 1px solid var(--line); color: var(--muted); font-size: 13px; letter-spacing: 0.04em; text-transform: uppercase;
    }
    h1 { margin: 18px 0 10px; font-family: var(--title-font); font-size: clamp(32px, 5vw, 54px); line-height: 1.04; letter-spacing: -0.03em; }
    .hero p { max-width: 880px; color: var(--muted); font-size: 16px; line-height: 1.7; margin: 0; }
    .stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 14px; margin-top: 26px; }
    .stat { padding: 16px 18px; background: rgba(255,255,255,0.76); border: 1px solid var(--line); border-radius: 18px; }
    .stat .label { color: var(--muted); font-size: 13px; margin-bottom: 6px; }
    .stat .value { font-size: 28px; font-weight: 700; letter-spacing: -0.03em; }
    .controls { position: sticky; top: 12px; z-index: 3; margin-top: 22px; padding: 18px; border: 1px solid var(--line); border-radius: 24px; background: rgba(250,244,236,0.9); backdrop-filter: blur(16px); box-shadow: 0 10px 24px rgba(54,32,16,0.08); }
    .control-grid { display: grid; grid-template-columns: 1.4fr 1fr 1fr; gap: 16px; }
    .field { display: flex; flex-direction: column; gap: 10px; }
    .field label { font-size: 13px; font-weight: 700; color: var(--muted); letter-spacing: 0.04em; text-transform: uppercase; }
    .search { width: 100%; padding: 14px 16px; border-radius: 16px; border: 1px solid var(--line); background: rgba(255,255,255,0.92); font: inherit; color: var(--text); }
    .chip-row { display: flex; flex-wrap: wrap; gap: 10px; }
    .chip { border: 1px solid var(--line); background: rgba(255,255,255,0.82); color: var(--text); padding: 10px 14px; border-radius: 999px; font: inherit; cursor: pointer; }
    .chip.active { border-color: rgba(143,61,46,0.35); background: rgba(143,61,46,0.12); color: #5b2419; }
    .chip[data-type="数值"].active { border-color: rgba(37,91,106,0.35); background: rgba(37,91,106,0.12); color: #173f49; }
    .chip[data-type="理论+数值"].active { border-color: rgba(93,74,153,0.35); background: rgba(93,74,153,0.12); color: #46337d; }
    .chip[data-type="实验"].active { border-color: rgba(47,107,57,0.35); background: rgba(47,107,57,0.12); color: #214c29; }
    .meta-row { display: flex; justify-content: space-between; align-items: center; gap: 16px; margin-top: 14px; color: var(--muted); font-size: 14px; }
    .paper-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(310px, 1fr)); gap: 18px; margin-top: 22px; }
    .paper { display: flex; flex-direction: column; gap: 14px; padding: 20px; background: var(--panel); border: 1px solid var(--line); border-radius: var(--radius); box-shadow: 0 10px 24px rgba(54,32,16,0.06); }
    .paper-top { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
    .tag { display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px; border-radius: 999px; font-size: 12px; font-weight: 700; border: 1px solid transparent; }
    .tag.category { background: rgba(45,36,29,0.08); color: var(--text); }
    .tag.type-theory { background: rgba(124,58,42,0.1); color: var(--theory); border-color: rgba(124,58,42,0.16); }
    .tag.type-numeric { background: rgba(37,91,106,0.1); color: var(--numeric); border-color: rgba(37,91,106,0.16); }
    .tag.type-both { background: rgba(93,74,153,0.1); color: var(--both); border-color: rgba(93,74,153,0.16); }
    .tag.type-experimental { background: rgba(47,107,57,0.1); color: var(--experimental); border-color: rgba(47,107,57,0.16); }
    .paper h2 { margin: 0; font-family: var(--title-font); font-size: 22px; line-height: 1.25; letter-spacing: -0.02em; }
    .paper h2 a { color: inherit; text-decoration: none; }
    .paper h2 a:hover { color: var(--accent); }
    .paper .id { color: var(--muted); font-size: 13px; }
    .author-block { display: grid; gap: 10px; padding: 14px 16px; border-radius: 18px; background: rgba(255,255,255,0.64); border: 1px solid var(--line); }
    .author-label { color: var(--muted); font-size: 12px; font-weight: 700; letter-spacing: 0.04em; text-transform: uppercase; }
    .author-list { list-style: none; margin: 0; padding: 0; display: grid; gap: 10px; }
    .author-item { display: grid; gap: 4px; }
    .author-item strong { font-size: 14px; }
    .author-item span { color: var(--muted); font-size: 13px; line-height: 1.55; }
    .author-note { color: var(--muted); font-size: 12px; }
    .paper .summary { margin: 0; font-size: 15px; line-height: 1.75; white-space: pre-line; }
    details { border-top: 1px solid var(--line); padding-top: 12px; }
    details summary { cursor: pointer; color: var(--accent-2); font-weight: 700; list-style: none; }
    details summary::-webkit-details-marker { display: none; }
    details p { margin: 10px 0 0; color: var(--muted); line-height: 1.72; font-size: 14px; white-space: pre-line; }
    .paper footer { margin-top: auto; display: flex; justify-content: space-between; align-items: center; gap: 12px; padding-top: 6px; color: var(--muted); font-size: 13px; }
    .paper footer a { color: var(--accent); font-weight: 700; text-decoration: none; }
    .empty { display: none; margin-top: 24px; padding: 28px; text-align: center; color: var(--muted); border: 1px dashed var(--line); border-radius: 22px; background: rgba(255,255,255,0.7); }
    @media (max-width: 980px) { .control-grid { grid-template-columns: 1fr; } .controls { position: static; } }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="eyebrow">arXiv Daily Digest · __DATE__</div>
      <h1>理论 / 数值 / 实验 arXiv 论文清单</h1>
      <p>
        数据来自 arXiv 当天的 <code>cond-mat</code>、<code>hep-th</code>、<code>math-ph</code>、<code>quant-ph</code> 四个分类页，口径限定为 <code>New submissions</code>。
        除理论和数值文章外，页面还会额外纳入与量子模拟、量子计算、冷原子、离子阱、超导量子比特相关的目标实验论文。中文摘要为自动翻译；下拉查看 arXiv 英文原文摘要。
      </p>
      <div class="stats" id="stats"></div>
    </section>
    <section class="controls">
      <div class="control-grid">
        <div class="field">
          <label for="search">搜索</label>
          <input class="search" id="search" type="search" placeholder="按标题、作者、摘要、arXiv 编号搜索">
        </div>
        <div class="field">
          <label>分类</label>
          <div class="chip-row" id="category-filters"></div>
        </div>
        <div class="field">
          <label>类型</label>
          <div class="chip-row" id="type-filters"></div>
        </div>
      </div>
      <div class="meta-row">
        <div id="result-count">正在加载…</div>
        <div><a href="../index.html">返回归档</a></div>
      </div>
    </section>
    <section class="paper-grid" id="paper-grid"></section>
    <section class="empty" id="empty-state">没有匹配到结果，试试清空搜索词或恢复筛选。</section>
  </div>
  <script>
    const papers = __PAPERS_JSON__;
    const categoryOrder = ["cond-mat", "hep-th", "math-ph", "quant-ph"];
    const typeOrder = ["\u7406\u8bba", "\u6570\u503c", "\u7406\u8bba+\u6570\u503c", "\u5b9e\u9a8c"];
    const state = { search: "", categories: new Set(categoryOrder), types: new Set(typeOrder) };
    const statsEl = document.getElementById("stats");
    const gridEl = document.getElementById("paper-grid");
    const resultCountEl = document.getElementById("result-count");
    const emptyStateEl = document.getElementById("empty-state");
    const searchEl = document.getElementById("search");
    function typeClass(type) { if (type === "\u7406\u8bba") return "type-theory"; if (type === "\u6570\u503c") return "type-numeric"; if (type === "\u5b9e\u9a8c") return "type-experimental"; return "type-both"; }
    function escapeHtml(value) {
      return String(value ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#39;");
    }
    function renderAuthors(paper) {
      const authors = paper.featured_authors || [];
      if (!authors.length) {
        return `<section class="author-block"><div class="author-label">作者</div><div class="author-note">未提取到作者信息。</div></section>`;
      }
      const items = authors.map((author) => `<li class="author-item"><strong>${escapeHtml(author.name)}</strong></li>`).join("");
      const note = paper.author_count > authors.length ? `显示前 3 位与后 3 位作者，共 ${paper.author_count} 位` : `共 ${paper.author_count} 位作者`;
      return `<section class="author-block"><div class="author-label">作者</div><ul class="author-list">${items}</ul><div class="author-note">${note}</div></section>`;
    }
    function statCard(label, value) { return `<article class="stat"><div class="label">${label}</div><div class="value">${value}</div></article>`; }
    function renderStats() {
      const categoryCounts = Object.fromEntries(categoryOrder.map((cat) => [cat, 0]));
      const typeCounts = Object.fromEntries(typeOrder.map((type) => [type, 0]));
      papers.forEach((paper) => { categoryCounts[paper.category] += 1; typeCounts[paper.type] += 1; });
      statsEl.innerHTML = [statCard("筛出论文", papers.length), ...categoryOrder.map((cat) => statCard(cat, categoryCounts[cat])), ...typeOrder.map((type) => statCard(type, typeCounts[type]))].join("");
    }
    function renderChips(containerId, values, selectedSet, onToggle, attrName) {
      const container = document.getElementById(containerId);
      container.innerHTML = values.map((value) => {
        const extra = attrName ? `${attrName}="${value}"` : "";
        const active = selectedSet.has(value) ? "active" : "";
        return `<button class="chip ${active}" type="button" data-value="${value}" ${extra}>${value}</button>`;
      }).join("");
      container.querySelectorAll(".chip").forEach((button) => button.addEventListener("click", () => onToggle(button.dataset.value)));
    }
    function toggleFromSet(set, value) { if (set.has(value)) { if (set.size > 1) set.delete(value); } else { set.add(value); } }
    function matches(paper) {
      const authorText = (paper.authors || []).map((author) => author.name).join(" ");
      const haystack = [paper.id, paper.category, paper.type, paper.title, paper.abstract, paper.summary, authorText].join(" ").toLowerCase();
      return state.categories.has(paper.category) && state.types.has(paper.type) && haystack.includes(state.search);
    }
    function renderPapers() {
      const filtered = papers.filter(matches);
      resultCountEl.textContent = `当前显示 ${filtered.length} / ${papers.length} 篇`;
      emptyStateEl.style.display = filtered.length ? "none" : "block";
      gridEl.innerHTML = filtered.map((paper) => {
        const safeUrl = escapeHtml(paper.url);
        return `
        <article class="paper">
          <div class="paper-top"><span class="tag category">${escapeHtml(paper.category)}</span><span class="tag ${typeClass(paper.type)}">${escapeHtml(paper.type)}</span></div>
          <div class="id">arXiv:${escapeHtml(paper.id)}</div>
          <h2><a href="${safeUrl}" target="_blank" rel="noreferrer">${escapeHtml(paper.title)}</a></h2>
          ${renderAuthors(paper)}
          <p class="summary">${escapeHtml(paper.summary)}</p>
          <details><summary>查看英文原文摘要</summary><p>${escapeHtml(paper.abstract)}</p></details>
          <footer><span>自动翻译</span><a href="${safeUrl}" target="_blank" rel="noreferrer">打开 arXiv</a></footer>
        </article>`;
      }).join("");
    }
    function rerenderFilters() {
      renderChips("category-filters", categoryOrder, state.categories, (value) => { toggleFromSet(state.categories, value); rerenderFilters(); renderPapers(); });
      renderChips("type-filters", typeOrder, state.types, (value) => { toggleFromSet(state.types, value); rerenderFilters(); renderPapers(); }, "data-type");
    }
    searchEl.addEventListener("input", (event) => { state.search = event.target.value.trim().toLowerCase(); renderPapers(); });
    renderStats();
    rerenderFilters();
    renderPapers();
  </script>
</body>
</html>
"""
    return template.replace("__DATE__", date_str).replace("__PAPERS_JSON__", papers_json)


def build_archive_html(entries: list[dict[str, Any]], link_prefix: str = ".") -> str:
    base = link_prefix.rstrip("/") or "."
    items = []
    for entry in entries:
        href = f"{base}/{entry['date']}/index.html" if base != "." else f"./{entry['date']}/index.html"
        items.append(
            f'<article class="card"><h2><a href="{href}">{entry["date"]}</a></h2><p>{entry["count"]} 篇 · 分类：{", ".join(entry["categories"])}。</p></article>'
        )
    cards = "\n".join(items) if items else '<p>还没有生成任何日报。</p>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>arXiv Daily Archive</title>
  <style>
    body {{ margin: 0; font-family: "Aptos", "Segoe UI", sans-serif; background: #f6f1e8; color: #2d241d; }}
    .shell {{ width: min(960px, calc(100% - 32px)); margin: 0 auto; padding: 32px 0 56px; }}
    .hero {{ padding: 28px; border-radius: 28px; background: rgba(255,255,255,0.86); border: 1px solid rgba(69,49,32,0.14); }}
    h1 {{ margin: 0 0 8px; font-size: 40px; }}
    p {{ color: #6d5d50; line-height: 1.7; }}
    .grid {{ display: grid; gap: 16px; margin-top: 24px; }}
    .card {{ padding: 18px 20px; border-radius: 22px; background: rgba(255,255,255,0.88); border: 1px solid rgba(69,49,32,0.14); }}
    .card h2 {{ margin: 0 0 10px; font-size: 22px; }}
    .card a {{ color: #8f3d2e; text-decoration: none; }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>arXiv Daily Archive</h1>
      <p>点击下面的日期打开当天生成的页面。输出目录固定为 <code>arxiv_daily</code>，每日结果会写入各自的日期子目录。</p>
    </section>
    <section class="grid">{cards}</section>
  </div>
</body>
</html>
"""


def write_archive(output_root: Path) -> None:
    entries: list[dict[str, Any]] = []
    for date_dir in sorted((item for item in output_root.iterdir() if item.is_dir()), reverse=True):
        papers_path = date_dir / "papers.json"
        if not papers_path.exists():
            continue
        papers = json.loads(papers_path.read_text(encoding="utf-8-sig"))
        categories = sorted({paper["category"] for paper in papers})
        entries.append({"date": date_dir.name, "count": len(papers), "categories": categories})

    archive_html = build_archive_html(entries)
    (output_root / "index.html").write_text(archive_html, encoding="utf-8-sig")
    (ROOT / "index.html").write_text(build_archive_html(entries, link_prefix=f"./{output_root.name}"), encoding="utf-8-sig")
    if entries:
        latest_target = f"./{entries[0]['date']}/index.html"
        latest_html = f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta http-equiv="refresh" content="0; url={latest_target}">
  <title>Latest arXiv Daily</title>
</head>
<body>
  <script>window.location.replace('{latest_target}');</script>
  <p><a href="{latest_target}">打开最新一期</a></p>
</body>
</html>
"""
        (output_root / "latest.html").write_text(latest_html, encoding="utf-8-sig")

def generate(date_str: str | None = None) -> Path:
    config = load_config()
    categories = config.get("categories", [])
    if not categories:
        raise ValueError("No categories configured.")

    date_value = dt.date.fromisoformat(date_str) if date_str else dt.date.today()
    output_root = ROOT / config.get("output_root", "arxiv_daily")
    output_root.mkdir(parents=True, exist_ok=True)
    day_dir = output_root / date_value.isoformat()
    day_dir.mkdir(parents=True, exist_ok=True)
    translation_enabled = bool(config.get("enable_summary_translation", True))

    log(f"[1/6] Preparing digest for {date_value.isoformat()}")
    fetched: list[dict[str, str]] = []
    for index, category in enumerate(categories, start=1):
        url = f"https://arxiv.org/list/{category}/new"
        log(f"[2/6] Fetching category {index}/{len(categories)}: {category}")
        html_text = fetch_text(url)
        category_papers = parse_new_submissions(category, html_text)
        fetched.extend(category_papers)
        log(f"      collected {len(category_papers)} submissions from {category}")

    log(f"[3/6] Filtering {len(fetched)} submissions")
    filtered = [paper for paper in fetched if should_include(paper)]
    log(f"      kept {len(filtered)} papers after filtering")

    log(f"[4/6] Enriching papers (translation={'on' if translation_enabled else 'off'}, authors=on)")
    papers = enrich_papers(filtered, translation_enabled)
    papers.sort(key=lambda item: (categories.index(item["category"]), item["id"]))

    log(f"[5/6] Writing files into {day_dir}")
    (day_dir / "papers.json").write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8-sig")
    (day_dir / "index.html").write_text(build_daily_html(date_value.isoformat(), papers), encoding="utf-8-sig")

    log("[6/6] Updating archive pages")
    write_archive(output_root)
    output_path = day_dir / "index.html"
    log(f"[done] Report ready: {output_path}")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a daily arXiv HTML digest.")
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

