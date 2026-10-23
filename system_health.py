import os
import sys
import gc
import time
import shutil
import logging
from logging.handlers import RotatingFileHandler
import threading
import subprocess
import faulthandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(BASE_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "robot.log")
FAULT_FILE = os.path.join(LOG_DIR, "segfault.log")

# 1. Configurare Logging cu Rotație (max 2MB x 3 arhive pentru a proteja cardul SD)
logger = logging.getLogger("RobotCompanion")
logger.setLevel(logging.DEBUG)
if not logger.handlers:
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] (%(threadName)s) %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)

# 2. Activare faulthandler pentru capturarea crash-urilor C / PortAudio / X11
_fault_fp = None
try:
    _fault_fp = open(FAULT_FILE, "a", encoding="utf-8")
    faulthandler.enable(file=_fault_fp, all_threads=True)
except Exception as e:
    logger.warning(f"Nu am putut activa faulthandler pe fișier: {e}")


def _global_excepthook(exc_type, exc_value, exc_tb):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_tb)
        return
    logger.critical("Excepție necapturată în firul principal:", exc_info=(exc_type, exc_value, exc_tb))


def _thread_excepthook(args):
    if issubclass(args.exc_type, SystemExit):
        return
    logger.error(
        f"Excepție necapturată în thread-ul '{args.thread.name if args.thread else 'necunoscut'}':",
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
    )


sys.excepthook = _global_excepthook
threading.excepthook = _thread_excepthook


def citeste_stare_hardware():
    """
    Citește temperatura CPU, memoria RAM liberă, starea de undervoltage/throttling
    (vcgencmd get_throttled) și conectivitatea pe Raspberry Pi.
    """
    stare = {
        "temp_c": 0.0,
        "ram_total_mb": 0,
        "ram_avail_mb": 0,
        "ram_procent": 0,
        "throttled_hex": "0x0",
        "undervoltage_acum": False,
        "undervoltage_trecut": False,
        "throttled_acum": False,
        "avertismente": []
    }

    # Temperatură CPU Linux
    try:
        cale_temp = "/sys/class/thermal/thermal_zone0/temp"
        if os.path.exists(cale_temp):
            with open(cale_temp, "r") as f:
                stare["temp_c"] = round(int(f.read().strip()) / 1000.0, 1)
    except Exception:
        pass

    # Memorie RAM (/proc/meminfo)
    try:
        if os.path.exists("/proc/meminfo"):
            mem = {}
            with open("/proc/meminfo", "r") as f:
                for line in f:
                    parts = line.split(":")
                    if len(parts) == 2:
                        k = parts[0].strip()
                        v = int(parts[1].strip().split()[0])
                        mem[k] = v
            tot = mem.get("MemTotal", 0) // 1024
            avail = mem.get("MemAvailable", mem.get("MemFree", 0)) // 1024
            stare["ram_total_mb"] = tot
            stare["ram_avail_mb"] = avail
            if tot > 0:
                stare["ram_procent"] = int(((tot - avail) / tot) * 100)
    except Exception:
        pass

    # Undervoltage & Throttling prin vcgencmd
    if os.name != "nt" and shutil.which("vcgencmd"):
        try:
            out = subprocess.check_output(["vcgencmd", "get_throttled"], timeout=2, text=True).strip()
            # Format: throttled=0x50000
            if "=" in out:
                hex_str = out.split("=")[1].strip()
                stare["throttled_hex"] = hex_str
                val = int(hex_str, 16)
                stare["undervoltage_acum"] = bool(val & 0x1)
                stare["throttled_acum"] = bool(val & 0x4)
                stare["undervoltage_trecut"] = bool(val & 0x10000)
        except Exception:
            pass

    if stare["temp_c"] >= 78.0:
        stare["avertismente"].append(f"Temperatură CPU ridicată: {stare['temp_c']}°C")
    if 0 < stare["ram_avail_mb"] < 130:
        stare["avertismente"].append(f"Memorie RAM scăzută: {stare['ram_avail_mb']} MB liberi")
        gc.collect()
    if stare["undervoltage_acum"]:
        stare["avertismente"].append("UNDERVOLTAGE ACTIV (alimentare sub 4.63V)!")
    elif stare["undervoltage_trecut"]:
        stare["avertismente"].append("S-a detectat undervoltage în sesiunea curentă.")

    return stare


class MonitorSanatatePi:
    """Thread de fundal care monitorizează periodic RAM-ul, temperatura și alimentarea."""
    def __init__(self, interval_sec=30):
        self.interval_sec = interval_sec
        self._stop_evt = threading.Event()
        self.ultima_stare = citeste_stare_hardware()
        self._thread = threading.Thread(target=self._loop, name="HealthMonitor", daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop_evt.set()

    def _loop(self):
        while not self._stop_evt.is_set():
            try:
                stare = citeste_stare_hardware()
                self.ultima_stare = stare
                for av in stare["avertismente"]:
                    logger.warning(f"[HEALTH MONITOR]: {av}")
            except Exception as e:
                logger.error(f"Eroare în HealthMonitor: {e}")
            self._stop_evt.wait(self.interval_sec)