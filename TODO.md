# TODO

## V1 This Week

- Add simple email/password auth with Flask sessions. [done in first pass]
- Add user model and associate prompt runs with users. [done in first pass]
- Add admin role for viewing all runs and managing users. [partial: admin can view all runs]
- Add create-user or invite flow for early testers. [partial: open tester signup exists]
- Add logout and current-user display.
- Scope normal users to their own runs.
- Keep admin able to view all runs.

## UX Polish

- Improve form labels and helper text.
- Rename "Coach ask" to something clearer, such as "What do you want Gemini to focus on?"
- Add better empty states for recent runs and response.
- Add clearer status messages for upload, validation, Gemini upload, Gemini processing, done, and failed.
- Add "Copy response" button.
- Add "Run another prompt on this video" flow.
- Add clearer feedback labels, such as "Was this useful?" and "What should be improved?"
- Show artifact availability or path after completion.
- Add timestamps in a friendlier format.
- Add a compact recent-runs table once there are many runs.

## Prompt Iteration

- Add output mode selector: general evaluation, SWOT, position fit, follow-up questions.
- Add editable advanced boilerplate prompt section.
- Add prompt version field to run metadata.
- Add side-by-side comparison for multiple runs on the same video.

## Storage And Cleanup

- Decide whether DB stores full prompts/responses long-term or only artifact paths.
- Add cleanup command for old uploads/artifacts.
- Add configurable retention policy.
- Make uploaded-video retention clear in the UI/admin docs.

## Database And Architecture

- Consider migrating from plain SQLAlchemy to Flask-SQLAlchemy if app/request integration becomes more useful than explicit sessions.
- Consider Postgres, likely AWS RDS, when the app moves beyond local sandbox usage.
- Keep large video/artifact storage outside the relational database.
- Consider S3 or another object store for uploaded videos and output artifacts when deployed.

## Future

- Google login or OAuth.
- Real background queue if usage grows.
- Deployment plan and environment checklist.
- Basic audit log for admin/user actions.
