# This Python file uses the following encoding: utf-8
import sys
import cv2
import time
import numpy as np
import math

from iTraceDB import iTraceDB
from EyeDataTypes import Gaze, Fixation
from TextDetector import get_text_boxes, highlight_frame

from PySide6 import QtCore, QtWidgets, QtGui

import ctypes
myappid = 'mycompany.myproduct.subproduct.version' # arbitrary string
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

WIN_WIDTH, WIN_HEIGHT = 800, 500
DEFAULT_ROLLING_WIN_SIZE = 1000 # Size of rolling window in miliseconds
DEFAULT_GAZE_RADIUS = 5
DEFAULT_FIXATION_RADIUS = 5
DEFAULT_VID_SCALE = 1 # INCREASING THIS CAUSES THE VIDEO TO BECOME MUCH LONGER, AND HAVE MUCH MORE DETAIL

# Converts color string (rgb) to color tuple (bgr)
def ConvertColorStringToTuple(color: "#XXXXXX") -> tuple[int]:
    color = color[1:]
    b = int(color[4:6],base=16)
    g = int(color[2:4],base=16)
    r = int(color[0:2],base=16)
    return (b,g,r)

# converts color tuple (bgr) to color string (rgb)
def ConvertColorTupleToString(color: tuple[int]) -> "#XXXXXX":
    return "#"+str(hex(color[2]))[2:].zfill(2)+str(hex(color[1]))[2:].zfill(2)+str(hex(color[0]))[2:].zfill(2)

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

        self.ROLLING_WIN_SIZE = DEFAULT_ROLLING_WIN_SIZE
        self.GAZE_RADIUS = DEFAULT_GAZE_RADIUS
        self.FIXATION_RADIUS = DEFAULT_FIXATION_RADIUS
        self.VID_SCALE = DEFAULT_VID_SCALE

        self.setWindowTitle("iTrace Visualization")
        self.setMinimumHeight(WIN_HEIGHT)
        self.setMinimumWidth(WIN_WIDTH)
        self.setWindowIcon(QtGui.QIcon("Visualize.png"))

        # Major File Data
        self.idb = None
        self.video = None
        self.dejavu = None

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
        self.gazeColor = (255,255,0)
        self.saccadeColor = (255,255,255)
        self.fixationColor = (0,0,255)
        self.highlightColor = (255,0,0)

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

        # # Draw Fixation Gazes Checkbox
        # self.draw_fixation_gazes_box = QtWidgets.QCheckBox("Mark Gaze Fixations",self)
        # self.draw_fixation_gazes_box.move(620, 300)
        # self.draw_fixation_gazes_box.setChecked(True)

        # Load Video Button
        self.video_load_button = QtWidgets.QPushButton("Select Video", self)
        self.video_load_button.move(50, 300)
        self.video_load_button.clicked.connect(self.videoLoadClicked)
        self.video_loaded_text = QtWidgets.QLabel("No Video Loaded", self)
        self.video_loaded_text.move(50, 325)

        # # Select DejaVu Button
        # self.dejavu_load_button = QtWidgets.QPushButton("Select Replay Data", self)
        # self.dejavu_load_button.move(150,300)
        # self.dejavu_load_button.clicked.connect(self.dejavuLoadClicked)
        # self.dejavu_loaded_text = QtWidgets.QLabel("No Data Loaded", self)
        # self.dejavu_loaded_text.move(150, 325)

        # Start Video Calculation Button
        self.start_video_button = QtWidgets.QPushButton("Start Visualization", self)
        self.start_video_button.move(25, 410)
        self.start_video_button.clicked.connect(self.startVideoClicked)

        # Colors
        ## Gaze Color Picker Button
        self.color_picker_button_gaze = QtWidgets.QPushButton("Gaze color", self)
        self.color_picker_button_gaze.move(30, 175) 
        self.color_picker_button_gaze.clicked.connect(self.gazePickerClicked)
        self.color_picker_text_gaze = QtWidgets.QLabel("", self)
        self.color_picker_text_gaze.setStyleSheet(f"QLabel {{ background-color : {ConvertColorTupleToString(self.gazeColor)}; }}")
        self.color_picker_text_gaze.setGeometry(115, 175, 23, 23)
        ## Saccade Color Picker Button
        self.color_picker_button_saccade = QtWidgets.QPushButton("Saccade color", self)
        self.color_picker_button_saccade.move(30, 200)
        self.color_picker_button_saccade.clicked.connect(self.saccadePickerClicked)
        self.color_picker_text_saccade = QtWidgets.QLabel("", self)
        self.color_picker_text_saccade.setStyleSheet(f"QLabel {{ background-color : {ConvertColorTupleToString(self.saccadeColor)}; }}")
        self.color_picker_text_saccade.setGeometry(115, 200, 23, 23)
        ## Fixation Color Picker Button
        self.color_picker_button_fixation = QtWidgets.QPushButton("Fixation color", self)
        self.color_picker_button_fixation.move(30, 225)
        self.color_picker_button_fixation.clicked.connect(self.fixationPickerClicked)
        self.color_picker_text_fixation = QtWidgets.QLabel("", self)
        self.color_picker_text_fixation.setStyleSheet(f"QLabel {{ background-color : {ConvertColorTupleToString(self.fixationColor)}; }}")
        self.color_picker_text_fixation.setGeometry(115, 225, 23, 23)
        ## Highlighting Color Picker Button
        self.color_picker_button_highlight = QtWidgets.QPushButton("Highlight color", self)
        self.color_picker_button_highlight.move(30, 250)
        self.color_picker_button_highlight.clicked.connect(self.highlightPickerClicked)
        self.color_picker_text_highlight = QtWidgets.QLabel("", self)
        self.color_picker_text_highlight.setStyleSheet(f"QLabel {{ background-color : {ConvertColorTupleToString(self.highlightColor)}; }}")
        self.color_picker_text_highlight.setGeometry(115, 250, 23, 23)

        # Progress Bar
        self.progress_bar = QtWidgets.QProgressBar(self)
        self.progress_bar.setGeometry(25,450,200,25)
        self.elapsed_time_text = QtWidgets.QLabel("00:00:00",self)
        self.elapsed_time_text.move(130,415)

        # Options
        ## Label
        self.options_text = QtWidgets.QLabel("Options",self)
        self.options_text.move(620,275)
        self.options_text.setStyleSheet("font-weight: bold");
        ## Highlighting Checkbox
        self.highlight_box = QtWidgets.QCheckBox("Highlight Lines",self)
        self.highlight_box.move(620, 300)
        self.highlight_box.setChecked(True)
        ## Draw Saccade Checkbox
        self.draw_saccade_box = QtWidgets.QCheckBox("Mark Saccades",self)
        self.draw_saccade_box.move(620, 325)
        self.draw_saccade_box.setChecked(True)
        ## Fade Delay
        self.fade_delay_box = QtWidgets.QLineEdit(self)
        self.fade_delay_box.setGeometry(620,350,25,20)
        self.fade_delay_box.setValidator(QtGui.QIntValidator())
        self.fade_delay_box.setText(str(DEFAULT_ROLLING_WIN_SIZE//1000))
        self.fade_delay_text = QtWidgets.QLabel("Fade Delay (seconds)",self)
        self.fade_delay_text.move(650,350)
        ## Video Stretch
        self.video_stretch_box = QtWidgets.QLineEdit(self)
        self.video_stretch_box.setGeometry(620,375,25,20)
        self.video_stretch_box.setValidator(QtGui.QIntValidator())
        self.video_stretch_box.setText(str(DEFAULT_VID_SCALE))
        self.video_stretch_text = QtWidgets.QLabel("Video Stretch Factor",self)
        self.video_stretch_text.move(650,375)
        ## Gaze Radius
        self.gaze_radius_box = QtWidgets.QLineEdit(self)
        self.gaze_radius_box.setGeometry(620,400,25,20)
        self.gaze_radius_box.setValidator(QtGui.QIntValidator())
        self.gaze_radius_box.setText(str(DEFAULT_GAZE_RADIUS))
        self.gaze_radius_text = QtWidgets.QLabel("Gaze Radius (pixels)",self)
        self.gaze_radius_text.move(650,400)
        ## Base Fixation Radius
        self.base_fixation_radius_box = QtWidgets.QLineEdit(self)
        self.base_fixation_radius_box.setGeometry(620,425,25,20)
        self.base_fixation_radius_box.setValidator(QtGui.QIntValidator())
        self.base_fixation_radius_box.setText(str(DEFAULT_FIXATION_RADIUS))
        self.base_fixation_radius_text = QtWidgets.QLabel("Base Fixation Radius (pixels)",self)
        self.base_fixation_radius_text.move(650,425)



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
        self.fixation_runs_list.clear()
        self.session_list.addItems(self.idb.GetSessions())

    def sessionLoadClicked(self, item):  # Select Session
        session_id = int(item.text().split(" - ")[1])

        self.fixation_runs_list.clear()
        self.fixation_runs_list.addItems(self.idb.GetFixationRuns(session_id))

        self.selected_session_time = self.idb.GetSessionTimeLength(session_id)
        self.session_start_time = self.idb.GetSessionStartTime(session_id)

    def fixationRunClicked(self, item):  # Select Fixation Run (Doesn't currently do anything extra)
        pass

    def videoLoadClicked(self): # Load Video
        video_file_path = QtWidgets.QFileDialog.getOpenFileName(self, "Open Database", "", "Video Files (*.flv *.mp4 *.mov *.mkv);;All Files (*.*)")[0]
        if(video_file_path == ''):
            return
        if(self.video):
            self.video.release()

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
        self.video_path = video_file_path

    def dejavuLoadClicked(self):
        dejavu_file_path = QtWidgets.QFileDialog.getOpenFileName(self, "Open DejaVu Data", "", "DejaVu Files (*.csv);;All Files (*.*)")[0]
        if(dejavu_file_path == ''):
            self.dejavu = None
            return

        with open(dejavu_file_path,'r') as dv_file:
            self.dejavu = dv_file.read().splitlines()

        self.dejavu_loaded_text.setText(dejavu_file_path.split("/")[-1])

    def startVideoClicked(self):
        # Ensure enough data
        if len(self.session_list.selectedItems()) == 0 or self.video is None:
            QtWidgets.QMessageBox.critical(self, "Error", "You are missing a required component")
            return
        # Ensure video matches
        if not self.doSessionVideoTimesMatch():
            dlg = ConfirmDialog(self, "Mismatched Lengths", "The session length does not seem to match the video length. Continue anywway?")
            if dlg.exec():
                pass
            else:
                return

        session_id = int(self.session_list.selectedItems()[0].text().split(" - ")[1])

        # If dejavu, ensure it matches
        if self.dejavu and int(self.dejavu[0].split(",")[1]) != session_id:
            dlg = ConfirmDialog(self, "Differing Dejavu Data", "The selected DejaVu data appears to come from a different session. Continue anywway?")
            if dlg.exec():
                pass
            else:
                return

        output_file_name, _ = QtWidgets.QFileDialog.getSaveFileName(self,"Save Video","","MP4(*.mp4)")
        if not output_file_name:
            return

        self.ROLLING_WIN_SIZE = int(self.fade_delay_box.text()) * 1000
        self.GAZE_RADIUS = int(self.gaze_radius_box.text())
        self.FIXATION_RADIUS = int(self.base_fixation_radius_box.text())
        self.VID_SCALE = int(self.video_stretch_box.text())

        t = time.time()
        print("Gathering Gazes, ",end="")
        
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
        if False: #self.draw_fixation_gazes_box.isChecked():
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

        if self.dejavu:
            print("Gathering Replay Data, Len:",len(self.dejavu))

        self.outputVideo(output_file_name, gazes=gazes, fixations=fixations, fixation_gazes=fixation_gazes, saccades=saccades, replay_data=self.dejavu)
        self.progress_bar.reset()

    def gazePickerClicked(self): # Show color picker dialog/save color option
        dialog = QtWidgets.QColorDialog(self)
        if self.gazeColor:
            dialog.setCurrentColor(QtGui.QColor(ConvertColorTupleToString(self.gazeColor)))
        if dialog.exec():
            self.setGazeColor(dialog.currentColor().name())

    def setGazeColor(self, color): # Sets color option
        if color != self.gazeColor:
            self.gazeColor = ConvertColorStringToTuple(color)
            self.color_picker_text_gaze.setStyleSheet(f"QLabel {{ background-color : {ConvertColorTupleToString(self.gazeColor)}; }}")

    def saccadePickerClicked(self): # Show color picker dialog/save color option
        dialog = QtWidgets.QColorDialog(self)
        if self.saccadeColor:
            dialog.setCurrentColor(QtGui.QColor(ConvertColorTupleToString(self.saccadeColor)))
        if dialog.exec():
            self.setSaccadeColor(dialog.currentColor().name())

    def setSaccadeColor(self, color): # Sets color option
        if color != self.saccadeColor:
            self.saccadeColor = ConvertColorStringToTuple(color)
            self.color_picker_text_saccade.setStyleSheet(f"QLabel {{ background-color : {ConvertColorTupleToString(self.saccadeColor)}; }}")

    def fixationPickerClicked(self): # Show color picker dialog/save color option
        dialog = QtWidgets.QColorDialog(self)
        if self.fixationColor:
            dialog.setCurrentColor(QtGui.QColor(ConvertColorTupleToString(self.fixationColor)))
        if dialog.exec():
            self.setFixationColor(dialog.currentColor().name())

    def setFixationColor(self, color): # Sets color option
        if color != self.fixationColor:
            self.fixationColor = ConvertColorStringToTuple(color)
            self.color_picker_text_fixation.setStyleSheet(f"QLabel {{ background-color : {ConvertColorTupleToString(self.fixationColor)}; }}")

    def highlightPickerClicked(self): # Show color picker dialog/save color option
        dialog = QtWidgets.QColorDialog(self)
        if self.highlightColor:
            dialog.setCurrentColor(QtGui.QColor(ConvertColorTupleToString(self.highlightColor)))
        if dialog.exec():
            self.setHighlightColor(dialog.currentColor().name())

    def setHighlightColor(self, color): # Sets color option
        if color != self.highlightColor:
            self.highlightColor = ConvertColorStringToTuple(color)
            self.color_picker_text_highlight.setStyleSheet(f"QLabel {{ background-color : {ConvertColorTupleToString(self.highlightColor)}; }}")


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
    def outputVideo(self, output_file_name, gazes, fixations=None, fixation_gazes = None, saccades=None, replay_data=None, archive_data=None):

        start = time.time()

        print("Writing Video")
        fourcc = cv2.VideoWriter_fourcc(*'XVID')
        video_out = cv2.VideoWriter(output_file_name, fourcc, self.video_fps, (self.video_width, self.video_height))

        video_len = int(self.video.get(cv2.CAP_PROP_FRAME_COUNT)) * self.VID_SCALE

        stamp = self.session_start_time
        step = (1 / self.video.get(cv2.CAP_PROP_FPS)) * 1000

        current_gaze = 0
        begin_gaze_window = 0
        current_fixation = 0 if len(fixations) != 0 else -1
        begin_fixation_window = current_fixation
        current_saccade = 0 if saccades != None and len(saccades) != 0 else -1
        current_replay = 1 if replay_data != None and len(replay_data) != 0 else -1

        count = 0
        write_loop_time = time.time()
        prev_img = None
        boxes = None
        while True:
            self.progress_bar.setValue(int(count/video_len*100))
            dt = int(time.time() - start)
            h = dt // (60*60)
            m = (dt - (h*60*60)) // 60
            s = dt - (h*60*60) - (m * 60)
            text = str(h).zfill(2)+":"+str(m).zfill(2)+":"+str(s).zfill(2)
            self.elapsed_time_text.setText(text)

            QtCore.QCoreApplication.processEvents()

            ret, img = self.video.read()
            if ret:
                for i in range(self.VID_SCALE):
                    use_stamp = stamp+((step/self.VID_SCALE)*(i))
                    use_img = img.copy()
                    orig = use_img.copy()

                    # Update text boxes if highlighting
                    if self.highlight_box.isChecked():
                        boxes = get_text_boxes(orig,prev_img,boxes)
                    # Draw Saccades
                    if current_saccade != -1:
                        current_saccade = self.draw_saccade(use_img, use_stamp, current_saccade, saccades)
                    # Draw Gazes
                    if current_gaze != -1:
                        current_gaze, begin_gaze_window = self.draw_gaze(use_img, use_stamp, current_gaze, gazes, begin_gaze_window)
                    # Draw Fixations
                    if current_fixation != -1:
                        current_fixation, begin_fixation_window = self.draw_fixation(use_img, use_stamp, current_fixation, fixations, fixation_gazes, begin_fixation_window, boxes)

                    video_out.write(use_img)
                    count += 1
                    prev_img = orig


                stamp += step
            else:
                break
        self.video.release()
        self.video = cv2.VideoCapture(self.video_path)
        video_out.release()


    def draw_fixation(self, frame, timestamp, current_fixation, fixations, fixation_gazes, begin_fixation_window, boxes):
        begin_time_stamp = timestamp - self.ROLLING_WIN_SIZE

        if current_fixation < len(fixations):
            check_fix = fixations[current_fixation]
            check_fix_time = ConvertWindowsTime(check_fix.fixation_start_event_time) + check_fix.duration

            check_begin_fix = fixations[begin_fixation_window]
            check_begin_fix_time = ConvertWindowsTime(check_begin_fix.fixation_start_event_time) + check_begin_fix.duration
            # find the new current fixation to print
            while check_fix_time <= timestamp:
                current_fixation += 1
                if current_fixation == len(fixations):
                    current_fixation -= 1
                    break
                check_fix = fixations[current_fixation]
                check_fix_time = ConvertWindowsTime(check_fix.fixation_start_event_time) + check_fix.duration
            # Find the new beginning of rolling window:
            if begin_time_stamp > 0:
                while check_begin_fix_time <= begin_time_stamp:
                    begin_fixation_window += 1
                    if begin_fixation_window == len(fixations):
                        begin_fixation_window -= 1
                        break
                    check_begin_fix = fixations[begin_fixation_window]
                    check_begin_fix_time = ConvertWindowsTime(check_begin_fix.fixation_start_event_time) + check_begin_fix.duration

            # Draw fixations in the rolling window
            for i in fixations[begin_fixation_window:current_fixation]:
                try:
                    if(int(i.x) < frame.shape[0] and int(i.y) < frame.shape[1] and int(i.x) > 0 and int(i.y) > 0):
                        self.draw_circle(frame, (int(i.x)), (int(i.y)), self.FIXATION_RADIUS + i.duration // 50, self.fixationColor, ((self.ROLLING_WIN_SIZE - (timestamp - (ConvertWindowsTime(i.fixation_start_event_time)+i.duration))) / self.ROLLING_WIN_SIZE) * 100)
                except ValueError:
                    pass

            self.draw_circle(frame, (int(fixations[current_fixation].x)), (int(fixations[current_fixation].y)), self.FIXATION_RADIUS + int(timestamp - (ConvertWindowsTime(fixations[current_fixation].fixation_start_event_time))) // 50, self.fixationColor, 100)
            if self.highlight_box.isChecked():
                highlight_frame(frame,boxes,fixations[current_fixation],self.highlightColor)
            # move the fixation_gazes into the draw gazes. check if the gazes are part of a fixation_gazes and then change color

            return current_fixation, begin_fixation_window
        else:
            return -1, -1

    def draw_gaze(self, frame, timestamp, current_gaze, gazes, begin_gaze_window): # returns the next gaze number
        begin_time_stamp = timestamp - self.ROLLING_WIN_SIZE
        
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
                    self.draw_circle(frame, (int(i.x)), (int(i.y)), self.GAZE_RADIUS, self.gazeColor, transparency)
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

            current_frame += 1

if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    app.setWindowIcon(QtGui.QIcon("Visualize.png"))
    window = MyWidget()
    window.resize(WIN_WIDTH, WIN_HEIGHT)
    window.show()

    sys.exit(app.exec())
