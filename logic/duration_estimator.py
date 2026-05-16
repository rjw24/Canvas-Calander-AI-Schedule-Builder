import base64
import hashlib
import json
import math
import os
import re
import secrets
from dataclasses import dataclass
from typing import Any, Dict, Optional

import requests


NRP_LLM_BASE_URL = "https://ellm.nrp-nautilus.io/v1"
DEFAULT_NRP_MODEL = "gpt-oss"
NRP_ENDPOINT_OPTIONS = [
    {
        "label": "NRP Managed LLM - Envoy gateway",
        "base_url": NRP_LLM_BASE_URL,
        "help": "Default OpenAI-compatible endpoint for NRP-managed LLMs.",
    },
]
NRP_CHAT_MODEL_OPTIONS = [
    {
        "id": "gpt-oss",
        "label": "gpt-oss - stable text reasoning, recommended",
        "help": "Good default for reproducible general-purpose text estimates.",
    },
    {
        "id": "qwen3-small",
        "label": "qwen3-small - faster long-context reasoning",
        "help": "Lower-latency option when the full qwen3 model is unnecessary.",
    },
    {
        "id": "qwen3",
        "label": "qwen3 - strongest frontier reasoning",
        "help": "Highest-capability option, usually slower than smaller models.",
    },
    {
        "id": "gemma",
        "label": "gemma - general multimodal model",
        "help": "Main supported Gemma model; fine for text, though this app does not use media inputs.",
    },
    {
        "id": "gemma-small",
        "label": "gemma-small - lightweight evaluating model",
        "help": "Fast, low-cost option; availability may change while evaluating.",
    },
    {
        "id": "kimi",
        "label": "kimi - agentic coding/evaluating",
        "help": "Large model tuned for coding workflows; overkill for most duration estimates.",
    },
    {
        "id": "glm-5",
        "label": "glm-5 - long-form reasoning/evaluating",
        "help": "Strong text model; availability may change while evaluating.",
    },
    {
        "id": "minimax-m2",
        "label": "minimax-m2 - efficient reasoning/evaluating",
        "help": "Good throughput for larger reasoning tasks; availability may change.",
    },
    {
        "id": "olmo",
        "label": "olmo - open/auditable evaluating model",
        "help": "Smaller open model; useful when auditable weights matter.",
    },
]


class DurationEstimateError(Exception):
    """Raised when the LLM estimate cannot be fetched or parsed."""


def new_cache_salt() -> str:
    return base64.b64encode(secrets.token_bytes(32)).decode("ascii")


def _float_or_default(value, default=0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clean_prompt_text(value: Any, max_chars: int = 6000) -> str:
    text = "" if value is None else str(value)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > max_chars:
        return text[:max_chars].rsplit(" ", 1)[0] + "\n[truncated]"
    return text


def _bounded_minutes(value: Any, default: int = 60) -> int:
    minutes = _float_or_default(value, default=default)
    minutes = max(15, min(minutes, 720))
    return int(math.ceil(minutes / 15) * 15)


def _bounded_confidence(value: Any, default: float = 0.5) -> float:
    confidence = _float_or_default(value, default=default)
    return max(0.0, min(confidence, 1.0))


def _as_list(value: Any) -> list:
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _rubric_points_possible(value: Any) -> Optional[float]:
    if not isinstance(value, dict):
        return None
    points = value.get("points_possible") or value.get("points")
    if points is None:
        return None
    return _float_or_default(points, default=0)


def assignment_estimate_cache_key(assignment: Dict[str, Any]) -> str:
    material = {
        "name": assignment.get("name") or assignment.get("title"),
        "course_name": assignment.get("course_name") or assignment.get("context"),
        "due_at": assignment.get("due_at"),
        "points": assignment.get("points"),
        "group_weight": assignment.get("group_weight"),
        "instructions": assignment.get("instructions") or assignment.get("description"),
        "submission_types": assignment.get("submission_types"),
        "allowed_extensions": assignment.get("allowed_extensions"),
        "grading_type": assignment.get("grading_type"),
        "allowed_attempts": assignment.get("allowed_attempts"),
        "peer_reviews": assignment.get("peer_reviews"),
        "peer_review_count": assignment.get("peer_review_count"),
        "use_rubric_for_grading": assignment.get("use_rubric_for_grading"),
        "rubric_settings": assignment.get("rubric_settings"),
        "group_category_id": assignment.get("group_category_id"),
        "grade_group_students_individually": assignment.get("grade_group_students_individually"),
        "external_tool_tag_attributes": assignment.get("external_tool_tag_attributes"),
    }
    encoded = json.dumps(material, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def heuristic_assignment_duration(assignment: Dict[str, Any]) -> Dict[str, Any]:
    title = str(assignment.get("name") or assignment.get("title") or "").lower()
    instructions = str(assignment.get("instructions") or assignment.get("description") or "")
    combined = f"{title} {instructions}".lower()
    points = _float_or_default(assignment.get("points"), default=0)
    group_weight = max(_float_or_default(assignment.get("group_weight"), default=1.0), 0.01)
    weighted_points = points * group_weight
    submission_types = {str(item).lower() for item in _as_list(assignment.get("submission_types"))}
    allowed_extensions = {str(item).lower() for item in _as_list(assignment.get("allowed_extensions"))}

    minutes = 45

    if weighted_points >= 75:
        minutes += 75
    elif weighted_points >= 35:
        minutes += 45
    elif weighted_points >= 10:
        minutes += 30

    keyword_adjustments = [
        (("project", "portfolio", "presentation", "final"), 150),
        (("essay", "paper", "report", "research", "write"), 120),
        (("programming", "code", "coding", "lab", "problem set", "homework"), 90),
        (("quiz", "discussion", "reflection", "reading"), 30),
    ]
    for keywords, adjustment in keyword_adjustments:
        if any(keyword in combined for keyword in keywords):
            minutes += adjustment
            break

    if {"online_upload", "student_annotation"} & submission_types:
        minutes += 45
    if {"discussion_topic"} & submission_types:
        minutes += 30
    if {"online_quiz"} & submission_types:
        minutes += 30
    if {"ppt", "pptx", "pdf", "doc", "docx", "zip", "py", "java", "ipynb"} & allowed_extensions:
        minutes += 30
    if assignment.get("peer_reviews") or assignment.get("peer_review_count"):
        minutes += 30
    if assignment.get("group_category_id") and assignment.get("grade_group_students_individually") is False:
        minutes += 45

    return {
        "estimated_minutes": _bounded_minutes(minutes),
        "confidence": 0.35,
        "method": "heuristic",
        "rationale": "Fallback estimate from title/instruction cues, submission type, and points adjusted by gradebook weight.",
    }


def _extract_json_object(text: str) -> Dict[str, Any]:
    decoder = json.JSONDecoder()
    content = text.strip()
    if content.startswith("```"):
        content = re.sub(r"^```(?:json)?", "", content).strip()
        content = re.sub(r"```$", "", content).strip()

    for index, char in enumerate(content):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(content[index:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue

    raise DurationEstimateError("The LLM response did not contain a JSON object.")


@dataclass
class LLMDurationEstimator:
    token: Optional[str] = None
    base_url: str = NRP_LLM_BASE_URL
    model: str = DEFAULT_NRP_MODEL
    timeout_seconds: int = 45
    cache_salt: Optional[str] = None

    def __post_init__(self):
        self.token = (
            self.token
            or os.environ.get("NRP_LLM_TOKEN")
            or os.environ.get("OPENAI_API_KEY")
        )
        self.base_url = (self.base_url or NRP_LLM_BASE_URL).rstrip("/")
        self.model = self.model or DEFAULT_NRP_MODEL
        if not self.token:
            raise DurationEstimateError("No NRP LLM token was provided.")

    def estimate_assignment_minutes(self, assignment: Dict[str, Any]) -> Dict[str, Any]:
        fallback = heuristic_assignment_duration(assignment)
        payload = {
            "model": self.model,
            "temperature": 0.1,
            "messages": self._messages(assignment, fallback),
        }
        if self.cache_salt:
            payload["cache_salt"] = self.cache_salt

        try:
            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.token}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except requests.RequestException as exc:
            raise DurationEstimateError(f"LLM request failed: {exc}") from exc
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise DurationEstimateError("LLM response had an unexpected shape.") from exc

        parsed = _extract_json_object(content)
        return {
            "estimated_minutes": _bounded_minutes(
                parsed.get("estimated_minutes"),
                default=fallback["estimated_minutes"],
            ),
            "confidence": _bounded_confidence(parsed.get("confidence"), default=0.5),
            "method": "llm",
            "model": self.model,
            "rationale": _clean_prompt_text(
                parsed.get("rationale") or parsed.get("reasoning") or fallback["rationale"],
                max_chars=500,
            ),
        }

    def _messages(self, assignment: Dict[str, Any], fallback: Dict[str, Any]):
        instructions = _clean_prompt_text(
            assignment.get("instructions") or assignment.get("description"),
            max_chars=6000,
        )
        user_prompt = {
            "assignment": assignment.get("name") or assignment.get("title") or "Untitled",
            "course": assignment.get("course_name") or assignment.get("context") or "Unknown",
            "due_at": str(assignment.get("due_at") or ""),
            "points": assignment.get("points"),
            "assignment_group": assignment.get("assignment_group_name"),
            "assignment_group_weight": assignment.get("group_weight"),
            "grading_type": assignment.get("grading_type"),
            "submission_types": assignment.get("submission_types"),
            "allowed_extensions": assignment.get("allowed_extensions"),
            "allowed_attempts": assignment.get("allowed_attempts"),
            "availability": {
                "unlock_at": assignment.get("unlock_at"),
                "lock_at": assignment.get("lock_at"),
            },
            "peer_reviews": {
                "required": assignment.get("peer_reviews"),
                "automatic": assignment.get("automatic_peer_reviews"),
                "count": assignment.get("peer_review_count"),
            },
            "rubric": {
                "used_for_grading": assignment.get("use_rubric_for_grading"),
                "points_possible": _rubric_points_possible(assignment.get("rubric_settings")),
                "criterion_count": len(_as_list(assignment.get("rubric"))),
            },
            "group_assignment": {
                "group_category_id": assignment.get("group_category_id"),
                "grade_group_students_individually": assignment.get("grade_group_students_individually"),
            },
            "external_tool": assignment.get("external_tool_tag_attributes"),
            "heuristic_minutes": fallback["estimated_minutes"],
            "canvas_instructions": instructions or "No Canvas instructions were provided.",
        }

        return [
            {
                "role": "system",
                "content": (
                    "You estimate how long a college assignment will take a student. "
                    "Return valid JSON only. Do not include markdown. Estimate active work time "
                    "in minutes, including reading instructions, researching, drafting, coding, "
                    "checking requirements, and submitting. Exclude class meeting time."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Estimate this assignment's required work time. Use Canvas instructions as "
                    "the main evidence, but do not infer effort from instruction word count. "
                    "Use submission type, required uploads/extensions, rubric, peer reviews, "
                    "group-work flags, attempts, due/availability dates, and external tool data "
                    "when available. Treat assignment group name as low-signal label text; "
                    "assignment group weight is the useful gradebook context for balancing point "
                    "differences between courses. If instructions are missing or vague, make a "
                    "conservative estimate and lower the confidence.\n\n"
                    f"{json.dumps(user_prompt, indent=2, default=str)}\n\n"
                    "Return exactly this JSON shape:\n"
                    "{"
                    "\"estimated_minutes\": integer, "
                    "\"confidence\": number_between_0_and_1, "
                    "\"rationale\": \"brief reason\""
                    "}"
                ),
            },
        ]
