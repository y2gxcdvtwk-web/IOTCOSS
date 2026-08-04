#include <WiFiS3.h>
#include <WiFiSSLClient.h>
#include <ArduinoJson.h>
#include <Wire.h>
#include <LiquidCrystal_I2C.h>

#if __has_include("arduino_secrets.h")
#include "arduino_secrets.h"
#else
#define WIFI_SSID "YOUR_WIFI_SSID"
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"
#define MOBIUS_API_KEY "YOUR_MOBIUS_API_KEY"
#endif

const char MOBIUS_HOST[] = "platform.iotcoss.ac.kr";
const int MOBIUS_PORT = 443;
const char MOBIUS_ROOT_PATH[] = "/api/proxy/swagger/Mobius";

const char MOBIUS_ORIGIN[] = "S";
const char MOBIUS_LECTURE[] = "LCT_20260002";
const char MOBIUS_CREATOR[] = "sjuADDHD";

const char DEVICE_ID[] = "desk-interface-uno-r4-01";
const char AE_NAME[] = "deskInterface";
const char LCD_COMMAND_CONTAINER[] = "lcdCommand";
const char BUTTON_EVENTS_CONTAINER[] = "buttonEvents";

const uint8_t BUTTON_A_PIN = 2;
const uint8_t BUTTON_B_PIN = 3;
const uint8_t LCD_I2C_ADDRESS = 0x27;
const uint8_t LCD_COLUMNS = 16;
const uint8_t LCD_ROWS = 2;

const unsigned long LCD_POLL_INTERVAL_MS = 750;
const unsigned long DEBOUNCE_MS = 40;
const unsigned long WIFI_RETRY_INTERVAL_MS = 5000;
const unsigned long HTTP_TIMEOUT_MS = 5000;
const unsigned long TEMP_MESSAGE_MS = 1500;

LiquidCrystal_I2C lcd(LCD_I2C_ADDRESS, LCD_COLUMNS, LCD_ROWS);
WiFiSSLClient client;

struct ButtonDebounce {
  bool lastReading;
  bool stableState;
  unsigned long changedAtMs;
};

ButtonDebounce buttonA = {HIGH, HIGH, 0};
ButtonDebounce buttonB = {HIGH, HIGH, 0};

unsigned long lastPollAtMs = 0;
unsigned long lastWifiAttemptAtMs = 0;
unsigned long requestCounter = 0;
bool wifiAttempted = false;
bool wifiWasLost = false;

String currentLine1 = "SYSTEM READY";
String currentLine2 = "PRESS BUTTON A";
String tempRestoreLine1 = "";
String tempRestoreLine2 = "";
unsigned long tempMessageUntilMs = 0;

String lastLcdResourceKey = "";
String lastLcdCommandId = "";

String currentSessionId = "";
String pendingSessionId = "";
String pendingSuggestionId = "";
String pendingCommandId = "";
String pendingPostureState = "";
String pendingDeskPosition = "";
String pendingNextMotorAction = "";
String pendingTargetPosition = "";
float pendingTargetHeightCm = -1.0;
bool pendingAcceptEnabled = false;
bool pendingRequiresResponse = false;
bool acceptPending = false;
bool sessionRunning = false;

String makeRequestId() {
  requestCounter++;
  return String("desk-iface-") + String(millis()) + "-" + String(requestCounter);
}

String buildPath(const char* container) {
  return String(MOBIUS_ROOT_PATH) + "/" + AE_NAME + "/" + container;
}

void writeLcdLine(uint8_t row, const String& text) {
  String line = text;
  if (line.length() > LCD_COLUMNS) {
    line = line.substring(0, LCD_COLUMNS);
  }
  while (line.length() < LCD_COLUMNS) {
    line += " ";
  }
  lcd.setCursor(0, row);
  lcd.print(line);
}

void displayRaw(const String& line1, const String& line2) {
  writeLcdLine(0, line1);
  writeLcdLine(1, line2);
}

void displayMessage(const String& line1, const String& line2) {
  currentLine1 = line1;
  currentLine2 = line2;
  tempMessageUntilMs = 0;
  displayRaw(currentLine1, currentLine2);
}

void displayTemporary(const String& line1, const String& line2) {
  tempRestoreLine1 = currentLine1;
  tempRestoreLine2 = currentLine2;
  tempMessageUntilMs = millis() + TEMP_MESSAGE_MS;
  displayRaw(line1, line2);
}

void expireTemporaryMessage() {
  if (tempMessageUntilMs == 0) {
    return;
  }
  if ((long)(millis() - tempMessageUntilMs) >= 0) {
    tempMessageUntilMs = 0;
    displayRaw(tempRestoreLine1, tempRestoreLine2);
  }
}

void clearPendingAccept() {
  acceptPending = false;
  pendingAcceptEnabled = false;
  pendingRequiresResponse = false;
  pendingTargetHeightCm = -1.0;
  pendingSuggestionId = "";
  pendingCommandId = "";
  pendingPostureState = "";
  pendingDeskPosition = "";
  pendingNextMotorAction = "";
  pendingTargetPosition = "";
  Serial.println("B disabled");
}

void updatePendingAccept() {
  bool raiseAllowed =
      pendingDeskPosition == "DOWN" &&
      (pendingPostureState == "STRETCH_WARNING" || pendingPostureState == "TURTLE_NECK") &&
      pendingNextMotorAction == "raise";
  bool lowerAllowed =
      pendingDeskPosition == "UP" &&
      pendingNextMotorAction == "lower";

  acceptPending =
      pendingAcceptEnabled &&
      pendingRequiresResponse &&
      pendingSessionId.length() > 0 &&
      (raiseAllowed || lowerAllowed);

  Serial.println(acceptPending ? "B enabled" : "B disabled");
}

void manageWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    if (wifiWasLost) {
      wifiWasLost = false;
      Serial.print("WiFi reconnected, IP=");
      Serial.println(WiFi.localIP());
      displayRaw(currentLine1, currentLine2);
    }
    return;
  }

  wifiWasLost = true;
  displayRaw("WIFI LOST", "RECONNECTING");
  unsigned long now = millis();
  if (wifiAttempted && now - lastWifiAttemptAtMs < WIFI_RETRY_INTERVAL_MS) {
    return;
  }
  wifiAttempted = true;
  lastWifiAttemptAtMs = now;
  Serial.print("Connecting to WiFi: ");
  Serial.println(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
}

String httpRequest(const char* method, const String& path, const String& body, bool createCin) {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("HTTP skipped: WiFi disconnected");
    return "";
  }
  if (!client.connect(MOBIUS_HOST, MOBIUS_PORT)) {
    Serial.println("HTTPS connect failed");
    return "";
  }
  client.setTimeout(HTTP_TIMEOUT_MS);

  client.print(method);
  client.print(" ");
  client.print(path);
  client.println(" HTTP/1.1");
  client.print("Host: ");
  client.println(MOBIUS_HOST);
  client.println("Accept: application/json");
  client.println("accept: */*");
  client.print("X-M2M-Origin: ");
  client.println(MOBIUS_ORIGIN);
  client.print("X-M2M-RI: ");
  client.println(makeRequestId());
  client.print("X-API-KEY: ");
  client.println(MOBIUS_API_KEY);
  client.print("X-AUTH-CUSTOM-LECTURE: ");
  client.println(MOBIUS_LECTURE);
  client.print("X-AUTH-CUSTOM-CREATOR: ");
  client.println(MOBIUS_CREATOR);

  if (createCin) {
    client.println("Content-Type: application/json;ty=4");
    client.print("Content-Length: ");
    client.println(body.length());
  }

  client.println("Connection: close");
  client.println();

  if (createCin) {
    client.print(body);
  }

  String response;
  unsigned long deadline = millis() + HTTP_TIMEOUT_MS;
  while (millis() < deadline) {
    while (client.available()) {
      response += (char)client.read();
      deadline = millis() + 1000;
    }
    if (!client.connected()) {
      break;
    }
    delay(1);
  }
  client.stop();
  return response;
}

int httpStatusCode(const String& response) {
  int firstSpace = response.indexOf(' ');
  if (firstSpace < 0 || firstSpace + 4 > response.length()) {
    return 0;
  }
  return response.substring(firstSpace + 1, firstSpace + 4).toInt();
}

String httpBody(const String& response) {
  int bodyIndex = response.indexOf("\r\n\r\n");
  int separatorLength = 4;
  if (bodyIndex < 0) {
    bodyIndex = response.indexOf("\n\n");
    separatorLength = 2;
  }
  if (bodyIndex < 0) {
    return "";
  }
  return response.substring(bodyIndex + separatorLength);
}

bool isChunkedResponse(const String& response) {
  int headerEnd = response.indexOf("\r\n\r\n");
  if (headerEnd < 0) {
    headerEnd = response.indexOf("\n\n");
  }
  if (headerEnd < 0) {
    return false;
  }
  String headers = response.substring(0, headerEnd);
  headers.toLowerCase();
  return headers.indexOf("transfer-encoding: chunked") >= 0;
}

String decodeChunkedBody(const String& chunked) {
  String decoded;
  int index = 0;
  while (index < chunked.length()) {
    int lineEnd = chunked.indexOf("\r\n", index);
    if (lineEnd < 0) {
      break;
    }
    String sizeText = chunked.substring(index, lineEnd);
    int semicolon = sizeText.indexOf(';');
    if (semicolon >= 0) {
      sizeText = sizeText.substring(0, semicolon);
    }
    sizeText.trim();

    long chunkSize = strtol(sizeText.c_str(), nullptr, 16);
    if (chunkSize <= 0) {
      break;
    }

    int dataStart = lineEnd + 2;
    int dataEnd = dataStart + chunkSize;
    if (dataEnd > chunked.length()) {
      break;
    }

    decoded += chunked.substring(dataStart, dataEnd);
    index = dataEnd + 2;
  }
  decoded.trim();
  return decoded;
}

String normalizedBody(const String& response) {
  String body = httpBody(response);
  if (isChunkedResponse(response)) {
    return decodeChunkedBody(body);
  }
  body.trim();
  return body;
}

String readStringField(JsonObject obj, const char* snakeName, const char* camelName = "") {
  const char* value = obj[snakeName] | "";
  if (!value[0] && camelName[0]) {
    value = obj[camelName] | "";
  }
  return String(value);
}

void fallbackLcdLines(
  const String& postureState,
  const String& deskPosition,
  String& line1,
  String& line2
) {
  if (deskPosition == "MOVING_UP") {
    line1 = "DESK MOVING UP";
    line2 = "PLEASE WAIT";
  } else if (deskPosition == "MOVING_DOWN") {
    line1 = "DESK MOVING DOWN";
    line2 = "PLEASE WAIT";
  } else if (deskPosition == "UP") {
    line1 = "DESK IS UP";
    line2 = "B: SIT DOWN";
  } else if (postureState == "STRETCH_WARNING") {
    line1 = "STRETCH NEEDED";
    line2 = "B: STAND UP";
  } else if (postureState == "TURTLE_NECK") {
    line1 = "TURTLE NECK";
    line2 = "B: STAND UP";
  } else if (postureState == "NORMAL") {
    line1 = "ANALYZING...";
    line2 = "POSTURE OK";
  } else {
    line1 = "SYSTEM READY";
    line2 = "PRESS BUTTON A";
  }
}

bool postButtonEvent(JsonDocument& content) {
  StaticJsonDocument<1024> payload;
  payload["m2m:cin"]["con"].set(content.as<JsonVariant>());

  String body;
  serializeJson(payload, body);
  String response = httpRequest("POST", buildPath(BUTTON_EVENTS_CONTAINER), body, true);
  int status = httpStatusCode(response);
  Serial.print("POST buttonEvents HTTP ");
  Serial.println(status);
  bool ok = status >= 200 && status < 300;
  if (!ok) {
    String bodyText = normalizedBody(response);
    if (bodyText.length() > 200) {
      bodyText = bodyText.substring(0, 200);
    }
    Serial.print("buttonEvents response: ");
    Serial.println(bodyText);
  }
  return ok;
}

bool latestLcdCommand(StaticJsonDocument<1536>& commandOut, String& resourceKeyOut) {
  String response = httpRequest(
    "GET",
    buildPath(LCD_COMMAND_CONTAINER) + "/latest",
    "",
    false
  );
  int status = httpStatusCode(response);
  Serial.print("GET lcdCommand/latest HTTP ");
  Serial.println(status);
  if (status == 404) {
    return false;
  }
  if (status < 200 || status >= 300) {
    return false;
  }

  StaticJsonDocument<3072> doc;
  DeserializationError error = deserializeJson(doc, normalizedBody(response));
  if (error) {
    Serial.print("LCD command JSON parse failed: ");
    Serial.println(error.c_str());
    return false;
  }

  JsonObject cin = doc["m2m:cin"];
  if (cin.isNull()) {
    return false;
  }

  const char* ri = cin["ri"] | "";
  const char* rn = cin["rn"] | "";
  JsonVariant con = cin["con"];
  if (con.isNull()) {
    return false;
  }

  resourceKeyOut = ri[0] ? String(ri) : String(rn);
  if (resourceKeyOut.length() == 0) {
    resourceKeyOut = "";
  }

  commandOut.clear();
  if (con.is<JsonObject>()) {
    commandOut.set(con);
  } else if (con.is<const char*>()) {
    DeserializationError conError = deserializeJson(commandOut, con.as<const char*>());
    if (conError) {
      Serial.print("LCD con JSON string parse failed: ");
      Serial.println(conError.c_str());
      return false;
    }
    if (commandOut.as<JsonObject>().isNull()) {
      return false;
    }
  } else {
    return false;
  }

  if (resourceKeyOut.length() == 0) {
    JsonObject command = commandOut.as<JsonObject>();
    resourceKeyOut = readStringField(command, "command_id", "commandId");
  }
  return resourceKeyOut.length() > 0;
}

void handleLcdCommand(StaticJsonDocument<1536>& commandDoc, const String& resourceKey) {
  JsonObject command = commandDoc.as<JsonObject>();
  String commandId = readStringField(command, "command_id", "commandId");

  if (resourceKey == lastLcdResourceKey) {
    return;
  }
  if (commandId.length() > 0 && commandId == lastLcdCommandId) {
    lastLcdResourceKey = resourceKey;
    return;
  }

  lastLcdResourceKey = resourceKey;
  if (commandId.length() > 0) {
    lastLcdCommandId = commandId;
  }

  currentSessionId = readStringField(command, "session_id", "sessionId");
  if (currentSessionId.length() > 0) {
    sessionRunning = true;
  }
  String suggestionId = readStringField(command, "suggestion_id", "suggestionId");
  String postureState = readStringField(command, "posture_state", "postureState");
  String deskPosition = readStringField(command, "desk_position", "deskPosition");
  String nextMotorAction = readStringField(command, "next_motor_action", "nextMotorAction");
  String targetPosition = readStringField(command, "target_position", "targetPosition");
  bool acceptEnabled = command["accept_enabled"] | false;
  bool requiresResponse = command["requires_response"] | false;
  float targetHeightCm = command["target_height_cm"] | -1.0;

  String line1 = readStringField(command, "line1");
  String line2 = readStringField(command, "line2");
  if (line1.length() == 0 || line2.length() == 0) {
    String fallbackLine1;
    String fallbackLine2;
    fallbackLcdLines(postureState, deskPosition, fallbackLine1, fallbackLine2);
    if (line1.length() == 0) {
      line1 = fallbackLine1;
    }
    if (line2.length() == 0) {
      line2 = fallbackLine2;
    }
  }
  displayMessage(line1, line2);

  pendingSessionId = currentSessionId;
  pendingSuggestionId = suggestionId;
  pendingCommandId = commandId;
  pendingPostureState = postureState;
  pendingDeskPosition = deskPosition;
  pendingNextMotorAction = nextMotorAction;
  pendingTargetPosition = targetPosition;
  pendingAcceptEnabled = acceptEnabled;
  pendingRequiresResponse = requiresResponse;
  pendingTargetHeightCm = targetHeightCm;
  updatePendingAccept();

  Serial.print("New LCD command: resource_key=");
  Serial.println(resourceKey);
  Serial.print("LCD applied state=");
  Serial.println(postureState);
  Serial.print("desk_position=");
  Serial.println(deskPosition);
  Serial.print("next_motor_action=");
  Serial.println(nextMotorAction);
}

void pollLcdCommand() {
  if (millis() - lastPollAtMs < LCD_POLL_INTERVAL_MS) {
    return;
  }
  lastPollAtMs = millis();

  StaticJsonDocument<1536> command;
  String resourceKey;
  if (latestLcdCommand(command, resourceKey)) {
    handleLcdCommand(command, resourceKey);
  }
}

void rememberLatestLcdCommandOnStartup() {
  StaticJsonDocument<1536> command;
  String resourceKey;
  if (!latestLcdCommand(command, resourceKey)) {
    return;
  }
  JsonObject obj = command.as<JsonObject>();
  lastLcdResourceKey = resourceKey;
  lastLcdCommandId = readStringField(obj, "command_id", "commandId");
  currentSessionId = "";
  clearPendingAccept();
  Serial.print("Startup ignored stale lcdCommand: ");
  Serial.println(resourceKey);
}

bool sendStartEvent() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("START SEND FAIL: WiFi disconnected");
    return false;
  }

  StaticJsonDocument<512> content;
  content["device_id"] = DEVICE_ID;
  content["button"] = "A";
  content["action"] = "start";
  content["event"] = "button_pressed";
  content["event_id"] = makeRequestId();
  content["uptime_ms"] = millis();

  bool ok = postButtonEvent(content);
  if (ok) {
    Serial.println("START event sent");
  } else {
    Serial.println("START SEND FAIL");
  }
  return ok;
}

bool sendStopEvent() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("STOP SEND FAIL: WiFi disconnected");
    return false;
  }

  StaticJsonDocument<512> content;
  content["device_id"] = DEVICE_ID;
  content["button"] = "A";
  content["action"] = "stop";
  content["event"] = "button_pressed";
  content["event_id"] = makeRequestId();
  content["uptime_ms"] = millis();
  if (currentSessionId.length() > 0) {
    content["session_id"] = currentSessionId;
  }

  bool ok = postButtonEvent(content);
  if (ok) {
    Serial.println("STOP event sent");
  } else {
    Serial.println("STOP SEND FAIL");
  }
  return ok;
}

bool sendAcceptEvent() {
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("ACCEPT failed: WiFi disconnected");
    return false;
  }

  StaticJsonDocument<768> content;
  content["device_id"] = DEVICE_ID;
  content["button"] = "B";
  content["action"] = "accept";
  content["event"] = "button_pressed";
  content["event_id"] = makeRequestId();
  content["session_id"] = pendingSessionId;
  content["desk_position"] = pendingDeskPosition;
  content["requested_motor_action"] = pendingNextMotorAction;
  if (pendingSuggestionId.length() > 0) {
    content["suggestion_id"] = pendingSuggestionId;
  }
  if (pendingCommandId.length() > 0) {
    content["command_id"] = pendingCommandId;
  }
  if (pendingTargetPosition.length() > 0) {
    content["target_position"] = pendingTargetPosition;
  }
  if (pendingTargetHeightCm >= 0.0) {
    content["target_height_cm"] = pendingTargetHeightCm;
  }
  content["uptime_ms"] = millis();

  bool ok = postButtonEvent(content);
  if (ok) {
    Serial.println("ACCEPT event sent");
  } else {
    Serial.println("ACCEPT failed");
  }
  return ok;
}

void onButtonAPressed() {
  if (sessionRunning) {
    Serial.println("Button A pressed: STOP");
    displayMessage("SESSION END", "PLEASE WAIT");
    if (sendStopEvent()) {
      sessionRunning = false;
      currentSessionId = "";
      clearPendingAccept();
      displayMessage("SYSTEM READY", "PRESS BUTTON A");
    } else {
      displayTemporary("STOP SEND FAIL", "TRY AGAIN");
    }
  } else {
    Serial.println("Button A pressed: START");
    displayMessage("ANALYSIS START", "PLEASE WAIT");
    if (sendStartEvent()) {
      sessionRunning = true;
    } else {
      displayTemporary("START SEND FAIL", "TRY AGAIN");
    }
  }
}

void onButtonBPressed() {
  Serial.println("Button B pressed");
  if (!acceptPending) {
    Serial.println("ACCEPT ignored: no pending request");
    return;
  }

  if (sendAcceptEvent()) {
    clearPendingAccept();
    displayMessage("REQUEST SENT", "PLEASE WAIT");
  }
}

void updateButton(ButtonDebounce& state, uint8_t pin, void (*onPressed)()) {
  bool reading = digitalRead(pin);
  unsigned long now = millis();
  if (reading != state.lastReading) {
    state.changedAtMs = now;
    state.lastReading = reading;
  }
  if (now - state.changedAtMs < DEBOUNCE_MS) {
    return;
  }
  if (reading != state.stableState) {
    state.stableState = reading;
    if (state.stableState == LOW) {
      onPressed();
    }
  }
}

void checkButtons() {
  if (digitalRead(BUTTON_A_PIN) == LOW && digitalRead(BUTTON_B_PIN) == LOW) {
    return;
  }
  updateButton(buttonA, BUTTON_A_PIN, onButtonAPressed);
  updateButton(buttonB, BUTTON_B_PIN, onButtonBPressed);
}

void setup() {
  Serial.begin(115200);

  pinMode(BUTTON_A_PIN, INPUT_PULLUP);
  pinMode(BUTTON_B_PIN, INPUT_PULLUP);

  lcd.init();
  lcd.backlight();
  displayMessage("SYSTEM READY", "PRESS BUTTON A");

  manageWiFi();
  unsigned long startedAt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startedAt < 10000) {
    manageWiFi();
    delay(50);
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi connected, IP=");
    Serial.println(WiFi.localIP());
    Serial.println("Waiting for LCD command");
    rememberLatestLcdCommandOnStartup();
  }
  displayMessage("SYSTEM READY", "PRESS BUTTON A");
}

void loop() {
  manageWiFi();
  expireTemporaryMessage();
  checkButtons();
  if (sessionRunning) {
    pollLcdCommand();
  }
}
