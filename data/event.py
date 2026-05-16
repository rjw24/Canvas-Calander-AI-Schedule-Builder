#This file holds the Event class, which outlines how Events are stored and changed, subject to change

class Event:

    def __init__(self, title, date, time, frequency, location):
        self.title = title
        self.date = date
        self.time = time
        self.frequency = frequency
        self.location = location

    #Event Accessors
    def GetTitle(self):
        return self.title
    def GetDate(self):
        return self.date
    def GetTime(self):
        return self.time
    def GetFreq(self):
        return self.frequency
    def GetLoc(self):
        return self.location
    
EventList = {} #Store all events across pages with IDs are their keys
