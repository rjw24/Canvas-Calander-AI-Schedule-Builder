import streamlit as sl
import pandas as pd
from event import *

sl.set_page_config("Edit Events")

if 'events' not in sl.session_state:
    sl.session_state.events = list(EventList.values())

sl.title("Event Editor")

def update():
    edited_data = sl.session_state.data_editor_key['edited_rows']
    for index, changes in edited_data.items():
        event_to_update = sl.session_state.events[index]
        for key, value in changes.items():
            setattr(event_to_update, key, value)

if len(EventList) > 0:
    events_df = pd.DataFrame([vars(p) for p in sl.session_state.events])
    sl.data_editor(events_df, key="data_editor_key", on_change=update, num_rows="dynamic")
    
    sl.write("Current state of Events")
    col1, col2, col3, col4 = sl.columns(4)
    with col1:
        sl.write("Event")
    with col2:
        sl.write("Time")
    with col3:
        sl.write("Location")
    with col4:
        sl.write("Frequency")
    for index in range(len(EventList)):
        col1, col2, col3, col4 = sl.columns(4)
        with col1:
            sl.caption(EventList[index].GetTitle())
        with col2:
            sl.caption(EventList[index].GetTime())
        with col3:
            sl.caption(f"{EventList[index].GetDate()} by {EventList[index].GetTime()}")
        with col4:
            sl.caption(EventList[index].GetLoc())
else:
    sl.write("There are no events to edit. Add an event if you wish to edit one.")

if sl.button("Return"):
    sl.switch_page("Dashboard.py")
