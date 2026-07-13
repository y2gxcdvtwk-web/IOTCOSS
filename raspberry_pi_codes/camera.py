import cv2

cap = cv2.VideoCapture(0, cv2.CAP_V4L2)
print("Opened:", cap.isOpened())
ret, frame = cap.read()
print("Read:", ret)