import requests
import threading
from config import load_complete_config_state, SAMMI_URL, SAMMI_PASS

def send_to_sammi(payload):
    """
    Sends a JSON payload to the SAMMI webhook if enabled.
    """
    if not isinstance(payload, dict): return
    
    config_state = load_complete_config_state()
    sammi_enabled = config_state.get("sammi", {}).get("sammi_enabled", True)
    if not sammi_enabled:
        return 
        
    headers = {"Content-Type": "application/json"}
    if SAMMI_PASS: headers["Authorization"] = SAMMI_PASS
    
    def _send():
        try:
            resp = requests.post(SAMMI_URL, json=payload, headers=headers, timeout=2)
            if resp.status_code != 200:
                print(f"[SAMMI] Failed: {resp.status_code} {resp.text}")
            else:
                print(f"[SAMMI] Sent event: {payload.get('trigger')} | Status: {resp.status_code}")
        except Exception as e:
            print(f"[SAMMI] Error sending: {e}") 
            
    threading.Thread(target=_send, daemon=True).start()
