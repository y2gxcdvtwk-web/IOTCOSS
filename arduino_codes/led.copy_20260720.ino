#include <WiFiS3.h>
#include <WiFiSSLClient.h>
#include <ArduinoJson.h>

// 1. Wi-Fi 및 Mobius 설정
const char ssid[] = "SSID0000";      //[cite: 3]
const char pass[] = "PASSWORD";      //[cite: 3]

const char MOBIUS_HOST[] = "platform.iotcoss.ac.kr"; //[cite: 1, 3]
const int MOBIUS_PORT = 443;                         //[cite: 1, 3]
const char PATH_GET_LIGHT_COMMAND[] = "/api/proxy/swagger/Mobius/postureLight/command/latest"; //[cite: 1, 3]

// 2. 삼색 LED 핀 설정 (Common Cathode - GND 공통)[cite: 3]
const int redPin = 9;    // b45 (및 b56) 연결
const int greenPin = 10; // b46 (및 b57) 연결
const int bluePin = 11;  // b47 (및 b58) 연결

// 3. 상태 및 제어 변수
WiFiSSLClient client;
String lastCommandId = "";
unsigned long lastPollTime = 0;
const unsigned long POLL_INTERVAL = 800; //[cite: 3]

int currentI = 0;             //[cite: 3]
int targetI = 0;              //[cite: 3]
unsigned long lastFadeTime = 0;
const int FADE_INTERVAL = 40;  //[cite: 3]

bool isWarningActive = false;
unsigned long warningReachedTime = 0;
const unsigned long WARNING_HOLD_DURATION = 5000; // 5초 대기

void setup() {
  Serial.begin(9600); //[cite: 3]

  pinMode(redPin, OUTPUT);
  pinMode(greenPin, OUTPUT);
  pinMode(bluePin, OUTPUT);

  // 초기 상태: 초록색 ON (b46/b57에 전압 공급)[cite: 3]
  updateLEDPins(0);

  connectWiFi(); //[cite: 3]
}

void loop() {
  // 1. Fade 및 5초 타이머 제어[cite: 3]
  updateLEDFade();

  // 2. 시리얼 입력 테스트[cite: 3]
  if (Serial.available()) {
    char c = Serial.read();
    if (c == 'w') {
      Serial.println("\n[TEST] Red Warning Triggered!");
      targetI = 255;
      isWarningActive = true;
      warningReachedTime = 0;
    } else if (c == 'n') {
      Serial.println("\n[TEST] Green Normal Triggered!");
      targetI = 0;
      isWarningActive = false;
    }
  }

  // 3. Mobius Polling[cite: 3]
  if (millis() - lastPollTime >= POLL_INTERVAL) {
    lastPollTime = millis();
    pollLightCommand();
  }
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return; //[cite: 3]
  Serial.print("Connecting to Wi-Fi...");
  while (WiFi.begin(ssid, pass) != WL_CONNECTED) { //[cite: 3]
    delay(1000);
    Serial.print(".");
  }
  Serial.println("\nWi-Fi Connected!"); //[cite: 3]
}

// Common Cathode (GND 연결) 신호 출력[cite: 3]
void updateLEDPins(int i) {
  analogWrite(greenPin, 255 - i); // i=0 일 때 HIGH (255) -> 초록 켜짐[cite: 3]
  analogWrite(redPin, i);         // i=0 일 때 LOW (0) -> 빨강 꺼짐[cite: 3]
  analogWrite(bluePin, 0);        //[cite: 3]
}

void updateLEDFade() {
  if (millis() - lastFadeTime >= FADE_INTERVAL) {
    lastFadeTime = millis();

    if (currentI < targetI) {
      currentI += 5;
      if (currentI > targetI) currentI = targetI;
      updateLEDPins(currentI);

      if (currentI == 255 && isWarningActive && warningReachedTime == 0) {
        warningReachedTime = millis();
        Serial.println("[Status] Fully Red! Starting 5s timer...");
      }
    } 
    else if (currentI > targetI) {
      currentI -= 5;
      if (currentI < targetI) currentI = targetI;
      updateLEDPins(currentI);
    }
  }

  // 5초 후 초록불 자동 복구
  if (isWarningActive && warningReachedTime > 0) {
    if (millis() - warningReachedTime >= WARNING_HOLD_DURATION) {
      Serial.println("[Timer] 5s Elapsed -> Returning to Green!");
      targetI = 0;
      isWarningActive = false;
      warningReachedTime = 0;
    }
  }
}

void pollLightCommand() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    return;
  }

  if (client.connect(MOBIUS_HOST, MOBIUS_PORT)) { //[cite: 3]
    client.print(String("GET ") + PATH_GET_LIGHT_COMMAND + " HTTP/1.1\r\n" +
                 "Host: " + MOBIUS_HOST + "\r\n" +
                 "Accept: application/json\r\n" +
                 "X-M2M-RI: posture-light-01-" + String(millis()) + "\r\n" +
                 "X-M2M-Origin: S\r\n" +
                 "X-API-KEY: REDACTED_MOBIUS_API_KEY_00000000\r\n" +
                 "X-AUTH-CUSTOM-LECTURE: LCT_20260002\r\n" +
                 "X-AUTH-CUSTOM-CREATOR: sjuADDHD\r\n" +
                 "Connection: close\r\n\r\n"); //[cite: 2, 3]

    unsigned long timeout = millis();
    while (client.available() == 0) {
      if (millis() - timeout > 1500) { //[cite: 3]
        client.stop(); //[cite: 3]
        return;
      }
    }

    String response = "";
    while (client.available()) { //[cite: 3]
      response += (char)client.read(); //[cite: 3]
    }
    client.stop(); //[cite: 3]

    if (response.length() == 0) return; //[cite: 3]

    int jsonStart = response.indexOf('{'); //[cite: 3]
    if (jsonStart == -1) return; //[cite: 3]

    String body = response.substring(jsonStart); //[cite: 3]
    parseAndApplyCommand(body); //[cite: 3]
  }
}

// CIN JSON 파싱 및 LED 제어 (기본 초록불 유지 버전)
// CIN JSON 파싱 및 LED 제어 (기본 초록불 유지 버전)
void parseAndApplyCommand(String jsonStr) {
  StaticJsonDocument<1024> doc;
  DeserializationError error = deserializeJson(doc, jsonStr);
  if (error) return;

  JsonObject cin = doc["m2m:cin"];
  if (cin.isNull()) return;

  const char* resourceName = cin["rn"];
  JsonObject con = cin["con"];
  if (con.isNull()) return;

  // 중복 데이터 무시
  if (resourceName && String(resourceName) == lastCommandId) {
    return;
  }
  if (resourceName) {
    lastCommandId = String(resourceName);
  }

  const char* command = con["command"];
  if (!command) return;

  Serial.print("\n>>> [Mobius Command]: ");
  Serial.println(command);

  // 1. 거북목 경고 시: 빨간불 Fade -> 5초 유지 -> 자동 초록불 복구
  if (strcmp(command, "WARNING") == 0) {
    targetI = 255;
    isWarningActive = true;
    warningReachedTime = 0;
    Serial.println("[status] WARNING_FADE_STARTED");
  } 
  // 2. 정상 자세 시: 초록불 유지
  else if (strcmp(command, "NORMAL") == 0) {
    targetI = 0;
    isWarningActive = false;
    warningReachedTime = 0;
    Serial.println("[status] NORMAL_FADE_STARTED");
  }
  // 3. OFF 명령이 들어와도 불을 끄지 않고 기본 초록불 상태 유지
  else if (strcmp(command, "OFF") == 0) {
    targetI = 0;
    isWarningActive = false;
    warningReachedTime = 0;
    Serial.println("[status] OFF_COMMAND_IGNORED_KEEP_GREEN");
  }
}