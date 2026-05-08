import subprocess
import re
import threading
import os
import platform

# --- CONFIGURATION ---
SUBNET = "192.168" 
RANGE_START = 1
RANGE_END = 100 

def get_startup_info():
    if platform.system() == "Windows":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        return startupinfo
    return None

def ping_thread_task(ip):
    try:
        param = '-n' if platform.system().lower() == 'windows' else '-c'
        timeout_flag = '-w' if platform.system().lower() == 'windows' else '-W'
        # 100ms timeout allows roughly 10s scan time for 100 IPs
        timeout_val = '100' if platform.system().lower() == 'windows' else '1'
        
        subprocess.call(
            ['ping', param, '1', timeout_flag, timeout_val, ip],
            startupinfo=get_startup_info(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.STDOUT
        )
    except Exception:
        pass

def ping_sweep():
    threads = []
    for i in range(RANGE_START, RANGE_END):
        ip = f"{SUBNET}.{i}"
        t = threading.Thread(target=ping_thread_task, args=(ip,))
        t.start()
        threads.append(t)
    
    for t in threads:
        t.join()

def get_active_devices():
    # Sweep
    ping_sweep()
    
    active_list = []
    try:
        if platform.system() == "Windows":
            output = subprocess.check_output("arp -a", startupinfo=get_startup_info(), shell=True).decode("latin-1")
        else:
            output = subprocess.check_output("arp -n", shell=True).decode("utf-8")
            
        lines = output.split('\n')
        
        for line in lines:
            line = line.strip()
            matcher = re.search(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+([0-9a-fA-F-]{17}|[0-9a-fA-F:]{17})', line)
            
            if matcher:
                ip = matcher.group(1)
                mac = matcher.group(2).replace("-", ":").upper()
                if ip.startswith(SUBNET):
                    active_list.append({'ip': ip, 'mac': mac})
                        
    except Exception as e:
        print(f"Scanner Error: {e}")
        return []

    return active_list