#This is a prototype of the add assignment page
#When the user wants to add a new assignment, this page is opened up
import streamlit as sl
import datetime
from assignment import *

sl.set_page_config("Add Assignment")

#Helper Function
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

#Assignment Menu
sl.title("Add New Assignment")
sl.header("Add Assignment Menu")

sl.subheader("Name")
name = sl.text_input("Input Assignment Name")
sl.subheader("Course")
course = sl.text_input("Input Course Name")

sl.subheader("Due Date")
end_date = str(sl.date_input("End Day"))
sl.subheader("Due Time")
end_time = str(sl.selectbox("End Time", times))

sl.subheader("Points")
points = sl.text_input("Input Points")
sl.subheader("Weight Percent")
weight_percent = sl.text_input("Input Grade Weight")
sl.subheader("Status")
status = sl.selectbox("Assignment Status", ("Unsubmitted", "Submitted", "Graded"))

col1, col2 = sl.columns(2)
with col1:
    if sl.button("Back"):
        sl.switch_page("Dashboard.py")
with col2:
    if sl.button("Confirm"):
        id = len(AssignmentList)
        new_assignment = Assignment(name, course, end_date, end_time, points, status, weight_percent)
        AssignmentList[id] = new_assignment
        sl.switch_page("Dashboard.py")
