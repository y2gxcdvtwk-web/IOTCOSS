#include <Wire.h>
#include <LiquidCrystal_I2C.h>

LiquidCrystal_I2C lcd(0x27, 16, 2);

const int btnA = 2; // A버튼: 내 의지로 캠 시작 요청
const int btnB = 3; // B버튼: 라즈파이 제안에 대한 수락

bool isProposed = false; // 라즈베리파이로부터 제안을 받았는지 체크하는 변수

void setup() {
  Serial.begin(9600);
  
  pinMode(btnA, INPUT_PULLUP);
  pinMode(btnB, INPUT_PULLUP);
  
  lcd.init();
  lcd.backlight();
  
  // 첫 화면: 라즈베리파이 신호나 A버튼 입력을 기다리는 상태
  showReadyScreen();
}

void loop() {
  // --- [파트 1: 라즈베리파이로부터 데이터 받기] ---
  if (Serial.available() > 0) {
    String inputData = Serial.readStringUntil('\n');
    inputData.trim(); // 양끝 공백 제거
    
    // 라즈베리파이가 거북목을 감지해서 스탠딩을 제안했을 때
    if (inputData == "PROPOSE_STAND") {
      isProposed = true; // B버튼 잠금 해제
      
      lcd.clear();
      lcd.setCursor(0, 0);
      lcd.print("Change to Stand?");
      lcd.setCursor(0, 1);
      lcd.print("버튼 B: 수락");
    }
  }

  // --- [파트 2: 버튼 A 입력 처리] ---
  if (digitalRead(btnA) == LOW) {
    Serial.println("START_CAM"); // 라즈파이로 캠 시작 명령 전송
    
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Button A Pressed");
    lcd.setCursor(0, 1);
    lcd.print("Sending: START");
    
    delay(500); // 디바운스 대기
  }
  
  // --- [파트 3: 버튼 B 입력 처리 (조건부 잠금)] ---
  // 라즈파이에게 제안을 받은 상태(isProposed == true)에서만 B버튼이 작동함!
  if (digitalRead(btnB) == LOW && isProposed) {
    Serial.println("AGREE_STAND"); // 라즈파이로 수락 명령 전송
    
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print("Button B Pressed");
    lcd.setCursor(0, 1);
    lcd.print("Sending: AGREE");
    
    delay(1000); // 메시지를 볼 수 있게 조금 더 길게 대기
    
    // 처리가 끝났으므로 상태를 초기화하고 다시 대기 화면으로
    isProposed = false;
    showReadyScreen();
  }
}

// 대기 화면 출력을 위한 간단한 함수
void showReadyScreen() {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("START TO STUDY");
  lcd.setCursor(0, 1);
  lcd.print("A:Start");
}