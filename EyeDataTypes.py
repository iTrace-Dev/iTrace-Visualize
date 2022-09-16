class Gaze:
    def __init__(self, init_tup):
        self.event_time, self.session_id, self.calibration_id, self.participant_id, self.tracker_time, self.system_time, self.x, self.y, self.left_x, self.left_y, self.left_pupil_diameter, self.left_validation, self.right_x, self.right_y, self.right_pupil_diameter, self.right_validation, self.user_left_x, self.user_left_y, self.user_left_z, self.user_right_x, self.user_right_y, self.user_right_z = init_tup

    def __str__(self):
        return "Gaze at "+str((self.x, self.y))

    def isNaN(self):
        try:
            check = int(self.x) + int(self.y)
            return False
        except ValueError:
            return True


class Fixation:
    def __init__(self, init_tup):
        self.fixation_id, self.fixation_run_id, self.fixation_start_event_time, self.fixation_order_number, self.x, self.y, self.fixation_target, self.source_file_line, self.source_file_col, self.token, self.syntactic_category, self.xpath, self.left_pupil_diameter, self.right_pupil_diameter, self.duration = init_tup

    def __str__(self):
        return "Fixation at "+str((self.x, self.y))
