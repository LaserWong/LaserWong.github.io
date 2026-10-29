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

## Summary providers (original Chinese archive)
- Primary: OpenAI `gpt-6.1-sol` via the Responses API, with low reasoning effort.
- Fallback: `deepseek-reasoner` using the existing `DEEPSEEK_API_KEY`.
- Both providers summarize the title and abstract into three Chinese sentences: work/method, technical or physical advance/results, and implications/outlook. Full-paper reading is not implemented.
- GPT uses a strict JSON schema, rendered as three numbered sentences. The prompt targets about 256 visible tokens; `openai_max_output_tokens` also covers reasoning and JSON overhead.
- Quota exhaustion, invalid credentials, and unavailable models disable GPT for the remainder of that run. The next run tries GPT again. Temporary rate limits and network failures receive up to three attempts, then the affected paper goes to DeepSeek.
- If neither API succeeds, the existing local fallback remains visibly labeled. Each paper records `summary_source`, `summary_model`, and `openai_status`; logs report token usage separately for each provider.
- The Kim Group generator and abstract display are unchanged.

### Local credentials
Set `OPENAI_API_KEY` (aliases: `GPTAPI_KY`, `gptapi_ky`) or set `OPENAI_API_KEY_FILE` to a file containing only the key. Environment credentials take priority.
Alternatively, create the Git-ignored `arxiv_daily_config.local.json` with an `openai_api_key_file` path. Relative paths are resolved from the repository root; do not put key contents in JSON configuration. This local configuration is never needed by GitHub Actions.

### GitHub Actions credentials
In `LaserWong.github.io` repository Settings > Secrets and variables > Actions, add repository secret `OPENAI_API_KEY` (or `GPTAPI_KY`) and keep `DEEPSEEK_API_KEY`.
Actions cannot access a key file on your computer. Without the OpenAI repository secret, it continues using DeepSeek. Keys are used only server-side and never embedded in HTML or committed to Git.
API usage is billed to the corresponding API account.

### Tests
Run `python -m unittest discover -s tests -v` for offline routing, error handling, credential loading, and summary-format tests. These tests do not use API credits.

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
- `arXiv Daily Archive` keeps the original Chinese interface with GPT-first, DeepSeek-fallback summaries.
- `arXiv Daily Archive_cornell` keeps the Cornell-style English filtering and ranking.
- Automatic Python installation may require administrator / sudo permissions depending on the machine.
