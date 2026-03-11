# LaserWong.github.io

GitHub Pages source for the personal `github-personal` site. This repository only contains the daily arXiv project.

## Included
- `tools/generate_arxiv_daily.py`: generator
- `arxiv_daily_config.json`: configuration
- `run_arxiv_daily.cmd`: local Windows launcher with Python bootstrap
- `run_arxiv_daily.sh`: local macOS / Linux launcher with Python bootstrap
- `requirements.txt`: Python dependency list
- `arxiv_daily/`: generated digest output and archive pages
- `index.html`: repository-root archive page
- `.github/workflows/daily-update.yml`: GitHub Actions workflow for daily regeneration

## Repository name
Use this exact repository name for the personal Pages site:
- `LaserWong.github.io`

## Local run
- Windows: `run_arxiv_daily.cmd`
- macOS / Linux: `./run_arxiv_daily.sh`

## Bootstrap behavior
- Requires Python 3.10+
- Creates a local `.venv`
- Installs or upgrades project dependencies from `requirements.txt`
- Attempts to install Python automatically if it is missing or too old

## Publish
1. Upload the full contents of this folder to the repository root of `LaserWong.github.io`.
2. GitHub Pages will serve the repository root.
3. The root page directly shows the arXiv archive directory.
4. If GitHub Actions are enabled, the workflow will regenerate the digest daily and commit new output.

## Schedule
- The workflow checks twice in UTC and only runs when the local time in `America/New_York` is 08:00.
- This keeps the update pinned to 8:00 AM New York time across EST and EDT.

## Notes
- This site keeps the original Chinese interface and translation behavior.
- Automatic Python installation may require administrator / sudo permissions depending on the machine.
