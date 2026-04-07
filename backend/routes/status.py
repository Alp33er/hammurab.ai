"""
M.I.N.I. System Status API — Gerçek zamanlı sistem durumu
"""

import subprocess
import json
import os
import re
from datetime import datetime
from fastapi import APIRouter

router = APIRouter()


def run_cmd(cmd: str, timeout: int = 10) -> str:
    """Komutu çalıştır, çıktıyı döndür."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.stdout.strip()
    except Exception:
        return ""


@router.get("/status")
async def get_system_status():
    """M.I.N.I. tam sistem durumu."""

    # Uptime
    uptime_raw = run_cmd("uptime")
    uptime_match = re.search(r"up\s+(.+?),\s+\d+\s+user", uptime_raw)
    uptime = uptime_match.group(1).strip() if uptime_match else uptime_raw

    # CPU & Memory
    cpu_usage = run_cmd(
        "ps -A -o %cpu | awk '{s+=$1} END {printf \"%.1f\", s}'"
    )
    mem_raw = run_cmd("vm_stat")
    mem_info = {}
    if mem_raw:
        pages = {}
        for line in mem_raw.split("\n"):
            if ":" in line:
                key, val = line.split(":", 1)
                val = val.strip().rstrip(".")
                try:
                    pages[key.strip()] = int(val)
                except ValueError:
                    pass
        page_size = 16384  # Apple Silicon
        total_mem_gb = 24  # M4 Pro
        free_pages = pages.get("Pages free", 0)
        inactive = pages.get("Pages inactive", 0)
        active = pages.get("Pages active", 0)
        wired = pages.get("Pages wired down", 0)
        compressed = pages.get("Pages occupied by compressor", 0)
        used_gb = (active + wired + compressed) * page_size / (1024**3)
        mem_info = {
            "total_gb": total_mem_gb,
            "used_gb": round(used_gb, 1),
            "percent": round(used_gb / total_mem_gb * 100, 1),
        }

    # Disk — macOS APFS: /System/Volumes/Data has actual user data
    disk_raw = run_cmd("df -h /System/Volumes/Data | tail -1")
    if not disk_raw:
        disk_raw = run_cmd("df -h / | tail -1")
    disk_parts = disk_raw.split()
    disk_info = {}
    if len(disk_parts) >= 5:
        disk_info = {
            "total": disk_parts[1],
            "used": disk_parts[2],
            "free": disk_parts[3],
            "percent": disk_parts[4],
        }

    # LaunchAgents
    agents_raw = run_cmd(
        "launchctl list 2>/dev/null | grep berrygames | awk '{print $1, $2, $3}'"
    )
    agents = []
    for line in agents_raw.split("\n"):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) >= 3:
            pid = parts[0]
            status = parts[1]
            name = parts[2]
            running = pid != "-" and pid != "0"
            agents.append(
                {
                    "name": name.replace("com.berrygames.", ""),
                    "full_name": name,
                    "running": running,
                    "pid": int(pid) if pid not in ("-", "0") else None,
                    "exit_code": int(status) if status != "-" else None,
                }
            )

    # tmux sessions
    tmux_raw = run_cmd("tmux ls -F '#{session_name}|#{session_created}' 2>/dev/null")
    sessions = []
    for line in tmux_raw.split("\n"):
        if not line.strip() or "|" not in line:
            continue
        name, created = line.split("|", 1)
        # Son log satırı
        log_dir = "/Users/mini/_BERRY_GAMES/_GAMES/_SCRIPTS/logs/tmux"
        last_log = run_cmd(
            f"ls -t {log_dir}/{name}_*.log 2>/dev/null | head -1"
        )
        last_line = ""
        if last_log:
            last_line = run_cmd(f"tail -1 '{last_log}' 2>/dev/null")[:200]
        sessions.append(
            {"name": name, "last_log_line": last_line}
        )

    # Aktif processler
    processes = {}
    unity_pid = run_cmd("pgrep -f 'Unity.*-batchmode' 2>/dev/null")
    xcode_pid = run_cmd("pgrep -f 'xcodebuild' 2>/dev/null")
    claude_pid = run_cmd("pgrep -f 'claude' 2>/dev/null | head -3")
    uvicorn_pid = run_cmd("pgrep -f 'uvicorn' 2>/dev/null | head -1")
    cloudflared_pid = run_cmd("pgrep -f 'cloudflared' 2>/dev/null | head -1")

    processes["unity"] = bool(unity_pid)
    processes["xcodebuild"] = bool(xcode_pid)
    processes["claude"] = bool(claude_pid)
    processes["uvicorn"] = bool(uvicorn_pid)
    processes["cloudflared"] = bool(cloudflared_pid)

    # Build queue
    queue_file = "/Users/mini/_BERRY_GAMES/_GAMES/_SCRIPTS/build_queue.json"
    build_queue = []
    if os.path.exists(queue_file):
        try:
            with open(queue_file) as f:
                build_queue = json.load(f)
        except Exception:
            pass

    # Son pipeline çalışmaları (log dosyalarının son değiştirilme zamanı)
    pipelines = []
    log_files = {
        "web_pipeline": "/Users/mini/_BERRY_GAMES/_GAMES/_SCRIPTS/logs/web_pipeline.log",
        "hukuk_tunnel": "/Users/mini/_BERRY_GAMES/_GAMES/_SCRIPTS/logs/hukuk_tunnel.log",
        "morning_briefing": "/Users/mini/_BERRY_GAMES/_GAMES/_SCRIPTS/logs/morning_briefing.log",
        "weekly_report": "/Users/mini/_BERRY_GAMES/_GAMES/_SCRIPTS/logs/weekly_report.log",
        "crashlytics": "/Users/mini/_BERRY_GAMES/_GAMES/_SCRIPTS/logs/crashlytics.log",
        "store_monitor": "/Users/mini/_BERRY_GAMES/_GAMES/_SCRIPTS/logs/store_monitor.log",
        "borsa_daily": "/Users/mini/_BERRY_GAMES/_GAMES/_SCRIPTS/logs/borsa_daily_update.log",
        "borsa_paper_trade": "/Users/mini/_BERRY_GAMES/_GAMES/_SCRIPTS/logs/borsa_paper_trade.log",
    }
    for name, path in log_files.items():
        if os.path.exists(path):
            mtime = os.path.getmtime(path)
            last_line = run_cmd(f"tail -1 '{path}' 2>/dev/null")[:200]
            pipelines.append(
                {
                    "name": name,
                    "last_run": datetime.fromtimestamp(mtime).isoformat(),
                    "last_line": last_line,
                }
            )
        else:
            pipelines.append({"name": name, "last_run": None, "last_line": "Log yok"})

    # Network (Tailscale)
    tailscale_ip = run_cmd("tailscale ip -4 2>/dev/null")

    return {
        "timestamp": datetime.now().isoformat(),
        "hostname": run_cmd("hostname"),
        "uptime": uptime,
        "cpu_percent": float(cpu_usage) if cpu_usage else 0,
        "memory": mem_info,
        "disk": disk_info,
        "launch_agents": agents,
        "tmux_sessions": sessions,
        "processes": processes,
        "build_queue": build_queue,
        "pipelines": pipelines,
        "tailscale_ip": tailscale_ip,
    }
