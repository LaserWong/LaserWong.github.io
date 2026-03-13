from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"

ARCHIVES = [
    {
        "slug": "arxiv_daily",
        "title": "arXiv Daily Archive",
        "description": "Chinese digest covering cond-mat, hep-th, math-ph, and quant-ph, focused on theory / numerical work plus selected quantum-platform experiments.",
    },
    {
        "slug": "arxiv_daily_cornell",
        "title": "arXiv Daily Archive (Kim Group)",
        "description": "English digest prioritizing AI for physics, quantum computation / simulation, quantum information, and CMT theory / computation across cond-mat, quant-ph, and cs.",
    },
]


def log(message: str) -> None:
    print(message, flush=True)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read_archive_meta(slug: str) -> dict[str, Any]:
    archive_root = ROOT / slug
    entries: list[dict[str, Any]] = []
    if archive_root.exists():
        for date_dir in sorted((item for item in archive_root.iterdir() if item.is_dir()), reverse=True):
            papers_path = date_dir / "papers.json"
            if not papers_path.exists():
                continue
            papers = json.loads(papers_path.read_text(encoding="utf-8-sig"))
            categories = sorted({paper["category"] for paper in papers})
            entries.append(
                {
                    "date": date_dir.name,
                    "count": len(papers),
                    "categories": categories,
                }
            )
    latest = entries[0] if entries else None
    return {"entries": entries, "latest": latest}


def build_home_html() -> str:
    cards: list[str] = []
    for archive in ARCHIVES:
        meta = read_archive_meta(archive["slug"])
        latest = meta["latest"]
        latest_html = '<div class="empty">No digests available yet.</div>'
        if latest:
            latest_html = (
                f'<div class="meta">Latest: <strong>{latest["date"]}</strong> '
                f'· {latest["count"]} papers · {", ".join(latest["categories"])}.</div>'
            )
        cards.append(
            f'''<article class="card">
  <div class="eyebrow">{archive["title"]}</div>
  <h2><a href="./{archive["slug"]}/index.html">{archive["title"]}</a></h2>
  <p>{archive["description"]}</p>
  {latest_html}
  <div class="actions"><a class="button" href="./{archive["slug"]}/index.html">Open archive</a></div>
</article>'''
        )
    card_html = "\n".join(cards)
    return f'''<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ArXiv Daily Portal</title>
  <style>
    body {{ margin: 0; font-family: "Aptos", "Segoe UI", Arial, sans-serif; background: linear-gradient(180deg, #fbf7f0 0%, #f2eadf 100%); color: #2c221b; }}
    .shell {{ width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 32px 0 60px; }}
    .hero {{ padding: 30px; border-radius: 28px; background: rgba(255,255,255,.88); border: 1px solid rgba(61,46,32,.14); box-shadow: 0 14px 28px rgba(54,32,16,.08); }}
    h1 {{ margin: 0 0 10px; font-size: clamp(36px, 5vw, 56px); line-height: 1.02; letter-spacing: -.03em; }}
    .hero p {{ margin: 0; max-width: 860px; line-height: 1.7; color: #6b5d52; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 18px; margin-top: 24px; }}
    .card {{ padding: 22px; border-radius: 24px; background: rgba(255,255,255,.9); border: 1px solid rgba(61,46,32,.14); box-shadow: 0 12px 26px rgba(54,32,16,.06); }}
    .eyebrow {{ display: inline-flex; padding: 8px 12px; border-radius: 999px; font-size: 12px; text-transform: uppercase; letter-spacing: .06em; color: #6b5d52; background: rgba(45,36,29,.06); }}
    .card h2 {{ margin: 16px 0 10px; font-size: 30px; line-height: 1.08; }}
    .card h2 a {{ color: inherit; text-decoration: none; }}
    .card h2 a:hover {{ color: #8f3d2e; }}
    .card p {{ margin: 0; line-height: 1.72; color: #6b5d52; }}
    .meta {{ margin-top: 16px; color: #40342b; line-height: 1.65; }}
    .empty {{ margin-top: 16px; color: #8c7b6d; }}
    .actions {{ margin-top: 18px; display: flex; gap: 12px; flex-wrap: wrap; }}
    .button {{ display: inline-block; padding: 11px 15px; border-radius: 999px; background: #8f3d2e; color: #fff; text-decoration: none; }}
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <h1>ArXiv Daily Portal</h1>
      <p>This landing page hosts two parallel daily arXiv digests. Use <strong>arXiv Daily Archive</strong> for the original Chinese theory / numerical digest, and <strong>arXiv Daily Archive (Kim Group)</strong> for the Kim Group English AI, quantum, and CMT selection.</p>
    </section>
    <section class="grid">{card_html}</section>
  </div>
</body>
</html>'''


def write_home_page() -> Path:
    target = ROOT / "index.html"
    target.write_text(build_home_html(), encoding="utf-8-sig")
    return target


def run_generators(date_str: str | None = None) -> None:
    original = load_module("generate_arxiv_daily", TOOLS / "generate_arxiv_daily.py")
    cornell = load_module("generate_arxiv_daily_cornell", TOOLS / "generate_arxiv_daily_cornell.py")
    log("[portal 1/3] Running original arXiv daily generator")
    original.generate(date_str=date_str)
    log("[portal 2/3] Running Kim Group arXiv daily generator")
    cornell.generate(date_str=date_str)
    log("[portal 3/3] Writing shared home page")
    write_home_page()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate both arXiv archives and the shared portal page.")
    parser.add_argument("--date", help="Target date in YYYY-MM-DD. Defaults to today.")
    parser.add_argument("--home-only", action="store_true", help="Only rebuild the shared home page from existing archive output.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.home_only:
        output = write_home_page()
        print(output)
        return 0
    run_generators(date_str=args.date)
    print(ROOT / "index.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
