# ============================================================================
#            GuitaRNG - Entropy Subsystems (MicroPython)
#            Jupiter Labs
# ============================================================================
#
# Contains:
#   - Blake3Conditioner  (BLAKE3-inspired ARX cryptographic conditioning)
#   - EntropyPool        (256-byte avalanche mixing pool)
#   - NistHealthMonitor  (RCT, APT, Chi-Square, Runs, Monobit)
#   - VonNeumannDebiaser (pair-based debiasing with efficiency tracking)
#   - shannon_entropy / min_entropy / base64_encode

import struct
import os
import time

from config import (
    POOL_SIZE, RCT_CUTOFF, APT_WINDOW, APT_MIN_ONES, APT_MAX_ONES,
    APT_WARN_MIN, APT_WARN_MAX,
)


# ============================================================================
#                    BLAKE3-INSPIRED CRYPTOGRAPHIC CONDITIONER
# ============================================================================

# BLAKE3 initialization vector (same as SHA-256)
BLAKE3_IV = (
    0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A,
    0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
)

# Message schedule permutation (BLAKE3 spec)
MSG_PERMUTATION = (2, 6, 3, 10, 7, 0, 4, 13, 1, 11, 12, 5, 9, 14, 15, 8)

_MASK32 = 0xFFFFFFFF


def _ror32(v, n):
    """32-bit rotate right."""
    v &= _MASK32
    return ((v >> n) | (v << (32 - n))) & _MASK32


def _rol32(v, n):
    """32-bit rotate left."""
    v &= _MASK32
    return ((v << n) | (v >> (32 - n))) & _MASK32


class Blake3Conditioner:
    """BLAKE3-inspired ARX construction for cryptographic entropy conditioning."""

    def __init__(self):
        self.state = list(BLAKE3_IV)
        self.buffer = bytearray(64)
        self.buf_len = 0
        self.blocks_processed = 0

    # -- Quarter-round G -------------------------------------------------------
    @staticmethod
    def _g(s, a, b, c, d, mx, my):
        s[a] = (s[a] + s[b] + mx) & _MASK32
        s[d] = _ror32(s[d] ^ s[a], 16)
        s[c] = (s[c] + s[d]) & _MASK32
        s[b] = _ror32(s[b] ^ s[c], 12)
        s[a] = (s[a] + s[b] + my) & _MASK32
        s[d] = _ror32(s[d] ^ s[a], 8)
        s[c] = (s[c] + s[d]) & _MASK32
        s[b] = _ror32(s[b] ^ s[c], 7)

    # -- One round of mixing ---------------------------------------------------
    @classmethod
    def _round(cls, s, m):
        # Column mixing
        cls._g(s, 0, 4, 8,  12, m[0],  m[1])
        cls._g(s, 1, 5, 9,  13, m[2],  m[3])
        cls._g(s, 2, 6, 10, 14, m[4],  m[5])
        cls._g(s, 3, 7, 11, 15, m[6],  m[7])
        # Diagonal mixing
        cls._g(s, 0, 5, 10, 15, m[8],  m[9])
        cls._g(s, 1, 6, 11, 12, m[10], m[11])
        cls._g(s, 2, 7, 8,  13, m[12], m[13])
        cls._g(s, 3, 4, 9,  14, m[14], m[15])

    # -- Permute message schedule ----------------------------------------------
    @staticmethod
    def _permute(m):
        return [m[MSG_PERMUTATION[i]] for i in range(16)]

    # -- Compress a 64-byte block ----------------------------------------------
    def _compress(self, block, flags):
        # Parse 16 little-endian u32 words from block
        m = list(struct.unpack('<16I', block))

        v = list(self.state) + list(BLAKE3_IV[:4])
        v.append(self.blocks_processed & _MASK32)
        v.append((self.blocks_processed >> 32) & _MASK32)
        v.append(64)    # block length
        v.append(flags)

        for _ in range(7):
            self._round(v, m)
            m = self._permute(m)

        for i in range(8):
            self.state[i] = (self.state[i] ^ v[i] ^ v[i + 8]) & _MASK32

        self.blocks_processed += 1

    # -- Public: absorb arbitrary data -----------------------------------------
    def absorb(self, data):
        for byte in data:
            self.buffer[self.buf_len] = byte
            self.buf_len += 1
            if self.buf_len == 64:
                self._compress(bytes(self.buffer), 0)
                self.buf_len = 0

    def absorb_u32(self, value):
        self.absorb(struct.pack('<I', value & _MASK32))

    def absorb_u16(self, value):
        self.absorb(struct.pack('<H', value & 0xFFFF))

    # -- Public: squeeze 32 bytes of conditioned entropy -----------------------
    def squeeze(self):
        if self.buf_len > 0 or self.blocks_processed == 0:
            for i in range(self.buf_len, 64):
                self.buffer[i] = 0
            if self.buf_len < 64:
                self.buffer[self.buf_len] = 0x80
            self._compress(bytes(self.buffer), 0x0B)
            self.buf_len = 0

        out = bytearray(32)
        for i in range(8):
            struct.pack_into('<I', out, i * 4, self.state[i])

        # Re-key for forward secrecy
        for i in range(8):
            mul = (self.state[i] * 0x85EBCA6B) & _MASK32
            self.state[i] = _rol32((mul + BLAKE3_IV[i]) & _MASK32, 13)

        return out

    def total_bytes(self):
        return self.blocks_processed * 64 + self.buf_len


# ============================================================================
#                         ENTROPY POOL (256 bytes with avalanche mixing)
# ============================================================================

SOURCE_PIEZO   = 0
SOURCE_HW_RNG  = 1
SOURCE_JITTER  = 2
SOURCE_TICKS   = 3
SOURCE_WIFI    = 4
SOURCE_BLE     = 5


class EntropyPool:
    """256-byte entropy pool with avalanche mixing across multiple offsets."""

    def __init__(self):
        self.pool = bytearray(POOL_SIZE)
        self.write_idx = 0
        self.total_mixed = 0
        self.adc_bytes = 0
        self.rng_bytes = 0
        self.jitter_bytes = 0
        self.tick_bytes = 0
        self.wifi_bytes = 0
        self.ble_bytes = 0

    def mix_byte(self, byte, source):
        idx = self.write_idx
        P = self.pool
        sz = POOL_SIZE

        P[idx] ^= byte

        n1  = (idx + 1)   % sz
        n7  = (idx + 7)   % sz
        n31 = (idx + 31)  % sz
        n127 = (idx + 127) % sz
        p1  = (idx + sz - 1) % sz

        P[n1]  ^= ((byte << 1) | (byte >> 7)) & 0xFF
        P[n7]  ^= ((byte << 3) | (byte >> 5)) & 0xFF
        P[n31] ^= ((byte >> 2) | (byte << 6)) & 0xFF
        P[n127] ^= ((byte >> 5) | (byte << 3)) & 0xFF
        P[p1]  ^= ((byte << 7) | (byte >> 1)) & 0xFF

        mixed = ((P[idx] + P[n1]) & 0xFF) * 0x9E & 0xFF
        mixed = ((mixed << 3) | (mixed >> 5)) & 0xFF
        P[n31] ^= mixed

        self.write_idx = n1
        self.total_mixed += 1

        if source == SOURCE_PIEZO:
            self.adc_bytes += 1
        elif source == SOURCE_HW_RNG:
            self.rng_bytes += 1
        elif source == SOURCE_JITTER:
            self.jitter_bytes += 1
        elif source == SOURCE_TICKS:
            self.tick_bytes += 1
        elif source == SOURCE_WIFI:
            self.wifi_bytes += 1
        elif source == SOURCE_BLE:
            self.ble_bytes += 1

    def mix_u16(self, value, source):
        self.mix_byte(value & 0xFF, source)
        self.mix_byte((value >> 8) & 0xFF, source)

    def mix_u32(self, value, source):
        self.mix_byte(value & 0xFF, source)
        self.mix_byte((value >> 8) & 0xFF, source)
        self.mix_byte((value >> 16) & 0xFF, source)
        self.mix_byte((value >> 24) & 0xFF, source)

    def extract(self, length):
        out = bytearray(length)
        for i in range(length):
            idx = (self.write_idx + i * 7) % POOL_SIZE
            out[i] = self.pool[idx]
        return out


# ============================================================================
#                    NIST SP 800-90B HEALTH TESTS
# ============================================================================

HEALTH_EXCELLENT = 0
HEALTH_GOOD      = 1
HEALTH_WARNING   = 2
HEALTH_FAIL      = 3

_STATUS_SYMBOLS = ("[*]", "[+]", "[!]", "[X]")
_STATUS_NAMES   = ("EXCELLENT", "GOOD     ", "WARNING  ", "FAIL     ")
_STATUS_COLORS  = ("\x1b[92m", "\x1b[32m", "\x1b[93m", "\x1b[91m")


def health_symbol(status):
    return _STATUS_SYMBOLS[status]

def health_name(status):
    return _STATUS_NAMES[status]

def health_color(status):
    return _STATUS_COLORS[status]


class NistHealthMonitor:
    """Full NIST SP 800-90B suite: RCT, APT, Chi-Square, Runs, Monobit."""

    def __init__(self):
        # RCT
        self.rct_last_byte = None
        self.rct_count = 1
        self.rct_max_seen = 0

        # APT (sliding window stored as bytearray of bits packed in bytes)
        self.apt_window = bytearray(APT_WINDOW // 8)
        self.apt_idx = 0
        self.apt_ones = 0
        self.apt_ready = False

        # Chi-Square
        self.byte_freq = [0] * 256
        self.chi_total = 0
        self.chi_squared = 0.0

        # Runs test
        self.last_bit = None
        self.runs_count = 0
        self.total_bits = 0

        # Monobit
        self.monobit_ones = 0
        self.monobit_total = 0

        # Tracking
        self.total_tests = 0
        self.rct_failures = 0
        self.apt_failures = 0
        self.chi_failures = 0
        self.warnings = 0
        self.last_status = HEALTH_GOOD

    def process_byte(self, byte):
        self.total_tests += 1
        worst = HEALTH_EXCELLENT

        # ---- RCT Test ----
        if self.rct_last_byte is not None:
            if byte == self.rct_last_byte:
                self.rct_count += 1
                if self.rct_count > self.rct_max_seen:
                    self.rct_max_seen = self.rct_count
                if self.rct_count > RCT_CUTOFF:
                    self.rct_failures += 1
                    worst = HEALTH_FAIL
                elif self.rct_count > (RCT_CUTOFF * 70 // 100):
                    self.warnings += 1
                    if worst != HEALTH_FAIL:
                        worst = HEALTH_WARNING
            else:
                self.rct_count = 1
        self.rct_last_byte = byte

        # ---- APT Test ----
        for i in range(8):
            bit = (byte >> i) & 1
            byte_idx = self.apt_idx // 8
            bit_idx = self.apt_idx % 8

            if self.apt_ready:
                old_bit = (self.apt_window[byte_idx] >> bit_idx) & 1
                if old_bit == 1:
                    self.apt_ones = max(0, self.apt_ones - 1)

            if bit == 1:
                self.apt_window[byte_idx] |= (1 << bit_idx)
                self.apt_ones += 1
            else:
                self.apt_window[byte_idx] &= ~(1 << bit_idx) & 0xFF

            self.apt_idx = (self.apt_idx + 1) % APT_WINDOW
            if self.apt_idx == 0:
                self.apt_ready = True

            if self.last_bit is not None and bit != self.last_bit:
                self.runs_count += 1
            self.last_bit = bit
            self.total_bits += 1

            if bit == 1:
                self.monobit_ones += 1
            self.monobit_total += 1

        if self.apt_ready:
            if self.apt_ones < APT_MIN_ONES or self.apt_ones > APT_MAX_ONES:
                self.apt_failures += 1
                worst = HEALTH_FAIL
            elif self.apt_ones < APT_WARN_MIN or self.apt_ones > APT_WARN_MAX:
                if worst == HEALTH_EXCELLENT:
                    worst = HEALTH_WARNING

        # ---- Chi-Square Test ----
        self.byte_freq[byte] += 1
        self.chi_total += 1

        if self.chi_total > 0 and self.chi_total % 256 == 0:
            self.chi_squared = self._compute_chi_square()
            if self.chi_squared > 350.0 or self.chi_squared < 170.0:
                self.chi_failures += 1
                worst = HEALTH_FAIL
            elif self.chi_squared > 310.0 or self.chi_squared < 198.0:
                if worst == HEALTH_EXCELLENT:
                    worst = HEALTH_GOOD

        if worst == HEALTH_EXCELLENT and self.total_tests < 64:
            worst = HEALTH_GOOD

        self.last_status = worst
        return worst

    def _compute_chi_square(self):
        if self.chi_total == 0:
            return 256.0
        expected = self.chi_total / 256.0
        chi_sq = 0.0
        for count in self.byte_freq:
            if count > 0:
                diff = count - expected
                chi_sq += (diff * diff) / expected
        return chi_sq

    def bias_percentage(self):
        if not self.apt_ready:
            return 50.0
        return (self.apt_ones / APT_WINDOW) * 100.0

    def runs_per_bit(self):
        if self.total_bits < 2:
            return 0.5
        return self.runs_count / self.total_bits

    def monobit_proportion(self):
        if self.monobit_total == 0:
            return 50.0
        return (self.monobit_ones / self.monobit_total) * 100.0


# ============================================================================
#                         VON NEUMANN DEBIASER
# ============================================================================

class VonNeumannDebiaser:
    """Classic pair-based debiasing with efficiency tracking."""

    def __init__(self):
        self.pending_bit = None
        self.output_bits = 0
        self.output_byte = 0
        self.bits_in = 0
        self.bits_out = 0

    def process_byte(self, byte, output, out_idx_ref):
        """Process one byte. out_idx_ref is a list [idx] for mutability."""
        out_idx = out_idx_ref[0]
        for i in range(8):
            bit = (byte >> i) & 1
            self.bits_in += 1

            if self.pending_bit is None:
                self.pending_bit = bit
            else:
                prev = self.pending_bit
                self.pending_bit = None
                if prev != bit:
                    self.output_byte |= (prev << self.output_bits)
                    self.output_bits += 1
                    self.bits_out += 1

                    if self.output_bits == 8:
                        if out_idx < len(output):
                            output[out_idx] = self.output_byte
                            out_idx += 1
                        self.output_byte = 0
                        self.output_bits = 0

        out_idx_ref[0] = out_idx

    def efficiency(self):
        if self.bits_in == 0:
            return 0.0
        return (self.bits_out / self.bits_in) * 100.0


# ============================================================================
#                         ENTROPY CALCULATIONS
# ============================================================================

def _log2_approx(x):
    """Integer-friendly log2 approximation (no math module needed)."""
    if x <= 0.0:
        return -20.0
    LN_2 = 0.693147
    exp = 0
    y = x
    while y >= 2.0:
        y /= 2.0
        exp += 1
    while y < 0.5:
        y *= 2.0
        exp -= 1
    z = (y - 1.0) / (y + 1.0)
    z2 = z * z
    ln_y = 2.0 * z * (1.0 + z2 / 3.0 + z2 * z2 / 5.0 + z2 * z2 * z2 / 7.0)
    return (ln_y / LN_2) + exp


def shannon_entropy(data):
    """Shannon entropy in bits/byte."""
    if not data:
        return 0.0
    freq = [0] * 256
    for b in data:
        freq[b] += 1
    length = len(data)
    entropy = 0.0
    for count in freq:
        if count > 0:
            p = count / length
            entropy -= p * _log2_approx(p)
    return entropy


def min_entropy(data):
    """Min-entropy in bits/byte."""
    if not data:
        return 0.0
    freq = [0] * 256
    max_freq = 0
    for b in data:
        freq[b] += 1
        if freq[b] > max_freq:
            max_freq = freq[b]
    return -_log2_approx(max_freq / len(data))


# ============================================================================
#                         TIMING JITTER COLLECTOR
# ============================================================================

def collect_timing_jitter():
    """Collect entropy from timing jitter using random work loops."""
    rng_bytes = os.urandom(4)
    seed = struct.unpack('<I', rng_bytes)[0]

    start = time.ticks_us()

    iterations = (seed & 0x3F) + 16
    dummy = seed
    for _ in range(iterations):
        dummy = ((dummy * 1103515245) + 12345) & _MASK32
        dummy ^= (dummy >> 16)
        dummy = _rol32(dummy, 5)

    elapsed = time.ticks_diff(time.ticks_us(), start) & _MASK32
    return (elapsed ^ dummy ^ _rol32(elapsed, 16)) & _MASK32


# ============================================================================
#                              BASE64 ENCODING
# ============================================================================

_B64 = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def base64_encode(data):
    """Encode bytes to base64 string (no padding dependency)."""
    out = []
    i = 0
    while i + 3 <= len(data):
        b0, b1, b2 = data[i], data[i + 1], data[i + 2]
        out.append(_B64[(b0 >> 2)])
        out.append(_B64[((b0 & 0x03) << 4) | (b1 >> 4)])
        out.append(_B64[((b1 & 0x0F) << 2) | (b2 >> 6)])
        out.append(_B64[(b2 & 0x3F)])
        i += 3

    r = len(data) - i
    if r == 1:
        out.append(_B64[(data[i] >> 2)])
        out.append(_B64[((data[i] & 0x03) << 4)])
        out.append(ord('='))
        out.append(ord('='))
    elif r == 2:
        out.append(_B64[(data[i] >> 2)])
        out.append(_B64[((data[i] & 0x03) << 4) | (data[i + 1] >> 4)])
        out.append(_B64[((data[i + 1] & 0x0F) << 2)])
        out.append(ord('='))

    return bytes(out).decode('ascii')
