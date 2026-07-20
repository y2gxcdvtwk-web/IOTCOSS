// ===================================================
// postureLight (삼색 RGB LED 모듈 2개 병렬 제어 코드)
// ===================================================

const int redPin = 5;   // 두 모듈의 R 핀이 묶여서 연결된 5번 핀 (PWM)
const int greenPin = 6; // 두 모듈의 G 핀이 묶여서 연결된 6번 핀 (PWM)

unsigned long lastStatusTime = 0;
const unsigned long statusInterval = 5000; // 5초마다 상태 보고

void setup() {
  Serial.begin(9600);
  
  pinMode(redPin, OUTPUT);
  pinMode(greenPin, OUTPUT);
  
  // [초기 상태] 켜지자마자 정상 상태를 뜻하는 초록색 불을 켜둡니다.
  analogWrite(redPin, 0);
  analogWrite(greenPin, 255); 
  
  sendStatus("READY");
}

void loop() {
  // --- 1. 수신: 라즈베리파이(또는 서버)로부터 들어오는 명령 파싱 ---
  if (Serial.available() > 0) {
    String inputData = Serial.readStringUntil('\n');
    inputData.trim();
    
    // [command] 프로토콜 감지
    if (inputData.startsWith("[command]")) {
      String command = inputData.substring(9); 
      command.trim();
      
      // 거북목 감지 등 경고 상황: 초록색은 꺼지고 빨간색이 서서히 차오름
      if (command == "WARNING" || command == "RED") {
        switchToWarning();
      } 
      // 자세 바로잡음 등 정상 복귀: 빨간색은 꺼지고 초록색이 서서히 차오름
      else if (command == "NORMAL" || command == "GREEN" || command == "OFF") {
        switchToNormal();
      }
    }
  }

  // --- 2. 송신: postureLight 장치의 주기적 상태 보고 ---
  unsigned long currentMillis = millis();
  if (currentMillis - lastStatusTime >= statusInterval) {
    lastStatusTime = currentMillis;
    sendStatus("RUNNING");
  }
}

// [경고 전환] 두 모듈의 초록색을 줄이면서 빨간색을 서서히 높이는 함수
void switchToWarning() {
  for (int i = 0; i <= 255; i += 5) {
    analogWrite(greenPin, 255 - i); // 초록색은 스르륵 꺼짐
    analogWrite(redPin, i);         // 빨간색은 서서히 켜짐
    delay(40);                      // 페이드인 속도 조절
  }
  analogWrite(greenPin, 0);
  analogWrite(redPin, 255); // 최대 밝기 유지
}

// [정상 복귀] 두 모듈의 빨간색을 줄이면서 초록색을 서서히 높이는 함수
void switchToNormal() {
  for (int i = 0; i <= 255; i += 5) {
    analogWrite(redPin, 255 - i);   // 빨간색은 스르륵 꺼짐
    analogWrite(greenPin, i);       // 초록색은 서서히 켜짐
    delay(40);
  }
  analogWrite(redPin, 0);
  analogWrite(greenPin, 255); // 최대 밝기 유지
}

// 모듈 상태 전송 함수
void sendStatus(String statusType) {
  Serial.println("[status]" + statusType);
}