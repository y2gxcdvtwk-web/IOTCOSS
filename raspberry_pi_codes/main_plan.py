def System_Init():
def Session():
    while !End Button:
        Wait(5 min)     ###내부에서 wait 함수 쓰는거보단 시작 시간 받아서 시간차로 계산하는게 정확
        Capture Image()
        Image Preprocessing()
        CSE Analysis()
        Save Result()
        Control Desk()
}
def main:

    System_Init()
    while 1:
        if Start_Button:
            Session()
        analysis()
        announcement()