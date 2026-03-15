# ============================================================================
#  Runtime control plane for GuitaRNG (MicroPython)
#
#  Same protocol over both UDP and USB serial:
#    GET
#    HELP
#    SET noise=12 threshold=55 debounce=120 baseline_shift=6
#    SET ip=192.etc.etc port=xxxx udp=1
#
#  Replies are plain text:
#    OK noise=.. threshold=.. debounce=.. baseline_shift=.. ip=a.b.c.d port=.. udp=0|1
#    ERR reason=...
# ============================================================================

# UDP port the ESP32-S3 listens on for config commands.
CTRL_PORT = 5010


class RuntimeSettings:
    """Live-tunable runtime settings initialized from config.py defaults."""

    __slots__ = (
        'noise_floor', 'hit_threshold', 'debounce_ms', 'baseline_shift',
        'udp_target_ip', 'udp_target_port', 'enable_udp_strum',
    )

    def __init__(self, noise_floor, hit_threshold, debounce_ms, baseline_shift,
                 udp_target_ip, udp_target_port, enable_udp_strum):
        self.noise_floor = noise_floor
        self.hit_threshold = hit_threshold
        self.debounce_ms = debounce_ms
        self.baseline_shift = baseline_shift
        self.udp_target_ip = list(udp_target_ip)   # mutable copy
        self.udp_target_port = udp_target_port
        self.enable_udp_strum = enable_udp_strum


def format_status(st):
    """Format current settings as an OK response string."""
    return "OK noise={} threshold={} debounce={} baseline_shift={} ip={}.{}.{}.{} port={} udp={}".format(
        st.noise_floor,
        st.hit_threshold,
        st.debounce_ms,
        st.baseline_shift,
        st.udp_target_ip[0], st.udp_target_ip[1],
        st.udp_target_ip[2], st.udp_target_ip[3],
        st.udp_target_port,
        1 if st.enable_udp_strum else 0,
    )


def _err(reason):
    return "ERR reason={}".format(reason)


def _parse_ip(s):
    parts = s.split('.')
    if len(parts) != 4:
        return None
    out = []
    for p in parts:
        try:
            v = int(p)
            if v < 0 or v > 255:
                return None
            out.append(v)
        except ValueError:
            return None
    return out


def handle_line(line, st):
    """
    Parse a control command and mutate `st` (RuntimeSettings).

    Returns:
        str or None — reply text (None = no reply needed)
    """
    line = line.strip()
    if not line:
        return None

    upper = line.upper()

    if upper == "GET":
        return format_status(st)

    if upper == "HELP":
        return "OK cmds: GET | SET noise=.. threshold=.. debounce=.. baseline_shift=.. ip=a.b.c.d port=.. udp=0|1"

    if upper.startswith("SET "):
        rest = line[4:]
        for kv in rest.split():
            parts = kv.split('=', 1)
            if len(parts) != 2:
                return _err("bad_kv")
            k, v = parts

            if k in ("noise", "noise_floor"):
                try:
                    st.noise_floor = int(v)
                except ValueError:
                    return _err("bad_noise")

            elif k in ("threshold", "hit"):
                try:
                    st.hit_threshold = int(v)
                except ValueError:
                    return _err("bad_threshold")

            elif k == "debounce":
                try:
                    st.debounce_ms = int(v)
                except ValueError:
                    return _err("bad_debounce")

            elif k in ("baseline_shift", "base"):
                try:
                    st.baseline_shift = int(v)
                except ValueError:
                    return _err("bad_baseline_shift")

            elif k == "ip":
                ip = _parse_ip(v)
                if ip is None:
                    return _err("bad_ip")
                st.udp_target_ip = ip

            elif k == "port":
                try:
                    st.udp_target_port = int(v)
                except ValueError:
                    return _err("bad_port")

            elif k == "udp":
                st.enable_udp_strum = v in ("1", "true", "True", "on", "ON")

            else:
                return _err("bad_key")

        return format_status(st)

    return _err("unknown_cmd")

