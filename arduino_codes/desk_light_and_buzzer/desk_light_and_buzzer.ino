#define Red_pin 3
#define Green_pin 5
#define Blue_pin 6
#define Button_pin 9

void setup() {//인풋은 나중에, 일단은 아웃풋만 설정
  pinMode(Red_pin,OUTPUT);
  pinMode(Green_pin,OUTPUT);
  pinMode(Blue_pin,OUTPUT);
}
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
void loop() {
    switch(input){
      case 0://평소
        Red_b=255;
        Green_b=255;
        Blue_b=200;
        led_write(Red_b,Green_b,Blue_b,1);
        break;
      case 1://거북목
        Red_b=255;
        Green_b=0;
        Blue_b=0;
        led_write(Red_b,Green_b,Blue_b,1);
        break;
    }
  delay(200);
}
