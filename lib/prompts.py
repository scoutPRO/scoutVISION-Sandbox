"""Prompt presets and prompt display helpers."""

import json
import re

from settings import DEFAULT_MODEL, GEMINI_MODELS, PROMPT_PATH

DEFAULT_USER_PROMPT = "Identify what a coach should notice first about this recruit."
USER_PROMPT_SECTION_LABELS = {
    "PLAYER TO FOCUS ON": "Player to Focus On",
    "EVALUATION REQUEST": "Evaluation Request",
}
USER_PROMPT_SECTION_RE = re.compile(
    r"(PLAYER TO FOCUS ON|EVALUATION REQUEST):\s*",
    re.IGNORECASE,
)
OUTPUT_MODES = {
    "general": {
        "label": "General Review",
        "instruction": (
            "Provide a balanced coach-facing review with summary, strengths, concerns, "
            "notable moments, follow-up questions, and fit signals.\n\n"
            "Return JSON with this shape:\n"
            "{\n"
            '  "summary": "short coach-facing summary",\n'
            '  "strengths": ["specific strengths visible in the reel"],\n'
            '  "concerns_or_unknowns": ['
            '"limitations, unclear signals, or things the video does not prove"'
            "],\n"
            '  "notable_moments": [\n'
            "    {\n"
            '      "timestamp": "mm:ss",\n'
            '      "observation": "what happened",\n'
            '      "why_it_matters": "why a coach might care"\n'
            "    }\n"
            "  ],\n"
            '  "coach_follow_up_questions": ["questions the coach should ask or verify"],\n'
            '  "fit_signals": ['
            '"signals related to role, athletic traits, decision making, effort, or coachability"'
            "]\n"
            "}"
        ),
    },
    "swot": {
        "label": "SWOT",
        "instruction": (
            "Frame the response as a SWOT review: strengths, weaknesses, opportunities, "
            "and threats or risks. Use only evidence visible in the video.\n\n"
            "Return JSON with this shape:\n"
            "{\n"
            '  "summary": "short coach-facing SWOT summary",\n'
            '  "strengths": ["visible strengths or advantages"],\n'
            '  "weaknesses": ["visible limitations or underdeveloped areas"],\n'
            '  "opportunities": ["ways the player could be used, developed, or evaluated"],\n'
            '  "threats": ["risks, unknowns, or reasons to request more evidence"],\n'
            '  "coach_follow_up_questions": ["questions to ask after watching the reel"]\n'
            "}"
        ),
    },
    "position_fit": {
        "label": "Position Fit",
        "instruction": (
            "Focus on position fit, likely role, transferable skills, and what additional "
            "film a coach would need before making a roster decision.\n\n"
            "Return JSON with this shape:\n"
            "{\n"
            '  "summary": "short position-fit summary",\n'
            '  "best_fit_positions": ["positions or roles that fit the visible traits"],\n'
            '  "role_projection": "how the player might be used by a team",\n'
            '  "supporting_evidence": [\n'
            "    {\n"
            '      "timestamp": "mm:ss",\n'
            '      "observation": "visible evidence for the fit",\n'
            '      "fit_signal": "trait, role, or skill shown"\n'
            "    }\n"
            "  ],\n"
            '  "concerns_or_unknowns": ["fit-related unknowns or missing evidence"],\n'
            '  "additional_film_to_request": ["specific clips a coach should ask for"]\n'
            "}"
        ),
    },
    "follow_up_questions": {
        "label": "Follow-Up Questions",
        "instruction": (
            "Focus on practical follow-up questions a coach should ask the player, "
            "club/team, or recruiting contact after watching this reel.\n\n"
            "Return JSON with this shape:\n"
            "{\n"
            '  "summary": "short summary of what the reel shows and does not prove",\n'
            '  "questions_for_player": ["questions to ask the player directly"],\n'
            '  "questions_for_coach_or_team": ["questions for a coach, club, or team contact"],\n'
            '  "film_to_request": ["specific extra film or situations to request"],\n'
            '  "verification_items": ["claims, context, or traits to verify"]\n'
            "}"
        ),
    },
}


def load_boilerplate_prompt() -> str:
    """Load the coach-facing boilerplate prompt from disk."""
    return PROMPT_PATH.read_text(encoding="utf-8").strip()


def parse_response_json(response_json: str | None) -> dict | list | None:
    """Parse the stored Gemini response JSON for structured display."""
    if not response_json:
        return None
    try:
        return json.loads(response_json)
    except json.JSONDecodeError:
        return None


def build_full_prompt(boilerplate_prompt: str, output_mode: str, user_prompt: str) -> str:
    """Build the complete prompt sent to Gemini for one review."""
    output_mode_instruction = OUTPUT_MODES[output_mode]["instruction"]
    return (
        f"{boilerplate_prompt}\n\n"
        f"OUTPUT MODE:\n{output_mode_instruction}\n\n"
        f"USER REQUEST:\n{user_prompt}"
    )


def review_type_label_from_prompt(full_prompt: str) -> str:
    """Return the review type label represented by a stored full prompt."""
    for mode_meta in OUTPUT_MODES.values():
        if mode_meta["instruction"] in full_prompt:
            return mode_meta["label"]
    return "Unknown"


def user_prompt_display_sections(user_prompt: str | None) -> list[dict[str, str]]:
    """Return user prompt sections with friendly labels for display."""
    if not user_prompt:
        return []

    cleaned_prompt = user_prompt.strip()
    matches = list(USER_PROMPT_SECTION_RE.finditer(cleaned_prompt))
    if not matches:
        return [{"label": "", "text": cleaned_prompt}]

    sections = []
    leading_text = cleaned_prompt[: matches[0].start()].strip()
    if leading_text:
        sections.append({"label": "", "text": leading_text})

    for index, match in enumerate(matches):
        text_start = match.end()
        text_end = matches[index + 1].start() if index + 1 < len(matches) else None
        text = cleaned_prompt[text_start:text_end].strip()
        if not text:
            continue
        label = USER_PROMPT_SECTION_LABELS[match.group(1).upper()]
        sections.append({"label": label, "text": text})

    return sections


def user_prompt_section_text(user_prompt: str | None, label: str) -> str:
    """Return one parsed user prompt section value by friendly label."""
    for section in user_prompt_display_sections(user_prompt):
        if section["label"] == label:
            return section["text"]
    return ""


def validate_review_settings(
    output_mode: str,
    model: str = DEFAULT_MODEL,
) -> str | None:
    """Return a validation error for submitted review settings, if any."""
    if output_mode not in OUTPUT_MODES:
        return "Choose one of the available output modes."
    if model not in GEMINI_MODELS:
        return "Choose one of the available Gemini models."
    return None


def build_api_user_prompt(player_focus: str, evaluation_request: str) -> str:
    """Build the user prompt from scoutSMART API form fields."""
    sections = []
    if player_focus:
        sections.append(f"PLAYER TO FOCUS ON: {player_focus}")
    sections.append(f"EVALUATION REQUEST: {evaluation_request or DEFAULT_USER_PROMPT}")
    return "\n\n".join(sections)
