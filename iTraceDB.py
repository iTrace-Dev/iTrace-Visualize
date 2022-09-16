import sqlite3

IDB_TABLES = ["calibration","calibration_point","calibration_sample","files","fixation","fixation_gaze","fixation_run","gaze","ide_context","participant","session","web_context"]


# Exception Class for handling DB matching errors
class IDBDoesNotMatch(Exception):
    def __str__(self):
        return "The provided database is not an iTrace Toolkit Database"


# Main iTrace Database Class
class iTraceDB:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.cursor = self.db.cursor()
        self._verify()

    # Verify the Database is a valid iTrace Database
    def _verify(self):
        tables = self.cursor.execute("""SELECT name FROM sqlite_master WHERE type='table';""").fetchall()
        if len(tables) != len(IDB_TABLES):
            raise IDBDoesNotMatch
        for x in tables:
            if x[0] not in IDB_TABLES:
                raise IDBDoesNotMatch

    # Get all the sessions from the database
    def GetSessions(self):
        sessions = self.cursor.execute("""SELECT * FROM session""").fetchall()
        rtn = []
        for session in sessions:
            rtn.append(session[9] + " - " + str(session[0]))
        return rtn

    # Get all the fixation_runs from the selected session
    def GetFixationRuns(self, session_id):
        runs = self.cursor.execute("""SELECT * FROM fixation_run WHERE session_id = ?""",(session_id,)).fetchall()
        rtn = []
        for run in runs:
            rtn.append(run[3] + " - " + str(run[0]))
        return rtn

    # Get the length in seconds of the session
    def GetSessionTimeLength(self, session_id):
        start = self.cursor.execute("""SELECT MIN(system_time) FROM gaze WHERE session_id = ?""", (session_id,)).fetchall()[0][0]
        end = self.cursor.execute("""SELECT MAX(system_time) FROM gaze WHERE session_id = ?""", (session_id,)).fetchall()[0][0]
        return (end - start) / 1000

    # Get the System time of the session start
    def GetSessionStartTime(self,session_id):
        return self.cursor.execute("""SELECT session_time FROM session WHERE session_id = ?""", (session_id,)).fetchall()[0][0]

    # Returns all the gazes from a session
    def GetAllSessionGazes(self, session_id):
        return self.cursor.execute("""SELECT * FROM gaze WHERE session_id = ?""", (session_id,)).fetchall()

    # Returns all the fixations from a fixation run
    def GetAllRunFixations(self, run_id):
        return self.cursor.execute("""SELECT * FROM fixation WHERE fixation_run_id = ? ORDER BY fixation_start_event_time""", (run_id,)).fetchall()

    # Returns a dictionary of fixation_gazes for the selected fixation_run
    def GetAllFixationGazes(self,fixations):
        all_fix_gazes = {}
        for fixation in fixations:
            all_fix_gazes[fixation.fixation_id] = self.cursor.execute("""SELECT * FROM fixation_gaze WHERE fixation_id = ?""", (fixation.fixation_id,)).fetchall()
        return all_fix_gazes

    # Returns the gaze that happened at a specified event_time
    def GetGazeFromEventTime(self,event_time):
        return self.cursor.execute("""SELECT * FROM gaze WHERE event_time = ?""", (event_time,)).fetchall()[0]

    # Gets the session from a fixation run
    #def GetSessionOfFixationRun(self,run_id):
    #    return self.cursor.execute("""SELECT session_id FROM fixation_run WHERE fixation_run_id = ?""", (run_id,)).fetchall()[0][0]

    # Calculates and returns the saccades of a fixation_run




