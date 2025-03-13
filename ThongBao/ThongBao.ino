/*
 * ThongBao.ino
 * Arduino code điều khiển thông báo LED và còi cho hệ thống điểm danh.
 * - LED xanh: bật trong 5 giây khi sinh viên điểm danh kịp thời (dưới 10 phút).
 * - LED đỏ: bật trong 5 giây khi sinh viên điểm danh trễ (trên 10 phút).
 * - Còi: kêu trong 5 giây, ứng với mỗi mốc thời gian (tiết) trễ.
 */

const int greenPin = 9;    // chân LED xanh
const int redPin   = 10;   // chân LED đỏ
const int buzzerPin = 11;  // chân còi

void setup() {
  pinMode(greenPin, OUTPUT);
  pinMode(redPin, OUTPUT);
  pinMode(buzzerPin, OUTPUT);
  Serial.begin(9600);
}

void loop() {
  if (Serial.available() > 0) {
    String command = Serial.readStringUntil('\n');
    command.trim();
    if (command == "GREEN_ON") {
      digitalWrite(greenPin, HIGH);
    } else if (command == "GREEN_OFF") {
      digitalWrite(greenPin, LOW);
    } else if (command == "RED_ON") {
      digitalWrite(redPin, HIGH);
    } else if (command == "RED_OFF") {
      digitalWrite(redPin, LOW);
    } else if (command == "BUZZER_ON") {
      digitalWrite(buzzerPin, HIGH);
    } else if (command == "BUZZER_OFF") {
      digitalWrite(buzzerPin, LOW);
    } else if (command == "RESET") {
      digitalWrite(greenPin, LOW);
      digitalWrite(redPin, LOW);
      digitalWrite(buzzerPin, LOW);
    }
  }
}
