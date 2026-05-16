from datetime import datetime, time, timedelta
import math
import re
from typing import Any, Dict, List, Optional, Tuple


def _as_list(value):
    if value in (None, ""):
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def infer_can_split(assignment: Dict[str, Any]) -> bool:
    submission_types = {str(item).lower() for item in _as_list(assignment.get("submission_types"))}
    title = str(assignment.get("title") or assignment.get("name") or "").lower()
    instructions = str(assignment.get("instructions") or assignment.get("description") or "").lower()

    if "online_quiz" in submission_types:
        return False
    if re.search(r"\b(quiz|exam|test|midterm)\b", title):
        return False
    if re.search(r"\b(timed quiz|timed exam|one sitting|single sitting)\b", instructions):
        return False

    return True


class SmartScheduler:
    """
    Builds study blocks from real availability windows instead of fixed slots.
    Existing calendar events, user blocked times, and generated study blocks all
    remove time from the same mutable free-window list.
    """

    STUDY_HOURS_START = 8
    STUDY_HOURS_END = 22
    SESSION_DURATION_MINUTES = 90
    BUFFER_MINUTES = 15
    MIN_SESSION_DURATION_MINUTES = 30
    DAYS_AHEAD = 14
    PART_GAP_MINUTES = 60

    def __init__(
        self,
        assignments: List[Dict[str, Any]],
        busy_events: List[Tuple[datetime, datetime]],
        study_hours_start: Any = None,
        study_hours_end: Any = None,
        days_ahead: int = DAYS_AHEAD,
        min_session_duration_minutes: int = MIN_SESSION_DURATION_MINUTES,
        max_session_duration_minutes: int = SESSION_DURATION_MINUTES,
        buffer_minutes: int = BUFFER_MINUTES,
        part_gap_minutes: int = PART_GAP_MINUTES,
    ):
        self.assignments = assignments
        self.busy_events = sorted(busy_events, key=lambda e: e[0])
        self.now = self._ceil_datetime(datetime.now().replace(second=0, microsecond=0))
        self.study_start = self._coerce_time(study_hours_start, self.STUDY_HOURS_START)
        self.study_end = self._coerce_time(study_hours_end, self.STUDY_HOURS_END)
        self.days_ahead = max(int(days_ahead or self.DAYS_AHEAD), 1)
        self.min_session_minutes = max(int(min_session_duration_minutes or self.MIN_SESSION_DURATION_MINUTES), 15)
        self.max_session_minutes = max(int(max_session_duration_minutes or self.SESSION_DURATION_MINUTES), self.min_session_minutes)
        self.buffer_minutes = max(int(buffer_minutes or self.BUFFER_MINUTES), 0)
        self.part_gap_minutes = max(int(part_gap_minutes or 0), 0)
        self.available_windows = self._build_free_windows()
        self.unscheduled_assignments: List[Dict[str, Any]] = []

    @staticmethod
    def _coerce_time(value, default_hour: int) -> time:
        if isinstance(value, time):
            return value
        if isinstance(value, int):
            if value >= 24:
                return time(hour=0, minute=0)
            return time(hour=max(0, min(value, 23)), minute=0)
        text = str(value or "").strip()
        if text in ("24", "24:00"):
            return time(hour=0, minute=0)
        for date_format in ("%H:%M", "%I:%M %p", "%H"):
            try:
                parsed = datetime.strptime(text, date_format)
                return time(hour=parsed.hour, minute=parsed.minute)
            except ValueError:
                continue
        return time(hour=default_hour, minute=0)

    @staticmethod
    def _ceil_datetime(value: datetime, interval_minutes: int = 15) -> datetime:
        extra = value.minute % interval_minutes
        if extra:
            value += timedelta(minutes=interval_minutes - extra)
        return value.replace(second=0, microsecond=0)

    @staticmethod
    def _duration_minutes(start: datetime, end: datetime) -> int:
        return int((end - start).total_seconds() // 60)

    def priority_score(self, assignment: Dict[str, Any]) -> float:
        due_at: datetime = assignment["due_at"]
        points: float = assignment.get("points", 10)
        weight: float = assignment.get("group_weight", 0.1)
        estimated_minutes = self.estimated_minutes(assignment)

        hours_until_due = max((due_at - self.now).total_seconds() / 3600, 0.01)
        urgency = 1 / hours_until_due
        importance = max(points, 1) * max(weight, 0.01)
        effort = max(estimated_minutes / self.max_session_minutes, 0.5)

        return urgency * importance * effort

    def estimated_minutes(self, assignment: Dict[str, Any]) -> int:
        try:
            minutes = float(assignment.get("estimated_minutes", self.max_session_minutes))
        except (TypeError, ValueError):
            minutes = self.max_session_minutes

        minutes = max(minutes, self.min_session_minutes)
        return int(math.ceil(minutes / 15) * 15)

    def _merged_busy_events(self) -> List[Tuple[datetime, datetime]]:
        buffered = []
        buffer_delta = timedelta(minutes=self.buffer_minutes)

        for start, end in self.busy_events:
            if start is None or end is None or end <= start:
                continue
            buffered.append((start - buffer_delta, end + buffer_delta))

        buffered.sort(key=lambda item: item[0])
        merged = []
        for start, end in buffered:
            if not merged or start > merged[-1][1]:
                merged.append([start, end])
            else:
                merged[-1][1] = max(merged[-1][1], end)

        return [(start, end) for start, end in merged]

    def _subtract_busy(self, window_start: datetime, window_end: datetime, busy_events):
        free_windows = [(window_start, window_end)]

        for busy_start, busy_end in busy_events:
            if busy_end <= window_start or busy_start >= window_end:
                continue

            next_windows = []
            for free_start, free_end in free_windows:
                if busy_end <= free_start or busy_start >= free_end:
                    next_windows.append((free_start, free_end))
                    continue
                if free_start < busy_start:
                    next_windows.append((free_start, min(busy_start, free_end)))
                if busy_end < free_end:
                    next_windows.append((max(busy_end, free_start), free_end))

            free_windows = next_windows

        return [
            (self._ceil_datetime(start), end)
            for start, end in free_windows
            if self._duration_minutes(self._ceil_datetime(start), end) >= self.min_session_minutes
        ]

    def _build_free_windows(self) -> List[Tuple[datetime, datetime]]:
        windows = []
        earliest_start = self._ceil_datetime(self.now + timedelta(minutes=self.buffer_minutes))
        end_window = self.now + timedelta(days=self.days_ahead)
        busy_events = self._merged_busy_events()
        day = self.now.date()

        while day <= end_window.date():
            day_start = datetime.combine(day, self.study_start)
            day_end = datetime.combine(day, self.study_end)
            if day_end <= day_start:
                day_end += timedelta(days=1)

            day_start = max(day_start, earliest_start)
            day_end = min(day_end, end_window)

            if day_end > day_start:
                windows.extend(self._subtract_busy(day_start, day_end, busy_events))

            day += timedelta(days=1)

        return sorted(windows, key=lambda item: item[0])

    def _find_window(
        self,
        required_minutes: int,
        due_at: datetime,
        earliest_start: Optional[datetime] = None,
    ):
        for index, (window_start, window_end) in enumerate(self.available_windows):
            start = max(window_start, earliest_start) if earliest_start else window_start
            start = self._ceil_datetime(start)
            end = min(window_end, due_at)
            if start >= end:
                continue
            if self._duration_minutes(start, end) >= required_minutes:
                return index, start, end
        return None

    def _reserve_window(self, start: datetime, end: datetime):
        buffer_delta = timedelta(minutes=self.buffer_minutes)
        reserve_start = start - buffer_delta
        reserve_end = end + buffer_delta
        next_windows = []

        for window_start, window_end in self.available_windows:
            if reserve_end <= window_start or reserve_start >= window_end:
                next_windows.append((window_start, window_end))
                continue

            if window_start < reserve_start:
                left = (window_start, min(reserve_start, window_end))
                if self._duration_minutes(*left) >= self.min_session_minutes:
                    next_windows.append(left)

            if reserve_end < window_end:
                right_start = self._ceil_datetime(max(reserve_end, window_start))
                right = (right_start, window_end)
                if self._duration_minutes(*right) >= self.min_session_minutes:
                    next_windows.append(right)

        self.available_windows = sorted(next_windows, key=lambda item: item[0])

    def _make_event(
        self,
        assignment: Dict[str, Any],
        start: datetime,
        end: datetime,
        score: float,
        part_number: int,
        part_count: int,
        estimated_minutes: int,
        remaining_minutes: int,
    ) -> Dict[str, Any]:
        due_at: datetime = assignment["due_at"]
        course_name = assignment.get("course_name", "Unknown")
        suffix = f" ({part_number}/{part_count})" if part_count > 1 else ""
        time_remaining_h = max((due_at - end).total_seconds() / 3600, 0)
        planned_minutes = self._duration_minutes(start, end)

        return {
            "title": f"study block for {assignment['name']} {course_name}{suffix}",
            "start_at": start.isoformat(),
            "end_at": end.isoformat(),
            "calendar_id": assignment.get("calendar_id"),
            "assignment_name": assignment["name"],
            "course_name": course_name,
            "canvas_assignment_id": assignment.get("canvas_assignment_id"),
            "planned_minutes": planned_minutes,
            "estimated_assignment_minutes": estimated_minutes,
            "remaining_assignment_minutes": remaining_minutes,
            "can_split": assignment.get("can_split", infer_can_split(assignment)),
            "description": (
                f"Priority score: {score:.4f} | "
                f"Planned block: {planned_minutes} min | "
                f"Estimated effort: {estimated_minutes} min | "
                f"Remaining assignment effort after block: {remaining_minutes} min | "
                f"Estimate method: {assignment.get('duration_method', 'heuristic')} | "
                f"Confidence: {assignment.get('duration_confidence', 'n/a')} | "
                f"Category weight: {assignment.get('group_weight', 1)} | "
                f"Due: {due_at.strftime('%Y-%m-%d %H:%M')} | "
                f"Time remaining after session: {time_remaining_h:.1f}h"
            ),
        }

    def _schedule_unsplittable(self, assignment, score, estimated_minutes):
        due_at = assignment["due_at"]
        found = self._find_window(estimated_minutes, due_at)
        if found is None:
            self.unscheduled_assignments.append({
                "assignment": assignment["name"],
                "reason": "No single free window before the due date was long enough.",
                "remaining_minutes": estimated_minutes,
            })
            return []

        _, start, window_end = found
        end = start + timedelta(minutes=estimated_minutes)
        if end > window_end:
            self.unscheduled_assignments.append({
                "assignment": assignment["name"],
                "reason": "No continuous window could fit the required duration.",
                "remaining_minutes": estimated_minutes,
            })
            return []

        self._reserve_window(start, end)
        return [self._make_event(assignment, start, end, score, 1, 1, estimated_minutes, 0)]

    def _schedule_splittable(self, assignment, score, estimated_minutes):
        due_at = assignment["due_at"]
        remaining = estimated_minutes
        last_end = None
        pieces = []

        while remaining > 0:
            earliest_start = None
            if last_end is not None and self.part_gap_minutes:
                earliest_start = last_end + timedelta(minutes=self.part_gap_minutes)

            required_minutes = min(remaining, self.min_session_minutes)
            found = self._find_window(required_minutes, due_at, earliest_start=earliest_start)
            if found is None and earliest_start is not None:
                found = self._find_window(required_minutes, due_at)
            if found is None:
                break

            _, start, window_end = found
            available_minutes = self._duration_minutes(start, window_end)
            block_minutes = min(remaining, self.max_session_minutes, available_minutes)
            if block_minutes < required_minutes:
                break

            end = start + timedelta(minutes=block_minutes)
            remaining = max(remaining - block_minutes, 0)
            pieces.append((start, end, remaining))
            self._reserve_window(start, end)
            last_end = end

        if remaining > 0:
            self.unscheduled_assignments.append({
                "assignment": assignment["name"],
                "reason": "Not enough free study time before the due date.",
                "remaining_minutes": remaining,
            })

        part_count = len(pieces)
        return [
            self._make_event(
                assignment,
                start,
                end,
                score,
                index,
                part_count,
                estimated_minutes,
                remaining_after,
            )
            for index, (start, end, remaining_after) in enumerate(pieces, start=1)
        ]

    def generate_predictions(self) -> List[Dict[str, Any]]:
        sorted_assignments = sorted(
            self.assignments,
            key=self.priority_score,
            reverse=True,
        )

        events = []
        for assignment in sorted_assignments:
            score = self.priority_score(assignment)
            estimated_minutes = self.estimated_minutes(assignment)
            can_split = assignment.get("can_split", infer_can_split(assignment))

            if can_split:
                events.extend(self._schedule_splittable(assignment, score, estimated_minutes))
            else:
                events.extend(self._schedule_unsplittable(assignment, score, estimated_minutes))

        return sorted(events, key=lambda event: event["start_at"])
