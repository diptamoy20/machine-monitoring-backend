"""
Daily service restart scheduler.

Runs forever. Every day at 8:00 AM local time, restarts both
machine-monitoring.service and main-live.service via systemctl.
"""

import subprocess
import time
import logging
from datetime import datetime, timedelta

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler("/var/www/stage.beas.in/public_html/machine-monitoring-opencv/daily_restart.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)

RESTART_HOUR = 8
RESTART_MINUTE = 0
SERVICES = ["machine-monitoring.service", "main-live.service"]


def next_run_time():
    now = datetime.now()
    target = now.replace(hour=RESTART_HOUR, minute=RESTART_MINUTE, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target


def restart_services():
    for service in SERVICES:
        logger.info(f"Restarting {service}...")
        try:
            result = subprocess.run(
                ["systemctl", "restart", service],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode == 0:
                logger.info(f"{service} restarted successfully.")
            else:
                logger.error(f"{service} restart failed: {result.stderr}")
        except Exception as e:
            logger.error(f"{service} restart error: {e}")

        time.sleep(3)
        status = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True, text=True
        ).stdout.strip()
        logger.info(f"{service} status after restart: {status}")


def main():
    logger.info("Daily restart scheduler started.")
    while True:
        target = next_run_time()
        wait_seconds = (target - datetime.now()).total_seconds()
        logger.info(f"Next restart scheduled for {target.isoformat()} ({wait_seconds/3600:.1f} hours from now)")

        while wait_seconds > 0:
            sleep_chunk = min(wait_seconds, 300)
            time.sleep(sleep_chunk)
            wait_seconds -= sleep_chunk

        logger.info("=== Daily restart triggered ===")
        restart_services()


if __name__ == "__main__":
    main()
