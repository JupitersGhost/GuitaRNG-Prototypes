# ============================================================================
#            GuitaRNG - V.1
#            Cryptographic Sound Guitar Entropy Harvester
#            MicroPython Port for ESP32-S3
# ============================================================================
#
# FEATURES:
# ---------
# - Multi-source entropy: Piezo ADC, Hardware RNG, Timing Jitter, WiFi RSSI
# - BLAKE3-inspired cryptographic conditioning (ARX construction)
# - Full NIST SP 800-90B health tests (RCT, APT, Chi-Square, Runs)
# - Von Neumann debiasing with efficiency tracking
# - Real-time entropy quality dashboard
# - RGB LED: rainbow spectrum cycle on strum, white pulsating idle
# - WiFi UDP: Pings Discord bot on strum + sends entropy bursts
# - Runtime tuning via UDP control plane (port 5010)
# - Forward secrecy via continuous re-keying
#
# HARDWARE: ESP32-S3-DevKitC (dual USB-C, addressable RGB on GPIO48)

import time
import os
import struct
import machine
import neopixel
import gc

from config import (
    # Timing
    POLL_DELAY_MS, SAMPLE_BATCH_SIZE, REPORT_INTERVAL,
    # Piezo / ADC
    ADC_NOISE_FLOOR, PIEZO_HIT_THRESHOLD, PIEZO_DEBOUNCE_MS, PIEZO_ADC_PIN,
    ENABLE_PIEZO, SHOW_RAW_ADC,
    # Entropy sources
    ENABLE_HW_RNG, ENABLE_TIMING_JITTER, ENABLE_SYSTEM_TICKS,
    ENABLE_WIFI_ENTROPY, ENABLE_BLE_ENTROPY,
    # Pool & health
    POOL_SIZE,
    # Reports
    SHOW_REPORTS,
    # Whitening
    ENABLE_VON_NEUMANN, ENABLE_BLAKE3_CONDITIONING,
    # Output
    OUTPUT_BASE64,
    # Network
    ENABLE_WIFI, ENABLE_WIFI_SEND,
    TARGET_IP, TARGET_PORT,
    WIFI_SSID, WIFI_PASSWORD,
    ENTROPY_RECEIVER_IP, ENTROPY_RECEIVER_PORT,
    ENTROPY_BURST_MODE, ENTROPY_BURST_MIN_SAMPLES, ENTROPY_BURST_MAX_INTERVAL_SEC,
    STATIC_IP, SUBNET_MASK, GATEWAY,
    USE_STATIC_IP,
    # RGB
    ENABLE_RGB, RGB_PIN, RGB_BRIGHTNESS, RGB_RAINBOW_ON_STRUM,
    RGB_IDLE_PULSE_MIN, RGB_IDLE_PULSE_MAX, RGB_IDLE_PULSE_STEP,
    RGB_IDLE_PULSE_DELAY_MS, RGB_IDLE_TIMEOUT_SEC,
)

from entropy import (
    Blake3Conditioner, EntropyPool, NistHealthMonitor, VonNeumannDebiaser,
    SOURCE_PIEZO, SOURCE_HW_RNG, SOURCE_JITTER, SOURCE_TICKS, SOURCE_WIFI, SOURCE_BLE,
    HEALTH_EXCELLENT, HEALTH_GOOD, HEALTH_WARNING, HEALTH_FAIL,
    health_symbol, health_name, health_color,
    shannon_entropy, min_entropy, collect_timing_jitter, base64_encode,
)

from control import RuntimeSettings, CTRL_PORT, handle_line, format_status


# ============================================================================
#                         CONSOLE COLORS
# ============================================================================

RESET  = "\x1b[0m"
BOLD   = "\x1b[1m"
DIM    = "\x1b[2m"
CYAN   = "\x1b[96m"
GREEN  = "\x1b[92m"
YELLOW = "\x1b[93m"
WHITE  = "\x1b[97m"


# ============================================================================
#                         RGB LED (WS2812B via neopixel)
# ============================================================================

# Full spectrum rainbow - 12 distinct colors (same as Rust version)
SPECTRUM = [
    (255, 0,   0),     # 0  RED
    (255, 127, 0),     # 1  ORANGE
    (255, 255, 0),     # 2  YELLOW
    (0,   255, 0),     # 3  GREEN
    (0,   255, 255),   # 4  CYAN
    (0,   0,   255),   # 5  BLUE
    (127, 0,   255),   # 6  PURPLE
    (255, 0,   255),   # 7  MAGENTA
    (255, 0,   127),   # 8  PINK
    (255, 63,  0),     # 9  DEEP ORANGE
    (127, 255, 0),     # 10 LIME
    (0,   127, 255),   # 11 SKY BLUE
]


def spectrum_next(index, brightness):
    """Get the next spectrum color scaled by brightness. Returns (r, g, b), new_index."""
    c = SPECTRUM[index % 12]
    r = c[0] * brightness // 255
    g = c[1] * brightness // 255
    b = c[2] * brightness // 255
    return (r, g, b), (index + 1) % 12


def set_led(np, color):
    """Set the single WS2812B LED color (r, g, b)."""
    np[0] = color
    np.write()


# ============================================================================
#                         DASHBOARD PRINTING
# ============================================================================

def print_bar(value, maximum, width):
    filled = int((value / maximum) * width) if maximum > 0 else 0
    filled = min(filled, width)
    bar = '#' * filled + '-' * (width - filled)
    print(bar, end='')


def entropy_grade(shannon, min_ent):
    avg = (shannon + min_ent) / 2.0
    if avg >= 7.85:
        return ("A+", "CRYPTOGRAPHIC", GREEN)
    elif avg >= 7.7:
        return ("A ", "EXCELLENT    ", GREEN)
    elif avg >= 7.5:
        return ("B+", "VERY GOOD    ", GREEN)
    elif avg >= 7.2:
        return ("B ", "GOOD         ", CYAN)
    elif avg >= 6.5:
        return ("C ", "FAIR         ", YELLOW)
    elif avg >= 5.5:
        return ("D ", "MARGINAL     ", YELLOW)
    else:
        return ("F ", "POOR         ", "\x1b[91m")


def print_dashboard(batch, pool, health, debiaser, raw_data, conditioned, wifi_connected):
    raw_shannon = shannon_entropy(raw_data)
    cond_shannon = shannon_entropy(conditioned)
    cond_min = min_entropy(conditioned)
    grade, grade_name, grade_color = entropy_grade(cond_shannon, cond_min)

    print()
    print("{}+==================================================================+{}".format(CYAN, RESET))
    print("{}|{} {}GUITARNG V1.0{} | Batch #{:<6} | Grade: {}{} {}({}){}    {}|{}".format(
        CYAN, RESET, BOLD, RESET, batch, grade_color, grade, RESET, grade_name, RESET, CYAN, RESET))
    print("{}+==================================================================+{}".format(CYAN, RESET))

    # Entropy Quality
    print("{}|{} {}--- ENTROPY QUALITY ---{}                                        {}|{}".format(
        CYAN, RESET, DIM, RESET, CYAN, RESET))

    print("{}|{} Raw Shannon:    {}{:.4f}{} bits/byte  ".format(CYAN, RESET, WHITE, raw_shannon, RESET), end='')
    print_bar(raw_shannon, 8.0, 12)
    print("                {}|{}".format(CYAN, RESET))

    print("{}|{} {}Cond Shannon:   {}{:.4f}{} bits/byte  ".format(CYAN, RESET, BOLD, GREEN, cond_shannon, RESET), end='')
    print_bar(cond_shannon, 8.0, 12)
    print("                {}|{}".format(CYAN, RESET))

    # Health Tests
    print("{}|{} {}--- HEALTH TESTS ---{}                                           {}|{}".format(
        CYAN, RESET, DIM, RESET, CYAN, RESET))

    print("{}|{} Status: {}{} {}{}  RCT:{} APT:{} Chi:{}                    {}|{}".format(
        CYAN, RESET,
        health_color(health.last_status), health_symbol(health.last_status),
        health_name(health.last_status), RESET,
        health.rct_failures, health.apt_failures, health.chi_failures,
        CYAN, RESET))

    # Sources
    total = max(pool.total_mixed, 1)
    adc_pct = (pool.adc_bytes / total) * 100.0
    rng_pct = (pool.rng_bytes / total) * 100.0
    wifi_pct = (pool.wifi_bytes / total) * 100.0
    ble_pct = (pool.ble_bytes / total) * 100.0
    vn_eff = debiaser.efficiency()

    print("{}|{} Piezo:{:>5.1f}%  HW_RNG:{:>5.1f}%  VN_Eff:{:>5.1f}%  WiFi:{}            {}|{}".format(
        CYAN, RESET, adc_pct, rng_pct, vn_eff,
        "Y" if wifi_connected else "N",
        CYAN, RESET))

    print("{}|{} WiFi_Ent:{:>4.1f}%  BLE_Ent:{:>4.1f}%  Sources: {}                  {}|{}".format(
        CYAN, RESET, wifi_pct, ble_pct,
        sum(1 for x in (pool.adc_bytes, pool.rng_bytes, pool.jitter_bytes,
                        pool.tick_bytes, pool.wifi_bytes, pool.ble_bytes) if x > 0),
        CYAN, RESET))

    print("{}+==================================================================+{}".format(CYAN, RESET))


# ============================================================================
#                         WiFi INITIALIZATION
# ============================================================================

def wifi_connect():
    """Attempt WiFi connection. Returns (wlan, connected) — never raises."""
    import network
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    if USE_STATIC_IP:
        ip_str = "{}.{}.{}.{}".format(*STATIC_IP)
        gw_str = "{}.{}.{}.{}".format(*GATEWAY)
        sn_str = "{}.{}.{}.{}".format(*SUBNET_MASK)
        # MicroPython ifconfig: (ip, subnet, gateway, dns)
        wlan.ifconfig((ip_str, sn_str, gw_str, gw_str))

    print("{}[guitarng]{} Connecting to SSID: {}...".format(GREEN, RESET, WIFI_SSID))
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)

    for attempt in range(20):
        if wlan.isconnected():
            ip = wlan.ifconfig()[0]
            print("{}[guitarng]{} WiFi connected! IP: {}".format(GREEN, RESET, ip))
            return wlan, True
        if attempt % 5 == 0:
            print("{}[guitarng]{} WiFi connecting... attempt {}".format(YELLOW, RESET, attempt + 1))
        time.sleep_ms(500)

    print("{}[guitarng]{} WiFi connection timeout, continuing without WiFi".format(YELLOW, RESET))
    return wlan, False


# ============================================================================
#                         UDP SOCKET HELPERS
# ============================================================================

def create_udp_socket(bind_port=None):
    """Create a non-blocking UDP socket, optionally bound to a port."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setblocking(False)
    if bind_port is not None:
        s.bind(('0.0.0.0', bind_port))
    return s


def udp_send(sock, data, ip_tuple, port):
    """Send UDP datagram. Returns True on success."""
    try:
        addr = "{}.{}.{}.{}".format(*ip_tuple)
        sock.sendto(data, (addr, port))
        return True
    except Exception:
        return False


def udp_recv(sock, bufsize=512):
    """Non-blocking UDP receive. Returns (data_bytes, addr) or (None, None)."""
    try:
        data, addr = sock.recvfrom(bufsize)
        return data, addr
    except OSError:
        return None, None


# ============================================================================
#                              HEALTH STATUS -> LED COLOR
# ============================================================================

def health_led_color(status, brightness):
    """Map health status to an RGB tuple for the LED."""
    if status == HEALTH_EXCELLENT:
        return (0, brightness, 0)
    elif status == HEALTH_GOOD:
        return (0, brightness // 2, brightness)
    elif status == HEALTH_WARNING:
        return (brightness, brightness // 2, 0)
    else:  # FAIL
        return (brightness, 0, 0)


# ============================================================================
#                         BLE ENTROPY HARVESTING
# ============================================================================

def _ble_harvest(ble):
    """
    Quick BLE scan burst — harvest entropy from:
      - Number of advertisements seen
      - RSSI of each advertisement (RF noise floor variation)
      - MAC address fragments (random addresses rotate frequently)
      - Inter-arrival timing between advertisements

    Returns a list of u32 entropy values, or empty list on failure.
    Each scan is brief (~100ms) to avoid blocking the main loop.
    """
    results = []
    _ble_scan_data = []

    def _scan_cb(event, data):
        if event == 5:  # _IRQ_SCAN_RESULT
            # data: (addr_type, addr, adv_type, rssi, adv_data)
            addr_type, addr, adv_type, rssi, adv_data = data
            t = time.ticks_us()
            # Must copy addr — MicroPython reuses the underlying buffer
            _ble_scan_data.append((rssi, bytes(addr), t))

    try:
        ble.irq(_scan_cb)
        # Scan for 80ms — short enough to not block, long enough to catch ads
        ble.gap_scan(80, 30000, 30000, True)  # active scan
        time.sleep_ms(100)  # let scan complete
        ble.gap_scan(None)  # stop scan
    except Exception:
        return results

    if not _ble_scan_data:
        return results

    # Mix all the juicy randomness together
    scan_count = len(_ble_scan_data) & 0xFFFFFFFF
    results.append(scan_count ^ (time.ticks_us() & 0xFFFFFFFF))

    for rssi, addr, t in _ble_scan_data:
        # RSSI varies with multipath, distance, interference — great entropy
        rssi_byte = rssi & 0xFF
        # MAC addr bytes — BLE random addresses change frequently
        addr_mix = 0
        for b in addr:
            addr_mix = ((addr_mix << 3) ^ b) & 0xFFFFFFFF
        # Combine: RSSI + address hash + arrival timing
        mixed = (rssi_byte << 24) | (addr_mix & 0x00FFFFFF)
        mixed ^= (t & 0xFFFFFFFF)
        results.append(mixed & 0xFFFFFFFF)

    return results


# ============================================================================
#                                    MAIN
# ============================================================================

def main():
    gc.collect()

    time.sleep_ms(1500)  # Wait for USB serial

    # ========================================================================
    #                              STARTUP BANNER
    # ========================================================================

    print()
    print("{}+==================================================================+{}".format(CYAN, RESET))
    print("{}|{}        {}GuitaRNG V1.0{} - Jupiter Labs / CHIRASU Network        {}|{}".format(
        CYAN, RESET, BOLD, RESET, CYAN, RESET))
    print("{}|{}        Cryptographic Sound Guitar Entropy Harvester             {}|{}".format(
        CYAN, RESET, CYAN, RESET))
    print("{}|{}        [MicroPython Edition]                                    {}|{}".format(
        CYAN, RESET, CYAN, RESET))
    print("{}+==================================================================+{}".format(CYAN, RESET))
    print("{}|{}  Sources: Piezo ADC | Hardware RNG | Timing Jitter | WiFi      {}|{}".format(
        CYAN, RESET, CYAN, RESET))
    print("{}|{}  Conditioning: BLAKE3-inspired ARX whitening (7 rounds)        {}|{}".format(
        CYAN, RESET, CYAN, RESET))
    print("{}|{}  Tests: NIST SP 800-90B (RCT, APT, Chi-Square, Runs, Monobit)  {}|{}".format(
        CYAN, RESET, CYAN, RESET))
    print("{}+==================================================================+{}".format(CYAN, RESET))
    print()

    # ========================================================================
    #                              RGB LED SETUP
    # ========================================================================

    print("{}[guitarng]{} Initializing GPIO...".format(GREEN, RESET))

    np = None
    spectrum_idx = 0
    led_is_idle = True
    idle_brightness = RGB_IDLE_PULSE_MIN
    idle_direction = 1   # 1 = brightening, -1 = dimming
    last_idle_tick = time.ticks_ms()

    if ENABLE_RGB:
        pin = machine.Pin(RGB_PIN, machine.Pin.OUT)
        np = neopixel.NeoPixel(pin, 1)

        # Startup: test ALL spectrum colors then set white idle
        print("{}[guitarng]{} RGB spectrum test...".format(GREEN, RESET))
        for _ in range(12):
            color, spectrum_idx = spectrum_next(spectrum_idx, RGB_BRIGHTNESS)
            set_led(np, color)
            time.sleep_ms(80)

        # Reset index and set white idle
        spectrum_idx = 0
        set_led(np, (RGB_BRIGHTNESS, RGB_BRIGHTNESS, RGB_BRIGHTNESS))
        print("{}[guitarng]{} RGB idle (white pulse)".format(GREEN, RESET))

    last_strum_time = time.ticks_ms()

    # ========================================================================
    #                              ADC FOR PIEZO (GPIO4)
    # ========================================================================

    adc = machine.ADC(machine.Pin(PIEZO_ADC_PIN), atten=machine.ADC.ATTN_11DB)
    print("{}[guitarng]{} ADC initialized on GPIO{} (piezo, read_u16 mode)".format(GREEN, RESET, PIEZO_ADC_PIN))

    # ========================================================================
    #                              HARDWARE RNG
    # ========================================================================

    print("{}[guitarng]{} Hardware RNG initialized (os.urandom)".format(GREEN, RESET))

    # ========================================================================
    #                              WIFI INITIALIZATION
    # ========================================================================

    wifi_connected = False
    wlan = None
    udp_sock = None       # STRUM + entropy sender
    ctrl_sock = None      # Control plane listener

    if ENABLE_WIFI:
        print("{}[guitarng]{} Initializing WiFi...".format(GREEN, RESET))
        try:
            wlan, wifi_connected = wifi_connect()
        except Exception as e:
            print("{}[guitarng]{} WiFi init error: {}".format(YELLOW, RESET, e))
            wifi_connected = False

        if wifi_connected:
            try:
                udp_sock = create_udp_socket(bind_port=5006)
                ctrl_sock = create_udp_socket(bind_port=CTRL_PORT)
                ip = wlan.ifconfig()[0]
                print("{}[guitarng]{} Network sockets ready | IP: {} | Ctrl: port {}".format(
                    GREEN, RESET, ip, CTRL_PORT))
            except Exception as e:
                print("{}[guitarng]{} Socket setup error: {}".format(YELLOW, RESET, e))
    else:
        print("{}[guitarng]{} WiFi disabled in config".format(YELLOW, RESET))

    # ========================================================================
    #                              BLE INITIALIZATION (Deferred)
    # ========================================================================
    #
    # BLE shares the radio with WiFi on ESP32-S3. Activating both at startup
    # can hard-hang the coexistence layer. We defer BLE init to the main loop
    # after WiFi is fully stable.

    ble = None
    ble_active = False
    ble_init_attempted = False
    ble_init_after_sample = 500  # wait this many samples before trying BLE

    if not ENABLE_BLE_ENTROPY:
        print("{}[guitarng]{} BLE entropy disabled in config".format(DIM, RESET))
        ble_init_attempted = True  # skip it entirely

    # ========================================================================
    #                         RUNTIME-TUNABLE SETTINGS
    # ========================================================================

    settings = RuntimeSettings(
        noise_floor=ADC_NOISE_FLOOR,
        hit_threshold=PIEZO_HIT_THRESHOLD,
        debounce_ms=PIEZO_DEBOUNCE_MS,
        baseline_shift=6,   # EMA alpha = 1/64
        udp_target_ip=list(TARGET_IP),
        udp_target_port=TARGET_PORT,
        enable_udp_strum=ENABLE_WIFI_SEND,
    )

    # ========================================================================
    #                              INITIALIZE SUBSYSTEMS
    # ========================================================================

    pool = EntropyPool()
    health = NistHealthMonitor()
    debiaser = VonNeumannDebiaser()
    conditioner = Blake3Conditioner()

    # Piezo baseline tracker
    piezo_baseline = 0
    piezo_baseline_inited = False

    # Baseline freeze window after a hit (keeps baseline from chasing ringdown)
    piezo_freeze_until = 0  # ticks_ms()

    # Buffers
    raw_buffer = bytearray(64)
    debiased_buffer = bytearray(64)
    conditioned = bytearray(32)

    # Statistics
    sample_count = 0
    piezo_samples = 0
    piezo_active = 0
    piezo_peak = 0
    batch_count = 0

    # Piezo hit detection
    last_piezo_hit_time = time.ticks_ms()

    # Entropy burst tracking
    entropy_samples_since_send = 0
    last_entropy_send = time.ticks_ms()

    print("{}[guitarng]{} Initializing entropy collection...".format(GREEN, RESET))
    print("{}[guitarng]{} Poll: {}ms | Batch: {} samples | Noise floor: {}".format(
        GREEN, RESET, POLL_DELAY_MS, SAMPLE_BATCH_SIZE, ADC_NOISE_FLOOR))
    print()
    print("{}[guitarng]{} System ready! Entering main loop...".format(GREEN, RESET))

    # ========================================================================
    #                              MAIN LOOP
    # ========================================================================

    while True:
        now = time.ticks_ms()

        # Keep WiFi status fresh
        if ENABLE_WIFI and wlan is not None:
            wifi_connected = wlan.isconnected()

        # ================================================================
        #              CONTROL PLANE (UDP)
        # ================================================================

        if wifi_connected and ctrl_sock is not None:
            data, addr = udp_recv(ctrl_sock)
            if data is not None:
                try:
                    cmd = data.decode('utf-8').strip()
                    reply = handle_line(cmd, settings)
                    if reply is not None:
                        ctrl_sock.sendto(reply.encode('utf-8'), addr)
                except Exception:
                    try:
                        ctrl_sock.sendto(b"ERR reason=utf8", addr)
                    except Exception:
                        pass

        # ================================================================
        #              DEFERRED BLE INIT (after WiFi is stable)
        # ================================================================

        if not ble_init_attempted and sample_count >= ble_init_after_sample:
            ble_init_attempted = True
            print("{}[guitarng]{} Attempting BLE init (deferred, WiFi stable)...".format(GREEN, RESET))
            try:
                import bluetooth
                ble = bluetooth.BLE()
                ble.active(True)
                ble_active = True
                print("{}[guitarng]{} BLE active — scanning for entropy".format(GREEN, RESET))
            except ImportError:
                print("{}[guitarng]{} BLE module not available on this firmware".format(YELLOW, RESET))
            except Exception as e:
                print("{}[guitarng]{} BLE init failed: {} (continuing without)".format(YELLOW, RESET, e))

        # ================================================================
        #                    COLLECT ENTROPY FROM ALL SOURCES
        # ================================================================

        # 1. Piezo ADC (burst-sample to catch fast piezo spikes)
        if ENABLE_PIEZO:
            # Take multiple rapid reads - piezo pulses are very short,
            # MicroPython's ADC is slower than Rust's read_oneshot,
            # so we burst-sample and keep the peak
            adc_val = 0
            for _burst in range(8):
                sample = adc.read_u16()
                if sample > adc_val:
                    adc_val = sample

            # Mix peak into entropy pool
            piezo_samples += 1
            if adc_val > piezo_peak:
                piezo_peak = adc_val

            pool.mix_u16(adc_val, SOURCE_PIEZO)
            conditioner.absorb_u16(adc_val)

            # ---- Piezo baseline (EMA, quiet-gated + freeze after hit) ----
            if not piezo_baseline_inited:
                piezo_baseline = adc_val
                piezo_baseline_inited = True
            else:
                dev = abs(adc_val - piezo_baseline)

                # Only let baseline move when things are calm, and not right after a hit.
                freeze_over = time.ticks_diff(now, piezo_freeze_until) >= 0
                quiet_gate = settings.noise_floor * 2
                if quiet_gate < 12:
                    quiet_gate = 12

                if freeze_over and dev <= quiet_gate:
                    shift = min(10, max(2, settings.baseline_shift))
                    if adc_val >= piezo_baseline:
                        piezo_baseline += (adc_val - piezo_baseline) >> shift
                    else:
                        piezo_baseline -= (piezo_baseline - adc_val) >> shift

            dev = abs(adc_val - piezo_baseline)

            # Debug output: show ADC status periodically (~2 sec = 200 samples at 10ms)
            if SHOW_RAW_ADC and piezo_samples % 200 == 0:
                print("{}[ADC]{} raw={:5d} base={:5d} dev={:5d} thresh={} peak={}".format(
                    DIM, RESET, adc_val, piezo_baseline, dev,
                    settings.hit_threshold, piezo_peak))

            elapsed_ms = time.ticks_diff(now, last_piezo_hit_time)
            debounce_ok = elapsed_ms > settings.debounce_ms

            # Dev-based noise gating
            if dev > settings.noise_floor:
                piezo_active += 1

            # ---- HIT DETECTION ----
            # Only trigger on UPWARD deviations (adc > baseline = real strum)
            if adc_val > piezo_baseline and dev >= settings.hit_threshold and debounce_ok:
                last_piezo_hit_time = now
                last_strum_time = now
                led_is_idle = False

                # Freeze baseline for 500ms after a hit
                piezo_freeze_until = time.ticks_add(now, 500)

                # Cycle through FULL SPECTRUM colors on strum
                if ENABLE_RGB and RGB_RAINBOW_ON_STRUM and np is not None:
                    color, spectrum_idx = spectrum_next(spectrum_idx, RGB_BRIGHTNESS)
                    set_led(np, color)

                # Send UDP "STRUM" packet to Discord bot (TARGET_IP:TARGET_PORT)
                udp_status = "NO_WIFI"
                if settings.enable_udp_strum and wifi_connected and udp_sock is not None:
                    ip = settings.udp_target_ip
                    port = settings.udp_target_port
                    if udp_send(udp_sock, b"STRUM", ip, port):
                        udp_status = "OK"
                    else:
                        udp_status = "FAIL"

                # ALWAYS print hit with status
                print("{}[HIT]{} ADC={} dev={} base={} -> STRUM {} [#{}]".format(
                    YELLOW, RESET, adc_val, dev, piezo_baseline, udp_status, spectrum_idx))

        # ---- RGB IDLE: white pulsating breath effect ----
        if ENABLE_RGB and np is not None:
            idle_elapsed_sec = time.ticks_diff(now, last_strum_time) / 1000.0

            if idle_elapsed_sec > RGB_IDLE_TIMEOUT_SEC:
                if not led_is_idle:
                    led_is_idle = True
                    idle_brightness = RGB_IDLE_PULSE_MIN
                    idle_direction = 1

                # Pulse the white LED smoothly
                if time.ticks_diff(now, last_idle_tick) >= RGB_IDLE_PULSE_DELAY_MS:
                    last_idle_tick = now
                    idle_brightness += RGB_IDLE_PULSE_STEP * idle_direction

                    pulse_max = min(RGB_IDLE_PULSE_MAX, RGB_BRIGHTNESS)
                    if idle_brightness >= pulse_max:
                        idle_brightness = pulse_max
                        idle_direction = -1
                    elif idle_brightness <= RGB_IDLE_PULSE_MIN:
                        idle_brightness = RGB_IDLE_PULSE_MIN
                        idle_direction = 1

                    set_led(np, (idle_brightness, idle_brightness, idle_brightness))

        # 2. Hardware RNG
        if ENABLE_HW_RNG:
            hw_rand = struct.unpack('<I', os.urandom(4))[0]
            pool.mix_u32(hw_rand, SOURCE_HW_RNG)
            conditioner.absorb_u32(hw_rand)

        # 3. Timing jitter
        if ENABLE_TIMING_JITTER:
            jitter = collect_timing_jitter()
            pool.mix_u32(jitter, SOURCE_JITTER)
            conditioner.absorb_u32(jitter)

        # 4. System ticks
        if ENABLE_SYSTEM_TICKS:
            ticks = time.ticks_us() & 0xFFFFFFFF
            mixed_ticks = ticks ^ ((ticks << 7) & 0xFFFFFFFF) ^ ((ticks >> 13) & 0xFFFFFFFF)
            mixed_ticks &= 0xFFFFFFFF
            pool.mix_u32(mixed_ticks, SOURCE_TICKS)
            conditioner.absorb_u32(mixed_ticks)

        # 5. WiFi RSSI entropy (every 50 samples to avoid overhead)
        if ENABLE_WIFI_ENTROPY and wifi_connected and wlan is not None:
            if sample_count % 50 == 0:
                try:
                    rssi = wlan.status('rssi')  # typically -30 to -90 dBm
                    rssi_time = time.ticks_us() & 0xFFFF
                    rssi_val = ((rssi & 0xFF) << 8) | (rssi_time & 0xFF)
                    pool.mix_u16(rssi_val, SOURCE_WIFI)
                    conditioner.absorb_u16(rssi_val)
                    rssi_mixed = (rssi & 0xFF) ^ ((rssi_time >> 3) & 0xFF)
                    pool.mix_byte(rssi_mixed, SOURCE_WIFI)
                except Exception:
                    pass  # WiFi may drop; never crash for entropy

        # 6. BLE scan entropy (every 500 samples — scans are expensive)
        if ENABLE_BLE_ENTROPY and ble_active:
            if sample_count % 500 == 0:
                try:
                    ble_entropy = _ble_harvest(ble)
                    if ble_entropy:
                        for val in ble_entropy:
                            pool.mix_u32(val, SOURCE_BLE)
                            conditioner.absorb_u32(val)
                except Exception:
                    pass  # BLE may fail; never crash for entropy

        sample_count += 1
        entropy_samples_since_send += 1

        # ================================================================
        #                         PROCESS BATCH
        # ================================================================

        if sample_count % SAMPLE_BATCH_SIZE == 0:
            batch_count += 1

            # Extract raw entropy from pool
            raw_buffer = pool.extract(64)

            # Von Neumann debiasing
            debiased_idx = [0]
            for byte in raw_buffer:
                debiaser.process_byte(byte, debiased_buffer, debiased_idx)

            # Feed debiased data to BLAKE3 conditioner
            if debiased_idx[0] > 0:
                conditioner.absorb(debiased_buffer[:debiased_idx[0]])

            # Health test the raw data
            for byte in raw_buffer:
                health.process_byte(byte)

            # Squeeze conditioned output
            conditioned = conditioner.squeeze()

            # Print dashboard periodically
            if SHOW_REPORTS and batch_count % REPORT_INTERVAL == 1:
                # Update RGB LED to show health status (only on dashboard tick)
                if ENABLE_RGB and np is not None and not led_is_idle:
                    status_color = health_led_color(health.last_status, RGB_BRIGHTNESS)
                    set_led(np, status_color)

                print_dashboard(
                    batch_count, pool, health, debiaser,
                    raw_buffer, conditioned, wifi_connected,
                )

            # Output TRNG data
            if health.last_status != HEALTH_FAIL:
                if OUTPUT_BASE64:
                    b64 = base64_encode(conditioned)
                    color = health_color(health.last_status)
                    print("{}TRNG:{}{}".format(color, b64, RESET))
            else:
                print("\x1b[91mTRNG:HEALTH_FAIL:RCT={}:APT={}:CHI={}{}".format(
                    health.rct_failures, health.apt_failures,
                    health.chi_failures, RESET))

            # ============================================================
            #               ENTROPY BURST SEND (to entropy receiver)
            # ============================================================
            # IMPORTANT: This remains separate from STRUM.
            # STRUM -> TARGET_IP:TARGET_PORT
            # ENTROPY -> ENTROPY_RECEIVER_IP:ENTROPY_RECEIVER_PORT

            if ENTROPY_BURST_MODE and ENABLE_WIFI_SEND and wifi_connected and udp_sock is not None:
                time_since_send = time.ticks_diff(time.ticks_ms(), last_entropy_send) // 1000
                should_send = (entropy_samples_since_send >= ENTROPY_BURST_MIN_SAMPLES
                               or time_since_send >= ENTROPY_BURST_MAX_INTERVAL_SEC)

                if should_send and health.last_status != HEALTH_FAIL:
                    sent = udp_send(udp_sock, conditioned, ENTROPY_RECEIVER_IP, ENTROPY_RECEIVER_PORT)
                    print("{}[ENTROPY]{} 32B -> {}.{}.{}.{}:{} | {} | {}".format(
                        GREEN, RESET,
                        ENTROPY_RECEIVER_IP[0], ENTROPY_RECEIVER_IP[1],
                        ENTROPY_RECEIVER_IP[2], ENTROPY_RECEIVER_IP[3],
                        ENTROPY_RECEIVER_PORT,
                        health_name(health.last_status),
                        "OK" if sent else "FAIL"))

                    entropy_samples_since_send = 0
                    last_entropy_send = time.ticks_ms()

            # Periodic GC to keep heap healthy
            if batch_count % 20 == 0:
                gc.collect()

        # Poll delay
        time.sleep_ms(POLL_DELAY_MS)


# ============================================================================
#                              ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    main()
