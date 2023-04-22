# This Python file uses the following encoding: utf-8
import sys
import cv2
import time
import numpy as np
import math
from iTraceDB import iTraceDB
from EyeDataTypes import Gaze, Fixation
from PySide6 import QtCore, QtWidgets, QtGui
# from PyQt5.QtCore import pyqtSignal

WIN_WIDTH, WIN_HEIGHT = 800, 600
ROLLING_WIN_SIZE = 1000 # Size of rolling window in miliseconds
GAZE_RADIUS = 5
FIXATION_RADIUS = 10

# Converts color string (rgb) to color tuple (bgr)
def ConvertColorStringToTuple(color: "#XXXXXX") -> tuple[int]:
    color = color[1:]
    b = int(color[4:6],base=16)
    g = int(color[2:4],base=16)
    r = int(color[0:2],base=16)
    return (b,g,r)

# converts color tuple (bgr) to color string (rgb)
def ConvertColorTupleToString(color: tuple[int]) -> "#XXXXXX":
    return "#"+str(hex(color[2]))+str(hex(color[1]))+str(hex(color[0]))

# Converts windows time to Unix time
def ConvertWindowsTime(t) -> int:
    return ((t / 10000000) - 11644473600) * 1000

# Takes the list of Fixations and Gazes and figures out the saccades
# Saccades are defined as the group of gazes between two consecutive fixations
def GetSaccadesOfGazesAndFixationGazes(idb,gazes,fixation_gazes) -> list[list[Gaze]]:
    fix_gaze_times = []
    for fix_id in fixation_gazes:
        for fixation_gaze in fixation_gazes[fix_id]:
            fix_gaze_times.append(Gaze(idb.GetGazeFromEventTime(fixation_gaze[1])).system_time)
    saccades = []
    add = []

    for gaze in gazes:
        if gaze.system_time in fix_gaze_times and len(add) == 0: #Do nothing, looking for next saccade
            pass
        elif gaze.system_time in fix_gaze_times and len(add) != 0: #End current saccade, start new one
            saccades.append(add)
            add = []
        elif gaze.system_time not in fix_gaze_times and not gaze.isNaN():
            add.append(gaze)
    if len(add) != 0:
        saccades.append(add)

    return saccades


class ConfirmDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, title="Dialog", msg="Warning"):
        super().__init__(parent)
        self.setWindowTitle(title)
        QBtn = QtWidgets.QDialogButtonBox.Yes | QtWidgets.QDialogButtonBox.No
        self.buttonBox = QtWidgets.QDialogButtonBox(QBtn)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

        self.layout = QtWidgets.QVBoxLayout()
        message = QtWidgets.QLabel(msg)
        self.layout.addWidget(message)
        self.layout.addWidget(self.buttonBox)
        self.setLayout(self.layout)


class MyWidget(QtWidgets.QWidget):
    
    def __init__(self):
        super().__init__()

        self.title = "iTrace Visualization"
        self.setMinimumHeight(WIN_WIDTH)
        self.setMinimumWidth(WIN_HEIGHT)

        # Major File Data
        self.idb = None
        self.video = None

        # Time variables
        self.selected_session_time = 0
        self.loaded_video_time = 0
        self.session_start_time = 0
        self.video_fps = 0
        self.video_frames = 0

        # Size variables
        self.video_width = 0
        self.video_height = 0

        # Color variables
        self.gazeColor = None
        self.saccadeColor = None

        # Load DB Button
        self.db_load_button = QtWidgets.QPushButton("Select Database", self)
        self.db_load_button.move(50, 50)
        self.db_load_button.clicked.connect(self.databaseButtonClicked)
        self.db_loaded_text = QtWidgets.QLabel("No Database Loaded", self)
        self.db_loaded_text.move(50, 75)

        # Session List
        self.session_list = QtWidgets.QListWidget(self)
        self.session_list.move(200, 75)
        self.session_list.itemClicked.connect(self.sessionLoadClicked)
        self.session_list_text = QtWidgets.QLabel("Sessions", self)
        self.session_list_text.move(200, 50)

        # Fixation Run List
        self.fixation_runs_list = QtWidgets.QListWidget(self)
        self.fixation_runs_list.move(500, 75)
        self.fixation_runs_list.itemClicked.connect(self.fixationRunClicked)
        self.fixation_runs_list_text = QtWidgets.QLabel("Fixation Runs", self)
        self.fixation_runs_list_text.move(500, 50)

        # Draw Fixation Gazes Checkbox
        self.draw_fixation_gazes_box = QtWidgets.QCheckBox("Mark Gaze Fixations",self)
        self.draw_fixation_gazes_box.move(650, 300)
        self.draw_fixation_gazes_box.setChecked(True)

        # Draw Saccade Checkbox
        self.draw_saccade_box = QtWidgets.QCheckBox("Mark Saccades",self)
        self.draw_saccade_box.move(650, 325)
        self.draw_saccade_box.setChecked(True)

        # Load Video Button
        self.video_load_button = QtWidgets.QPushButton("Select Video", self)
        self.video_load_button.move(50, 300)
        self.video_load_button.clicked.connect(self.videoLoadClicked)
        self.video_loaded_text = QtWidgets.QLabel("No Video Loaded", self)
        self.video_loaded_text.move(50, 325)

        # Start Video Calculation Button
        self.start_video_button = QtWidgets.QPushButton("Start Visualization", self)
        self.start_video_button.move(675, 750)
        self.start_video_button.clicked.connect(self.startVideoClicked)

        # Load Gaze Color Picker Button (moved left to align with saccade button)
        self.color_picker_button = QtWidgets.QPushButton("Choose Gaze color", self)
        self.color_picker_button.move(30, 175) 
        self.color_picker_button.clicked.connect(self.gazePickerClicked)
        self.color_picker_text = QtWidgets.QLabel("Default color selected", self)
        self.color_picker_text.move(30, 200)

        # Load Saccade Color Picker Button (moved left to fit)
        self.color_picker_button = QtWidgets.QPushButton("Choose Saccade color", self)
        self.color_picker_button.move(30, 225)
        self.color_picker_button.clicked.connect(self.saccadePickerClicked)
        self.color_picker_text = QtWidgets.QLabel("Default color selected", self)
        self.color_picker_text.move(30, 250)

    def databaseButtonClicked(self): # Load Database
        db_file_path = QtWidgets.QFileDialog.getOpenFileName(self, "Open Database", "Desktop/iTrace/Testing/Visualize", "SQLite Files (*.db3 *.db *.sqlite *sqlite3)")[0]
        if(db_file_path == ''):
            return
        try:
            self.idb = iTraceDB(db_file_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            return
        self.db_loaded_text.setText(db_file_path.split("/")[-1])
        self.session_list.clear()
        self.session_list.addItems(self.idb.GetSessions())

    def sessionLoadClicked(self, item):  # Select Session
        session_id = int(item.text().split(" - ")[1])

        self.fixation_runs_list.clear()
        self.fixation_runs_list.addItems(self.idb.GetFixationRuns(session_id))

        self.selected_session_time = self.idb.GetSessionTimeLength(session_id)
        self.session_start_time = self.idb.GetSessionStartTime(session_id)

    def fixationRunClicked(self, item):  # Select Fixation (Doesn't currently do anything extra)
        pass

    def videoLoadClicked(self): # Load Video
        video_file_path = QtWidgets.QFileDialog.getOpenFileName(self, "Open Database", "", "Video Files (*.flv *.mp4 *.mov *.mkv);;All Files (*.*)")[0]
        if(video_file_path == ''):
            return

        self.video = cv2.VideoCapture(video_file_path)
        if(not self.video.isOpened()):  # Starts to draw on the video
            QtWidgets.QMessageBox.critical(self, "Error", "Error loading video file")
            self.video = None
            return

        self.video_loaded_text.setText(video_file_path.split("/")[-1])
        self.video_fps = int(self.video.get(cv2.CAP_PROP_FPS))
        self.video_height = int(self.video.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.video_width = int(self.video.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.video_frames = int(self.video.get(cv2.CAP_PROP_FRAME_COUNT))
        self.loaded_video_time = self.video_frames / self.video_fps

    def startVideoClicked(self):
        if len(self.session_list.selectedItems()) == 0 or self.video is None:
            QtWidgets.QMessageBox.critical(self, "Error", "You are missing a required component")
            return
        if not self.doSessionVideoTimesMatch():
            dlg = ConfirmDialog(self, "Mismatched Lengths", "The session length does not seem to match the video length. Continue anywway?")
            if dlg.exec():
                pass
            else:
                return

        start = time.time()



        # Get Array of Frames
        #t = time.time()
        #print("Gathering Frames, ",end="")
        #frames = {}
        #stamp = self.session_start_time
        #step = (1 / self.video.get(cv2.CAP_PROP_FPS)) * 1000
        #while True:
        #    ret, img = self.video.read()
        #    if ret:
        #        frames[stamp] = img
        #        for i in range(VID_SCALE-1):
        #            frames[stamp+((step/VID_SCALE)*(i+1))] = img.copy()
        #        stamp += step
        #    else:
        #        break
        #print("Len:",len(frames),"Elapsed:",time.time()-t)

        t = time.time()
        print("Gathering Gazes, ",end="")
        session_id = int(self.session_list.selectedItems()[0].text().split(" - ")[1])
        gaze_tups = self.idb.GetAllSessionGazes(session_id)
        gazes = [Gaze(tup) for tup in gaze_tups]
        print("Len:",len(gazes),"Elapsed:",time.time()-t)


        fixations = None
        if(len(self.fixation_runs_list.selectedItems()) != 0):
            t = time.time()
            print("Gathering Fixations, ",end="")
            fixation_run_id = int(self.fixation_runs_list.selectedItems()[0].text().split(" - ")[1])
            fixation_tups = self.idb.GetAllRunFixations(fixation_run_id)
            fixations = [Fixation(tup) for tup in fixation_tups]
            print("Len:",len(fixations),"Elapsed:",time.time()-t)

        fixation_gazes = None
        if self.draw_fixation_gazes_box.isChecked():
            t = time.time()
            print("Gathering Fixation Gazes, ",end="")
            fixation_gazes = self.idb.GetAllFixationGazes(fixations)
            print("Len:",len(fixation_gazes),"Elapsed:",time.time()-t)

        saccades = None
        if self.draw_saccade_box.isChecked():
            t = time.time()
            print("Gathering Saccades, ",end="")
            saccades = GetSaccadesOfGazesAndFixationGazes(self.idb, gazes, fixation_gazes if fixation_gazes is not None else self.idb.GetAllFixationGazes(fixations))
            print("Len:",len(saccades),"Elapsed:",time.time()-t)


        self.outputVideo(gazes=gazes, fixations=fixations, fixation_gazes=fixation_gazes, saccades=saccades)

        print("DONE! Time elapsed:", time.time()-start, "secs")

    def gazePickerClicked(self): # Show color picker dialog/save color option
        dialog = QtWidgets.QColorDialog(self)
        if self.gazeColor:
            dialog.setCurrentColor(QtGui.QColor(ConvertColorTupleToString(self.gazeColor)))
        if dialog.exec():
            self.setGazeColor(dialog.currentColor().name())

    def setGazeColor(self, color): # Sets color option
        if color != self.gazeColor:
            self.gazeColor = ConvertColorStringToTuple(color)
            print(self.gazeColor)

    def saccadePickerClicked(self): # Show color picker dialog/save color option
        dialog = QtWidgets.QColorDialog(self)
        if self.saccadeColor:
            dialog.setCurrentColor(QtGui.QColor(ConvertColorTupleToString(self.saccadeColor)))
        if dialog.exec():
            self.setSaccadeColor(dialog.currentColor().name())

    def setSaccadeColor(self, color): # Sets color option
        if color != self.saccadeColor:
            self.saccadeColor = ConvertColorStringToTuple(color)

    def draw_circle(self, frame, cx, cy, radius, bgr, transparency):
        for x in range(cx-radius, cx+radius):
            for y in range(cy-radius, cy+radius):
                if math.dist([x, y], [cx, cy]) < radius and x >= 0 and y >= 0 and x < frame.shape[1] and y < frame.shape[0]:
                    b = frame[int(y), int(x), 0] * (100 - transparency) / 100  + bgr[0] * transparency / 100 # get B value
                    g = frame[int(y), int(x), 1] * (100 - transparency) / 100  + bgr[1] * transparency / 100 # get G value
                    r = frame[int(y), int(x), 2] * (100 - transparency) / 100  + bgr[2] * transparency / 100 # get R value

                    transparent_bgr = [b,g,r]

                    frame[y, x] = transparent_bgr

    # Returns true if the session time and video time are within a second of each other
    def doSessionVideoTimesMatch(self):
        return abs(self.selected_session_time - self.loaded_video_time) < 1

    # Creates the output video given the input parameters:

        # gazes - List of Gazes - REQUIRED
        # fixations - List of Fixations
        # fixation_gazes - Dictionary of fixation_ids to fixation_gazes
        # saccades - List of list of gazes making up a Saccade
        # replay data - List of mouse and keyboard inputs
        # archive_data - XML data of the srcML Archive File
    def outputVideo(self, gazes, fixations=None, fixation_gazes = None, saccades=None, replay_data=None, archive_data=None):

        VID_SCALE = 1  # INCREASING THIS CAN CAUSE MEMORY ISSUES.
                       # A 1:41 minute video will use over
                       # 100 GB of RAM if scale is above 3

        print("Writing Video")
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        video_out = cv2.VideoWriter("output.mp4", fourcc, self.video_fps, (self.video_width, self.video_height))

        video_len = int(self.video.get(cv2.CAP_PROP_FRAME_COUNT)) * VID_SCALE

        stamp = self.session_start_time
        step = (1 / self.video.get(cv2.CAP_PROP_FPS)) * 1000

        current_gaze = 0
        begin_gaze_window = 0
        current_fixation = 0 if len(fixations) != 0 else -1
        begin_fixation_window = current_fixation
        current_saccade = 0 if saccades != None and len(saccades) != 0 else -1

        count = 0
        write_loop_time = time.time()
        while True:
            if time.time() - write_loop_time > 15:
                write_loop_time = time.time()
                print(f'{round(count/video_len*100,2)}%')

            ret, img = self.video.read()
            if ret:

                for i in range(VID_SCALE):
                    use_stamp = stamp+((step/VID_SCALE)*(i))
                    use_img = img.copy()
                    # Draw Fixations
                    if current_fixation != -1:
                        current_fixation, begin_fixation_window = self.draw_fixation(use_img, use_stamp, current_fixation, fixations, fixation_gazes, begin_fixation_window)
                    # Draw Saccades
                    if current_saccade != -1:
                        current_saccade = self.draw_saccade(use_img, use_stamp, current_saccade, saccades)
                    # Draw Gazes
                    if current_gaze != -1:
                        current_gaze, begin_gaze_window = self.draw_gaze(use_img, use_stamp, current_gaze, gazes, begin_gaze_window)

                    video_out.write(use_img)
                    count += 1

                stamp += step
            else:
                break



        video_out.release()


    def draw_fixation(self, frame, timestamp, current_fixation, fixations, fixation_gazes, begin_fixation_window):
        begin_time_stamp = timestamp - ROLLING_WIN_SIZE

        if current_fixation < len(fixations):
            check_fix = fixations[current_fixation]
            check_fix_time = ConvertWindowsTime(check_fix.fixation_start_event_time) + check_fix.duration

            check_begin_fix = fixations[begin_fixation_window]
            check_begin_fix_time = ConvertWindowsTime(check_begin_fix.fixation_start_event_time) + check_begin_fix.duration
            # find the new current fixation to print
            while check_fix_time <= timestamp:
                current_fixation += 1
                check_fix = fixations[current_fixation]
                check_fix_time = ConvertWindowsTime(check_fix.fixation_start_event_time) + check_fix.duration
            # Find the new beginning of rolling window:
            if begin_time_stamp > 0:
                while check_begin_fix_time <= begin_time_stamp:
                    begin_fixation_window += 1
                    check_begin_fix = fixations[begin_fixation_window]
                    check_begin_fix_time = ConvertWindowsTime(check_begin_fix.fixation_start_event_time) + check_begin_fix.duration

            transparency_increment = 100 / (current_fixation + 1 - begin_fixation_window) # Amount to increment
            transparency = int(transparency_increment) # Percentage value

            # Draw fixations in the rolling window
            for i in fixations[begin_fixation_window: current_fixation+1]:
                try:
                    if(int(i.x) < frame.shape[0] and int(i.y) < frame.shape[1] and int(i.x) > 0 and int(i.y) > 0):
                        self.draw_circle(frame, (int(i.x)), (int(i.y)), FIXATION_RADIUS, [0, 0, 255], transparency)
                        #cv2.circle(frame, (int(i.x), int(i.y)), 10, (b, g, r), 2)
                        #self.draw_circle(frame, int(i.x), int(i.y), FIXATION_RADIUS, [b, g, r])
                    if(transparency + transparency_increment < 100): # Increase transparency until 100%
                        transparency += transparency_increment 
                except ValueError:
                    pass
            
            # move the fixation_gazes into the draw gazes. check if the gazes are part of a fixation_gazes and then change color

            # Check if too early to draw
            #if ConvertWindowsTime(check_fix.fixation_start_event_time) <= timestamp:
                # Draw Fixation Gazes first if wanted
                #if fixation_gazes is not None:
                #    for fixation_gaze in fixation_gazes[check_fix.fixation_id]:
                #        gaze = Gaze(self.idb.GetGazeFromEventTime(fixation_gaze[1]))
                #        try:
                #            cv2.circle(frame, (int(gaze.x), int(gaze.y)), 2, (32, 128, 2), 2)
                #        except ValueError:
                #            pass
                # Then draw Fixation
                #try:
            #        cv2.circle(frame, (int(check_fix.x), int(check_fix.y)), 10, (0, 0, 255), 2)
            #    except ValueError:
            #        pass
            return current_fixation, begin_fixation_window
        else:
            return -1, -1

    def draw_gaze(self, frame, timestamp, current_gaze, gazes, begin_gaze_window): # returns the next gaze number
        begin_time_stamp = timestamp - ROLLING_WIN_SIZE
        
        if current_gaze < len(gazes):
            check_gaze = gazes[current_gaze]
            check_gaze_time = check_gaze.system_time
            
            check_begin_gaze = gazes[begin_gaze_window]
            check_begin_gaze_time = check_begin_gaze.system_time
            
            while check_gaze_time <= timestamp:
                current_gaze += 1
                check_gaze = gazes[current_gaze]
                check_gaze_time = check_gaze.system_time
            
            if begin_time_stamp > 0:
                while check_begin_gaze_time <= begin_time_stamp: #loop until the begging gaze is within the timeframe of the rolling window
                    begin_gaze_window += 1
                    check_begin_gaze = gazes[begin_gaze_window]
                    check_begin_gaze_time = check_begin_gaze.system_time
            
            transparency_increment = 100 / (current_gaze + 1 - begin_gaze_window) # Amount to increment
            transparency = int(transparency_increment) # Percentage value
            for i in gazes[begin_gaze_window: current_gaze + 1]:
                try: 
                    self.draw_circle(frame, (int(i.x)), (int(i.y)), GAZE_RADIUS, self.gazeColor, transparency)
                    # self.draw_circle(frame, (int(i.x)), (int(i.y)), GAZE_RADIUS, [255,255,0])
                    # cv2.circle(frame, (int(i.x), int(i.y)), 2, (255, 255, 0))
                    if(transparency + transparency_increment < 100): # Increase transparency until 100%
                        transparency += transparency_increment 
                except ValueError:
                    pass
            
            return current_gaze, begin_gaze_window
        else:
            return -1, -1

    def draw_saccade(self, frame, timestamp, current_saccade, saccades):
        if current_saccade < len(saccades):
            check_saccade = saccades[current_saccade]
            check_saccade_time = check_saccade[-1].system_time
            while check_saccade_time <= timestamp:
                current_saccade += 1
                check_saccade = saccades[current_saccade]
                check_saccade_time = check_saccade[-1].system_time
            if check_saccade[0].system_time <= timestamp:
                for i in range(len(check_saccade)-1):
                    cv2.line(frame, (int(check_saccade[i].x), int(check_saccade[i].y)), (int(check_saccade[i+1].x), int(check_saccade[i+1].y)), self.saccadeColor, 2)
            return current_saccade
        else:
            return -1    
    
    def __HOLDER__(self):

        keys = list(video_frames.keys())

        current_frame = 0
        current_gaze = 0
        current_fixation = 0
        current_saccade = 0

        print("Drawing on frames")
        loop_time = time.time()
        while current_frame < len(keys) - 1:
            current_frame_time = keys[current_frame]
            if(time.time() - loop_time >= 15):
                print(f'{current_frame / len(keys) * 100}%')
                loop_time = time.time()

            #Saccades
            if saccades is not None and current_saccade < len(saccades):
                check_saccade = saccades[current_saccade]
                check_saccade_time = check_saccade[-1].system_time
                while check_saccade_time <= current_frame_time:
                    current_saccade += 1
                    check_saccade = saccades[current_saccade]
                    check_saccade_time = check_saccade[-1].system_time
                if check_saccade[0].system_time <= current_frame_time:
                    for i in range(len(check_saccade)-1):
                        cv2.line(video_frames[keys[current_frame]], (int(check_saccade[i].x), int(check_saccade[i].y)), (int(check_saccade[i+1].x), int(check_saccade[i+1].y)), (255,255,255), 2)

            #Gazes
            if current_gaze < len(gazes):
                check_gaze = gazes[current_gaze]
                check_gaze_time = check_gaze.system_time
                while check_gaze_time <= current_frame_time:
                    current_gaze += 1
                    check_gaze = gazes[current_gaze]
                    check_gaze_time = check_gaze.system_time
                try:
                    cv2.circle(video_frames[keys[current_frame]], (int(check_gaze.x), int(check_gaze.y)), 2, (255, 255, 0), 2)
                except ValueError:
                    pass
                    #print("Gaze",current_gaze,"is NaN")

            current_frame += 1

if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    window = MyWidget()
    window.resize(WIN_WIDTH, WIN_HEIGHT)
    window.show()
    sys.exit(app.exec())
