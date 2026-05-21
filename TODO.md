# TODO

## User Accounts And Access

- [x] Add simple email/password auth with Flask sessions.
- [x] Add user model.
- [x] Associate prompt reviews with users.
- [x] Add logout and current-user display.
- [x] Scope normal users to their own reviews.
- [x] Keep admin able to view all reviews.
- [x] Add open tester signup.
- [x] Add admin-only user list.
- [ ] Track and show Last Login on the admin user list.
- [ ] Add admin-only create-user form.
- [ ] Add admin-only password reset.
- [ ] Add admin-only activate/deactivate user control.
- [ ] Decide whether open signup should stay enabled for deployed beta.
- [x] Add "contact admin to reset password" copy on login page.
- [ ] Add change-password page for logged-in users.

## UI/UX Polish

- [x] Improve form labels and helper text.
- [x] Rename "Coach ask" to something clearer, such as "What do you want Gemini to focus on?"
- [x] Add better empty states for recent reviews and response.
- [ ] Add clearer status messages for upload, validation, Gemini upload, Gemini processing, done, and failed.
- [x] Improve top navigation spacing, labels, and admin/user controls.
- [x] Make recent reviews easier to scan with clearer titles, metadata, and spacing.
- [x] Reduce visual weight of completed progress bars in recent reviews.
- [x] Show owner/status/feedback metadata as quiet labels instead of dense inline text.
- [x] Add "Copy response" button.
- [x] Add "Download response" button.
- [ ] Add "Review again with a new prompt" flow.
- [x] Add clearer feedback labels, such as "Was this useful?" and "What should be improved?"
- [x] Show artifact availability or path after completion.
- [ ] Add timestamps in a friendlier format.
- [ ] Add a compact recent reviews table once there are many reviews.

## Prompt Iteration

- [ ] Add output mode selector: general evaluation, SWOT, position fit, follow-up questions.
- [ ] Add editable advanced boilerplate prompt section.
- [ ] Add prompt version field to review metadata.
- [ ] Add side-by-side comparison for multiple reviews on the same video.

## Storage And Cleanup

- [ ] Decide whether DB stores full prompts/responses long-term or only artifact paths.
- [ ] Add cleanup command for old uploads/artifacts.
- [ ] Add configurable retention policy.
- [ ] Make uploaded-video retention clear in the UI/admin docs.

## Database And Architecture

- [ ] Consider migrating from plain SQLAlchemy to Flask-SQLAlchemy if app/request integration becomes more useful than explicit sessions.
- [ ] Consider Postgres, likely AWS RDS, when the app moves beyond local sandbox usage.
- [ ] Keep large video/artifact storage outside the relational database.
- [ ] Consider S3 or another object store for uploaded videos and output artifacts when deployed.

## Future

- [ ] Google login or OAuth.
- [ ] Real background queue if usage grows.
- [ ] Deployment plan and environment checklist.
- [ ] Basic audit log for admin/user actions.
