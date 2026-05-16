import streamlit as sl
import pandas as pd
from datetime import datetime, timedelta

from logic.scheduler import SmartScheduler, infer_can_split

try:
    from data.assignment import AssignmentList
except ModuleNotFoundError:
    AssignmentList = {}

try:
    from data.event import EventList
except ModuleNotFoundError:
    EventList = {}

WEEKDAY_OPTIONS = [
    "Every day",
    "Weekdays",
    "Weekends",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
]
DEFAULT_SCHEDULE_SETTINGS = {
    "study_start_hour": SmartScheduler.STUDY_HOURS_START,
    "study_end_hour": SmartScheduler.STUDY_HOURS_END,
    "days_ahead": SmartScheduler.DAYS_AHEAD,
    "min_block_minutes": SmartScheduler.MIN_SESSION_DURATION_MINUTES,
    "max_block_minutes": SmartScheduler.SESSION_DURATION_MINUTES,
    "buffer_minutes": SmartScheduler.BUFFER_MINUTES,
    "part_gap_minutes": SmartScheduler.PART_GAP_MINUTES,
}


def _parse_datetime(value):
    if isinstance(value, datetime):
        return value
    if value is None:
        return None

    text = str(value).strip()
    if not text:
        return None

    iso_text = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(iso_text)
    except ValueError:
        pass

    for date_format in ("%Y-%m-%d %I:%M %p", "%Y-%m-%d", "%m/%d/%Y %I:%M %p"):
        try:
            return datetime.strptime(text, date_format)
        except ValueError:
            continue

    return None


def _format_datetime(value):
    parsed = _parse_datetime(value)
    if parsed is None:
        return str(value) if value else "No date"
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.strftime("%b %d, %Y %I:%M %p").replace(" 0", " ")


def _format_time_left(value):
    parsed = _parse_datetime(value)
    if parsed is None:
        return "No due date"

    now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
    remaining = parsed - now
    if remaining.total_seconds() <= 0:
        return "Past due"

    total_minutes = int(remaining.total_seconds() // 60)
    days, day_remainder = divmod(total_minutes, 24 * 60)
    hours, minutes = divmod(day_remainder, 60)

    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"

def _format_points(points):
    if points in (None, ""):
        return "0"
    try:
        number = float(points)
    except (TypeError, ValueError):
        return str(points)
    return str(int(number)) if number.is_integer() else f"{number:g}"


def _clean_value(value, default=""):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except (TypeError, ValueError):
        pass
    return value


def _clean_text(value, default=""):
    value = _clean_value(value, default=default)
    return str(value).strip() if value != "" else default


def _preview_text(value, max_chars=120):
    text = _clean_text(value)
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rsplit(" ", 1)[0] + "..."


def _number_or_default(value, default=0):
    value = _clean_value(value, default=default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _bool_or_default(value, default=True):
    value = _clean_value(value, default=default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "no", "off")
    return bool(value)


def _normalize_weight(value, default=1.0):
    value = _clean_value(value, default=default)
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


def _weight_percent(value):
    try:
        return round(float(value) * 100, 2)
    except (TypeError, ValueError):
        return 100


def _set_if_changed(item, key, value):
    if item.get(key) == value:
        return False
    item[key] = value
    return True


def _assignment_advice(due_at, points):
    parsed = _parse_datetime(due_at)
    if parsed is None:
        return "Add a deadline before scheduling."

    now = datetime.now(parsed.tzinfo) if parsed.tzinfo else datetime.now()
    remaining = parsed - now
    if remaining.total_seconds() <= 0:
        return "Review this overdue item."
    if remaining <= timedelta(days=1):
        return "Work on this first."
    if remaining <= timedelta(days=3):
        return "Schedule a focused block soon."

    try:
        if float(points or 0) >= 50:
            return "Reserve a longer study block."
    except (TypeError, ValueError):
        pass

    return "Plan time before the deadline."


def _canvas_assignment_rows(assignments):
    rows = []
    for assignment in assignments:
        title = assignment.get("title") or assignment.get("name") or "Untitled"
        due_at = assignment.get("due_at") or assignment.get("start_at")
        points = assignment.get("points")
        rows.append({
            "Assignment": title,
            "Class": assignment.get("course_name") or assignment.get("context") or assignment.get("course") or "Unknown",
            "Due": _format_datetime(due_at),
            "Time Left": _format_time_left(due_at),
            "Points": _format_points(points),
            "Category": assignment.get("assignment_group_name", "Unweighted"),
            "Weight": f"{_weight_percent(assignment.get('group_weight', 1))}%",
            "Advice": _assignment_advice(due_at, points),
        })
    return rows


def _prototype_assignment_rows():
    rows = []
    for assignment in AssignmentList.values():
        due_at = f"{assignment.GetDate()} {assignment.GetTime()}"
        points = assignment.GetPoints()
        rows.append({
            "Assignment": assignment.GetName(),
            "Class": assignment.GetCourse(),
            "Due": _format_datetime(due_at),
            "Time Left": _format_time_left(due_at),
            "Points": _format_points(points),
            "Advice": _assignment_advice(due_at, points),
        })
    return rows


def _canvas_event_rows(events):
    rows = []
    for event in events:
        start = event.get("start") or event.get("start_at")
        end = event.get("end") or event.get("end_at")
        rows.append({
            "Event": event.get("title") or "Untitled",
            "Start": _format_datetime(start),
            "End": _format_datetime(end),
            "Calendar": event.get("context") or "Personal",
        })
    return rows


def _prototype_event_rows():
    rows = []
    for event in EventList.values():
        start = f"{event.GetDate()} {event.GetTime()}"
        rows.append({
            "Event": event.GetTitle(),
            "Start": _format_datetime(start),
            "End": "No end time",
            "Calendar": event.GetLoc(),
            "Frequency": event.GetFreq(),
        })
    return rows


def _assignment_editor_rows(assignments):
    rows = []
    for index, assignment in enumerate(assignments):
        row_id = assignment.get("id") or f"assignment_{index}"
        assignment["id"] = row_id
        if "can_split" not in assignment:
            assignment["can_split"] = infer_can_split(assignment)
        weight = assignment.get("group_weight")
        rows.append({
            "id": row_id,
            "Include": _bool_or_default(assignment.get("include", True)),
            "Can Split": _bool_or_default(assignment.get("can_split"), default=True),
            "Assignment": assignment.get("title") or assignment.get("name") or "Untitled",
            "Course": assignment.get("course_name") or assignment.get("context") or assignment.get("course") or "Unknown",
            "Due": assignment.get("due_at") or assignment.get("start_at") or "",
            "Points": _number_or_default(assignment.get("points"), default=0),
            "Category": assignment.get("assignment_group_name", "Unweighted"),
            "Category Weight %": assignment.get("group_weight_percent", _weight_percent(weight or 1)),
            "Instructions Preview": _preview_text(
                assignment.get("instructions") or assignment.get("description"),
            ),
        })
    return pd.DataFrame(rows)


def _event_editor_rows(events):
    rows = []
    for index, event in enumerate(events):
        row_id = event.get("id") or f"event_{index}"
        event["id"] = row_id
        rows.append({
            "id": row_id,
            "Include": _bool_or_default(event.get("include", True)),
            "Event": event.get("title") or "Untitled",
            "Start": event.get("start") or event.get("start_at") or "",
            "End": event.get("end") or event.get("end_at") or "",
            "Calendar": event.get("context") or "Personal",
        })
    return pd.DataFrame(rows)


def _merge_assignment_edits(assignments, edited_rows):
    changed = False
    by_id = {assignment.get("id"): assignment for assignment in assignments}

    for row in edited_rows:
        assignment = by_id.get(row.get("id"))
        if assignment is None:
            continue

        include = _bool_or_default(row.get("Include"), default=True)
        can_split = _bool_or_default(row.get("Can Split"), default=True)
        title = _clean_text(row.get("Assignment"), default="Untitled")
        course = _clean_text(row.get("Course"), default="Unknown")
        due_at = _clean_text(row.get("Due"))
        points = _number_or_default(row.get("Points"), default=0)
        category = _clean_text(row.get("Category"), default="Unweighted")
        group_weight = _normalize_weight(row.get("Category Weight %"), default=assignment.get("group_weight", 1))
        group_weight_percent = _weight_percent(group_weight)

        changed |= _set_if_changed(assignment, "include", include)
        changed |= _set_if_changed(assignment, "can_split", can_split)
        changed |= _set_if_changed(assignment, "title", title)
        changed |= _set_if_changed(assignment, "course_name", course)
        changed |= _set_if_changed(assignment, "context", course)
        changed |= _set_if_changed(assignment, "due_at", due_at)
        changed |= _set_if_changed(assignment, "points", points)
        changed |= _set_if_changed(assignment, "assignment_group_name", category)
        changed |= _set_if_changed(assignment, "group_weight", group_weight)
        changed |= _set_if_changed(assignment, "group_weight_percent", group_weight_percent)

    return changed


def _assignment_label(assignment):
    title = assignment.get("title") or assignment.get("name") or "Untitled"
    course = assignment.get("course_name") or assignment.get("context") or assignment.get("course") or "Unknown"
    return f"{title} ({course})"


def _render_assignment_instructions_editor(assignments, version):
    by_id = {assignment.get("id"): assignment for assignment in assignments}
    assignment_ids = [assignment.get("id") for assignment in assignments if assignment.get("id")]
    if not assignment_ids:
        return

    selected_id = sl.selectbox(
        "Assignment instructions",
        assignment_ids,
        format_func=lambda item_id: _assignment_label(by_id[item_id]),
        key=f"assignment_instructions_select_{version}",
    )
    assignment = by_id.get(selected_id)
    if assignment is None:
        return

    current = assignment.get("instructions") or assignment.get("description") or ""
    edited = sl.text_area(
        "Instructions",
        value=current,
        height=220,
        key=f"assignment_instructions_{version}_{selected_id}",
    )
    if _set_if_changed(assignment, "instructions", edited):
        assignment["description"] = edited
        sl.session_state.processed_schedule = None


def _merge_event_edits(events, edited_rows):
    changed = False
    by_id = {event.get("id"): event for event in events}

    for row in edited_rows:
        event = by_id.get(row.get("id"))
        if event is None:
            continue

        include = _bool_or_default(row.get("Include"), default=True)
        title = _clean_text(row.get("Event"), default="Untitled")
        start = _clean_text(row.get("Start"))
        end = _clean_text(row.get("End"))
        calendar = _clean_text(row.get("Calendar"), default="Personal")

        changed |= _set_if_changed(event, "include", include)
        changed |= _set_if_changed(event, "title", title)
        changed |= _set_if_changed(event, "start", start)
        changed |= _set_if_changed(event, "end", end)
        changed |= _set_if_changed(event, "context", calendar)

    return changed


def _render_workload(raw_data):
    assignments = raw_data.get("assignments", []) if raw_data else []
    events = raw_data.get("events", []) if raw_data else []

    if raw_data is None:
        assignment_rows = _prototype_assignment_rows()
        event_rows = _prototype_event_rows()
    else:
        assignment_rows = _canvas_assignment_rows(assignments)
        event_rows = _canvas_event_rows(events)

    sl.header("Assignment List")
    if assignment_rows:
        sl.dataframe(assignment_rows, use_container_width=True, hide_index=True)
    else:
        sl.info("No assignments found for the selected range.")

    sl.header("Event List")
    if event_rows:
        sl.dataframe(event_rows, use_container_width=True, hide_index=True)
    else:
        sl.info("No events found for the selected range.")


def _render_editable_workload(raw_data):
    assignments = raw_data.get("assignments", [])
    events = raw_data.get("events", [])
    version = sl.session_state.get("raw_data_version", 0)

    sl.header("Assignment List")
    if assignments:
        assignment_df = _assignment_editor_rows(assignments)
        edited_assignments = sl.data_editor(
            assignment_df,
            key=f"assignment_editor_{version}",
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_order=[
                "Include",
                "Can Split",
                "Assignment",
                "Course",
                "Due",
                "Points",
                "Category",
                "Category Weight %",
                "Instructions Preview",
            ],
            column_config={
                "Include": sl.column_config.CheckboxColumn("Include"),
                "Can Split": sl.column_config.CheckboxColumn("Can Split"),
                "Points": sl.column_config.NumberColumn("Points", min_value=0, step=1),
                "Category Weight %": sl.column_config.NumberColumn(
                    "Category Weight %",
                    min_value=0,
                    max_value=100,
                    step=0.1,
                ),
                "Instructions Preview": sl.column_config.TextColumn(
                    "Instructions Preview",
                    disabled=True,
                    width="large",
                ),
            },
        )
        if _merge_assignment_edits(assignments, edited_assignments.to_dict("records")):
            sl.session_state.processed_schedule = None

        _render_assignment_instructions_editor(assignments, version)

        included = sum(1 for assignment in assignments if assignment.get("include", True))
        sl.caption(f"{included} of {len(assignments)} assignments included in scheduler calculations.")

        if sl.button("Remove unchecked assignments", disabled=included == len(assignments)):
            raw_data["assignments"] = [
                assignment for assignment in assignments
                if assignment.get("include", True)
            ]
            sl.session_state.processed_schedule = None
            sl.rerun()
    else:
        sl.info("No assignments found for the selected range.")

    sl.header("Event List")
    if events:
        event_df = _event_editor_rows(events)
        edited_events = sl.data_editor(
            event_df,
            key=f"event_editor_{version}",
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            column_order=["Include", "Event", "Start", "End", "Calendar"],
            column_config={
                "Include": sl.column_config.CheckboxColumn("Include"),
            },
        )
        if _merge_event_edits(events, edited_events.to_dict("records")):
            sl.session_state.processed_schedule = None

        included = sum(1 for event in events if event.get("include", True))
        sl.caption(f"{included} of {len(events)} events included as busy calendar time.")

        if sl.button("Remove unchecked events", disabled=included == len(events)):
            raw_data["events"] = [
                event for event in events
                if event.get("include", True)
            ]
            sl.session_state.processed_schedule = None
            sl.rerun()
    else:
        sl.info("No events found for the selected range.")


def _render_schedule(schedule):
    if not schedule:
        sl.info("Run the optimizer after fetching Canvas data to generate study blocks.")
        return

    rows = []
    for event in schedule:
        rows.append({
            "Study Block": event.get("title", "Study block"),
            "Start": _format_datetime(event.get("start_at")),
            "End": _format_datetime(event.get("end_at")),
            "Minutes": event.get("planned_minutes", ""),
            "Target Calendar": event.get("calendar_id", "Personal"),
            "Canvas Event ID": event.get("pushed_canvas_event_id", ""),
            "Details": event.get("description", ""),
        })
    sl.dataframe(rows, use_container_width=True, hide_index=True)


def _render_unscheduled_assignments(items):
    if not items:
        return
    sl.warning(f"{len(items)} assignment(s) have estimated work that could not be fully scheduled.")
    sl.dataframe(items, use_container_width=True, hide_index=True)


def _render_canvas_sync_result(result):
    if not result:
        return

    action = result.get("action")
    if action == "add":
        created = result.get("created", [])
        skipped = result.get("skipped", 0)
        failed = result.get("failed", [])

        if created:
            sl.caption(f"Last Canvas add: {len(created)} block(s) created.")
        if skipped:
            sl.caption(f"{skipped} block(s) were already added in this session.")
        if failed:
            sl.dataframe(failed, use_container_width=True, hide_index=True)
    elif action == "delete":
        deleted = result.get("deleted", [])
        failed = result.get("failed", [])
        window = result.get("window")

        if window:
            sl.caption(f"Last Canvas delete checked {window[0]} through {window[1]}.")
        if deleted:
            sl.caption(f"{len(deleted)} generated block(s) deleted.")
        if failed:
            sl.dataframe(failed, use_container_width=True, hide_index=True)


def _schedule_settings():
    settings = dict(DEFAULT_SCHEDULE_SETTINGS)
    settings.update(sl.session_state.get("schedule_settings", {}))
    return settings


def _setting_number(label, value, minimum, maximum, step, key):
    return int(sl.number_input(label, min_value=minimum, max_value=maximum, value=int(value), step=step, key=key))


def _render_schedule_settings():
    settings = _schedule_settings()

    col1, col2 = sl.columns(2)
    with col1:
        study_start_hour = _setting_number(
            "Study start hour",
            settings["study_start_hour"],
            0,
            23,
            1,
            "setting_study_start_hour",
        )
        min_block_minutes = _setting_number(
            "Minimum block minutes",
            settings["min_block_minutes"],
            15,
            240,
            15,
            "setting_min_block_minutes",
        )
        buffer_minutes = _setting_number(
            "Buffer minutes",
            settings["buffer_minutes"],
            0,
            120,
            5,
            "setting_buffer_minutes",
        )
    with col2:
        study_end_hour = _setting_number(
            "Study end hour",
            settings["study_end_hour"],
            1,
            24,
            1,
            "setting_study_end_hour",
        )
        max_block_minutes = _setting_number(
            "Maximum split block minutes",
            settings["max_block_minutes"],
            30,
            360,
            15,
            "setting_max_block_minutes",
        )
        part_gap_minutes = _setting_number(
            "Gap between assignment parts",
            settings["part_gap_minutes"],
            0,
            1440,
            15,
            "setting_part_gap_minutes",
        )

    days_ahead = _setting_number(
        "Scheduling horizon days",
        settings["days_ahead"],
        1,
        30,
        1,
        "setting_days_ahead",
    )

    new_settings = {
        "study_start_hour": study_start_hour,
        "study_end_hour": study_end_hour,
        "days_ahead": days_ahead,
        "min_block_minutes": min_block_minutes,
        "max_block_minutes": max(max_block_minutes, min_block_minutes),
        "buffer_minutes": buffer_minutes,
        "part_gap_minutes": part_gap_minutes,
    }
    if new_settings != sl.session_state.get("schedule_settings"):
        sl.session_state.schedule_settings = new_settings
        sl.session_state.processed_schedule = None


def _blocked_time_rows():
    rows = sl.session_state.get("custom_blocked_times", [])
    return pd.DataFrame(
        rows,
        columns=["Include", "Name", "Day", "Start", "End"],
    )


def _normalize_blocked_rows(records):
    normalized = []
    for row in records:
        name = _clean_text(row.get("Name"), default="Blocked")
        day = _clean_text(row.get("Day"), default="Every day")
        start = _clean_text(row.get("Start"))
        end = _clean_text(row.get("End"))
        if not start and not end:
            continue
        normalized.append({
            "Include": _bool_or_default(row.get("Include"), default=True),
            "Name": name,
            "Day": day if day in WEEKDAY_OPTIONS else "Every day",
            "Start": start,
            "End": end,
        })
    return normalized


def _render_blocked_time_settings():
    edited = sl.data_editor(
        _blocked_time_rows(),
        key="custom_blocked_time_editor",
        use_container_width=True,
        hide_index=True,
        num_rows="dynamic",
        column_order=["Include", "Name", "Day", "Start", "End"],
        column_config={
            "Include": sl.column_config.CheckboxColumn("Include", default=True),
            "Day": sl.column_config.SelectboxColumn("Day", options=WEEKDAY_OPTIONS, default="Every day"),
            "Start": sl.column_config.TextColumn("Start"),
            "End": sl.column_config.TextColumn("End"),
        },
    )
    rows = _normalize_blocked_rows(edited.to_dict("records"))
    if rows != sl.session_state.get("custom_blocked_times", []):
        sl.session_state.custom_blocked_times = rows
        sl.session_state.processed_schedule = None


def ViewDashboard(
    on_run_optimizer=None,
    on_push_study_blocks=None,
    on_delete_study_blocks=None,
):
    raw_data = sl.session_state.get("raw_data")
    authenticated = sl.session_state.get("authenticated", False)

    sl.title("Welcome to your Canvas Dashboard!")

    if not authenticated:
        sl.info("Please enter your Canvas token in the sidebar to begin.")
        if AssignmentList or EventList:
            sl.caption("Showing local prototype data.")
            _render_workload(raw_data=None)
        return

    tab1, tab2, tab3 = sl.tabs(["Current Tasks", "Smart Schedule", "Settings"])

    with tab1:
        if raw_data is None:
            sl.warning("Select calendars and click Fetch Canvas Data in the sidebar.")
        else:
            user = raw_data.get("user")
            if user:
                sl.subheader(f"Workload for {user}")
            _render_editable_workload(raw_data)

    with tab2:
        if sl.button("Run Optimizer", type="primary", disabled=raw_data is None):
            if on_run_optimizer is None:
                sl.warning("Optimizer is not connected yet.")
            else:
                on_run_optimizer()

        schedule = sl.session_state.get("processed_schedule")
        _render_schedule(schedule)
        _render_unscheduled_assignments(sl.session_state.get("unscheduled_assignments"))

        if schedule:
            col1, col2 = sl.columns(2)
            with col1:
                if sl.button("Add study blocks to Canvas", disabled=on_push_study_blocks is None):
                    on_push_study_blocks()
            with col2:
                if sl.button("Delete generated study blocks from Canvas", disabled=on_delete_study_blocks is None):
                    on_delete_study_blocks()

        _render_canvas_sync_result(sl.session_state.get("canvas_sync_result"))

    with tab3:
        sl.header("Scheduler Settings")
        _render_schedule_settings()

        sl.header("Blocked Time")
        _render_blocked_time_settings()

        if sl.button("Clear Session"):
            sl.session_state.clear()
            sl.rerun()


VeiwDashboard = ViewDashboard


if __name__ == "__main__":
    sl.set_page_config(page_title="My Canvas Dashboard", layout="wide")
    ViewDashboard()
