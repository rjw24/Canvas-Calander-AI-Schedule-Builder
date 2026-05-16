import streamlit as st
from data.canvas_client import CanvasInterface
from logic.scheduler import SmartScheduler, infer_can_split
from logic.duration_estimator import (
    DEFAULT_NRP_MODEL,
    DurationEstimateError,
    LLMDurationEstimator,
    NRP_CHAT_MODEL_OPTIONS,
    NRP_ENDPOINT_OPTIONS,
    NRP_LLM_BASE_URL,
    assignment_estimate_cache_key,
    heuristic_assignment_duration,
    new_cache_salt,
)
from datetime import datetime, timedelta
from Dashboard import ViewDashboard
import os

CANVAS_BASE_URL = "https://csufullerton.instructure.com"
WEEKDAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DEFAULT_SCHEDULE_SETTINGS = {
    "study_start_hour": SmartScheduler.STUDY_HOURS_START,
    "study_end_hour": SmartScheduler.STUDY_HOURS_END,
    "days_ahead": SmartScheduler.DAYS_AHEAD,
    "min_block_minutes": SmartScheduler.MIN_SESSION_DURATION_MINUTES,
    "max_block_minutes": SmartScheduler.SESSION_DURATION_MINUTES,
    "buffer_minutes": SmartScheduler.BUFFER_MINUTES,
    "part_gap_minutes": SmartScheduler.PART_GAP_MINUTES,
}

st.set_page_config(page_title="Smart Canvas Planner", layout="wide")


def _parse_canvas_datetime(value):
    if isinstance(value, datetime):
        return value
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _scheduler_datetime(value):
    parsed = _parse_canvas_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is not None:
        return parsed.astimezone().replace(tzinfo=None)
    return parsed


def _number_or_default(value, default=1):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _weight_or_default(value, default=1):
    if value in (None, ""):
        return default

    text = str(value).strip()
    if text.endswith("%"):
        text = text[:-1]

    try:
        weight = float(text)
    except (TypeError, ValueError):
        return default

    if weight > 1:
        return weight / 100
    return weight


def _bool_or_default(value, default=True):
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    return bool(value)


def _parse_clock_time(value):
    text = str(value or "").strip()
    for date_format in ("%H:%M", "%I:%M %p", "%H"):
        try:
            return datetime.strptime(text, date_format).time()
        except ValueError:
            continue
    return None


def _parse_date(value, default):
    parsed = _scheduler_datetime(value)
    if parsed is None:
        return default
    return parsed.date()


def _blocked_row_matches_date(day_rule, date_value):
    weekday_name = WEEKDAY_NAMES[date_value.weekday()]
    if day_rule == "Every day":
        return True
    if day_rule == "Weekdays":
        return date_value.weekday() < 5
    if day_rule == "Weekends":
        return date_value.weekday() >= 5
    return day_rule == weekday_name


def _custom_blocked_events(raw_data, assignments):
    rows = st.session_state.get("custom_blocked_times", [])
    if not rows:
        return []

    now = datetime.now()
    start_date = _parse_date(raw_data.get("fetch_start"), now.date())
    due_dates = [assignment["due_at"].date() for assignment in assignments if assignment.get("due_at")]
    default_end = max(due_dates) if due_dates else (now + timedelta(days=14)).date()
    end_date = _parse_date(raw_data.get("fetch_end"), default_end)
    end_date = max(end_date, default_end)

    blocked = []
    day = start_date
    while day <= end_date:
        for row in rows:
            if not _bool_or_default(row.get("Include"), default=True):
                continue
            if not _blocked_row_matches_date(str(row.get("Day") or "Every day"), day):
                continue

            start_time = _parse_clock_time(row.get("Start"))
            end_time = _parse_clock_time(row.get("End"))
            if start_time is None or end_time is None:
                continue

            start_at = datetime.combine(day, start_time)
            end_at = datetime.combine(day, end_time)
            if end_at <= start_at:
                end_at += timedelta(days=1)
            blocked.append((start_at, end_at))
        day += timedelta(days=1)

    return blocked


def _canvas_event_id(event):
    if event is None:
        return None
    if isinstance(event, dict):
        return event.get("id")
    return getattr(event, "id", None)


def _schedule_window(schedule):
    starts = []
    ends = []

    for block in schedule or []:
        start = _scheduler_datetime(block.get("start_at"))
        end = _scheduler_datetime(block.get("end_at"))
        if start is not None:
            starts.append(start)
        if end is not None:
            ends.append(end)

    if starts and ends:
        return min(starts).date().isoformat(), max(ends).date().isoformat()

    now = datetime.now()
    return now.date().isoformat(), (now + timedelta(days=14)).date().isoformat()


def _build_scheduler_inputs(raw_data):
    assignments = []
    for assignment in raw_data.get("assignments", []):
        if not assignment.get("include", True):
            continue

        due_at = _scheduler_datetime(assignment.get("due_at") or assignment.get("start_at"))
        if due_at is None:
            continue

        course_name = (
            assignment.get("course_name")
            or assignment.get("context")
            or assignment.get("course")
            or "Unknown"
        )

        scheduler_assignment = {
            "name": assignment.get("title") or assignment.get("name") or "Untitled",
            "course_name": course_name,
            "due_at": due_at,
            "points": _number_or_default(assignment.get("points"), default=1),
            "group_weight": _weight_or_default(assignment.get("group_weight"), default=1),
            "assignment_group_name": assignment.get("assignment_group_name", "Unweighted"),
            "canvas_assignment_id": assignment.get("canvas_assignment_id"),
            "calendar_id": raw_data.get("personal_calendar_id"),
            "instructions": assignment.get("instructions") or assignment.get("description") or "",
            "can_split": _bool_or_default(assignment.get("can_split"), default=infer_can_split(assignment)),
        }
        for key in (
            "submission_types",
            "allowed_extensions",
            "grading_type",
            "allowed_attempts",
            "lock_at",
            "unlock_at",
            "peer_reviews",
            "automatic_peer_reviews",
            "peer_review_count",
            "use_rubric_for_grading",
            "rubric_settings",
            "rubric",
            "group_category_id",
            "grade_group_students_individually",
            "external_tool_tag_attributes",
        ):
            if key in assignment:
                scheduler_assignment[key] = assignment.get(key)

        assignments.append(scheduler_assignment)

    existing_events = []
    for event in raw_data.get("events", []):
        if not event.get("include", True):
            continue

        start = _scheduler_datetime(event.get("start") or event.get("start_at"))
        end = _scheduler_datetime(event.get("end") or event.get("end_at"))
        if start is not None and end is not None and end > start:
            existing_events.append((start, end))

    existing_events.extend(_custom_blocked_events(raw_data, assignments))

    return assignments, existing_events


def _apply_duration_estimate(assignment, estimate):
    assignment["estimated_minutes"] = estimate.get("estimated_minutes", 60)
    assignment["duration_confidence"] = estimate.get("confidence")
    assignment["duration_method"] = estimate.get("method", "heuristic")
    assignment["duration_rationale"] = estimate.get("rationale", "")
    if estimate.get("model"):
        assignment["duration_model"] = estimate.get("model")


def _llm_token_available():
    return bool(
        st.session_state.get("nrp_llm_token")
        or os.environ.get("NRP_LLM_TOKEN")
        or os.environ.get("OPENAI_API_KEY")
    )


def _estimate_assignment_durations(assignments):
    for assignment in assignments:
        _apply_duration_estimate(assignment, heuristic_assignment_duration(assignment))

    if not st.session_state.get("use_llm_duration_estimates", False):
        return

    if not _llm_token_available():
        st.warning("LLM duration estimates are enabled, but no NRP LLM token was provided. Using heuristic estimates.")
        return

    if "llm_duration_cache" not in st.session_state:
        st.session_state.llm_duration_cache = {}
    if "llm_cache_salt" not in st.session_state:
        st.session_state.llm_cache_salt = new_cache_salt()

    try:
        estimator = LLMDurationEstimator(
            token=st.session_state.get("nrp_llm_token"),
            base_url=st.session_state.get("nrp_llm_base_url", NRP_LLM_BASE_URL),
            model=st.session_state.get("nrp_llm_model", DEFAULT_NRP_MODEL),
            cache_salt=st.session_state.llm_cache_salt,
        )
    except DurationEstimateError as exc:
        st.warning(f"Could not initialize LLM duration estimator: {exc}")
        return

    failures = []
    progress = st.progress(0, text="Estimating assignment durations with the LLM...")
    total = len(assignments)

    for index, assignment in enumerate(assignments, start=1):
        cache_key = assignment_estimate_cache_key(assignment)
        estimate = st.session_state.llm_duration_cache.get(cache_key)

        if estimate is None:
            try:
                estimate = estimator.estimate_assignment_minutes(assignment)
                st.session_state.llm_duration_cache[cache_key] = estimate
            except DurationEstimateError as exc:
                failures.append(f"{assignment.get('name', 'Untitled')}: {exc}")
                estimate = heuristic_assignment_duration(assignment)

        _apply_duration_estimate(assignment, estimate)
        progress.progress(index / total, text=f"Estimated {index} of {total} assignments")

    progress.empty()

    if failures:
        st.warning(f"Used heuristic estimates for {len(failures)} assignment(s) because LLM estimation failed.")


def _select_option_index(options, value, key):
    for index, option in enumerate(options):
        if option.get(key) == value:
            return index
    return len(options)


def _render_llm_settings():
    st.text_input("NRP LLM Token", type="password", key="nrp_llm_token")

    endpoint_labels = [option["label"] for option in NRP_ENDPOINT_OPTIONS] + ["Custom OpenAI-compatible endpoint"]
    endpoint_index = _select_option_index(
        NRP_ENDPOINT_OPTIONS,
        st.session_state.get("nrp_llm_base_url", NRP_LLM_BASE_URL),
        "base_url",
    )
    endpoint_choice = st.selectbox(
        "LLM Endpoint",
        endpoint_labels,
        index=endpoint_index,
        key="nrp_llm_endpoint_choice",
    )
    if endpoint_choice == "Custom OpenAI-compatible endpoint":
        st.text_input("Custom Base URL", key="nrp_llm_base_url")
    else:
        selected_endpoint = NRP_ENDPOINT_OPTIONS[endpoint_labels.index(endpoint_choice)]
        st.session_state.nrp_llm_base_url = selected_endpoint["base_url"]
        st.caption(selected_endpoint["help"])

    model_labels = [option["label"] for option in NRP_CHAT_MODEL_OPTIONS] + ["Custom model ID"]
    model_index = _select_option_index(
        NRP_CHAT_MODEL_OPTIONS,
        st.session_state.get("nrp_llm_model", DEFAULT_NRP_MODEL),
        "id",
    )
    model_choice = st.selectbox(
        "NRP Model",
        model_labels,
        index=model_index,
        key="nrp_llm_model_choice",
    )
    if model_choice == "Custom model ID":
        st.text_input("Custom Model ID", key="nrp_llm_model")
    else:
        selected_model = NRP_CHAT_MODEL_OPTIONS[model_labels.index(model_choice)]
        st.session_state.nrp_llm_model = selected_model["id"]
        st.caption(selected_model["help"])


def run_optimizer():
    raw_data = st.session_state.get("raw_data")
    if not raw_data:
        st.warning("Fetch Canvas data before running the optimizer.")
        return

    assignments, existing_events = _build_scheduler_inputs(raw_data)
    if not assignments:
        st.session_state.processed_schedule = []
        st.warning("No assignments with due dates were available to schedule.")
        return

    _estimate_assignment_durations(assignments)

    try:
        schedule_settings = dict(DEFAULT_SCHEDULE_SETTINGS)
        schedule_settings.update(st.session_state.get("schedule_settings", {}))
        scheduler = SmartScheduler(
            assignments,
            existing_events,
            study_hours_start=schedule_settings.get("study_start_hour"),
            study_hours_end=schedule_settings.get("study_end_hour"),
            days_ahead=schedule_settings.get("days_ahead"),
            min_session_duration_minutes=schedule_settings.get("min_block_minutes"),
            max_session_duration_minutes=schedule_settings.get("max_block_minutes"),
            buffer_minutes=schedule_settings.get("buffer_minutes"),
            part_gap_minutes=schedule_settings.get("part_gap_minutes"),
        )
        st.session_state.processed_schedule = scheduler.generate_predictions()
        st.session_state.unscheduled_assignments = scheduler.unscheduled_assignments
        st.session_state.canvas_sync_result = None
    except Exception as exc:
        st.error(f"Could not generate the smart schedule: {exc}")
        return

    count = len(st.session_state.processed_schedule)
    if count:
        st.success(f"Generated {count} study block{'s' if count != 1 else ''}.")
    else:
        st.info("No open study blocks were found in the current schedule window.")
    if st.session_state.get("unscheduled_assignments"):
        st.warning(f"{len(st.session_state.unscheduled_assignments)} assignment(s) still have unscheduled estimated work.")


def push_study_blocks_to_canvas():
    ci = st.session_state.get("ci")
    raw_data = st.session_state.get("raw_data") or {}
    schedule = st.session_state.get("processed_schedule") or []

    if ci is None:
        st.error("Connect to Canvas before adding study blocks.")
        return
    if not schedule:
        st.warning("Run the optimizer before adding study blocks to Canvas.")
        return

    created = []
    failed = []
    skipped = 0

    for block in schedule:
        if block.get("pushed_canvas_event_id"):
            skipped += 1
            continue

        calendar_id = block.get("calendar_id") or raw_data.get("personal_calendar_id")
        try:
            event = ci.push_study_block(
                block.get("title", "study block"),
                block.get("start_at"),
                block.get("end_at"),
                calendar_id=calendar_id,
                description=block.get("description"),
            )
            event_id = _canvas_event_id(event)
            block["pushed_canvas_event_id"] = event_id
            created.append({
                "id": event_id,
                "title": block.get("title", "study block"),
            })
        except Exception as exc:
            failed.append({
                "title": block.get("title", "study block"),
                "error": str(exc),
            })

    st.session_state.canvas_sync_result = {
        "action": "add",
        "created": created,
        "failed": failed,
        "skipped": skipped,
    }

    if created:
        st.success(f"Added {len(created)} study block{'s' if len(created) != 1 else ''} to Canvas.")
    if skipped:
        st.info(f"Skipped {skipped} study block{'s' if skipped != 1 else ''} already added in this session.")
    if failed:
        st.error(f"Could not add {len(failed)} study block{'s' if len(failed) != 1 else ''}.")


def delete_study_blocks_from_canvas():
    ci = st.session_state.get("ci")
    raw_data = st.session_state.get("raw_data") or {}
    schedule = st.session_state.get("processed_schedule") or []

    if ci is None:
        st.error("Connect to Canvas before deleting study blocks.")
        return

    start_date, end_date = _schedule_window(schedule)
    calendar_id = raw_data.get("personal_calendar_id")

    try:
        result = ci.delete_generated_study_blocks(start_date, end_date, calendar_id=calendar_id)
    except Exception as exc:
        st.error(f"Could not delete study blocks from Canvas: {exc}")
        return

    for block in schedule:
        block.pop("pushed_canvas_event_id", None)

    deleted = result.get("deleted", [])
    failed = result.get("failed", [])

    st.session_state.canvas_sync_result = {
        "action": "delete",
        "deleted": deleted,
        "failed": failed,
        "window": (start_date, end_date),
    }

    if deleted:
        st.success(f"Deleted {len(deleted)} generated study block{'s' if len(deleted) != 1 else ''} from Canvas.")
    else:
        st.info("No generated study blocks were found in Canvas for the current schedule window.")
    if failed:
        st.error(f"Could not delete {len(failed)} study block{'s' if len(failed) != 1 else ''}.")


# --- 1. SESSION STATE INITIALIZATION ---
if 'authenticated' not in st.session_state:
    st.session_state.authenticated = False
if 'raw_data' not in st.session_state:
    st.session_state.raw_data = None
if 'processed_schedule' not in st.session_state:
    st.session_state.processed_schedule = None
if 'calendar_options' not in st.session_state:
    st.session_state.calendar_options = []
if 'raw_data_version' not in st.session_state:
    st.session_state.raw_data_version = 0
if 'canvas_sync_result' not in st.session_state:
    st.session_state.canvas_sync_result = None
if 'unscheduled_assignments' not in st.session_state:
    st.session_state.unscheduled_assignments = []
if 'use_llm_duration_estimates' not in st.session_state:
    st.session_state.use_llm_duration_estimates = False
if 'nrp_llm_base_url' not in st.session_state:
    st.session_state.nrp_llm_base_url = NRP_LLM_BASE_URL
if 'nrp_llm_model' not in st.session_state:
    st.session_state.nrp_llm_model = DEFAULT_NRP_MODEL
if 'schedule_settings' not in st.session_state:
    st.session_state.schedule_settings = dict(DEFAULT_SCHEDULE_SETTINGS)
if 'custom_blocked_times' not in st.session_state:
    st.session_state.custom_blocked_times = []

# --- 2. SIDEBAR: AUTHENTICATION ---
with st.sidebar:
    st.header("Authentication")
    user_token = st.text_input("Enter Canvas Manual Token", type="password")
    
    if st.button("Connect to Canvas"):
        if user_token:
            try:
                ci = CanvasInterface(user_token, CANVAS_BASE_URL)
                st.session_state.ci = ci
                st.session_state.calendar_options = ci.get_calendar_sources()
                st.session_state.authenticated = True
                st.session_state.raw_data = None
                st.session_state.processed_schedule = None
                st.session_state.unscheduled_assignments = []
                st.success("Connected! Now select your calendars.")
            except Exception as exc:
                st.session_state.authenticated = False
                st.error(f"Could not connect to Canvas: {exc}")
        else:
            st.warning("Enter a Canvas token before connecting.")

    st.divider()
    st.header("Duration Prediction")
    st.checkbox("Use NRP LLM duration estimates", key="use_llm_duration_estimates")
    if st.session_state.use_llm_duration_estimates:
        _render_llm_settings()

    # Only show the selection and fetch button IF authenticated
    if st.session_state.authenticated:
        st.divider()
        st.header("Calendar Selection")
        
        # Create a display-friendly list for the multiselect
        options = st.session_state.calendar_options
        selected_names = st.multiselect(
            "Select Calendars to Sync",
            options=[opt["name"] for opt in options],
            default=[opt["name"] for opt in options] # Default to all selected
        )
        
        # Map the selected names back to their IDs
        selected_ids = [opt["id"] for opt in options if opt["name"] in selected_names]

        if st.button("Fetch Canvas Data"):
            with st.spinner("Fetching data..."):
                start = datetime.now().strftime("%Y-%m-%d")
                end = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
                
                workload = st.session_state.ci.get_student_workload(start, end, calendar_ids=selected_ids)
                events = st.session_state.ci.get_existing_events(start, end, calendar_ids=selected_ids)
                
                st.session_state.raw_data = {
                    "user": st.session_state.ci.user.name,
                    "personal_calendar_id": f"user_{st.session_state.ci.user.id}",
                    "fetch_start": start,
                    "fetch_end": end,
                    "assignments": workload,
                    "events": events,
                }
                st.session_state.processed_schedule = None
                st.session_state.unscheduled_assignments = []
                st.session_state.canvas_sync_result = None
                st.session_state.raw_data_version += 1
                st.success(f"Pulled {len(workload)} assignments and {len(events)} events!")

# --- 3. MAIN DASHBOARD LOGIC ---
ViewDashboard(
    on_run_optimizer=run_optimizer,
    on_push_study_blocks=push_study_blocks_to_canvas,
    on_delete_study_blocks=delete_study_blocks_from_canvas,
)
