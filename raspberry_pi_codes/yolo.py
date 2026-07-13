import cv2
import time
import numpy as np
import subprocess
from ai_edge_litert.interpreter import Interpreter

# 1. 모델 로드
print("TFLite 인터프리터 로딩 중...")
interpreter = Interpreter(model_path='yolo11n.tflite')
interpreter.allocate_tensors()

input_details = interpreter.get_input_details()
output_details = interpreter.get_output_details()
input_shape = input_details[0]['shape'] # 모델이 요구하는 모양 확인 [1, 640, 640, 3] 또는 [1, 3, 640, 640]
print(f"모델 입력 형식: {input_shape}")

# 2. 카메라 연결
width, height = 640, 480
print("카메라 연결 중...")
cmd = ['rpicam-vid', '-t', '0', '--codec', 'yuv420', '--width', str(width), '--height', str(height), '--framerate', '15', '-o', '-']
process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)
time.sleep(2)

frame_size = int(width * height * 1.5)

try:
    while True:
        raw_frame = process.stdout.read(frame_size)
        if len(raw_frame) != frame_size: break

        yuv_frame = np.frombuffer(raw_frame, dtype=np.uint8).reshape((int(height * 1.5), width))
        frame = cv2.cvtColor(yuv_frame, cv2.COLOR_YUV2BGR_I420)

        # 3. 전처리
        img = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = cv2.resize(img, (640, 640)).astype(np.float32) / 255.0
        
        # 모델 입력 형식에 따른 차원 조정
        if input_shape[1] == 3: # [1, 3, 640, 640] 인 경우
            input_data = np.transpose(img, (2, 0, 1))
            input_data = np.expand_dims(input_data, axis=0)
        else: # [1, 640, 640, 3] 인 경우
            input_data = np.expand_dims(img, axis=0)
        
        # 4. 추론
        interpreter.set_tensor(input_details[0]['index'], input_data)
        interpreter.invoke()
        
        # 결과 확인 (테스트용 출력)
        output_data = interpreter.get_tensor(output_details[0]['index'])
        
        # 5. 화면 출력
        cv2.putText(frame, "AI Running...", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
        cv2.imshow("YOLO TFLite Inference", frame)
        
        if cv2.waitKey(1) & 0xFF == ord('q'): break

except Exception as e:
    print(f"에러 발생: {e}")
finally:
    process.terminate()
    cv2.destroyAllWindows()