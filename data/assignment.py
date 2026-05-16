#This file holds the Assignment class, which outlines how Assignments are stored and changed, subject to change

class Assignment:
    def __init__(self, name, course, prof, due_date, due_time, pts, status, weight):
        self.name = name
        self.course = course
        self.due_date = due_date
        self.due_time = due_time
        self.status = status
        self.points = pts
        self.weight_score = weight
    
    #Assignment Accessors
    def GetName(self):
        return self.name
    def GetCourse(self):
        return self.course
    def GetDate(self):
        return self.due_date
    def GetTime(self):
        return self.due_time
    def GetStatus(self):
        return self.status
    def GetPoints(self):
        return self.points
    def GetWeight(self):
        return self.weight_score

AssignmentList = {} #Will store all Assignments across pages, keyed by IDs
