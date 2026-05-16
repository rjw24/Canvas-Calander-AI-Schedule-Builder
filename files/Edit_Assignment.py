import streamlit as sl
import pandas as pd
from assignment import *

sl.set_page_config("Edit Assignments")

if 'assignments' not in sl.session_state:
    sl.session_state.assignments = list(AssignmentList.values())

sl.title("Assignment Editor")

def update():
    edited_data = sl.session_state.data_editor_key['edited_rows']
    for index, changes in edited_data.items():
        event_to_update = sl.session_state.assignments[index]
        for key, value in changes.items():
            setattr(event_to_update, key, value)

if len(AssignmentList) > 0:
    assignments_df = pd.DataFrame([vars(p) for p in sl.session_state.assignments])
    sl.data_editor(assignments_df, key="data_editor_key", on_change=update, num_rows="dynamic")
    
    sl.write("Current state of Assignments")
    col1, col2, col3, col4 = sl.columns(4)
    with col1:
        sl.write("Name")
    with col2:
        sl.write("Course")
    with col3:
        sl.write("Due Date")
    with col4:
        sl.write("Points")
    for index in range(len(AssignmentList)):
        col1, col2, col3, col4 = sl.columns(4)
        with col1:
            sl.caption(AssignmentList[index].GetName())
        with col2:
            sl.caption(AssignmentList[index].GetCourse())
        with col3:
            sl.caption(f"{AssignmentList[index].GetDate()} by {AssignmentList[index].GetTime()}")
        with col4:
            sl.caption(AssignmentList[index].GetPoints())
else:
    sl.write("There are no assignments to edit. Add an assignment if you wish to edit one.")

if sl.button("Return"):
    sl.switch_page("Dashboard.py")
