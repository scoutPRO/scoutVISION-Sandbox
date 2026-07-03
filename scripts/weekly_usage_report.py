"""Send the weekly scoutVISION Sandbox usage report."""

from __future__ import annotations

import argparse

from database import ensure_storage
from lib.email import send_email
from lib.weekly_report import (
    build_weekly_usage_report,
    render_weekly_usage_report,
    render_weekly_usage_report_html,
    report_subject,
)
from settings import WEEKLY_REPORT_DAYS, WEEKLY_REPORT_RECIPIENTS


def parse_recipients(value: str | None) -> list[str]:
    """Parse comma-separated recipients from CLI input."""
    if not value:
        return list(WEEKLY_REPORT_RECIPIENTS)
    return [item.strip() for item in value.split(",") if item.strip()]


def main() -> int:
    """Build and optionally send the weekly report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days",
        type=int,
        default=WEEKLY_REPORT_DAYS,
        help="Number of trailing days to include.",
    )
    parser.add_argument(
        "--to",
        default=None,
        help="Comma-separated recipient list. Defaults to WEEKLY_REPORT_RECIPIENTS.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the report without sending email.",
    )
    args = parser.parse_args()

    ensure_storage()
    report = build_weekly_usage_report(days=args.days)
    body = render_weekly_usage_report(report)
    html = render_weekly_usage_report_html(report)
    subject = report_subject(report)

    if args.dry_run:
        print(f"Subject: {subject}\n")
        print(body)
        return 0

    recipients = parse_recipients(args.to)
    send_email(subject=subject, text=body, html=html, to=recipients)
    print(f"Sent weekly usage report to {', '.join(recipients)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
