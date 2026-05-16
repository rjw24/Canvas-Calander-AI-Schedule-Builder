import streamlit as st
from data.canvas_client import CanvasInterface
from logic.scheduler import SmartScheduler
from datetime import datetime, timedelta
from Dashboard import ViewDashboard

CANVAS_BASE_URL = "https://csufullerton.instructure.com"

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

        assignments.append({
            "name": assignment.get("title") or assignment.get("name") or "Untitled",
            "course_name": course_name,
            "due_at": due_at,
            "points": _number_or_default(assignment.get("points"), default=1),
            "group_weight": _weight_or_default(assignment.get("group_weight"), default=1),
            "assignment_group_name": assignment.get("assignment_group_name", "Unweighted"),
            "canvas_assignment_id": assignment.get("canvas_assignment_id"),
            "calendar_id": raw_data.get("personal_calendar_id"),
        })

    existing_events = []
    for event in raw_data.get("events", []):
        if not event.get("include", True):
            continue

        start = _scheduler_datetime(event.get("start") or event.get("start_at"))
        end = _scheduler_datetime(event.get("end") or event.get("end_at"))
        if start is not None and end is not None and end > start:
            existing_events.append((start, end))

    return assignments, existing_events


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

    try:
        scheduler = SmartScheduler(assignments, existing_events)
        st.session_state.processed_schedule = scheduler.generate_predictions()
        st.session_state.canvas_sync_result = None
    except Exception as exc:
        st.error(f"Could not generate the smart schedule: {exc}")
        return

    count = len(st.session_state.processed_schedule)
    if count:
        st.success(f"Generated {count} study block{'s' if count != 1 else ''}.")
    else:
        st.info("No open study blocks were found in the current schedule window.")


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
                st.success("Connected! Now select your calendars.")
            except Exception as exc:
                st.session_state.authenticated = False
                st.error(f"Could not connect to Canvas: {exc}")
        else:
            st.warning("Enter a Canvas token before connecting.")

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
                st.session_state.canvas_sync_result = None
                st.session_state.raw_data_version += 1
                st.success(f"Pulled {len(workload)} assignments and {len(events)} events!")

# --- 3. MAIN DASHBOARD LOGIC ---
ViewDashboard(
    on_run_optimizer=run_optimizer,
    on_push_study_blocks=push_study_blocks_to_canvas,
    on_delete_study_blocks=delete_study_blocks_from_canvas,
)
