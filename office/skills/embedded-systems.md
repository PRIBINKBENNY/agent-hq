# Embedded systems for robots (updated 2026-10-21)
- Boards: ESP32 (Wi-Fi, cheap, Arduino and ESP-IDF), Raspberry Pi Pico (RP2040/RP2350, MicroPython or C), Raspberry
  Pi 4/5 for Linux-level perception. Pick the cheapest board that has the timers and I/O the robot needs.
- Servos: hobby PWM servos (50 Hz, 1-2 ms pulse) for small arms; serial bus servos (Dynamixel-style, half-duplex UART)
  when you need position feedback and daisy-chaining; always a separate power rail with a common ground.
- Firmware structure: a fixed-rate control loop (e.g. 100 Hz) driven by a hardware timer; a serial protocol with a
  length byte, command id, payload and checksum; a watchdog that centres or holds the robot if the host goes quiet.
- Safety in firmware, not the host: joint limits, max velocity, current limit, and an e-stop input that cuts PWM
  without software.
- Host link: USB serial or Wi-Fi (ESP32) with a small Python driver that mirrors the protocol and has unit tests
  against recorded byte streams. Log every frame with a timestamp.
- Calibration: store per-joint offsets in flash, expose a calibrate command, and never hard-code them in the host.
- Power: brown-outs cause most "random resets"; measure current under load, size the supply at 1.5x, add bulk
  capacitance near the servos.
- Document the wiring with a diagram and a bill of materials with prices; it is part of the deliverable.
Sources: ESP-IDF and Raspberry Pi Pico SDK docs; Dynamixel protocol 2.0 documentation; Arduino Servo library notes.
