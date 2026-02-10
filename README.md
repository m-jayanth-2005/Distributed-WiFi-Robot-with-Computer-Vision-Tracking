# 🤖 ESP32-ESP8266 WiFi Robot with Computer Vision Tracking

## 📌 Project Overview
This project is a **modular, WiFi-controlled robot** designed for telemedicine and patient monitoring. It features a **Centralized WiFi Architecture** where multiple ESP modules connect to a single router to distribute processing tasks.

The system supports **Dual Modes**:
1.  **Manual Mode:** Remote control via keyboard (WASD) with Pan/Tilt camera adjustment.
2.  **Auto-Tracking Mode:** Autonomous person tracking using Computer Vision (Haar Cascades + CSRT Tracking) and PID control for smooth movements.

---

## 📂 System Architecture
The project follows a **Model-View-Controller (MVC)** design pattern to ensure scalability for future AI integration.

### **Device 1: The Eyes (ESP32-CAM)**
* **Role:** Captures live video and streams it via HTTP (MJPEG).
* **Protocol:** HTTP Web Server on Port `81`.
* **Resolution:** QVGA (320x240) optimized for low latency (<200ms).

### **Device 2: The Muscles (ESP8266 NodeMCU)**
* **Role:** Receives motor commands and drives the L298N driver and servos.
* **Protocol:** UDP Listener on Port `1235`.
* **Failsafe:** Auto-stops motors if no signal is received for 1 second (Watchdog).

### **Device 3: The Brain (Laptop/PC)**
* **Role:** Runs the Python application (`medical_robot.py`).
* **Functions:** * Fetches video stream.
    * Runs OpenCV tracking algorithms.
    * Calculates PID error correction.
    * Sends UDP commands to ESP8266.
    * Manages SQLite database (`medibot.db`) for patient logs.

---

## 🛠 Hardware Requirements
* **Microcontrollers:**
    * 1x AI-Thinker ESP32-CAM
    * 1x ESP8266 NodeMCU (ESP-12E)
* **Motor Driver:**
    * 1x L298N Motor Driver Module
* **Actuators:**
    * 2x DC Gear Motors + Wheels
    * 2x SG90 Micro Servos (Pan/Tilt mechanism)
* **Power:**
    * 2x 18650 Li-ion Batteries (7.4V source)
    * External 5V Regulator (recommended for ESP32-CAM stability)
* **Network:**
    * WiFi Router (2.4GHz)

---

## 🔌 Wiring Diagram

### **ESP8266 (NodeMCU) to L298N & Servos**
| Component | Pin Label | ESP8266 Pin (D-Notation) | Function |
| :--- | :--- | :--- | :--- |
| **L298N** | ENA | **D7** | Left Motor Speed (PWM) |
| | IN1 | **D1** | Left Motor Dir A |
| | IN2 | **D2** | Left Motor Dir B |
| | IN3 | **D3** | Right Motor Dir A |
| | IN4 | **D4** | Right Motor Dir B |
| | ENB | **D8** | Right Motor Speed (PWM) |
| **Servos** | Pan Signal | **D5** | Left/Right Camera Movement |
| | Tilt Signal | **D6** | Up/Down Camera Movement |

> **⚠️ Important:** Connect the **Ground (GND)** of the L298N, Batteries, and ESP8266 together.

---

## 💻 Software Requirements

### **1. Arduino IDE (For Microcontrollers)**
* **Board Managers:**
    * `http://arduino.esp8266.com/stable/package_esp8266com_index.json`
    * `https://dl.espressif.com/dl/package_esp32_index.json`
* **Required Libraries:** `ESP8266WiFi`, `WiFiUdp`, `Servo`, `esp_camera`, `WiFi`.

### **2. Python Environment (For The Brain)**
* **Python 3.x**
* **Required Libraries:**
    ```bash
    pip install opencv-python opencv-contrib-python pillow numpy
    ```

---

## 🚀 Installation & Setup

### **Step 1: Flash Device 1 (ESP32-CAM)**
1.  Open `Device1_ESP32_Camera.ino`.
2.  Update `ssid` and `password` variables.
3.  Select Board: **AI Thinker ESP32-CAM**.
4.  Upload code.
5.  Open Serial Monitor, reset board, and note the **Camera IP** (e.g., `192.168.1.41`).

### **Step 2: Flash Device 2 (ESP8266)**
1.  Open `Device2_ESP8266_Motors.ino`.
2.  Update `ssid` and `password` variables.
3.  Select Board: **NodeMCU 1.0 (ESP-12E Module)**.
4.  Upload code.
5.  Open Serial Monitor, reset board, and note the **Motor IP** (e.g., `192.168.1.221`).

### **Step 3: Run the Brain (Python)**
1.  Open `medical_robot.py`.
2.  Update `DEFAULT_CAM_IP` and `DEFAULT_MOTOR_IP` at the top of the file.
3.  Run the script:
    ```bash
    python medical_robot.py
    ```

---

## 🎮 Usage Guide

### **Manual Mode**
* **Connect:** Enter IPs and click "CONNECT".
* **Drive:** Use `W` (Forward), `S` (Backward), `A` (Spin Left), `D` (Spin Right).
* **Look:** Use `Arrow Keys` to move the camera head.
* **Speed:** Adjust the on-screen slider.

### **Auto-Tracking Mode**
1.  Click the **"MODE: MANUAL"** button to switch to **AUTO**.
2.  The robot scans for a face (Haar Cascade).
3.  Once detected (Green Box), it locks on using the CSRT Tracker.
4.  PID Controller adjusts motor speed to keep the person centered.
5.  **Safety:** If the target is lost, the robot stops moving immediately.

---

## 🔮 Future Roadmap
* [ ] **Activity Recognition:** Integrate TensorFlow Lite for pose classification (Sitting, Standing, Falling).
* [ ] **Cloud Dashboard:** Web interface for remote doctor access.
* [ ] **Voice Interaction:** Two-way audio communication via ESP32.

---

## 📄 License
This project is open-source and available under the MIT License.
