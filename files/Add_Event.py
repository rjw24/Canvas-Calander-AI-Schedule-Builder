#This is a prototype of the add event page
#When the user wants to add a new event, this page is opened up

import streamlit as sl
import datetime
from event import *

sl.set_page_config("Add Event")

#Helper Functions
def generate_times():
    """Generates a list of times in 12-hour AM/PM format (e.g., '12:00 AM')."""
    times = []
    for h in range(24):
        for m in [0, 15, 30, 45]: # You can adjust the minute interval
            # Create a datetime object to use for formatting
            time_obj = datetime.strptime(f"{h:02d}:{m:02d}", "%H:%M").time()
            # Format to 12-hour with AM/PM using strftime
            times.append(time_obj.strftime("%I:%M %p"))
    return times
times = generate_times()

#Event Menu
sl.title("Add New Event")
sl.header("Add Event Menu")

sl.subheader("Title")
title = sl.text_input("Input Event Title")

sl.subheader("Date")
date = str(sl.date_input("Input Date"))
sl.subheader("Time")
time = str(sl.selectbox("Input Time", times))

sl.subheader("Frequency")
frequency = sl.selectbox("Select your event's frequency:", ("Does not repeat", "Daily", "Weekly", "Monthly", "Annually", "Every weekday", "Custom"))
sl.subheader("Location")
location = sl.text_input("Input Event Location")

col1, col2 = sl.columns(2)
with col1:
    if sl.button("Back"):
        sl.switch_page("Dashboard.py")
with col2:
    if sl.button("Confirm"):
        id = len(EventList)
        new_event = Event(title, date, time, frequency, location)
        EventList[id] = new_event
        sl.switch_page("Dashboard.py")
