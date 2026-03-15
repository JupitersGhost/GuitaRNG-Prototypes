# ╔═══════════════════════════════════════════════════════════════════════════════╗
# ║                    GuitaRNG (MicroPython)            ║
# ║                    All tunable parameters in one place                      ║
# ╚═══════════════════════════════════════════════════════════════════════════════╝
#
# TUNING GUIDE:
# ─────────────
# • Low entropy scores? Increase SAMPLE_BATCH_SIZE, lower POLL_DELAY_MS
# • Too many health failures? Relax RCT_CUTOFF and APT bounds
# • No piezo activity? Lower ADC_NOISE_FLOOR to 20-30
# • CPU too busy? Increase POLL_DELAY_MS to 10-20ms

# ═══════════════════════════════════════════════════════════════════════════════════
#                              TIMING / POLLING
# ═══════════════════════════════════════════════════════════════════════════════════

# Milliseconds between entropy collection cycles
POLL_DELAY_MS = 10

# Number of samples before processing a batch
SAMPLE_BATCH_SIZE = 256

# How often to print the dashboard (in batches)
REPORT_INTERVAL = 5

# Minimum bytes required for valid output
MIN_OUTPUT_BYTES = 8

# ═══════════════════════════════════════════════════════════════════════════════════
#                              PIEZO / ADC SETTINGS
# ═══════════════════════════════════════════════════════════════════════════════════

# ADC deviation below this is considered noise
ADC_NOISE_FLOOR = 25

# Threshold for detecting a guitar strum/hit event (DEVIATION from baseline)
# Start low, raise if too many false triggers.
PIEZO_HIT_THRESHOLD = 170

# Debounce window to prevent duplicate hit detections (ms)
PIEZO_DEBOUNCE_MS = 80

# ADC attenuation level (11dB for full 0-3.3V range)
ADC_ATTENUATION_DB = 11

# ADC GPIO pin for piezo sensor
PIEZO_ADC_PIN = 4

# Enable piezo entropy source
ENABLE_PIEZO = True

# Show raw ADC values in debug output (prints every ~2 seconds)
SHOW_RAW_ADC = True

# ═══════════════════════════════════════════════════════════════════════════════════
#                              ENTROPY SOURCES
# ═══════════════════════════════════════════════════════════════════════════════════

# Enable ESP32 hardware RNG (highly recommended)
ENABLE_HW_RNG = True

# Enable timing jitter entropy collection
ENABLE_TIMING_JITTER = True

# Enable system tick entropy
ENABLE_SYSTEM_TICKS = True

# Enable WiFi RSSI/timing entropy harvesting
ENABLE_WIFI_ENTROPY = True

# Enable BLE advertisement timing entropy
ENABLE_BLE_ENTROPY = True

# Enable colorful ANSI console output
ENABLE_COLORS = True

# ═══════════════════════════════════════════════════════════════════════════════════
#                              ENTROPY POOL
# ═══════════════════════════════════════════════════════════════════════════════════

# Size of the entropy mixing pool in bytes
POOL_SIZE = 256

# ═══════════════════════════════════════════════════════════════════════════════════
#                              HEALTH TESTS (NIST SP 800-90B)
# ═══════════════════════════════════════════════════════════════════════════════════

# Enable Repetition Count Test
ENABLE_RCT = True

# Enable Adaptive Proportion Test
ENABLE_APT = True

# RCT: Maximum allowed consecutive identical values before failure
RCT_CUTOFF = 32

# APT: Sliding window size in bits
APT_WINDOW = 512

# APT: Minimum acceptable ones count in window
APT_MIN_ONES = 180

# APT: Maximum acceptable ones count in window
APT_MAX_ONES = 332

# APT: Warning threshold (tighter than failure)
APT_WARN_MIN = 200
APT_WARN_MAX = 312

# ═══════════════════════════════════════════════════════════════════════════════════
#                              REPORTING / DISPLAY
# ═══════════════════════════════════════════════════════════════════════════════════

# Enable periodic dashboard reports
SHOW_REPORTS = True

# ═══════════════════════════════════════════════════════════════════════════════════
#                              WHITENING / CONDITIONING
# ═══════════════════════════════════════════════════════════════════════════════════

# Enable Von Neumann debiasing
ENABLE_VON_NEUMANN = True

# Enable BLAKE3-inspired cryptographic conditioning
ENABLE_BLAKE3_CONDITIONING = True

# ═══════════════════════════════════════════════════════════════════════════════════
#                              OUTPUT FORMAT
# ═══════════════════════════════════════════════════════════════════════════════════

# Output entropy as Base64 encoded string
OUTPUT_BASE64 = True

# Output entropy as hexadecimal string
OUTPUT_HEX = False

# Output raw binary bits (for debugging)
OUTPUT_RAW_BITS = False

# ═══════════════════════════════════════════════════════════════════════════════════
#                              ENTROPY SCORING
# ═══════════════════════════════════════════════════════════════════════════════════

# Minimum entropy (bits/byte) required for cryptographic use
MIN_ENTROPY_CRYPTO = 7.5

# ═══════════════════════════════════════════════════════════════════════════════════
#                              NETWORK (WiFi + UDP to Discord Bot)
# ═══════════════════════════════════════════════════════════════════════════════════

# Enable WiFi connectivity
ENABLE_WIFI = True

# Enable UDP sending to Discord bot
ENABLE_WIFI_SEND = True

# Target IP for Discord bot (Aoi Midori's listener)
TARGET_IP = (xx, xxx, xx, xxx)

# Target UDP port for Discord bot
TARGET_PORT = 5005

# WiFi SSID
WIFI_SSID = "YOUR_SSID_HERE"

# WiFi Password
WIFI_PASSWORD = "YOUR_PW_HERE"

# Enable Headscale/Tailscale mesh networking (future feature)
USE_HEADSCALE = False

# Headscale hostname (future feature)
#HEADSCALE_HOST = "mesh.local"

# Entropy receiver IP (placeholder for entropy mixing server)
ENTROPY_RECEIVER_IP = (xx, xxx, xx, xxx)

# Entropy receiver port
ENTROPY_RECEIVER_PORT = 5056

# Send entropy in bursts (not continuous stream)
ENTROPY_BURST_MODE = True

# Minimum samples before sending entropy burst
ENTROPY_BURST_MIN_SAMPLES = 256

# Maximum time between entropy sends (seconds)
ENTROPY_BURST_MAX_INTERVAL_SEC = 30

# ═══════════════════════════════════════════════════════════════════════════════════
#                              RGB LED (GPIO48 Addressable WS2812B)
# ═══════════════════════════════════════════════════════════════════════════════════

# Enable RGB LED status indicator
ENABLE_RGB = True

# RGB LED data pin (GPIO48 on ESP32-S3-DevKitC)
RGB_PIN = 48

# LED brightness (0-255, keep moderate for longevity)
RGB_BRIGHTNESS = 200

# Milliseconds between rainbow hue shifts
RGB_CYCLE_SPEED_MS = 100

# Cycle colors on piezo hits
RGB_RAINBOW_ON_STRUM = True

# Idle LED mode: white pulsating breath effect
RGB_IDLE_PULSE_MIN = 10       # minimum brightness during pulse
RGB_IDLE_PULSE_MAX = 200      # maximum brightness during pulse (capped by RGB_BRIGHTNESS)
RGB_IDLE_PULSE_STEP = 3       # brightness change per tick
RGB_IDLE_PULSE_DELAY_MS = 30  # ms between pulse steps

# Seconds of no strum before returning to idle pulse
RGB_IDLE_TIMEOUT_SEC = 2

# ═══════════════════════════════════════════════════════════════════════════════════
#                              BLUETOOTH
# ═══════════════════════════════════════════════════════════════════════════════════

# Enable Bluetooth Low Energy
ENABLE_BLE = True

# BLE device name
BLE_DEVICE_NAME = "ESP-32-GuitaRNG"

# ═══════════════════════════════════════════════════════════════════════════════════
#                              STATIC IP CONFIGURATION (Optional)
# ═══════════════════════════════════════════════════════════════════════════════════

# Use static IP instead of DHCP
USE_STATIC_IP = False

# Static IP address
STATIC_IP = (xxx, xxx, x, xxx)

# Subnet mask
SUBNET_MASK = (xxx, xxx, xxx, x)

# Gateway
GATEWAY = (xxx, xxx, x, x)
