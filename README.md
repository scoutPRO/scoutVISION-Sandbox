# ScoutVision Gemini Sandbox

Small tester site for iterating on Gemini prompts against recruit highlight reels.

## What It Does

- Upload one highlight reel, limited to 5 minutes by default.
- Prepends a fixed coach/recruit analysis boilerplate prompt.
- Lets testers edit only the user-facing coach ask.
- Sends the video and composed prompt to Gemini.
- Runs Gemini processing in a lightweight Flask background thread so uploads return quickly.
- Shows a clean response view plus the full Gemini response JSON.
- Stores runs, prompts, outputs, like/dislike feedback, and feedback notes in SQLite.

## Local Setup

```bash
poetry env use 3.13
poetry install
poetry run pre-commit install
cp .env.example .env
```

Set `GEMINI_API_KEY` in `.env`, then run:

```bash
poetry run python app.py
```

Open `http://127.0.0.1:5055`.

After submitting a video, the app redirects to a run page with status `queued` or `processing`.
That page refreshes every 5 seconds until the run finishes.

## Linting

Ruff runs through pre-commit before each commit:

```bash
poetry run pre-commit run --all-files
```

The hook checks Ruff lint rules, including line length, and verifies formatting
with `ruff format --check`.

## Environment Variables

- `GEMINI_API_KEY`: required.
- `GEMINI_MODEL`: default `gemini-2.5-pro`.
- `DATA_DIR`: default `data`.
- `DATABASE_PATH`: default `data/prompt_lab.sqlite3`.
- `MAX_VIDEO_SECONDS`: default `300`.
- `MAX_UPLOAD_MB`: default `800`.
- `PORT`: used by Railway, default local port `5055`.

## Railway Notes

This app uses local SQLite and local video uploads. On Railway, configure a persistent volume and set `DATA_DIR` to the mounted volume path if you want runs and uploads to survive redeploys.

Background processing currently uses in-process Flask threads. That is fine for this low-traffic sandbox, but it is not durable across deploys or process restarts. If this becomes a longer-lived internal tool, move processing to a real queue.

The service start command is:

```bash
poetry run gunicorn app:app --bind 0.0.0.0:$PORT
```
