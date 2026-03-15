GuitaRNG

Cryptographic Sound Guitar Entropy Harvester (MicroPython Edition)
A Jupiter Labs Project

GuitaRNG is a True Random Number Generator (TRNG) built for the ESP32-S3. It harvests high-quality entropy from the physical world, specifically from the acoustic resonance and percussive hits of a guitar via a piezo sensor, and combines it with environmental and silicon-level noise.

The raw entropy is conditioned using a BLAKE3-inspired ARX construction and continuously monitored using a suite of NIST SP 800-90B health tests to ensure cryptographic viability.
Features

    Multi-Source Harvesting: Collects entropy from Piezo ADC (guitar strums), ESP32 Hardware RNG, CPU Timing Jitter, WiFi RSSI variations, and BLE advertisement timing.

    Robust Conditioning: Utilizes an avalanche mixing pool (256-byte) paired with a BLAKE3-inspired cryptographic conditioner (7-round ARX construction) and Von Neumann debiasing.

    Real-Time Health Monitoring: Implements continuous NIST SP 800-90B health checks, including Repetition Count Test (RCT), Adaptive Proportion Test (APT), Chi-Square, and Runs tests.

    Network & Discord Integration: Sends base64-encoded entropy bursts to a designated receiver via UDP and broadcasts live "STRUM" events to external listeners (like a Discord bot).

    Live Tuning: Features a UDP control plane (port 5010) to adjust ADC noise floors, hit thresholds, and debounce settings on the fly without rebooting.

    Interactive RGB: Includes WS2812B NeoPixel support for visual feedback. It cycles a full color spectrum on a recognized strum and returns to a pulsating white idle state.

Hardware Requirements

    Microcontroller: ESP32-S3 (Tested on DevKitC WROOM1 N16R8).

    Sensor: Analog piezo electric sensor wired to an ADC-capable pin (Default: GPIO 4).

    Visuals (Optional): ESP32-S3 addressable LED compatible.

Project Structure

    boot.py: Minimal bootstrapper; enables garbage collection and preps the board.

    config.py: The master configuration file. All tunable parameters (thresholds, networking, pins, toggles) live here.

    control.py: The runtime control plane for live UDP parameter adjustments.

    entropy.py: The core cryptographic engine containing the BLAKE3 conditioner, pool mixing, debiasing, and NIST health monitors.

    main.py: The main execution loop handling sensor polling, networking, LED management, and dashboard reporting.

Installation & Setup

    Flash your ESP32-S3 with the latest MicroPython firmware.

    Clone this repository and update config.py with your specific parameters:

        Add your WIFI_SSID and WIFI_PASSWORD.

        Update TARGET_IP (for the strum listener) and ENTROPY_RECEIVER_IP to your network architecture.

        Adjust PIEZO_ADC_PIN and RGB_PIN if your wiring differs from the defaults.

    Upload all .py files to the root of your ESP32-S3 using your preferred tool (e.g., mpremote, ampy, or Thonny).

    Reboot the board. You can connect via USB serial to view the real-time entropy grading dashboard and ADC debugging stats.

Tuning Guide

Every guitar and piezo setup is different. Use the serial monitor output to fine-tune your configuration in config.py or live via UDP:

    Too many false hits? Raise PIEZO_HIT_THRESHOLD or ADC_NOISE_FLOOR.

    Low entropy scores? Increase SAMPLE_BATCH_SIZE or lower POLL_DELAY_MS.

    Health test failures? Ensure the environment isn't completely static and verify the hardware RNG/Jitter sources are enabled.