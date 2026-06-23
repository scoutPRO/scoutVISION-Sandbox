"""Flask-RESTX routes for the scoutSMART evaluation API."""

import uuid

from flask import request, url_for
from flask_restx import Api, Resource, fields, reqparse
from werkzeug.datastructures import FileStorage
from werkzeug.utils import secure_filename

from lib.prompt_runs import find_run
from lib.prompts import build_api_user_prompt, validate_review_settings
from lib.reviews import api_evaluation_payload, create_queued_review
from lib.video import allowed_video, delete_video
from settings import DEFAULT_MODEL, SCOUTSMART_API_KEY, UPLOAD_DIR


def validate_api_key() -> tuple[dict[str, str], int] | None:
    """Return an API auth error when a shared scoutSMART API key is configured."""
    if not SCOUTSMART_API_KEY:
        return None

    supplied_key = request.headers.get("X-API-Key", "")
    if supplied_key != SCOUTSMART_API_KEY:
        return {"error": "Invalid or missing API key.", "status": "failed"}, 401
    return None


def register_evaluation_api(api: Api) -> None:
    """Register scoutSMART evaluation API routes on a Flask-RESTX API."""
    evaluation_ns = api.namespace(
        "api/v1",
        description="Video evaluation endpoints.",
    )

    evaluation_upload_parser = reqparse.RequestParser()
    evaluation_upload_parser.add_argument(
        "video",
        type=FileStorage,
        location="files",
        required=True,
        help="Video file to evaluate.",
    )
    evaluation_upload_parser.add_argument(
        "account_id",
        location="form",
        required=True,
        help="scoutSMART account identifier for attribution.",
    )
    evaluation_upload_parser.add_argument(
        "user_id",
        location="form",
        required=False,
        help="Optional scoutSMART user identifier for attribution.",
    )
    evaluation_upload_parser.add_argument(
        "review_type",
        location="form",
        required=False,
        default="general",
        help="Review type. One of: general, swot, position_fit, follow_up_questions.",
    )
    evaluation_upload_parser.add_argument(
        "player_focus",
        location="form",
        required=False,
        help="Optional description of the player Gemini should focus on.",
    )
    evaluation_upload_parser.add_argument(
        "evaluation_request",
        location="form",
        required=False,
        help="Optional coaching/evaluation instruction.",
    )
    evaluation_response_model = evaluation_ns.model(
        "EvaluationResponse",
        {
            "evaluation_id": fields.String,
            "status": fields.String,
            "review_type": fields.String,
            "video_filename": fields.String,
            "video_duration_seconds": fields.Float,
            "created_at": fields.String,
            "error": fields.String,
            "result": fields.Raw,
            "response_text": fields.String,
            "usage": fields.Raw,
        },
    )
    evaluation_accepted_model = evaluation_ns.model(
        "EvaluationAccepted",
        {
            "evaluation_id": fields.String,
            "status": fields.String,
            "status_url": fields.String,
        },
    )
    evaluation_error_model = evaluation_ns.model(
        "EvaluationError",
        {
            "evaluation_id": fields.String,
            "error": fields.String,
            "status": fields.String,
        },
    )

    @evaluation_ns.route("/evaluations")
    @evaluation_ns.doc(security="ApiKeyAuth")
    class EvaluationResource(Resource):
        """Create a scoutSMART video evaluation."""

        @evaluation_ns.expect(evaluation_upload_parser)
        @evaluation_ns.response(202, "Evaluation queued.", evaluation_accepted_model)
        @evaluation_ns.response(400, "Invalid request.", evaluation_error_model)
        @evaluation_ns.response(401, "Unauthorized.", evaluation_error_model)
        def post(self):
            """Upload one video and queue an asynchronous Gemini evaluation."""
            auth_error = validate_api_key()
            if auth_error is not None:
                return auth_error

            video = request.files.get("video")
            if not video or not video.filename:
                return {"error": "Upload a video file.", "status": "failed"}, 400
            if not allowed_video(video.filename):
                return {"error": "Unsupported video file type.", "status": "failed"}, 400

            account_id = request.form.get("account_id", "").strip()
            if not account_id:
                return {"error": "account_id is required.", "status": "failed"}, 400

            run_id = str(uuid.uuid4())
            safe_name = secure_filename(video.filename)
            stored_path = UPLOAD_DIR / f"{run_id}_{safe_name}"
            video.save(stored_path)

            output_mode = request.form.get("review_type", "general").strip() or "general"
            error = validate_review_settings(output_mode, DEFAULT_MODEL)
            if error:
                delete_video(stored_path)
                return {"evaluation_id": run_id, "error": error, "status": "failed"}, 400

            user_prompt = build_api_user_prompt(
                request.form.get("player_focus", "").strip(),
                request.form.get("evaluation_request", "").strip(),
            )
            review = create_queued_review(
                run_id=run_id,
                user_id=None,
                video_filename=video.filename,
                stored_path=stored_path,
                model=DEFAULT_MODEL,
                user_prompt=user_prompt,
                output_mode=output_mode,
                external_account_id=account_id,
                external_user_id=request.form.get("user_id", "").strip() or None,
                integration_source="scoutsmart_api",
            )

            return {
                "evaluation_id": review.id,
                "status": review.status,
                "status_url": url_for(
                    "api/v1_evaluation_status_resource",
                    evaluation_id=review.id,
                ),
            }, 202

    @evaluation_ns.route("/evaluations/<string:evaluation_id>")
    @evaluation_ns.doc(security="ApiKeyAuth")
    class EvaluationStatusResource(Resource):
        """Return status and result for a scoutSMART video evaluation."""

        @evaluation_ns.response(200, "Evaluation status.", evaluation_response_model)
        @evaluation_ns.response(401, "Unauthorized.", evaluation_error_model)
        @evaluation_ns.response(404, "Evaluation not found.", evaluation_error_model)
        def get(self, evaluation_id: str):
            """Return one queued, processing, completed, or failed evaluation."""
            auth_error = validate_api_key()
            if auth_error is not None:
                return auth_error

            run = find_run(evaluation_id)
            if run is None or run.integration_source != "scoutsmart_api":
                return {
                    "evaluation_id": evaluation_id,
                    "error": "Evaluation not found.",
                    "status": "failed",
                }, 404
            return api_evaluation_payload(run)
