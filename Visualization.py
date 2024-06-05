# This Python file uses the following encoding: utf-8
import sys
import cv2
import time
import numpy as np
import math
import re
import random
import colorsys
from PIL import Image, ImageFont, ImageDraw

from lxml import etree as ET
from iTraceDB import iTraceDB
from EyeDataTypes import Gaze, Fixation
from TextDetector import get_text_boxes, highlight_frame

from PySide6 import QtCore, QtWidgets, QtGui

import ctypes
myappid = 'mycompany.myproduct.subproduct.version' # arbitrary string
ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)

WIN_WIDTH, WIN_HEIGHT = 950, 465
DEFAULT_ROLLING_WIN_SIZE = 1000 # Size of rolling window in miliseconds
DEFAULT_GAZE_RADIUS = 5
DEFAULT_FIXATION_RADIUS = 5
DEFAULT_VID_SCALE = 1 # INCREASING THIS CAUSES THE VIDEO TO BECOME MUCH LONGER, AND HAVE MUCH MORE DETAIL
DEFAULT_NUM_OF_COLORS = 5

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

def FindMatchingPath(all_files,target_file):
    target_file.replace("\\","/")
    target_file = target_file.lower()
    file_split = target_file.split("/")
    check = file_split[-1]
    
    possible = []
    for file in all_files:
        if file.lower().endswith(check):
            possible.append(file.split("/"))

    if len(possible) == 0:
        return None
    elif len(possible) == 1:
        return "/".join(possible[0])

    shortest = ""
    passes = 1

    while len(possible) != 1:
        candidates = []
        if passes > len(file_split):
            return shortest
        for unit_path in possible:
            if passes > len(unit_path):
                if shortest == "":
                    shortest = "/".join(unit_path)
                continue
            unit_check = unit_path[len(unit_path) - passes].lower()
            file_check = file_split[len(file_split) - passes]
            if unit_check == file_check:
                candidates.append(unit_path)
        possible = candidates
        passes += 1

    if len(possible) == 0:
        return None;
    return "/".join(possible[0])

def GetLineAndCol(element):
    try:
        return (int(element.attrib["{http://www.srcML.org/srcML/position}start"].split(":")[0]),
                int(element.attrib["{http://www.srcML.org/srcML/position}start"].split(":")[1]),
                int(element.attrib["{http://www.srcML.org/srcML/position}end"].split(":")[0]),
                int(element.attrib["{http://www.srcML.org/srcML/position}end"].split(":")[1]))
    except:
        xml_remover = re.compile("<.*?>")
        text = xml_remover.sub('',ET.tostring(element).decode()).replace("&gt;",">").replace("&lt;","<").replace("&amp;","&")
        return (1,1,len(text.split("\n")),max([len(x.rstrip()) for x in text.split("\n")]))

def GetTokenStartPoint(line_start,col_start,elements):
    xml_remover = re.compile("<.*?>")
    for element in elements:
        if type(element) == str:
            s = element
        else:
            s = xml_remover.sub('',ET.tostring(element).decode())
        s = s.replace("&gt;",">").replace("&lt;","<").replace("&amp;","&")
        lines = s.split('\n')
        if len(lines) > 1:
            line_start += len(lines) - 1
            col_start = 0
        col_start += len(lines[-1])
    return line_start, col_start


SINGLE_CHAR_TOKENS = ["{","}","[","]","(",")","'",'"',".",",",";"]
def FindTokenInElement(line,col,element):
    # print("*",line,col)
    xml_remover = re.compile("<.*?>")
    text = xml_remover.sub('',ET.tostring(element).decode()).replace("&gt;",">").replace("&lt;","<").replace("&amp;","&")
    lines = text.split("\n")
    token_line = lines[line - 1]

    if col > len(token_line):
        #return ((line,col),(line,col))
        return

    char = token_line[col - 1]
    if char.isspace():
        return
    elif char in SINGLE_CHAR_TOKENS:
        return ((line,col),(line,col))
    elif char.isalnum():
        mode = "word"
    else:
        mode = "op"

    start = col - 1
    end = col - 1

    # print("|"+char+"|",mode,token_line)

    while token_line[start].isalnum() if mode == "word" else ((not token_line[start].isalnum()) and (not token_line[start].isspace()) and (token_line[start] not in SINGLE_CHAR_TOKENS)):
        start -= 1
        if start < 0:
            start = -1
            break

    while token_line[end].isalnum() if mode == "word" else ((not token_line[end].isalnum()) and (not token_line[end].isspace()) and (token_line[end] not in SINGLE_CHAR_TOKENS)):
        end += 1
        if end > len(token_line) - 1:
            end = len(token_line)
            break
    # print("|"+str(line),str(start),str(end)+"|")
    return ((line,start+2),(line,end))




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
        self.video_idb = None
        self.code_idb = None
        self.graph_idb = None
        self.video = None
        self.dejavu = None
        self.code_srcml = None
        self.graph_srcml = None

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
        self.startColor = (0,0,255)
        self.endColor = (0,255,0)

        # Tabs
        self.tab_widget = QtWidgets.QTabWidget(self)

        self.video_tab = QtWidgets.QWidget()
        self.video_layout = QtWidgets.QGridLayout()
        self.video_tab.setLayout(self.video_layout)

        self.code_tab = QtWidgets.QWidget()
        self.code_layout = QtWidgets.QGridLayout()
        self.code_tab.setLayout(self.code_layout)

        self.graph_tab = QtWidgets.QWidget()
        self.graph_layout = QtWidgets.QGridLayout()
        self.graph_tab.setLayout(self.graph_layout)

        # Inner File Tabs
        self.file_tabs = {}

# Video Tab
############################################################################
        # Load DB Button
        self.video_db_load_button = QtWidgets.QPushButton("Select Database", self)
        self.video_db_load_button.clicked.connect(self.videoDatabaseButtonClicked)
        self.video_db_loaded_text = QtWidgets.QLabel("No Database Loaded", self)
        self.video_layout.addWidget(self.video_db_load_button,1,0)
        self.video_layout.addWidget(self.video_db_loaded_text,0,0)


        self.video_layout.setColumnMinimumWidth(1,23)
        self.video_layout.setColumnMinimumWidth(2,10)

        # Session List
        self.video_session_list = QtWidgets.QListWidget(self)
        self.video_session_list.itemClicked.connect(self.videoSessionLoadClicked)
        self.video_layout.addWidget(self.video_session_list,1,3,10,10)
        self.video_session_list_text = QtWidgets.QLabel("Sessions", self)
        self.video_layout.addWidget(self.video_session_list_text,0,3)
        self.video_layout.setColumnMinimumWidth(9,250)

        # Fixation Run List
        self.video_fixation_runs_list = QtWidgets.QListWidget(self)
        self.video_fixation_runs_list.itemClicked.connect(self.videoFixationRunClicked)
        self.video_layout.addWidget(self.video_fixation_runs_list,1,13,10,10)
        self.video_fixation_runs_list_text = QtWidgets.QLabel("Fixation Runs", self)
        self.video_layout.addWidget(self.video_fixation_runs_list_text,0,13)

        # Colors
        ## Gaze Color Picker Button
        self.color_picker_button_gaze = QtWidgets.QPushButton("Gaze color", self)
        self.color_picker_button_gaze.clicked.connect(self.gazePickerClicked)
        self.video_layout.addWidget(self.color_picker_button_gaze,3,0)
        self.color_picker_text_gaze = QtWidgets.QLabel("", self)
        self.color_picker_text_gaze.setStyleSheet(f"QLabel {{ background-color : {ConvertColorTupleToString(self.gazeColor)}; }}")
        self.color_picker_text_gaze.setGeometry(115, 175, 23, 23)
        self.video_layout.addWidget(self.color_picker_text_gaze,3,1)

        # Saccade Color Picker Button
        self.color_picker_button_saccade = QtWidgets.QPushButton("Saccade color", self)
        self.color_picker_button_saccade.clicked.connect(self.saccadePickerClicked)
        self.video_layout.addWidget(self.color_picker_button_saccade,4,0)
        self.color_picker_text_saccade = QtWidgets.QLabel("", self)
        self.color_picker_text_saccade.setStyleSheet(f"QLabel {{ background-color : {ConvertColorTupleToString(self.saccadeColor)}; }}")
        self.color_picker_text_saccade.setGeometry(115, 200, 23, 23)
        self.video_layout.addWidget(self.color_picker_text_saccade,4,1)

        ## Fixation Color Picker Button
        self.color_picker_button_fixation = QtWidgets.QPushButton("Fixation color", self)
        self.color_picker_button_fixation.clicked.connect(self.fixationPickerClicked)
        self.video_layout.addWidget(self.color_picker_button_fixation,5,0)
        self.color_picker_text_fixation = QtWidgets.QLabel("", self)
        self.color_picker_text_fixation.setStyleSheet(f"QLabel {{ background-color : {ConvertColorTupleToString(self.fixationColor)}; }}")
        self.color_picker_text_fixation.setGeometry(115, 225, 23, 23)
        self.video_layout.addWidget(self.color_picker_text_fixation,5,1)

        ## Highlighting Color Picker Button
        self.color_picker_button_highlight = QtWidgets.QPushButton("Highlight color", self)
        self.color_picker_button_highlight.clicked.connect(self.highlightPickerClicked)
        self.video_layout.addWidget(self.color_picker_button_highlight,6,0)
        self.color_picker_text_highlight = QtWidgets.QLabel("", self)
        self.color_picker_text_highlight.setStyleSheet(f"QLabel {{ background-color : {ConvertColorTupleToString(self.highlightColor)}; }}")
        self.color_picker_text_highlight.setGeometry(115, 250, 23, 23)
        self.video_layout.addWidget(self.color_picker_text_highlight,6,1)

        # Draw Fixation Gazes Checkbox
        # self.draw_fixation_gazes_box = QtWidgets.QCheckBox("Mark Gaze Fixations",self)
        # self.draw_fixation_gazes_box.move(620, 300)
        # self.draw_fixation_gazes_box.setChecked(True)

        # Load Video Button
        self.video_load_button = QtWidgets.QPushButton("Select Video", self)
        self.video_load_button.clicked.connect(self.videoLoadClicked)
        self.video_layout.addWidget(self.video_load_button,11,0)
        self.video_loaded_text = QtWidgets.QLabel("No Video Loaded", self)
        self.video_layout.addWidget(self.video_loaded_text,12,0)

        # # Select DejaVu Button
        # self.dejavu_load_button = QtWidgets.QPushButton("Select Replay Data", self)
        # self.dejavu_load_button.move(150,300)
        # self.dejavu_load_button.clicked.connect(self.dejavuLoadClicked)
        # self.dejavu_loaded_text = QtWidgets.QLabel("No Data Loaded", self)
        # self.dejavu_loaded_text.move(150, 325)

        # Options
        ## Label
        self.options_text = QtWidgets.QLabel("Options",self)
        self.options_text.setStyleSheet("font-weight: bold")
        self.video_layout.addWidget(self.options_text,11,22)

        ## Highlighting Checkbox
        self.highlight_box = QtWidgets.QCheckBox("Highlight Lines",self)
        self.highlight_box.setChecked(True)
        self.video_layout.addWidget(self.highlight_box,12,22)

        ## Draw Saccade Checkbox
        self.draw_saccade_box = QtWidgets.QCheckBox("Mark Saccades",self)
        self.draw_saccade_box.setChecked(True)
        self.video_layout.addWidget(self.draw_saccade_box,13,22)

        ## Fade Delay
        self.fade_delay_box = QtWidgets.QLineEdit(self)
        self.fade_delay_box.setGeometry(620,350,25,20)
        self.fade_delay_box.setValidator(QtGui.QIntValidator())
        self.fade_delay_box.setText(str(DEFAULT_ROLLING_WIN_SIZE//1000))
        self.video_layout.addWidget(self.fade_delay_box,14,21)
        self.fade_delay_text = QtWidgets.QLabel("Fade Delay (seconds)",self)
        self.video_layout.addWidget(self.fade_delay_text,14,22)

        ## Video Stretch
        self.video_stretch_box = QtWidgets.QLineEdit(self)
        self.video_stretch_box.setGeometry(620,375,25,20)
        self.video_stretch_box.setValidator(QtGui.QIntValidator())
        self.video_stretch_box.setText(str(DEFAULT_VID_SCALE))
        self.video_layout.addWidget(self.video_stretch_box,15,21)
        self.video_stretch_text = QtWidgets.QLabel("Video Stretch Factor",self)
        self.video_layout.addWidget(self.video_stretch_text,15,22)

        ## Gaze Radius
        self.gaze_radius_box = QtWidgets.QLineEdit(self)
        self.gaze_radius_box.setGeometry(620,400,25,20)
        self.gaze_radius_box.setValidator(QtGui.QIntValidator())
        self.gaze_radius_box.setText(str(DEFAULT_GAZE_RADIUS))
        self.video_layout.addWidget(self.gaze_radius_box,16,21)
        self.gaze_radius_text = QtWidgets.QLabel("Gaze Radius (pixels)",self)
        self.video_layout.addWidget(self.gaze_radius_text,16,22)

        ## Base Fixation Radius
        self.base_fixation_radius_box = QtWidgets.QLineEdit(self)
        self.base_fixation_radius_box.setGeometry(620,425,25,20)
        self.base_fixation_radius_box.setValidator(QtGui.QIntValidator())
        self.base_fixation_radius_box.setText(str(DEFAULT_FIXATION_RADIUS))
        self.video_layout.addWidget(self.base_fixation_radius_box,17,21)
        self.base_fixation_radius_text = QtWidgets.QLabel("Base Fixation Radius (pixels)",self)
        self.video_layout.addWidget(self.base_fixation_radius_text,17,22)

        # Start Video Calculation Button
        self.start_video_button = QtWidgets.QPushButton("Start Visualization", self)
        self.start_video_button.clicked.connect(self.startVideoClicked)
        self.video_layout.addWidget(self.start_video_button,16,0)

        # Progress Bar
        self.progress_bar = QtWidgets.QProgressBar(self)
        # self.progress_bar.setGeometry(25,450,200,25)
        self.video_layout.addWidget(self.progress_bar,17,0,1,4)
        self.elapsed_time_text = QtWidgets.QLabel("00:00:00",self)
        self.video_layout.addWidget(self.elapsed_time_text,16,1,1,3)

# Heatmap Tab
############################################################################

        # DB Button
        self.code_db_load_button = QtWidgets.QPushButton("Select Database", self)
        self.code_db_load_button.clicked.connect(self.codeDatabaseButtonClicked)
        self.code_db_loaded_text = QtWidgets.QLabel("No Database Loaded", self)
        self.code_layout.addWidget(self.code_db_load_button,1,0)
        self.code_layout.addWidget(self.code_db_loaded_text,0,0)

        self.code_layout.setRowMinimumHeight(2,10)

        self.time_process_box = QtWidgets.QCheckBox("Process Time",self)
        self.time_process_box.setChecked(False)
        self.code_layout.addWidget(self.time_process_box,2,0)

        self.average_runs = QtWidgets.QCheckBox("Average Runs",self)
        self.average_runs.setChecked(False)
        self.code_layout.addWidget(self.average_runs,3,0)

        # srcML Button
        self.code_srcml_load_button = QtWidgets.QPushButton("Select srcML Archive", self)
        self.code_srcml_load_button.clicked.connect(self.codeSrcmlButtonClicked)
        self.code_srcml_loaded_text = QtWidgets.QLabel("No srcML Loaded",self)
        self.code_layout.addWidget(self.code_srcml_load_button,5,0)
        self.code_layout.addWidget(self.code_srcml_loaded_text,4,0)


        # Number of colors
        self.color_number_box = QtWidgets.QLineEdit(self)
        self.color_number_box.setMaximumWidth(23)
        self.color_number_box.setGeometry(620,400,25,20)
        self.color_number_box.setValidator(QtGui.QIntValidator())
        self.color_number_box.setText(str(DEFAULT_NUM_OF_COLORS))
        self.code_layout.addWidget(self.color_number_box,8,1)
        self.color_number_text = QtWidgets.QLabel("# of colors",self)
        self.code_layout.addWidget(self.color_number_text,8,0)

        self.code_layout.setRowMinimumHeight(9,10)

        # Process Button
        self.process_code_button = QtWidgets.QPushButton("Process Image",self)
        self.process_code_button.clicked.connect(self.generateCodeHeatmap)
        self.code_layout.addWidget(self.process_code_button,10,0)

        # Session List
        self.code_session_list = QtWidgets.QListWidget(self)
        self.code_session_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        self.code_session_list.itemClicked.connect(self.codeSessionLoadClicked)
        self.code_layout.addWidget(self.code_session_list,1,3,10,10)
        self.code_session_list_text = QtWidgets.QLabel("Sessions", self)
        self.code_layout.addWidget(self.code_session_list_text,0,3)

        # Fixation Run List
        self.code_fixation_runs_list = QtWidgets.QListWidget(self)
        self.code_fixation_runs_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        self.code_fixation_runs_list.itemClicked.connect(self.codeFixationRunClicked)
        self.code_layout.addWidget(self.code_fixation_runs_list,1,13,10,10)
        self.code_fixation_runs_list_text = QtWidgets.QLabel("Fixation Runs", self)
        self.code_layout.addWidget(self.code_fixation_runs_list_text,0,13)



# Graph Tab
############################################################################
        # DB Button
        self.graph_db_load_button = QtWidgets.QPushButton("Select Database", self)
        self.graph_db_load_button.clicked.connect(self.graphDatabaseButtonClicked)
        self.graph_db_loaded_text = QtWidgets.QLabel("No Database Loaded", self)
        self.graph_layout.addWidget(self.graph_db_load_button,1,0)
        self.graph_layout.addWidget(self.graph_db_loaded_text,0,0)

        # srcML Button
        self.graph_srcml_load_button = QtWidgets.QPushButton("Select srcML Archive", self)
        self.graph_srcml_load_button.clicked.connect(self.graphSrcmlButtonClicked)
        self.graph_srcml_loaded_text = QtWidgets.QLabel("No srcML Loaded",self)
        self.graph_layout.addWidget(self.graph_srcml_load_button,5,0)
        self.graph_layout.addWidget(self.graph_srcml_loaded_text,4,0)

        # Session List
        self.graph_session_list = QtWidgets.QListWidget(self)
        self.graph_session_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        self.graph_session_list.itemClicked.connect(self.graphSessionLoadClicked)
        self.graph_layout.addWidget(self.graph_session_list,1,3,10,10)
        self.graph_session_list_text = QtWidgets.QLabel("Sessions", self)
        self.graph_layout.addWidget(self.graph_session_list_text,0,3)

        # Fixation Run List
        self.graph_fixation_runs_list = QtWidgets.QListWidget(self)
        self.graph_fixation_runs_list.setSelectionMode(QtWidgets.QAbstractItemView.SelectionMode.MultiSelection)
        self.graph_fixation_runs_list.itemClicked.connect(self.graphFixationRunClicked)
        self.graph_layout.addWidget(self.graph_fixation_runs_list,1,13,10,10)
        self.graph_fixation_runs_list_text = QtWidgets.QLabel("Fixation Runs", self)
        self.graph_layout.addWidget(self.graph_fixation_runs_list_text,0,13)


        self.graph_aoi_list = QtWidgets.QTabWidget(self)
        self.graph_layout.addWidget(self.graph_aoi_list,1,26,10,10)
        self.graph_aoi_list_text = QtWidgets.QLabel("Files", self)
        self.graph_layout.addWidget(self.graph_aoi_list_text,0,26)




        self.tab_widget.addTab(self.video_tab,'Gaze Cloud Video')
        self.tab_widget.addTab(self.code_tab,'Tokenized Heatmap')
        self.tab_widget.addTab(self.graph_tab,'Graphs')





    def videoDatabaseButtonClicked(self): # Load Database
        db_file_path = QtWidgets.QFileDialog.getOpenFileName(self, "Open Database", "", "SQLite Files (*.db3 *.db *.sqlite *sqlite3)")[0]
        if(db_file_path == ''):
            return
        try:
            self.video_idb = iTraceDB(db_file_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            return
        display_name = db_file_path.split("/")[-1]
        if len(display_name) > 20:
            display_name = display_name[:20]
        self.video_db_loaded_text.setText(display_name)
        self.video_session_list.clear()
        self.video_fixation_runs_list.clear()

        sessions = self.video_idb.GetSessions()
        self.video_session_list.addItems(sessions)

    def codeDatabaseButtonClicked(self): # Load Database
        db_file_path = QtWidgets.QFileDialog.getOpenFileName(self, "Open Database", "", "SQLite Files (*.db3 *.db *.sqlite *sqlite3)")[0]
        if(db_file_path == ''):
            return
        try:
            self.code_idb = iTraceDB(db_file_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            return
        display_name = db_file_path.split("/")[-1]
        if len(display_name) > 20:
            display_name = display_name[:20]
        self.code_db_loaded_text.setText(display_name)
        self.code_session_list.clear()
        self.code_fixation_runs_list.clear()

        sessions = self.code_idb.GetSessionsWithParticipantID()
        self.code_session_list.addItems(sessions)

    def graphDatabaseButtonClicked(self): # Load Database
        db_file_path = QtWidgets.QFileDialog.getOpenFileName(self, "Open Database", "", "SQLite Files (*.db3 *.db *.sqlite *sqlite3)")[0]
        if(db_file_path == ''):
            return
        try:
            self.graph_idb = iTraceDB(db_file_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            return
        display_name = db_file_path.split("/")[-1]
        if len(display_name) > 20:
            display_name = display_name[:20]
        self.graph_db_loaded_text.setText(display_name)
        self.graph_session_list.clear()
        self.graph_fixation_runs_list.clear()

        sessions = self.graph_idb.GetSessionsWithParticipantID()
        self.graph_session_list.addItems(sessions)

    def codeSrcmlButtonClicked(self): # Load srcML
        srcml_file_path = QtWidgets.QFileDialog.getOpenFileName(self, "Open srcML Archive","","srcML Files (*.xml *.srcml)")[0]
        if(srcml_file_path == ''):
            return
        try:
            self.code_srcml = ET.parse(srcml_file_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            return
        print(self.code_srcml.getroot().attrib)
        if("filename" in self.code_srcml.getroot().attrib):
            QtWidgets.QMessageBox.critical(self, "srcML Error", "The provided srcML file is not an archive file")
            self.video = None
            return
        display_name = srcml_file_path.split("/")[-1]
        if len(display_name) > 20:
            display_name = display_name[:20]
        self.code_srcml_loaded_text.setText(display_name)

    def graphSrcmlButtonClicked(self): # Load srcML
        srcml_file_path = QtWidgets.QFileDialog.getOpenFileName(self, "Open srcML Archive","","srcML Files (*.xml *.srcml)")[0]
        if(srcml_file_path == ''):
            return
        try:
            self.graph_srcml = ET.parse(srcml_file_path)
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", str(e))
            return
        print(self.graph_srcml.getroot().attrib)
        if("filename" in self.graph_srcml.getroot().attrib):
            QtWidgets.QMessageBox.critical(self, "srcML Error", "The provided srcML file is not an archive file")
            self.video = None
            return
        display_name = srcml_file_path.split("/")[-1]
        if len(display_name) > 20:
            display_name = display_name[:20]
        self.graph_srcml_loaded_text.setText(display_name)
        self.createFileTabs()

    def videoSessionLoadClicked(self, item):  # Select Session
        session_id = int(item.text().split(" - ")[1])

        self.video_fixation_runs_list.clear()
        self.video_fixation_runs_list.addItems(self.video_idb.GetFixationRuns(session_id))

        self.selected_session_time = self.video_idb.GetSessionTimeLength(session_id)
        self.session_start_time = self.video_idb.GetSessionStartTime(session_id)

    def codeSessionLoadClicked(self, item):  # Select Session
        particpant_id = item.text().split(" - ")[0]
        task_name = item.text().split(" - ")[1]
        session_id = int(item.text().split(" - ")[2])

        selected = self.code_session_list.selectedItems()
        fixation_runs = self.code_idb.GetFixationRunsWithSession(session_id)
        list_id = f"----------- {particpant_id} - {task_name} -----------"
        print(self.code_fixation_runs_list.findItems(list_id,QtCore.Qt.MatchExactly))
        if item not in selected:
            self.code_fixation_runs_list.takeItem(self.code_fixation_runs_list.row(self.code_fixation_runs_list.findItems(list_id,QtCore.Qt.MatchExactly)[0]))

            for run in fixation_runs:
                self.code_fixation_runs_list.takeItem(self.code_fixation_runs_list.row(self.code_fixation_runs_list.findItems(run,QtCore.Qt.MatchExactly)[0]))
        else:
            # self.code_fixation_runs_list.clear()
            self.code_fixation_runs_list.addItem(list_id)
            self.code_fixation_runs_list.addItems(fixation_runs)

    def graphSessionLoadClicked(self, item):  # Select Session
        particpant_id = item.text().split(" - ")[0]
        task_name = item.text().split(" - ")[1]
        session_id = int(item.text().split(" - ")[2])

        selected = self.graph_session_list.selectedItems()
        fixation_runs = self.graph_idb.GetFixationRunsWithSession(session_id)
        list_id = f"----------- {particpant_id} - {task_name} -----------"
        print(self.graph_fixation_runs_list.findItems(list_id,QtCore.Qt.MatchExactly))
        if item not in selected:
            self.graph_fixation_runs_list.takeItem(self.graph_fixation_runs_list.row(self.graph_fixation_runs_list.findItems(list_id,QtCore.Qt.MatchExactly)[0]))

            for run in fixation_runs:
                self.graph_fixation_runs_list.takeItem(self.graph_fixation_runs_list.row(self.graph_fixation_runs_list.findItems(run,QtCore.Qt.MatchExactly)[0]))
        else:
            # self.code_fixation_runs_list.clear()
            self.graph_fixation_runs_list.addItem(list_id)
            self.graph_fixation_runs_list.addItems(fixation_runs)

        if self.graph_srcml != None:
            self.createFileTabs()

    def videoFixationRunClicked(self, item):  # Select Fixation Run (Doesn't currently do anything extra)
        pass

    def codeFixationRunClicked(self, item):  
        if item.text().startswith("-----------") and item in self.code_fixation_runs_list.selectedItems():
            item.setSelected(False)

    def graphFixationRunClicked(self, item):  
        if item.text().startswith("-----------") and item in self.graph_fixation_runs_list.selectedItems():
            item.setSelected(False)

    def createFileTabs(self):
        self.file_tabs = {}

        sessions = self.graph_session_list.selectedItems()
        if len(sessions) == 0:
            return

        db_files = set()
        for session in sessions:
            db_files |= set([x[0].split("/")[-1] for x in self.graph_idb.GetFilesLookedAtBySession(session.text().split(" - ")[2])])
        print(db_files)
        # srcml_root = self.graph_srcml.getroot()
        # units = {}
        # for unit in srcml_root:
        #     units[unit.attrib["filename"]] = unit

        # files = [FindMatchingPath(list(units.keys()), file) for file in db_files]
        # print(files)




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

        display_name = video_file_path.split("/")[-1]
        if len(display_name) > 20:
            display_name = display_name[:20]
        self.video_loaded_text.setText(display_name)
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
        if len(self.video_session_list.selectedItems()) == 0 or self.video is None:
            QtWidgets.QMessageBox.critical(self, "Error", "You are missing a required component")
            return
        # Ensure video matches
        if not self.doSessionVideoTimesMatch():
            dlg = ConfirmDialog(self, "Mismatched Lengths", "The session length does not seem to match the video length. Continue anyway?")
            if dlg.exec():
                pass
            else:
                return

        session_id = int(self.video_session_list.selectedItems()[0].text().split(" - ")[1])

        # If dejavu, ensure it matches
        if self.dejavu and int(self.dejavu[0].split(",")[1]) != session_id:
            dlg = ConfirmDialog(self, "Differing DejaVu Data", "The selected DejaVu data appears to come from a different session. Continue anywway?")
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
        
        gaze_tups = self.video_idb.GetAllSessionGazes(session_id)
        gazes = [Gaze(tup) for tup in gaze_tups]
        print("Len:",len(gazes),"Elapsed:",time.time()-t)

        fixations = None
        if(len(self.video_fixation_runs_list.selectedItems()) != 0):
            t = time.time()
            print("Gathering Fixations, ",end="")
            fixation_run_id = int(self.video_fixation_runs_list.selectedItems()[0].text().split(" - ")[1])
            fixation_tups = self.video_idb.GetAllRunFixations(fixation_run_id)
            fixations = [Fixation(tup) for tup in fixation_tups]
            print("Len:",len(fixations),"Elapsed:",time.time()-t)

        fixation_gazes = None
        if False: #self.draw_fixation_gazes_box.isChecked():
            t = time.time()
            print("Gathering Fixation Gazes, ",end="")
            fixation_gazes = self.video_idb.GetAllFixationGazes(fixations)
            print("Len:",len(fixation_gazes),"Elapsed:",time.time()-t)

        saccades = None
        if self.draw_saccade_box.isChecked():
            t = time.time()
            print("Gathering Saccades, ",end="")
            saccades = GetSaccadesOfGazesAndFixationGazes(self.video_idb, gazes, fixation_gazes if fixation_gazes is not None else self.video_idb.GetAllFixationGazes(fixations))
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

    def generateCodeHeatmap(self):
        if(self.code_idb == None or self.code_srcml == None or len(self.code_fixation_runs_list.selectedItems()) == 0):
            QtWidgets.QMessageBox.critical(self, "Error", "You are missing a required component")
            return
        srcml_root = self.code_srcml.getroot()

        output_folder_name = QtWidgets.QFileDialog.getExistingDirectory(self,"Open Directory")
        if not output_folder_name:
            return

        output_data = {}
        text_data = {}

        for fixation_run in self.code_fixation_runs_list.selectedItems():

            fixation_run_id = int(fixation_run.text().split(" - ")[1])
            session_id = int(fixation_run.text().split(" - ")[2])

            xml_remover = re.compile("<.*?>")
            # At 28 Font size, bounding boxes are 17x28
            #    32 Font size, bounding boxes are 19x31
            font = ImageFont.truetype("cour.ttf",32)
            W = 19
            H = 31

            units = {}

            for unit in srcml_root:
                units[unit.attrib["filename"]] = unit

            gazed_files = [x[0] for x in self.code_idb.GetFilesLookedAtBySession(session_id)]
            print(gazed_files)

            for target_file in gazed_files:
                print(target_file)
                unit_target = FindMatchingPath(list(units.keys()),target_file)
                print(target_file,"->",unit_target)
                if unit_target == None:
                    continue
                unit = units[unit_target]

                file = unit.attrib["filename"].split("/")[-1]
                src_str = xml_remover.sub('',ET.tostring(unit).decode()).replace("&gt;",">").replace("&lt;","<").replace("&amp;","&")

                lines = src_str.split("\n")
                rows = len(lines)
                cols = max([len(line.rstrip()) for line in lines])

                height = rows * H
                width = cols * W

                

                draw_tokens = {}
                fixation_tups = self.code_idb.GetAllRunFixationsTargetingFile(fixation_run_id,target_file)
                fixations = [Fixation(tup) for tup in fixation_tups]
                print("FIXES:",len(fixations))
                # fixations = [None]
                for fixation in fixations:
                    line_num = fixation.source_file_line
                    col_num = fixation.source_file_col

                    if line_num == -1 or col_num == -1:
                        continue

                    element = unit
                    #print((line_num,col_num),"->",FindTokenInElement(line_num,col_num,unit))
                    # print("\n---------------------------------")
                    coords = FindTokenInElement(line_num,col_num,unit)

                    if coords == None:
                        print(line_num,col_num,"???")
                        continue
                        # coords = ((line_num,col_num),(line_num,col_num))

                    if coords not in draw_tokens:
                        draw_tokens[coords] = 0

                    if self.time_process_box.isChecked():
                        draw_tokens[coords] += fixation.duration
                    else:
                        draw_tokens[coords] += 1

                if self.average_runs.isChecked():
                    min_count = min(list(draw_tokens.values()))
                    max_count = max(list(draw_tokens.values()))
                    diff = max_count - min_count

                    for coords in draw_tokens:
                        val = draw_tokens[coords]
                        draw_tokens[coords] = (val - min_count) / diff

                    if file in output_data:
                        output_data[file] = {k : draw_tokens.get(k,0) + output_data[file].get(k,0) for k in set(draw_tokens) | set(output_data[file]) }
                    else:
                        text_data[file] = src_str
                        output_data[file] = draw_tokens
                else:
                    output_data[f"{file}-{session_id}-{fixation_run_id}"] = draw_tokens
                    text_data[f"{file}-{session_id}-{fixation_run_id}"] = src_str

        for file in output_data:
            data = output_data[file]

            # Create blank file
            img = np.zeros((height,width,3), dtype=np.uint8)
            img.fill(255)

            img = Image.fromarray(img)
            draw = ImageDraw.Draw(img)

            start_color = self.startColor
            end_color = self.endColor

            num_of_colors = int(self.color_number_box.text())

            hsv_start = 270
            hsv_end = 0
            step = (hsv_end - hsv_start) / (num_of_colors - 1)
            colors = []
            for i in range(0,num_of_colors):
                rgb = colorsys.hsv_to_rgb((hsv_start + (step * i)) / 360,0.5,1)
                colors.append((int(rgb[2]*255),int(rgb[1]*255),int(rgb[0]*255)))
                # print("RGB",(colors[-1][2],colors[-1][1],colors[-1][0]),step,i)

            if len(list(data.values())) != 0:
                min_count = min(list(data.values()))
                max_count = max(list(data.values()))
                step = (max_count - min_count) / (len(colors) - 1)

                for coords in data:
                    pos = ((coords[0][1]-1)*W,(coords[0][0]-1)*H,(coords[1][1]*W)-1,(coords[1][0]*H)-1)
                    count = data[coords]
                    # print(pos)
                    # print("!",min_count,max_count,step,count)
                    # print(int((count - min_count) / step))
                    color = colors[int((count - min_count) / step) if step != 0 else -1]
                    
                    draw.rectangle(pos,fill=color)

                draw.text((0,0),text_data[file],(0,0,0),font=font)
                img = np.array(img)

                cv2.imwrite(f"{output_folder_name}/{file}.png",img)

        print("DONE!")






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
