/*
  DRV8825 + NEMA17 stepper motor test sketch for Arduino UNO R4 WiFi.

  This sketch is only for bench testing motor direction, step count, and speed.
  It does not connect to Wi-Fi or Mobius.

  Existing project motor pins:
    STEP: D4
    DIR : D5

  Serial Monitor:
    baud rate: 115200
    line ending: Newline

  Commands:
    h                 Print help
    stat              Print current settings
    u                 Move UP using default steps
    d                 Move DOWN using default steps
    u 1000            Move UP 1000 steps
    d 1000            Move DOWN 1000 steps
    s 500             Set default move steps
    v 500 500         Set STEP high/low pulse width in microseconds
    b 1000 1000       Move UP 1000 steps, pause 1000 ms, then DOWN 1000 steps
    i                 Invert direction mapping
    x                 Emergency stop

  Notes:
    - Motor force/torque is mainly set by DRV8825 current limit Vref and motor
      power supply, not by Arduino code.
    - This code helps find usable speed and step count. If the motor skips,
      stalls, or vibrates, increase pulse widths or reduce steps/load.
*/

const uint8_t STEP_PIN = 4;
const uint8_t DIR_PIN = 5;

// The current project motor sketch uses HIGH for UP and LOW for DOWN.
bool dirToUpLevel = HIGH;

const unsigned long ABSOLUTE_MAX_STEPS = 20000;
const unsigned int MIN_PULSE_US = 100;
const unsigned int MAX_PULSE_US = 5000;

unsigned long defaultSteps = 500;
unsigned int stepHighUs = 500;
unsigned int stepLowUs = 500;

bool moving = false;
bool stepPinHigh = false;
bool currentMoveUp = true;
unsigned long remainingSteps = 0;
unsigned long completedSteps = 0;
unsigned long lastEdgeAtUs = 0;

bool bouncePending = false;
unsigned long bounceSteps = 0;
unsigned long bouncePauseMs = 1000;
unsigned long bounceResumeAtMs = 0;

String inputLine = "";

void printHelp() {
  Serial.println();
  Serial.println("=== Stepper Motor Test ===");
  Serial.println("h                 help");
  Serial.println("stat              current settings");
  Serial.println("u                 move UP default steps");
  Serial.println("d                 move DOWN default steps");
  Serial.println("u 1000            move UP 1000 steps");
  Serial.println("d 1000            move DOWN 1000 steps");
  Serial.println("s 500             set default steps");
  Serial.println("v 500 500         set high/low pulse us");
  Serial.println("b 1000 1000       up, pause ms, down");
  Serial.println("i                 invert UP/DOWN direction");
  Serial.println("x                 emergency stop");
  Serial.println();
}

void printStatus() {
  Serial.println();
  Serial.println("=== Status ===");
  Serial.print("STEP_PIN=D");
  Serial.println(STEP_PIN);
  Serial.print("DIR_PIN=D");
  Serial.println(DIR_PIN);
  Serial.print("UP level=");
  Serial.println(dirToUpLevel == HIGH ? "HIGH" : "LOW");
  Serial.print("defaultSteps=");
  Serial.println(defaultSteps);
  Serial.print("stepHighUs=");
  Serial.println(stepHighUs);
  Serial.print("stepLowUs=");
  Serial.println(stepLowUs);
  Serial.print("moving=");
  Serial.println(moving ? "true" : "false");
  Serial.print("remainingSteps=");
  Serial.println(remainingSteps);
  Serial.println();
}

unsigned long clampSteps(unsigned long steps) {
  if (steps == 0) {
    return defaultSteps;
  }
  if (steps > ABSOLUTE_MAX_STEPS) {
    Serial.print("Step count clamped to ");
    Serial.println(ABSOLUTE_MAX_STEPS);
    return ABSOLUTE_MAX_STEPS;
  }
  return steps;
}

unsigned int clampPulse(unsigned long value) {
  if (value < MIN_PULSE_US) {
    return MIN_PULSE_US;
  }
  if (value > MAX_PULSE_US) {
    return MAX_PULSE_US;
  }
  return (unsigned int)value;
}

void setDirection(bool up) {
  currentMoveUp = up;
  bool level = up ? dirToUpLevel : !dirToUpLevel;
  digitalWrite(DIR_PIN, level);
  delayMicroseconds(20);
}

void startMove(bool up, unsigned long steps) {
  if (moving) {
    Serial.println("Ignored: motor is already moving. Send x to stop.");
    return;
  }

  steps = clampSteps(steps);
  setDirection(up);
  digitalWrite(STEP_PIN, LOW);
  stepPinHigh = false;
  remainingSteps = steps;
  completedSteps = 0;
  lastEdgeAtUs = micros();
  moving = true;

  Serial.print("Move start: direction=");
  Serial.print(up ? "UP" : "DOWN");
  Serial.print(", steps=");
  Serial.print(steps);
  Serial.print(", high_us=");
  Serial.print(stepHighUs);
  Serial.print(", low_us=");
  Serial.println(stepLowUs);
}

void stopMove(const char* reason) {
  digitalWrite(STEP_PIN, LOW);
  moving = false;
  stepPinHigh = false;
  remainingSteps = 0;
  bouncePending = false;

  Serial.print("Motor stopped: ");
  Serial.println(reason);
}

void finishMove() {
  digitalWrite(STEP_PIN, LOW);
  moving = false;
  stepPinHigh = false;

  Serial.print("Move complete: direction=");
  Serial.print(currentMoveUp ? "UP" : "DOWN");
  Serial.print(", completed_steps=");
  Serial.println(completedSteps);

  if (bouncePending) {
    bounceResumeAtMs = millis() + bouncePauseMs;
    Serial.print("Bounce pause ms=");
    Serial.println(bouncePauseMs);
  }
}

void updateMotor() {
  if (!moving) {
    if (bouncePending && millis() >= bounceResumeAtMs) {
      bouncePending = false;
      startMove(false, bounceSteps);
    }
    return;
  }

  unsigned long nowUs = micros();
  unsigned long interval = stepPinHigh ? stepHighUs : stepLowUs;

  if ((unsigned long)(nowUs - lastEdgeAtUs) < interval) {
    return;
  }

  lastEdgeAtUs = nowUs;

  if (stepPinHigh) {
    digitalWrite(STEP_PIN, LOW);
    stepPinHigh = false;
    completedSteps++;
    if (remainingSteps > 0) {
      remainingSteps--;
    }
    if (remainingSteps == 0) {
      finishMove();
    }
  } else {
    digitalWrite(STEP_PIN, HIGH);
    stepPinHigh = true;
  }
}

String tokenAt(const String& line, int index) {
  int tokenIndex = 0;
  int start = -1;
  for (int i = 0; i <= line.length(); i++) {
    bool separator = (i == line.length()) || isWhitespace(line.charAt(i));
    if (!separator && start < 0) {
      start = i;
    }
    if (separator && start >= 0) {
      if (tokenIndex == index) {
        return line.substring(start, i);
      }
      tokenIndex++;
      start = -1;
    }
  }
  return "";
}

void handleCommand(String line) {
  line.trim();
  if (line.length() == 0) {
    return;
  }

  String command = tokenAt(line, 0);
  command.toLowerCase();

  if (command == "h" || command == "help") {
    printHelp();
    return;
  }

  if (command == "stat") {
    printStatus();
    return;
  }

  if (command == "x" || command == "stop") {
    stopMove("serial stop");
    return;
  }

  if (command == "i") {
    dirToUpLevel = !dirToUpLevel;
    Serial.print("Direction mapping inverted. UP level=");
    Serial.println(dirToUpLevel == HIGH ? "HIGH" : "LOW");
    return;
  }

  if (command == "s") {
    unsigned long steps = tokenAt(line, 1).toInt();
    defaultSteps = clampSteps(steps);
    Serial.print("defaultSteps=");
    Serial.println(defaultSteps);
    return;
  }

  if (command == "v") {
    unsigned long highValue = tokenAt(line, 1).toInt();
    unsigned long lowValue = tokenAt(line, 2).toInt();
    if (highValue == 0 || lowValue == 0) {
      Serial.println("Usage: v <high_us> <low_us>");
      return;
    }
    stepHighUs = clampPulse(highValue);
    stepLowUs = clampPulse(lowValue);
    Serial.print("Pulse updated: high_us=");
    Serial.print(stepHighUs);
    Serial.print(", low_us=");
    Serial.println(stepLowUs);
    return;
  }

  if (command == "u" || command == "up") {
    startMove(true, tokenAt(line, 1).toInt());
    return;
  }

  if (command == "d" || command == "down") {
    startMove(false, tokenAt(line, 1).toInt());
    return;
  }

  if (command == "b" || command == "bounce") {
    if (moving) {
      Serial.println("Ignored: motor is already moving. Send x to stop.");
      return;
    }
    bounceSteps = clampSteps(tokenAt(line, 1).toInt());
    unsigned long pauseValue = tokenAt(line, 2).toInt();
    bouncePauseMs = pauseValue == 0 ? 1000 : pauseValue;
    bouncePending = true;
    startMove(true, bounceSteps);
    return;
  }

  Serial.print("Unknown command: ");
  Serial.println(line);
  Serial.println("Send h for help.");
}

void readSerial() {
  while (Serial.available() > 0) {
    char ch = (char)Serial.read();
    if (ch == '\r') {
      continue;
    }
    if (ch == '\n') {
      handleCommand(inputLine);
      inputLine = "";
    } else {
      inputLine += ch;
      if (inputLine.length() > 80) {
        inputLine = "";
        Serial.println("Input too long; cleared.");
      }
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  pinMode(STEP_PIN, OUTPUT);
  pinMode(DIR_PIN, OUTPUT);
  digitalWrite(STEP_PIN, LOW);
  digitalWrite(DIR_PIN, !dirToUpLevel);

  Serial.println("Stepper motor test ready.");
  printHelp();
  printStatus();
}

void loop() {
  readSerial();
  updateMotor();
}
