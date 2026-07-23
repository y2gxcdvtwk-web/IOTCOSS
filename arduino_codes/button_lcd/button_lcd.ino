#include <WiFiS3.h>
#include <WiFiSSLClient.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ArduinoJson.h>

// ==========================================
// 1. 네트워크 및 Mobius 설정
// ==========================================
char ssid[] = "ADDHD";         // 사용하는 Wi-Fi 이름
char pass[] = "PASSWORD";     // 사용하는 Wi-Fi 비밀번호

const char MOBIUS_HOST[] = "platform.iotcoss.ac.kr";
const int MOBIUS_PORT = 443;
const char MOBIUS_BASE_PATH[] = "/api/proxy/swagger/Mobius";

// 인증 헤더
const char API_KEY[] = "REDACTED_MOBIUS_API_KEY_00000000";
const char CUSTOM_LECTURE[] = "LCT20260002";
const char CUSTOM_CREATOR[] = "sjuADDHD";

// 장치 식별자
const char DEVICE_ID[] = "desk-interface-01";

// ==========================================
// 2. 하드웨어 핀 및 객체 정의
// ==========================================
const int BTN_KICKOFF_PIN = 2; // A버튼 (시작/종료)
const int BTN_ACCEPT_PIN  = 3; // B버튼 (수락)

LiquidCrystal_I2C lcd(0x27, 16, 2); // I2C 주소 0x27 (출력 안될 시 0x3F 확인)

// ==========================================
// 3. 상태 관리 변수
// ==========================================
long bootId = 0;
unsigned long seqNumber = 1;

// LCD Command 메모리 저장 변수
String currentSessionId = "";
String currentSuggestionId = "";
String lastLcdCommandId = "";
bool hasActiveSuggestion = false;

// 버튼 디바운싱
unsigned long lastKickoffTime = 0;
unsigned long lastAcceptTime = 0;
const unsigned long debounceDelay = 200;

// Polling 타이머 (1초 주기)
unsigned long lastPollTime = 0;
const unsigned long pollInterval = 5000;

// ==========================================
// 4. 주요 함수 구현
// ==========================================

// Wi-Fi 연결 함수
void connectWiFi() {
  while (WiFi.status() != WL_CONNECTED) {
    Serial.print("Attempting to connect to SSID: ");
    Serial.println(ssid);
    WiFi.begin(ssid, pass);
    delay(5000);
  }
  Serial.println("Connected to WiFi");
}

// 이벤트 ID 생성기: {deviceId}-{bootId}-{sequence}
String generateEventId() {
  char buf[64];
  snprintf(buf, sizeof(buf), "%s-%ld-%06lu", DEVICE_ID, bootId, seqNumber++);
  return String(buf);
}

// buttonEvents CIN 생성 (POST)
void sendButtonEvent(const char* buttonType) {
WiFiSSLClient client;
  if (!client.connect(MOBIUS_HOST, MOBIUS_PORT)) {
    Serial.println("Connection failed for POST buttonEvent");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
    Serial.print("RSSI: ");
    Serial.println(WiFi.RSSI());
    return;
}
  client.setTimeout(20);
  StaticJsonDocument<512> doc;
  JsonObject cin = doc.createNestedObject("m2m:cin");
  JsonObject con = cin.createNestedObject("con");

  con["schemaVersion"] = "1.0";
  con["eventId"] = generateEventId();
  con["deviceId"] = DEVICE_ID;
  
  if (currentSessionId.length() > 0) {
    con["sessionId"] = currentSessionId;
  }
  
  con["button"] = buttonType;
  
  if (strcmp(buttonType, "ACCEPT") == 0 && currentSuggestionId.length() > 0) {
    con["suggestionId"] = currentSuggestionId;
  }

  con["pressedAt"] = nullptr; // NTP 미동기화 시 null
  con["uptimeMs"] = millis();

  String jsonBody;
  serializeJson(doc, jsonBody);

  String requestPath = String(MOBIUS_BASE_PATH) + "/deskInterface/buttonEvents";

  client.println("POST " + requestPath + " HTTP/1.1");
  client.println("Host: " + String(MOBIUS_HOST));
  client.println("Accept: application/json");
  client.println("Content-Type: application/json;ty=4");
  client.println("X-M2M-RI: " + String(DEVICE_ID) + "-" + String(millis()));
  client.println("X-M2M-Origin: S");
  client.println("X-API-KEY: " + String(API_KEY));
  client.println("X-AUTH-CUSTOM-LECTURE: " + String(CUSTOM_LECTURE));
  client.println("X-AUTH-CUSTOM-CREATOR: " + String(CUSTOM_CREATOR));
  client.print("Content-Length: ");
  client.println(jsonBody.length());
  client.println("Connection: close");
  client.println();
  client.println(jsonBody);

  Serial.println("Sent Button Event POST");
  client.stop();
}

// 버튼 입력 처리 및 디바운싱
void checkButtons() {
  unsigned long now = millis();

  // A버튼 (KICKOFF) 체크
  if (digitalRead(BTN_KICKOFF_PIN) == 1) {
    if (now - lastKickoffTime > debounceDelay) {
      lastKickoffTime = now;
      Serial.println("[BTN] KICKOFF Pressed");
      sendButtonEvent("KICKOFF");
    }
  }

  // B버튼 (ACCEPT) 체크
  if (digitalRead(BTN_ACCEPT_PIN) == 1) {
    if (now - lastAcceptTime > debounceDelay) {
      lastAcceptTime = now;
      // 활성 제안이 있을 때만 수락 이벤트 전송
      if (hasActiveSuggestion) {
        Serial.println("[BTN] ACCEPT Pressed");
        sendButtonEvent("ACCEPT");
      } else {
        Serial.println("[BTN] ACCEPT Ignored (No active suggestion)");
      }
    }
  }
}

// lcdCommand/latest Polling (GET)
void pollLcdCommand() {
WiFiSSLClient client;
  Serial.println("1");
if (!client.connect(MOBIUS_HOST, MOBIUS_PORT)) {
    Serial.println("SSL connect fail");
    Serial.print("IP: ");
    Serial.println(WiFi.localIP());
    Serial.print("RSSI: ");
    Serial.println(WiFi.RSSI());
    return;
}

  Serial.println("2");

  client.setTimeout(30);

  Serial.println("3");
  String requestPath = String(MOBIUS_BASE_PATH) + "/deskInterface/lcdCommand/latest";

  client.println("GET " + requestPath + " HTTP/1.1");
  client.println("Host: " + String(MOBIUS_HOST));
  client.println("Accept: application/json");
  client.println("X-M2M-RI: " + String(DEVICE_ID) + "-" + String(millis()));
  client.println("X-M2M-Origin: S");
  client.println("X-API-KEY: " + String(API_KEY));
  client.println("X-AUTH-CUSTOM-LECTURE: " + String(CUSTOM_LECTURE));
  client.println("X-AUTH-CUSTOM-CREATOR: " + String(CUSTOM_CREATOR));
  client.println("Connection: close");
  client.println();

  // Response Body 파싱
  bool isBody = false;
  String jsonResponse = "";

  while (client.connected() || client.available()) {
    checkButtons(); 
    String line = client.readStringUntil('\n');
    if (line == "\r") {
      isBody = true;
      continue;
    }
    if (isBody) {
      jsonResponse += line;
    }
  }
  client.stop();

  if (jsonResponse.length() == 0) return;

  // JSON 파싱
  DynamicJsonDocument doc(1024);
  DeserializationError error = deserializeJson(doc, jsonResponse);
  if (error) return;

  JsonObject con = doc["m2m:cin"]["con"];
  if (con.isNull()) return;

  String commandId = con["commandId"].as<String>();

  // 새로운 명령일 때만 LCD 갱신
  if (commandId.length() > 0 && commandId != lastLcdCommandId) {
    lastLcdCommandId = commandId;

    if (con.containsKey("sessionId")) {
      currentSessionId = con["sessionId"].as<String>();
    }
    if (con.containsKey("suggestionId")) {
      currentSuggestionId = con["suggestionId"].as<String>();
    } else {
      currentSuggestionId = "";
    }

    String screen = con["screen"].as<String>();
    String line1 = con["line1"].as<String>();
    String line2 = con["line2"].as<String>();

    // 스탠딩 제안 화면 여부 업데이트
    hasActiveSuggestion = (screen == "STAND_SUGGESTION");

    // LCD 출력
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print(line1.substring(0, 16));
    lcd.setCursor(0, 1);
    lcd.print(line2.substring(0, 16));

    Serial.println("Updated LCD: [" + line1 + "] / [" + line2 + "]");
  }
}

// ==========================================
// 5. Arduino standard setup & loop
// ==========================================
void setup() {
  Serial.begin(115200);
  
  pinMode(BTN_KICKOFF_PIN, INPUT_PULLUP);
  pinMode(BTN_ACCEPT_PIN, INPUT_PULLUP);

  lcd.init();
  lcd.backlight();
  lcd.setCursor(0, 0);
  lcd.print("Connecting WiFi");

  connectWiFi();
    Serial.print("Firmware Version : ");
    Serial.println(WiFi.firmwareVersion());
    Serial.print("Latest Version   : ");
    Serial.println(WIFI_FIRMWARE_LATEST_VERSION);

  // bootId 임의 생성
  randomSeed(analogRead(0));
  bootId = random(1000, 9999);

  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print("System Ready");
  lcd.setCursor(0, 1);
  lcd.print("Press A to Start");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
    Serial.print("Firmware Version : ");
    Serial.println(WiFi.firmwareVersion());
    Serial.print("Latest Version   : ");
    Serial.println(WIFI_FIRMWARE_LATEST_VERSION);
  }

  // 1. 버튼 입력 감지
  checkButtons();

  // 2. LCD 명령 Polling (1초 주기)
  unsigned long currentMillis = millis();
  if (currentMillis - lastPollTime >= pollInterval) {
    lastPollTime = currentMillis;
    pollLcdCommand();
  }
}