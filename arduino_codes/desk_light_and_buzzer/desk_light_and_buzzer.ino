#define Red_pin 3
#define Green_pin 5
#define Blue_pin 6
#define Buzzer_pin 9

void setup() {//인풋은 나중에, 일단은 아웃풋만 설정
  pinMode(Red_pin,OUTPUT);
  pinMode(Green_pin,OUTPUT);
  pinMode(Blue_pin,OUTPUT);
  pinMode(Buzzer_pin,OUTPUT);
  Serial.begin(9600);
}
int Red_b=255;//brightness
int Green_b=255;
int Blue_b=200;//좀 눈 덜아프게
void led_write(int Red_b,int Green_b,int Blue_b,int on){
  if(on){
  analogWrite(Red_pin,Red_b);
  analogWrite(Green_pin,Green_b);
  analogWrite(Blue_pin,Blue_b);
  }
  else{
  analogWrite(Red_pin,0);
  analogWrite(Green_pin,0);
  analogWrite(Blue_pin,0);
  }
}
int condition=0;
void loop() {
  /*색깔을 어떻게 하지?

  */
  condition++;//확인용
  if(condition==3)condition-=3;
  //condition=input;//인풋은 아직 미구현
  switch(condition){
    case 0://평소
      Red_b=255;
      Green_b=255;
      Blue_b=20;
      led_write(Red_b,Green_b,Blue_b,1);
      noTone(Buzzer_pin);
      break;
    case 1://거북목
      Red_b=255;
      Green_b=255;
      Blue_b=0;
      led_write(Red_b,Green_b,Blue_b,1);
      noTone(Buzzer_pin);
      break;
    case 2://졸때
      Red_b=255;
      Green_b=0;
      Blue_b=0;
      led_write(Red_b,Green_b,Blue_b,1);
      tone(Buzzer_pin,440);
      break;
  }
  delay(1000);
}
