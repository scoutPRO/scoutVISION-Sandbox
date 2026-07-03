"""Weekly usage report generation for the Sandbox app."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from html import escape

from sqlalchemy.orm import joinedload

from database import SessionLocal
from models import PromptRun
from settings import APP_BASE_URL


@dataclass
class UserUsage:
    """Usage summary for one web or external user identity."""

    label: str
    count: int = 0
    completed: int = 0
    failed: int = 0
    processing: int = 0
    total_video_seconds: float = 0.0
    feedback_count: int = 0
    account_id: str | None = None
    user_id: str | None = None
    source: str | None = None


@dataclass
class FeedbackItem:
    """Feedback attached to a prompt run."""

    created_at: datetime
    run_id: str
    user_label: str
    video_filename: str
    rating: str | None
    notes: str | None
    url: str | None = None


@dataclass
class WeeklyUsageReport:
    """Weekly report data ready for rendering."""

    start_at: datetime
    end_at: datetime
    total_runs: int
    status_counts: Counter[str]
    active_users: list[UserUsage] = field(default_factory=list)
    feedback_items: list[FeedbackItem] = field(default_factory=list)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _duration_label(seconds: float) -> str:
    minutes = seconds / 60
    if minutes >= 1:
        return f"{minutes:.1f} min"
    return f"{seconds:.0f} sec"


def _run_user_key(run: PromptRun) -> tuple[str, str]:
    if run.user:
        return ("web", run.user.id)
    if run.external_account_id or run.external_user_id:
        return (
            run.integration_source or "external",
            (
                f"{run.external_account_id or 'unknown-account'}:"
                f"{run.external_user_id or 'unknown-user'}"
            ),
        )
    return ("unknown", "unknown")


def _source_label(source: str | None) -> str:
    """Return a human-friendly integration source label."""
    if source == "scoutsmart_api":
        return "scoutSMART API"
    if not source:
        return "External API"
    return source.replace("_", " ").title()


def _run_user_label(run: PromptRun) -> str:
    if run.user:
        return f"{run.user.name} <{run.user.email}>"
    if run.external_account_id or run.external_user_id:
        account_id = run.external_account_id or "not provided"
        user_id = run.external_user_id or "not provided"
        return f"{_source_label(run.integration_source)} account {account_id} / user {user_id}"
    return "No user recorded"


def _run_url(run_id: str) -> str | None:
    if not APP_BASE_URL:
        return None
    return f"{APP_BASE_URL}/runs/{run_id}"


def build_weekly_usage_report(
    *,
    days: int = 7,
    end_at: datetime | None = None,
) -> WeeklyUsageReport:
    """Build a usage and feedback report for the trailing window."""
    if days <= 0:
        raise ValueError("days must be positive")

    end = _as_utc(end_at or datetime.now(UTC))
    start = end - timedelta(days=days)

    with SessionLocal() as session:
        runs = (
            session.query(PromptRun)
            .options(joinedload(PromptRun.user))
            .filter(PromptRun.created_at >= start)
            .filter(PromptRun.created_at < end)
            .order_by(PromptRun.created_at.asc())
            .all()
        )

        usage_by_user: dict[tuple[str, str], UserUsage] = {}
        status_counts: Counter[str] = Counter()
        feedback_items: list[FeedbackItem] = []

        for run in runs:
            key = _run_user_key(run)
            if key not in usage_by_user:
                usage_by_user[key] = UserUsage(
                    label=_run_user_label(run),
                    account_id=run.external_account_id,
                    user_id=run.external_user_id,
                    source=run.integration_source or key[0],
                )

            usage = usage_by_user[key]
            usage.count += 1
            usage.total_video_seconds += run.video_duration_seconds or 0.0
            status = run.status or "unknown"
            status_counts[status] += 1
            if status == "completed":
                usage.completed += 1
            elif status == "failed":
                usage.failed += 1
            else:
                usage.processing += 1

            has_feedback = bool(run.feedback_rating or run.feedback_notes)
            if has_feedback:
                usage.feedback_count += 1
                feedback_items.append(
                    FeedbackItem(
                        created_at=_as_utc(run.created_at),
                        run_id=run.id,
                        user_label=usage.label,
                        video_filename=run.video_filename,
                        rating=run.feedback_rating,
                        notes=run.feedback_notes,
                        url=_run_url(run.id),
                    )
                )

    active_users = sorted(
        usage_by_user.values(),
        key=lambda item: (-item.count, item.label.lower()),
    )
    feedback_items.sort(key=lambda item: item.created_at)

    return WeeklyUsageReport(
        start_at=start,
        end_at=end,
        total_runs=len(runs),
        status_counts=status_counts,
        active_users=active_users,
        feedback_items=feedback_items,
    )


def render_weekly_usage_report(report: WeeklyUsageReport) -> str:
    """Render the weekly usage report as plain text."""
    lines: list[str] = []
    lines.append("scoutVISION Sandbox Weekly Usage Report")
    lines.append(
        f"Window: {report.start_at:%Y-%m-%d %H:%M UTC} to {report.end_at:%Y-%m-%d %H:%M UTC}"
    )
    lines.append("")
    lines.append(f"Total reviews: {report.total_runs}")
    if report.status_counts:
        status_text = ", ".join(
            f"{status}: {count}" for status, count in sorted(report.status_counts.items())
        )
        lines.append(f"Statuses: {status_text}")
    lines.append("")

    lines.append("Active users")
    if not report.active_users:
        lines.append("- No active users in this window.")
    else:
        for usage in report.active_users:
            lines.append(
                f"- {usage.label}: {usage.count} review(s), "
                f"{usage.completed} completed, {usage.failed} failed, "
                f"{usage.processing} other, "
                f"{_duration_label(usage.total_video_seconds)} video, "
                f"{usage.feedback_count} feedback item(s)"
            )
    lines.append("")

    lines.append("Feedback received")
    if not report.feedback_items:
        lines.append("- No feedback received in this window.")
    else:
        for item in report.feedback_items:
            lines.append(
                f"- {item.created_at:%Y-%m-%d} | {item.user_label} | "
                f"{item.video_filename} | rating={item.rating or '-'}"
            )
            if item.notes:
                lines.append(f"  Notes: {item.notes.strip()}")
            if item.url:
                lines.append(f"  Review: {item.url}")
    lines.append("")
    return "\n".join(lines)


def _status_badge(status: str, count: int) -> str:
    css_class = {
        "completed": "ok",
        "failed": "bad",
        "queued": "muted",
        "processing": "muted",
    }.get(status, "muted")
    return f'<span class="badge {css_class}">{escape(status)}: {count}</span>'


def render_weekly_usage_report_html(report: WeeklyUsageReport) -> str:
    """Render the weekly usage report as a compact HTML email."""
    status_html = " ".join(
        _status_badge(status, count) for status, count in sorted(report.status_counts.items())
    )
    if not status_html:
        status_html = '<span class="muted">No reviews in this window</span>'

    if report.active_users:
        user_rows = "\n".join(
            "<tr>"
            f"<td>{escape(usage.label)}</td>"
            f"<td>{usage.count}</td>"
            f"<td>{usage.completed}</td>"
            f"<td>{usage.failed}</td>"
            f"<td>{usage.processing}</td>"
            f"<td>{escape(_duration_label(usage.total_video_seconds))}</td>"
            f"<td>{usage.feedback_count}</td>"
            "</tr>"
            for usage in report.active_users
        )
    else:
        user_rows = '<tr><td colspan="7" class="muted">No active users in this window.</td></tr>'

    if report.feedback_items:
        feedback_items = "\n".join(
            "<li>"
            f"<strong>{item.created_at:%Y-%m-%d}</strong> - "
            f"{escape(item.user_label)} - {escape(item.video_filename)} "
            f'<span class="badge muted">{escape(item.rating or "-")}</span>'
            f"{f'<p>{escape(item.notes.strip())}</p>' if item.notes else ''}"
            f"{f'<a href="{escape(item.url)}">Open review</a>' if item.url else ''}"
            "</li>"
            for item in report.feedback_items
        )
    else:
        feedback_items = '<li class="muted">No feedback received in this window.</li>'

    return f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <style>
      body {{ font-family: Arial, sans-serif; color: #20242a; line-height: 1.45; }}
      .container {{ max-width: 760px; margin: 0 auto; padding: 24px; }}
      h1 {{ font-size: 22px; margin: 0 0 4px; }}
      h2 {{ font-size: 16px; margin: 28px 0 10px; }}
      .muted {{ color: #687180; }}
      .summary {{ background: #f5f7fa; border: 1px solid #dfe5ec; padding: 14px; }}
      .badge {{
        display: inline-block;
        border-radius: 4px;
        padding: 2px 7px;
        margin: 2px;
        font-size: 12px;
      }}
      .ok {{ background: #e9f7ef; color: #166534; }}
      .bad {{ background: #fdecec; color: #991b1b; }}
      table {{ border-collapse: collapse; width: 100%; }}
      th, td {{
        border-bottom: 1px solid #e5e7eb;
        padding: 8px;
        text-align: left;
        vertical-align: top;
      }}
      th {{ background: #f8fafc; font-size: 12px; color: #526071; text-transform: uppercase; }}
      ul {{ padding-left: 20px; }}
      li {{ margin-bottom: 12px; }}
      a {{ color: #0b63ce; }}
    </style>
  </head>
  <body>
    <div class="container">
      <h1>scoutVISION Sandbox Weekly Usage Report</h1>
      <div class="muted">
        {report.start_at:%Y-%m-%d %H:%M UTC} to {report.end_at:%Y-%m-%d %H:%M UTC}
      </div>

      <div class="summary">
        <strong>Total reviews:</strong> {report.total_runs}<br>
        <strong>Statuses:</strong> {status_html}
      </div>

      <h2>Active Users</h2>
      <table>
        <thead>
          <tr>
            <th>User</th>
            <th>Reviews</th>
            <th>Completed</th>
            <th>Failed</th>
            <th>Other</th>
            <th>Video</th>
            <th>Feedback</th>
          </tr>
        </thead>
        <tbody>
          {user_rows}
        </tbody>
      </table>

      <h2>Feedback Received</h2>
      <ul>
        {feedback_items}
      </ul>
    </div>
  </body>
</html>"""


def report_subject(report: WeeklyUsageReport) -> str:
    """Return the default weekly report email subject."""
    return f"scoutVISION Sandbox weekly usage - {report.end_at:%Y-%m-%d}"
