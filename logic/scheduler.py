from datetime import datetime, timedelta
from typing import List, Tuple, Dict, Any


class SmartScheduler:
    """
    Priority scoring based on:
    - assignment due date
    - assignment type weight value
    - free time windows
    """

    STUDY_HOURS_START = 8
    STUDY_HOURS_END = 22
    SESSION_DURATION_MINUTES = 60
    BUFFER_MINUTES = 15

    def __init__(
        self,
        assignments: List[Dict[str, Any]],
        busy_events: List[Tuple[datetime, datetime]],
    ):
        self.assignments = assignments
        self.busy_events = sorted(busy_events, key=lambda e: e[0])
        self.now = datetime.now().replace(second=0, microsecond=0)

    def priority_score(self, assignment: Dict[str, Any]) -> float:
        due_at: datetime = assignment["due_at"]
        points: float = assignment.get("points", 10)
        weight: float = assignment.get("group_weight", 0.1)

        hours_until_due = max((due_at - self.now).total_seconds() / 3600, 0.01)
        urgency = 1 / hours_until_due
        importance = points * weight

        return urgency * importance

    def free_slots(self, days_ahead: int = 7) -> List[Tuple[datetime, datetime]]:
        slots = []
        candidate = self.now.replace(minute=0, second=0, microsecond=0) + timedelta(minutes=self.BUFFER_MINUTES)
        end_window = self.now + timedelta(days=days_ahead)

        while candidate < end_window:
            day_start = candidate.replace(hour=self.STUDY_HOURS_START, minute=0)
            day_end = candidate.replace(hour=self.STUDY_HOURS_END, minute=0)

            if candidate < day_start:
                candidate = day_start
                continue

            if candidate >= day_end:
                candidate = (candidate + timedelta(days=1)).replace(hour=self.STUDY_HOURS_START, minute=0)
                continue

            slot_end = candidate + timedelta(minutes=self.SESSION_DURATION_MINUTES)

            if slot_end > day_end:
                candidate = (candidate + timedelta(days=1)).replace(hour=self.STUDY_HOURS_START, minute=0)
                continue

            overlaps = False
            for busy_start, busy_end in self.busy_events:
                buffered_start = busy_start - timedelta(minutes=self.BUFFER_MINUTES)
                buffered_end = busy_end + timedelta(minutes=self.BUFFER_MINUTES)
                if candidate < buffered_end and slot_end > buffered_start:
                    overlaps = True
                    candidate = buffered_end
                    break

            if not overlaps:
                slots.append((candidate, slot_end))
                candidate = slot_end + timedelta(minutes=self.BUFFER_MINUTES)

        return slots

    def generate_predictions(self) -> List[Dict[str, Any]]:
        sorted_assignments = sorted(
            self.assignments,
            key=self.priority_score,
            reverse=True
        )

        free_slots = self.free_slots()
        used_slot_indices = set()
        events = []

        for assignment in sorted_assignments:
            score = self.priority_score(assignment)
            due_at: datetime = assignment["due_at"]
            course_name = assignment.get("course_name", "Unknown")
            event_title = f"study block for {assignment['name']} {course_name}"

            slot_index = None
            for i, (slot_start, _) in enumerate(free_slots):
                if i in used_slot_indices:
                    continue
                if slot_start < due_at:
                    slot_index = i
                    break

            if slot_index is None:
                for i in range(len(free_slots)):
                    if i not in used_slot_indices:
                        slot_index = i
                        break

            if slot_index is None:
                continue

            used_slot_indices.add(slot_index)
            slot_start, slot_end = free_slots[slot_index]

            time_remaining_h = max((due_at - slot_end).total_seconds() / 3600, 0)

            events.append({
                "title": event_title,
                "start_at": slot_start.isoformat(),
                "end_at": slot_end.isoformat(),
                "calendar_id": assignment.get("calendar_id"),
                "assignment_name": assignment["name"],
                "course_name": course_name,
                "canvas_assignment_id": assignment.get("canvas_assignment_id"),
                "description": (
                    f"Priority score: {score:.4f} | "
                    f"Category: {assignment.get('assignment_group_name', 'Unweighted')} | "
                    f"Due: {due_at.strftime('%Y-%m-%d %H:%M')} | "
                    f"Time remaining after session: {time_remaining_h:.1f}h"
                ),
            })

        return sorted(events, key=lambda e: e["start_at"])
