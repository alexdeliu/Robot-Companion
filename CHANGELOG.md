# Changelog - Robot Companion

## [1.0.0] - 2026-10-24
### Added / Adăugat
- Adaptive Kiosk UI (`main.py`) with unified state machine (`RobotState`), `DND` mode, live wake-word telemetry bar, and Hardware Status overlay (`v1.0.0`).
- Multi-strategy Wake Word engine (`ears/wake_word.py`) with stateful `_StreamDSP16k` filter (100 Hz High-Pass + AGC + 16 kHz upsampler) and fuzzy matching.
- YouTube Music & SPI Video player (`brain/abilities/youtube_player.py`) with UNIX socket IPC (`/tmp/robot_mpv_ipc.sock`) and `ffmpeg` SPI Canvas video renderer.
- Interactive Wikipedia cards (`wikipedia_ro.py`), 5-day Open-Meteo forecast (`weather.py`), and voice timers (`timers.py`).
- Hardware health monitor (`system_health.py`) and complete diagnostic suite (`release_check.py`, `diag_youtube.py`, `ui_selftest.py`, `wake_eval.py`, `diag_mic.py`).