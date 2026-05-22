# ScoutVision Gemini Sandbox

Small tester site for iterating on Gemini prompts against player reels.

## What It Does

- Upload one player reel, limited to 5 minutes by default.
- Combines a shared base prompt with a selected review type and tester request.
- Lets testers choose an output shape and adjust the user-facing Gemini ask.
- Requires users to log in before submitting or viewing reviews.
- Lets beta testers create their own non-admin accounts when signup is enabled.
- Sends the video and composed prompt to Gemini.
- Runs Gemini processing in a lightweight Flask background thread so uploads return quickly.
- Shows a clean response view plus the full Gemini response JSON.
- Stores reviews, prompts, outputs, like/dislike feedback, and feedback notes in SQLite.
- Manages the database schema with SQLAlchemy ORM models and Alembic migrations.
- Exports completed review artifacts to `out/<review_id>/` for easy inspection.

## Local Setup

```bash
poetry env use 3.13
poetry install
poetry run pre-commit install
cp .env.example .env
```

Set `GEMINI_API_KEY`, `SECRET_KEY`, and the bootstrap admin credentials in `.env`,
then run:

```bash
poetry run python app.py
```

Open `http://127.0.0.1:5055`.

After submitting a video, the app redirects to a review page with status `queued` or `processing`.
The upload form shows client-side upload progress, then the review page polls a JSON
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
- `GEMINI_MODEL`: default `models/gemini-2.5-pro`; must match one of the backend model options.
- `SECRET_KEY`: required outside local development.
- `BOOTSTRAP_ADMIN_EMAIL`: creates this admin user on startup when set.
- `BOOTSTRAP_ADMIN_PASSWORD`: password for the bootstrap admin user.
- `BOOTSTRAP_ADMIN_NAME`: default `Admin`.
- `ALLOW_SIGNUP`: default `true`; when true, visitors can create tester accounts.
- `DATA_DIR`: default `data`.
- `OUT_DIR`: default `out`.
- `DATABASE_PATH`: default `data/prompt_lab.sqlite3`.
- `DATABASE_URL`: optional SQLAlchemy database URL. Defaults to SQLite from `DATABASE_PATH`.
- `MAX_VIDEO_SECONDS`: default `300`.
- `MAX_UPLOAD_MB`: default `800`.
- `KEEP_UPLOADED_VIDEOS`: default `true`; when true, successful review videos remain available for Review Again until upload retention removes them.
- `KEEP_FAILED_UPLOADS`: default `true`; when true, failed review videos are kept for debugging.
- `UPLOAD_RETENTION_DAYS`: default `3`; uploaded video files older than this are deleted during requests.
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

When a review completes, the app writes inspectable files to `out/<review_id>/`:

- `prompt.txt`: full prompt sent to Gemini.
- `response.json`: displayed response JSON.
- `gemini_response_full.json`: full Gemini SDK response JSON.
- `metadata.json`: run metadata such as model, video path, duration, and status.

Review IDs use canonical UUIDs, for example `a35b3b0e-1af6-4260-9da8-b8a642fcc5cb`.

## Railway Notes

This app uses local SQLite and local prompt/response artifacts. On Railway, attach a
persistent volume if reviews and users should survive redeploys. For the first
Railway beta, mount the volume at `/data` and set:

```bash
DATA_DIR=/data
OUT_DIR=/data/out
KEEP_UPLOADED_VIDEOS=true
UPLOAD_RETENTION_DAYS=3
```

That keeps the SQLite database and exported artifacts on the volume. Successful
videos remain briefly available for the Review Again flow, and the app deletes
uploaded video files older than the configured retention window during later
requests. Set `KEEP_UPLOADED_VIDEOS=false` if the Railway volume fills too
quickly and successful videos should be deleted immediately after Gemini
processing.

Configure these required Railway variables before the first review:

```bash
GEMINI_API_KEY=<company Gemini key>
SECRET_KEY=<generated Flask secret>
BOOTSTRAP_ADMIN_EMAIL=<initial admin email>
BOOTSTRAP_ADMIN_PASSWORD=<generated admin password>
BOOTSTRAP_ADMIN_NAME=<initial admin display name>
```

`ALLOW_SIGNUP=true` is the default beta behavior. Set it explicitly in Railway if
you want signup behavior to be obvious from the service variables.

Background processing currently uses in-process Flask threads. That is fine for this low-traffic sandbox, but it is not durable across deploys or process restarts. If this becomes a longer-lived internal tool, move processing to a real queue.

The service start command is:

```bash
poetry run gunicorn app:app --bind 0.0.0.0:$PORT
```
