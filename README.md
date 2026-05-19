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
- Manages the database schema with SQLAlchemy ORM models and Alembic migrations.
- Exports completed run artifacts to `out/<run_id>/` for easy inspection.

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
The upload form shows client-side upload progress, then the run page polls a JSON
status endpoint for stage updates until Gemini processing finishes.

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
- `OUT_DIR`: default `out`.
- `DATABASE_PATH`: default `data/prompt_lab.sqlite3`.
- `DATABASE_URL`: optional SQLAlchemy database URL. Defaults to SQLite from `DATABASE_PATH`.
- `MAX_VIDEO_SECONDS`: default `300`.
- `MAX_UPLOAD_MB`: default `800`.
- `KEEP_UPLOADED_VIDEOS`: default `false`; when false, successful run videos are deleted after processing.
- `KEEP_FAILED_UPLOADS`: default `true`; when true, failed run videos are kept for debugging.
- `PORT`: used by Railway, default local port `5055`.

## Database Migrations

The app runs Alembic migrations on startup for this sandbox. You can also run them
explicitly:

```bash
poetry run alembic upgrade head
```

After changing SQLAlchemy models, create a migration with:

```bash
poetry run alembic revision --autogenerate -m "Describe schema change"
```

## Output Artifacts

When a run completes, the app writes inspectable files to `out/<run_id>/`:

- `prompt.txt`: full prompt sent to Gemini.
- `response.json`: displayed response JSON.
- `gemini_response_full.json`: full Gemini SDK response JSON.
- `metadata.json`: run metadata such as model, video path, duration, and status.

Run IDs use canonical UUIDs, for example `a35b3b0e-1af6-4260-9da8-b8a642fcc5cb`.

## Railway Notes

This app uses local SQLite and local video uploads. On Railway, configure a persistent volume and set `DATA_DIR` to the mounted volume path if you want runs and uploads to survive redeploys.

Background processing currently uses in-process Flask threads. That is fine for this low-traffic sandbox, but it is not durable across deploys or process restarts. If this becomes a longer-lived internal tool, move processing to a real queue.

The service start command is:

```bash
poetry run gunicorn app:app --bind 0.0.0.0:$PORT
```
