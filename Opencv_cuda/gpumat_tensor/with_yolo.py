import cv2
import numpy as np

mog = cv2.createBackgroundSubtractorKNN(detectShadows=True)

camera = cv2.VideoCapture('081122024 0300.asf')

ret, frame = camera.read()
while ret:
    fgmask = mog.apply(frame)
    th = cv2.threshold(np.copy(fgmask), 244, 255, cv2.THRESH_BINARY)[1]

    th = cv2.erode(th, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)), iterations=2)
    dilated = cv2.dilate(th, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (8, 3)), iterations=2)

    cv2.imshow('mog', fgmask)
    cv2.imshow('thresh', th)
    cv2.imshow('dilated',dilated)
    cv2.imshow('detection', frame)

    # Read the next frame
    ret, frame = camera.read()

    # Break loop if 'q' is pressed
    if cv2.waitKey(30) & 0xFF == ord('q'):
        break

camera.release()
cv2.destroyAllWindows()
