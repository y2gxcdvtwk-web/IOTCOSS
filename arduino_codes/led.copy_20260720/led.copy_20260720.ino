#include <WiFiS3.h>
#include <WiFiSSLClient.h>
#include <ArduinoJson.h>

const char WIFI_SSID[] = "ADDHD";
const char WIFI_PASSWORD[] = "PASSWORD";

const char MOBIUS_HOST[] = "platform.iotcoss.ac.kr";
const int MOBIUS_PORT = 443;
const char MOBIUS_ROOT_PATH[] = "/api/proxy/swagger/Mobius";

const char MOBIUS_ORIGIN[] = "S";
const char MOBIUS_API_KEY[] = "REDACTED_MOBIUS_API_KEY_00000000";
const char MOBIUS_LECTURE[] = "LCT_20260002";
const char MOBIUS_CREATOR[] = "sjuADDHD";

const char DEVICE_ID[] = "posture-light-uno-r4-01";
const char AE_NAME[] = "postureLight";
const char COMMAND_CONTAINER[] = "command";
const char STATUS_CONTAINER[] = "status";
const char EVENTS_CONTAINER[] = "lightEvents";

// Existing repository wiring used D5 for red and D6 for green.
// Confirm the blue pin and LED type on the actual RGB module before upload.
const uint8_t RED_PIN = 5;
const uint8_t GREEN_PIN = 6;
const uint8_t BLUE_PIN = 9;
const bool RGB_COMMON_ANODE = false;

const unsigned long COMMAND_POLL_INTERVAL_MS = 750;
const unsigned long WIFI_RETRY_INTERVAL_MS = 5000;
const unsigned long HTTP_TIMEOUT_MS = 5000;
const unsigned long STATUS_INTERVAL_MS = 10000;

WiFiSSLClient client;

unsigned long lastPollAtMs = 0;
unsigned long lastStatusAtMs = 0;
unsigned long lastWifiAttemptAtMs = 0;
unsigned long requestCounter = 0;
bool wifiAttempted = false;

String lastCommandResourceKey = "";
String lastCommandId = "";
String activeState = "BOOT";

int currentRed = 0;
int currentGreen = 0;
int currentBlue = 0;
int fadeStartRed = 0;
int fadeStartGreen = 0;
int fadeStartBlue = 0;
int targetRed = 0;
int targetGreen = 255;
int targetBlue = 0;

bool fadeActive = false;
unsigned long fadeStartedAtMs = 0;
unsigned long fadeDurationMs = 0;

String makeRequestId() {
  requestCounter++;
  return String("light-") + String(millis()) + "-" + String(requestCounter);
}

String buildPath(const char* container) {
  return String(MOBIUS_ROOT_PATH) + "/" + AE_NAME + "/" + container;
}

int clampColor(int value) {
  if (value < 0) return 0;
  if (value > 255) return 255;
  return value;
}

void writePwm(uint8_t pin, int value) {
  int pwm = RGB_COMMON_ANODE ? 255 - clampColor(value) : clampColor(value);
  analogWrite(pin, pwm);
}

void applyRgb(int red, int green, int blue) {
  currentRed = clampColor(red);
  currentGreen = clampColor(green);
  currentBlue = clampColor(blue);
  writePwm(RED_PIN, currentRed);
  writePwm(GREEN_PIN, currentGreen);
  writePwm(BLUE_PIN, currentBlue);
}

void defaultRgbForState(const String& state, int& red, int& green, int& blue) {
  if (state == "NORMAL" || state == "DESK_UP" || state == "MOVING_DOWN") {
    red = 0;
    green = 255;
    blue = 0;
    return;
  }
  if (state == "STRETCH_WARNING" || state == "TURTLE_NECK") {
    red = 255;
    green = 0;
    blue = 0;
  }
}

void manageWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

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

bool postContentInstance(const char* container, JsonDocument& content) {
  StaticJsonDocument<768> payload;
  payload["m2m:cin"]["con"].set(content.as<JsonVariant>());
  String body;
  serializeJson(payload, body);

  String response = httpRequest("POST", buildPath(container), body, true);
  int status = httpStatusCode(response);
  return status >= 200 && status < 300;
}

void sendStatus(const char* state) {
  StaticJsonDocument<512> content;
  content["device_id"] = DEVICE_ID;
  content["state"] = state;
  content["current_red"] = currentRed;
  content["current_green"] = currentGreen;
  content["current_blue"] = currentBlue;
  content["reported_at_ms"] = millis();
  postContentInstance(STATUS_CONTAINER, content);
}

void sendLightEvent(const char* eventName, const String& commandId) {
  StaticJsonDocument<512> content;
  content["device_id"] = DEVICE_ID;
  content["event"] = eventName;
  if (commandId.length() > 0) {
    content["command_id"] = commandId;
  }
  content["state"] = activeState;
  content["red"] = currentRed;
  content["green"] = currentGreen;
  content["blue"] = currentBlue;
  content["occurred_at_ms"] = millis();
  postContentInstance(EVENTS_CONTAINER, content);
}

bool latestLightCommand(StaticJsonDocument<1024>& commandOut, String& resourceKeyOut) {
  String response = httpRequest(
    "GET",
    buildPath(COMMAND_CONTAINER) + "/latest",
    "",
    false
  );
  int status = httpStatusCode(response);
  Serial.print("GET postureLight/command/latest HTTP ");
  Serial.println(status);
  if (status == 404) {
    return false;
  }
  if (status < 200 || status >= 300) {
    return false;
  }

  StaticJsonDocument<2048> doc;
  DeserializationError error = deserializeJson(doc, normalizedBody(response));
  if (error) {
    Serial.print("Lighting command parse failed: ");
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

  commandOut.clear();
  if (con.is<JsonObject>()) {
    commandOut.set(con);
  } else if (con.is<const char*>()) {
    DeserializationError conError = deserializeJson(commandOut, con.as<const char*>());
    if (conError) {
      Serial.print("Lighting command parse failed: ");
      Serial.println(conError.c_str());
      return false;
    }
    if (commandOut.as<JsonObject>().isNull()) {
      return false;
    }
  } else {
    Serial.println("Lighting command parse failed: con is not an object");
    return false;
  }

  if (resourceKeyOut.length() == 0) {
    JsonObject command = commandOut.as<JsonObject>();
    const char* commandId = command["command_id"] | "";
    resourceKeyOut = String(commandId);
  }
  return resourceKeyOut.length() > 0;
}

void startFade(int red, int green, int blue, unsigned long transitionMs) {
  fadeStartRed = currentRed;
  fadeStartGreen = currentGreen;
  fadeStartBlue = currentBlue;
  targetRed = clampColor(red);
  targetGreen = clampColor(green);
  targetBlue = clampColor(blue);
  fadeStartedAtMs = millis();
  fadeDurationMs = transitionMs;

  if (transitionMs == 0) {
    fadeActive = false;
    applyRgb(targetRed, targetGreen, targetBlue);
    Serial.println("Lighting fade complete");
    return;
  }

  fadeActive = true;
  Serial.println("Lighting fade started");
}

void updateFade() {
  if (!fadeActive) {
    return;
  }

  unsigned long elapsed = millis() - fadeStartedAtMs;
  if (elapsed >= fadeDurationMs) {
    fadeActive = false;
    applyRgb(targetRed, targetGreen, targetBlue);
    Serial.println("Lighting fade complete");
    sendLightEvent("fade_complete", lastCommandId);
    return;
  }

  float progress = (float)elapsed / (float)fadeDurationMs;
  int red = fadeStartRed + (int)((targetRed - fadeStartRed) * progress);
  int green = fadeStartGreen + (int)((targetGreen - fadeStartGreen) * progress);
  int blue = fadeStartBlue + (int)((targetBlue - fadeStartBlue) * progress);
  applyRgb(red, green, blue);
}

void handleLightCommand(StaticJsonDocument<1024>& commandDoc, const String& resourceKey) {
  JsonObject command = commandDoc.as<JsonObject>();
  String commandId = String(command["command_id"] | "");
  if (resourceKey == lastCommandResourceKey) {
    return;
  }
  if (commandId.length() > 0 && commandId == lastCommandId) {
    lastCommandResourceKey = resourceKey;
    Serial.println("Lighting command unchanged");
    return;
  }

  lastCommandResourceKey = resourceKey;
  if (commandId.length() > 0) {
    lastCommandId = commandId;
  }

  activeState = String(command["state"] | "UNKNOWN");
  int red = currentRed;
  int green = currentGreen;
  int blue = currentBlue;
  defaultRgbForState(activeState, red, green, blue);
  if (command.containsKey("red")) {
    red = command["red"] | red;
  }
  if (command.containsKey("green")) {
    green = command["green"] | green;
  }
  if (command.containsKey("blue")) {
    blue = command["blue"] | blue;
  }
  unsigned long transitionMs = command["transition_ms"] | 0;

  Serial.print("New lighting command: command_id=");
  Serial.println(commandId);
  Serial.print("Light command: state=");
  Serial.print(activeState);
  Serial.print(" target=");
  Serial.print(red);
  Serial.print(",");
  Serial.print(green);
  Serial.print(",");
  Serial.print(blue);
  Serial.print(" transition=");
  Serial.println(transitionMs);

  startFade(red, green, blue, transitionMs);
  sendLightEvent("command_applied", commandId);
}

void pollLightCommand() {
  if (millis() - lastPollAtMs < COMMAND_POLL_INTERVAL_MS) {
    return;
  }
  lastPollAtMs = millis();

  StaticJsonDocument<1024> command;
  String resourceKey;
  if (latestLightCommand(command, resourceKey)) {
    handleLightCommand(command, resourceKey);
  }
}

void rememberLatestCommandOnStartup() {
  StaticJsonDocument<1024> command;
  String resourceKey;
  if (!latestLightCommand(command, resourceKey)) {
    return;
  }
  JsonObject obj = command.as<JsonObject>();
  lastCommandResourceKey = resourceKey;
  lastCommandId = String(obj["command_id"] | "");
  Serial.print("Startup ignored stale lighting command: ");
  Serial.println(resourceKey);
}

void setup() {
  Serial.begin(115200);
  Serial.println("Lighting controller started");

  pinMode(RED_PIN, OUTPUT);
  pinMode(GREEN_PIN, OUTPUT);
  pinMode(BLUE_PIN, OUTPUT);
  applyRgb(0, 0, 0);

  manageWiFi();
  unsigned long startedAt = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - startedAt < 10000) {
    manageWiFi();
    delay(50);
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.print("WiFi connected, IP=");
    Serial.println(WiFi.localIP());
    rememberLatestCommandOnStartup();
    sendStatus("online");
  }
}

void loop() {
  manageWiFi();
  updateFade();
  pollLightCommand();

  if (WiFi.status() == WL_CONNECTED && millis() - lastStatusAtMs >= STATUS_INTERVAL_MS) {
    lastStatusAtMs = millis();
    sendStatus("online");
  }
}
