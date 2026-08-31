import subprocess
import socket
import time
import os
import logging

logger = logging.getLogger(__name__)

def is_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def ensure_chrome_running(port=9224, profile_dir="/tmp/pnr-chrome-profile"):
    """
    Ensures Google Chrome is running with the specified debugging port.
    If it's not running, launches a new isolated instance.
    """
    if is_port_in_use(port):
        logger.info(f"Chrome is already listening on port {port}")
        return True
    
    logger.info(f"Port {port} not in use. Attempting to launch Chrome...")
    mac_chrome_path = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
    if not os.path.exists(mac_chrome_path):
        logger.error(f"Chrome not found at {mac_chrome_path}")
        return False
        
    cmd = [
        mac_chrome_path,
        f"--remote-debugging-port={port}",
        f"--user-data-dir={profile_dir}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-sync",
        "--disable-gpu",
        "--disable-dev-shm-usage"
    ]
    
    subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Wait up to 5 seconds for port to open
    for _ in range(50):
        if is_port_in_use(port):
            time.sleep(1)  # Give Chrome a moment to fully initialize its CDP endpoints
            logger.info(f"Successfully launched Chrome on port {port}")
            return True
        time.sleep(0.1)
        
    logger.error(f"Failed to verify Chrome opened on port {port}")
    return False
