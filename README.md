# LaserWong.github.io

GitHub Pages source for the personal `github-personal` site. This repository now hosts two daily arXiv archives on a shared landing page.

## Included
- `tools/generate_arxiv_daily.py`: original Chinese digest generator
- `tools/generate_arxiv_daily_cornell.py`: Cornell-style English digest generator
- `tools/generate_arxiv_portal.py`: combined runner that updates both archives and the shared home page
- `arxiv_daily_config.json`: configuration for the original digest
- `arxiv_daily_cornell_config.json`: configuration for the Cornell digest
- `run_arxiv_daily.cmd`: local Windows launcher with Python bootstrap
- `run_arxiv_daily.sh`: local macOS / Linux launcher with Python bootstrap
- `requirements.txt`: Python dependency list
- `arxiv_daily/`: original archive output
- `arxiv_daily_cornell/`: Cornell archive output
- `index.html`: shared portal page linking to both archives
- `.github/workflows/daily-update.yml`: GitHub Actions workflow for daily regeneration

## Repository name
Use this exact repository name for the personal Pages site:
- `LaserWong.github.io`

## Local run
- Windows: `run_arxiv_daily.cmd`
- macOS / Linux: `./run_arxiv_daily.sh`

The local launcher now updates both archives and refreshes the shared landing page.

## Bootstrap behavior
- Requires Python 3.10+
- Creates a local `.venv`
- Installs or upgrades project dependencies from `requirements.txt`
- Attempts to install Python automatically if it is missing or too old

## Publish
1. Upload the full contents of this folder to the repository root of `LaserWong.github.io`.
2. GitHub Pages will serve the repository root.
3. The root page shows the shared portal with `arXiv Daily Archive` and `arXiv Daily Archive_cornell`.
4. If GitHub Actions are enabled, the workflow will regenerate both archives daily and commit new output.

## Schedule
- The workflow checks twice in UTC and only runs when the local time in `America/New_York` is 08:00.
- This keeps the update pinned to 8:00 AM New York time across EST and EDT.

## Notes
- `arXiv Daily Archive` keeps the original Chinese interface and translation behavior.
- `arXiv Daily Archive_cornell` keeps the Cornell-style English filtering and ranking.
- Automatic Python installation may require administrator / sudo permissions depending on the machine.
