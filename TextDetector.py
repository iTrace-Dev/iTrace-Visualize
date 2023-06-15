import cv2
import numpy as np
import random

import time

X_ = 1
Y_ = 0

def flood_fill(frame, start_pos):
    queue = []
    pixels = []
    queue.append(start_pos)
    while len(queue) != 0:
        n = queue.pop(0)
        x = n[X_]
        y = n[Y_]

        if(frame[x,y] == 255):
            #print("P",frame[y,x])
            frame[x,y] = 128
            pixels.append((y,x))
            # N
            if y > 0:
                queue.append((y-1,x))
            # S
            if y < frame.shape[1]-1:
                queue.append((y+1,x))
            # W
            if x > 0:
                queue.append((y,x-1))
            # E
            if x < frame.shape[0]-1:
                queue.append((y,x+1))

    miny, minx = start_pos
    maxy, maxx = start_pos
    for pixel in pixels:
        x = pixel[X_]
        y = pixel[Y_]
        minx = x if x < minx else minx
        miny = y if y < miny else miny
        maxx = x if x > maxx else maxx
        maxy = y if y > maxy else maxy
    for ix in range(minx,maxx):
        for iy in range(miny,maxy):
            frame[ix,iy] = 128

    return ((miny, minx), (maxy, maxx))

def is_in_box(box,coord):
    X = 0
    Y = 1
    MIN = 0
    MAX = 1
    return (coord[X] >= box[MIN][X]) and (coord[X] <= box[MAX][X]) and (coord[Y] >= box[MIN][Y]) and (coord[Y] <= box[MAX][Y])



def get_text_boxes(current_frame, previous_frame, boxes):
    if previous_frame is None:
        previous_frame = 255 - current_frame
    res = cv2.absdiff(current_frame, previous_frame)
    res = res.astype(np.uint8)
    percentage = (np.count_nonzero(res) * 100) / res.size
    if percentage > 5:
        print(percentage)
        
        print("Generating new highlight data")
        original = current_frame.copy()
        # Process Image
        #print(cropped)
        #cv2.imshow("Cropped",cropped)
        ## Invert
        inv = cv2.bitwise_not(original)
        ## Gray
        gray = cv2.cvtColor(inv,cv2.COLOR_BGR2GRAY)
        ## Darken
        gray = cv2.convertScaleAbs(gray,alpha=1,beta=-100)
        ## Dilate
        ret, thresh1 = cv2.threshold(gray,0,255,cv2.THRESH_OTSU | cv2.THRESH_BINARY_INV)
        rect_kernel = cv2.getStructuringElement(cv2.MORPH_RECT,(20,3))
        dilation = cv2.dilate(thresh1, rect_kernel,iterations=1)

        boxes = []
        for y in range(dilation.shape[1]):
            for x in range(dilation.shape[0]):
                if dilation[x][y] == 255:
                    box = flood_fill(dilation,(y,x))
                    boxes.append(box)
        # avg_height = 0
        # for box in boxes:
        #     print(box,"->",box[1][1] - box[0][1])
        #     avg_height += box[1][1] - box[0][1]
        # avg_height /= len(boxes)
    return boxes

def highlight_frame(frame,boxes,fixation,color):
    for box in boxes:
        # For now, highlight them all
        start = (box[0][0],box[0][1])
        end = (box[1][0],box[1][1])
        if(is_in_box(box,(fixation.x,fixation.y))):
            for x in range(box[0][0],box[1][0]):
                for y in range(box[0][1],box[1][1]):
                    b = frame[int(y), int(x), 0] * (50) / 100  + color[0] * 50 / 100 # get B value
                    g = frame[int(y), int(x), 1] * (50) / 100  + color[1] * 50 / 100 # get B value
                    r = frame[int(y), int(x), 2] * (50) / 100  + color[2] * 50 / 100 # get B value
                    frame[y,x] = (b,g,r)
            #frame = cv2.rectangle(frame,start,end,(random.randint(0,255),random.randint(0,255),random.randint(0,255)),3)
