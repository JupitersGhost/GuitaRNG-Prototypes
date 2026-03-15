# ============================================================================
#  boot.py - GuitaRNG V1.0 (MicroPython)
#  Jupiter Labs / CHIRASU Network
#
#  This runs BEFORE main.py on every boot/reset.
#  Keep it minimal — heavy init goes in main.py.
# ============================================================================

import gc
import esp

esp.osdebug(None)


gc.enable()
gc.collect()


print("\x1b[96m[boot]\x1b[0m GuitaRNG v1.0 — booting...")

