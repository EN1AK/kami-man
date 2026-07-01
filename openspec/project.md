# Project: Kami Man Bot

## Purpose

Kami Man Bot is a QQ bot built on NoneBot2 and OneBot V11. It provides card lookup and ruling lookup for Yu-Gi-Oh!, MyCard battle-platform statistics and subscription notifications, Riftbound card lookup, and bot administration commands.

This OpenSpec baseline describes the behavior currently implemented in the repository. It is not a roadmap and does not define future changes.

## Tech Stack

- Python 3.10+
- NoneBot2
- OneBot V11 adapter
- nonebot-plugin-apscheduler
- httpx and aiohttp for external HTTP APIs
- beautifulsoup4 and markdown for HTML/Markdown parsing
- Pillow for help-image rendering
- matplotlib for MyCard chart rendering
- pytz for timezone conversion

## Runtime

- Entry point: `bot.py`
- Host: `0.0.0.0`
- Port: `18080`
- Command starts: `/` and empty string
- Superuser configured in code: `2954452539`
- Plugin loading:
  - `nonebot_plugin_apscheduler`
  - all modules under `plugins/`

## Project Structure

- `bot.py`: NoneBot startup and adapter/plugin registration.
- `plugins/`: NoneBot command handlers and message-flow logic.
- `services/`: API clients, local JSON access, data formatting helpers.
- `assets/`: help Markdown, help-image renderer, Riftbound data sync script.
- `data/`: local runtime data and Riftbound card database.
- `openspec/`: OpenSpec project metadata and source-of-truth specs.

## Commands

- Run locally: `python bot.py`
- Render help image manually: `python assets/render_help.py`
- Sync Riftbound card database manually: `python assets/sync_riftbound_db.py`

There is no committed dependency lockfile, test command, lint command, or build command in the current baseline.

## External Services

- YGOCDB API: `https://ygocdb.com/api/v0/`
- Yu-Gi-Oh! primary image CDN: `https://cdn.233.momobako.com/ygoimg/ygopro/{id}.webp`
- Yu-Gi-Oh! fallback image CDN: `https://cdncf.moecube.com/ygopro-super-pre/data/pics/{id}.jpg`
- MyCard API: `https://sapi.moecube.com:444/ygopro/`
- Riftbound data source: `https://raw.githubusercontent.com/choowx2002/project_k_image/main`
- Riftbound image URLs are stored per card in `data/riftbound_cards.json`.

## Data Storage

The project uses local JSON files under `data/` for runtime state. These files are ignored by `.gitignore` via `data/*.json`.

Generated help image `assets/help.png` is also ignored by `.gitignore`.

## Boundaries

- Always document baseline specs from implemented behavior or explicit repository documentation.
- Always treat `data/*.json` as runtime state rather than source code.
- Ask first before adding dependencies, changing runtime storage, changing deployment assumptions, or modifying command behavior.
- Never commit secrets, runtime user data, generated help images, or unrelated business-code changes as part of baseline spec work.

## Open Questions

- Dependency versions are not pinned in the repository.
- No test framework or test command is defined.
- The deployed host timezone is not specified; MyCard logic mixes local `datetime.now()` with explicit Asia/Shanghai conversions.
- MyCard API response field semantics are inferred from current code because no formal API schema is committed.
