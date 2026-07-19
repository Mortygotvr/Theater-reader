import asyncio
import traceback
import time
import threading
import re
import ctypes

try:
    import keyboard
except ImportError:
    keyboard = None

# Constants for direct OS-level key injection
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

# A lookup map to decouple from the `keyboard` module's internal APIs that are breaking.
# This gives us exact Virtual Key codes (VK) for OS injection.
VK_MAP = {
    'f1': 0x70, 'f2': 0x71, 'f3': 0x72, 'f4': 0x73, 'f5': 0x74, 'f6': 0x75,
    'f7': 0x76, 'f8': 0x77, 'f9': 0x78, 'f10': 0x79, 'f11': 0x7A, 'f12': 0x7B,
    'f13': 0x7C, 'f14': 0x7D, 'f15': 0x7E, 'f16': 0x7F, 'f17': 0x80, 'f18': 0x81, 'f19': 0x82, 'f20': 0x83, 'f21': 0x84, 'f22': 0x85, 'f23': 0x86, 'f24': 0x87,
    'shift': 0x10, 'ctrl': 0x11, 'alt': 0x12,
    'enter': 0x0D, 'esc': 0x1B, 'space': 0x20, 'tab': 0x09, 'backspace': 0x08,
    'up': 0x26, 'down': 0x28, 'left': 0x25, 'right': 0x27,
    'numpad 0': 0x60, 'numpad 1': 0x61, 'numpad 2': 0x62, 'numpad 3': 0x63,
    'numpad 4': 0x64, 'numpad 5': 0x65, 'numpad 6': 0x66, 'numpad 7': 0x67,
    'numpad 8': 0x68, 'numpad 9': 0x69,
    'multiply': 0x6A, 'add': 0x6B, 'subtract': 0x6D, 'decimal': 0x6E, 'divide': 0x6F,
}

def get_vk_for_key(k):
    k = k.lower().strip()
    if k in VK_MAP:
        return VK_MAP[k]
    # For a-z and 0-9, VK is just the ASCII of the uppercase character
    if len(k) == 1 and ('a' <= k <= 'z' or '0' <= k <= '9'):
        return ord(k.upper())
    return 0


# Global tracking to prevent double-firing
_last_fired = {}

def check_and_fire_hotkeys(config, incoming_trigger, event_queue=None):
    """
    Checks if an incoming stream alert matches a configured hotkey
    and physically simulates the keystrokes on the system.
    """
    if not config.get("enable_hotkeys", False):
        return

    if not keyboard:
        return
        
    hotkeys = config.get("hotkeys", [])
    if not hotkeys: 
        return

    def log_diag(msg):
        print(msg)
        if event_queue:
            try: 
                event_queue.put(("system_diag", "KeyTriggers", "diag", "diag", {"message": msg}))
            except: pass

    def _execute_macro(keys_str, delay):
        def _task():
            if delay > 0:
                time.sleep(delay / 1000.0)
            try:
                log_diag(f"[Hotkey Bridge] Executing Raw OS Keystroke -> {keys_str} (Triggered by: {incoming_trigger})")
                
                # Split the macro components (e.g. 'ctrl+f1' -> ['ctrl', 'f1'])
                keys = keys_str.split('+')
                
                # We completely bypass the python library for sending because games/heavy apps 
                # often ignore synthetic "Virtual Keys". We force the OS to inject raw Hardware Scan Codes.
                
                # Step 1: Press all keys down using raw C-Types Win32 API
                for k in keys:
                    try:
                        vk = get_vk_for_key(k)
                        if vk == 0:
                            log_diag(f"[Hotkey Bridge] Could not find Virtual Key code for {k}")
                            continue
                        
                        # Translate the VK to a hardware scan code directly from Windows mappings
                        scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0) # 0 = MAPVK_VK_TO_VSC
                        # Send the scancode into the Windows keystroke pipeline with KEYEVENTF_SCANCODE
                        ctypes.windll.user32.keybd_event(vk, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYDOWN, 0)
                    except Exception as hw_e:
                        log_diag(f"[Hotkey Bridge] Mapping failure for {k}: {hw_e}")
                    
                time.sleep(0.1) 
                
                # Step 2: Release in exact reverse order
                for k in reversed(keys):
                    try:
                        vk = get_vk_for_key(k)
                        if vk == 0: continue
                        
                        scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
                        ctypes.windll.user32.keybd_event(vk, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)
                    except Exception as hw_e:
                        log_diag(f"[Hotkey Bridge] Release mapping failure for {k}: {hw_e}")
                        
            except Exception as e:
                log_diag(f"[Hotkey Bridge] Error firing {keys_str}: {e}")
                
        threading.Thread(target=_task, daemon=True).start()

    for hk in hotkeys:
        hk_trigger = hk.get("trigger", "").strip()
        if not hk_trigger: continue
        
        # Turn "Twitch * sub" into a much safer regex matching rule that ignores extra spaces
        # and doesn't get strict locked behind ^ and $ edge boundaries that tests ruin
        # Ex: "Twitch * sub" -> "Twitch .* sub"
        base_pattern = re.escape(hk_trigger).replace(r"\*", ".*")
        pattern_str = f"(?i){base_pattern}"
        
        try:
            if re.search(pattern_str, incoming_trigger):
                modifiers = []
                if hk.get("ctrl"): modifiers.append("ctrl")
                if hk.get("alt"): modifiers.append("alt")
                if hk.get("shift"): modifiers.append("shift")
                
                raw_key = (hk.get("assigned_key") or hk.get("key") or "").lower().strip()
                if raw_key.startswith("num "):
                    if raw_key == "num *": raw_key = "multiply"
                    elif raw_key == "num +": raw_key = "add"
                    elif raw_key == "num -": raw_key = "subtract"
                    elif raw_key == "num .": raw_key = "decimal"
                    elif raw_key == "num /": raw_key = "divide"
                    else: raw_key = raw_key.replace("num ", "numpad ")
                
                # 'keyboard' module uses 'page up'/'page down' with spaces.
                # Just ensure it maps correctly to the underlying OS hook string
                
                if raw_key:
                    modifiers.append(raw_key)
                    _execute_macro("+".join(modifiers), int(hk.get("delay", 0)))
        except Exception as e:
            log_diag(f"[Hotkey Bridge] Pattern error '{hk_trigger}': {e}")


def start_key_listener(config, event_queue):
    global _last_fired
    
    def log_diag(msg):
        print(msg)
        try:
            event_queue.put(("system_diag", "KeyTriggers", "diag", "diag", {"message": msg}))
        except: pass

    # Clean up existing hotkeys if any are currently bound
    if keyboard is not None:
        try:
            keyboard.unhook_all()
        except Exception as e:
            log_diag(f"[KeyTriggers] Warning unhooking keys: {e}")

    if not config.get("enable_hotkeys", False):
        log_diag("[KeyTriggers] Hotkeys disabled in settings. Skipping listener initialization.")
        return
            
    _last_fired.clear()

    if not keyboard:
        log_diag("[KeyTriggers] Warning: 'keyboard' module not installed. Keypress triggers will not work.")
        return
        
    hotkey_configs = config.get("key_to_triggers", [])
    if not hotkey_configs:
        return

    log_diag(f"[KeyTriggers] Registering {len(hotkey_configs)} keypress triggers...")
    
    for idx, hk in enumerate(hotkey_configs):
        trigger_str = hk.get("trigger", "").strip()
        if not trigger_str: continue
        
        # Build the hotkey string as expected by 'keyboard' module
        modifiers = []
        if hk.get("ctrl"): modifiers.append("ctrl")
        if hk.get("alt"): modifiers.append("alt")
        if hk.get("shift"): modifiers.append("shift")
        
        # Format the base key for the python keyboard module constraints
        raw_key = (hk.get("assigned_key") or hk.get("key") or "").lower().strip()
        base_key = raw_key
        if base_key.startswith("num "):
            base_key = base_key.replace("num ", "numpad ")

        if base_key:
            modifiers.append(base_key)
        
        if not modifiers:
            continue
            
        kb_str = "+".join(modifiers)
        
        def make_callback(t_str, delays, hotkey_id):
            log_diag(f"[KeyTriggers] Binding OS Hook: {hotkey_id} -> {t_str}")
            def callback():
                now = time.time()
                if now - _last_fired.get(hotkey_id, 0) < 0.5:
                    return
                _last_fired[hotkey_id] = now

                def _push():
                    log_diag(f"[KeyTriggers] >> DETECTED: '{hotkey_id}'! Firing: '{t_str}'")
                    event_queue.put(("local_hotkey", "System", "Key Trigger", t_str, {"message": "", "username": "LocalUser"}))
                
                if delays > 0:
                    threading.Timer(delays / 1000.0, _push).start()
                else:
                    _push()
            return callback
        
        try:
            delay_ms = int(hk.get("delay", 0))
            
            # Use raw unhookable Global Listener binding instead of structured Hotkeys
            # This completely bypasses Windows focus requirements by reading the direct raw buffer
            def global_listener(e):
                if e.event_type == 'down' and e.name == base_key:
                    # Check modifiers locally instead of relying on the keyboard modules broken state machine
                    mods_active = True
                    if 'ctrl' in modifiers and not keyboard.is_pressed('ctrl'): mods_active = False
                    if 'alt' in modifiers and not keyboard.is_pressed('alt'): mods_active = False
                    if 'shift' in modifiers and not keyboard.is_pressed('shift'): mods_active = False
                    
                    if mods_active:
                        make_callback(trigger_str, delay_ms, kb_str)()
                        
            log_diag(f"[KeyTriggers] Appended Raw OS API Listener for: {kb_str}")
            keyboard.hook(global_listener)
            
        except Exception as e:
            log_diag(f"[KeyTriggers] Failed to bind ({kb_str}) -> {trigger_str}: {e}")

def stop_key_listener():
    if keyboard:
        try:
            keyboard.unhook_all()
        except:
            pass
