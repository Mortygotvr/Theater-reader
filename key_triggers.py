import asyncio
import traceback
import time
import threading
import re
import ctypes
import sys
import shutil
import subprocess

try:
    import keyboard
except ImportError:
    keyboard = None

try:
    from pynput import keyboard as pynput_keyboard
except ImportError:
    pynput_keyboard = None

# Constants for direct OS-level key injection (Windows)
KEYEVENTF_KEYDOWN = 0x0000
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

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
    if len(k) == 1 and ('a' <= k <= 'z' or '0' <= k <= '9'):
        return ord(k.upper())
    return 0

_last_fired = {}
_pynput_listener = None
_pressed_keys = set()

def _normalize_key_name(key):
    try:
        if hasattr(key, 'name') and key.name:
            n = key.name.lower()
            if n in ('ctrl_l', 'ctrl_r', 'ctrl', 'control'): return 'ctrl'
            if n in ('alt_l', 'alt_r', 'alt_gr', 'alt'): return 'alt'
            if n in ('shift_l', 'shift_r', 'shift'): return 'shift'
            if n in ('cmd', 'cmd_l', 'cmd_r', 'super', 'win'): return 'win'
            if n == 'page_up': return 'page up'
            if n == 'page_down': return 'page down'
            return n
        elif hasattr(key, 'char') and key.char:
            return key.char.lower()
        elif hasattr(key, 'vk') and key.vk:
            vk = key.vk
            if 96 <= vk <= 105:
                return f"numpad {vk - 96}"
            if vk == 106: return "multiply"
            if vk == 107: return "add"
            if vk == 109: return "subtract"
            if vk == 110: return "decimal"
            if vk == 111: return "divide"
    except Exception:
        pass
    return str(key).lower()

def _simulate_keypress_pynput(keys_str):
    if not pynput_keyboard:
        return False
    try:
        ctl = pynput_keyboard.Controller()
        parts = [k.lower().strip() for k in keys_str.split('+')]
        
        def resolve_key(k):
            if k in ('ctrl', 'control'): return pynput_keyboard.Key.ctrl
            if k == 'alt': return pynput_keyboard.Key.alt
            if k == 'shift': return pynput_keyboard.Key.shift
            if k in ('win', 'cmd', 'super'): return pynput_keyboard.Key.cmd
            if k == 'enter': return pynput_keyboard.Key.enter
            if k == 'space': return pynput_keyboard.Key.space
            if k == 'tab': return pynput_keyboard.Key.tab
            if k == 'esc': return pynput_keyboard.Key.esc
            if k == 'backspace': return pynput_keyboard.Key.backspace
            if k == 'up': return pynput_keyboard.Key.up
            if k == 'down': return pynput_keyboard.Key.down
            if k == 'left': return pynput_keyboard.Key.left
            if k == 'right': return pynput_keyboard.Key.right
            if k.startswith('f') and k[1:].isdigit():
                return getattr(pynput_keyboard.Key, k, None)
            if len(k) == 1:
                return k
            return getattr(pynput_keyboard.Key, k, None)

        resolved = [resolve_key(k) for k in parts if resolve_key(k) is not None]
        for rk in resolved:
            ctl.press(rk)
        time.sleep(0.05)
        for rk in reversed(resolved):
            ctl.release(rk)
        return True
    except Exception as e:
        print(f"[Hotkey Bridge] pynput simulation error: {e}")
        return False

def check_and_fire_hotkeys(config, incoming_trigger, event_queue=None):
    if not config.get("enable_hotkeys", False):
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
                log_diag(f"[Hotkey Bridge] Executing Keystroke -> {keys_str} (Triggered by: {incoming_trigger})")
                
                if sys.platform == "win32" and hasattr(ctypes, "windll"):
                    keys = keys_str.split('+')
                    for k in keys:
                        try:
                            vk = get_vk_for_key(k)
                            if vk == 0: continue
                            scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
                            ctypes.windll.user32.keybd_event(vk, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYDOWN, 0)
                        except Exception as hw_e:
                            log_diag(f"[Hotkey Bridge] Mapping failure for {k}: {hw_e}")
                        
                    time.sleep(0.1) 
                    
                    for k in reversed(keys):
                        try:
                            vk = get_vk_for_key(k)
                            if vk == 0: continue
                            scan = ctypes.windll.user32.MapVirtualKeyW(vk, 0)
                            ctypes.windll.user32.keybd_event(vk, scan, KEYEVENTF_SCANCODE | KEYEVENTF_KEYUP, 0)
                        except Exception as hw_e:
                            log_diag(f"[Hotkey Bridge] Release mapping failure for {k}: {hw_e}")
                else:
                    # Non-Windows (Linux / macOS)
                    if shutil.which("xdotool"):
                        try:
                            subprocess.run(["xdotool", "key", keys_str.replace("+", "+")], check=False)
                        except Exception as e:
                            log_diag(f"[Hotkey Bridge] xdotool error: {e}")
                    elif pynput_keyboard:
                        if not _simulate_keypress_pynput(keys_str):
                            if keyboard:
                                try: keyboard.send(keys_str)
                                except Exception as e: log_diag(f"[Hotkey Bridge] keyboard.send error: {e}")
                    elif keyboard:
                        try:
                            keyboard.send(keys_str)
                        except Exception as e:
                            log_diag(f"[Hotkey Bridge] keyboard.send error: {e}")
                    else:
                        log_diag(f"[Hotkey Bridge] Hotkey simulation not supported on this OS setup ({keys_str})")

            except Exception as e:
                log_diag(f"[Hotkey Bridge] Error firing {keys_str}: {e}")
                
        threading.Thread(target=_task, daemon=True).start()

    for hk in hotkeys:
        hk_trigger = hk.get("trigger", "").strip()
        if not hk_trigger: continue
        
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
                
                if raw_key:
                    modifiers.append(raw_key)
                    _execute_macro("+".join(modifiers), int(hk.get("delay", 0)))
        except Exception as e:
            log_diag(f"[Hotkey Bridge] Pattern error '{hk_trigger}': {e}")


def stop_key_listener():
    global _pynput_listener, _pressed_keys
    _pressed_keys.clear()
    if _pynput_listener is not None:
        try:
            _pynput_listener.stop()
        except Exception:
            pass
        _pynput_listener = None

    if keyboard:
        try:
            keyboard.unhook_all()
        except Exception:
            pass

def start_key_listener(config, event_queue):
    global _last_fired, _pynput_listener, _pressed_keys
    
    def log_diag(msg):
        print(msg)
        try:
            event_queue.put(("system_diag", "KeyTriggers", "diag", "diag", {"message": msg}))
        except: pass

    stop_key_listener()

    if not config.get("enable_hotkeys", False):
        log_diag("[KeyTriggers] Hotkeys disabled in settings. Skipping listener initialization.")
        return
            
    _last_fired.clear()
    _pressed_keys.clear()

    hotkey_configs = config.get("key_to_triggers", [])
    if not hotkey_configs:
        return

    log_diag(f"[KeyTriggers] Registering {len(hotkey_configs)} keypress triggers...")
    
    parsed_triggers = []
    for hk in hotkey_configs:
        trigger_str = hk.get("trigger", "").strip()
        if not trigger_str: continue
        
        modifiers = set()
        if hk.get("ctrl"): modifiers.add("ctrl")
        if hk.get("alt"): modifiers.add("alt")
        if hk.get("shift"): modifiers.add("shift")
        
        raw_key = (hk.get("assigned_key") or hk.get("key") or "").lower().strip()
        base_key = raw_key
        if base_key.startswith("num "):
            base_key = base_key.replace("num ", "numpad ")

        if not base_key: continue
        
        kb_str = "+".join(sorted(list(modifiers) + [base_key]))
        parsed_triggers.append({
            "trigger_str": trigger_str,
            "modifiers": modifiers,
            "base_key": base_key,
            "delay_ms": int(hk.get("delay", 0)),
            "kb_str": kb_str
        })

    # On Linux or non-root environments, use pynput to avoid keyboard's hardcoded root check
    use_pynput = sys.platform.startswith("linux") or (keyboard is None)

    if use_pynput and pynput_keyboard:
        try:
            def on_press(key):
                kname = _normalize_key_name(key)
                if kname:
                    _pressed_keys.add(kname)

                for item in parsed_triggers:
                    base_k = item["base_key"]
                    req_mods = item["modifiers"]
                    
                    if kname == base_k:
                        if req_mods.issubset(_pressed_keys):
                            now = time.time()
                            hotkey_id = item["kb_str"]
                            if now - _last_fired.get(hotkey_id, 0) < 0.5:
                                continue
                            _last_fired[hotkey_id] = now
                            
                            t_str = item["trigger_str"]
                            delays = item["delay_ms"]
                            
                            def _push():
                                log_diag(f"[KeyTriggers] >> DETECTED (pynput): '{hotkey_id}'! Firing: '{t_str}'")
                                event_queue.put(("local_hotkey", "System", "Key Trigger", t_str, {"message": "", "username": "LocalUser"}))

                            if delays > 0:
                                threading.Timer(delays / 1000.0, _push).start()
                            else:
                                _push()

            def on_release(key):
                kname = _normalize_key_name(key)
                if kname in _pressed_keys:
                    _pressed_keys.discard(kname)

            _pynput_listener = pynput_keyboard.Listener(on_press=on_press, on_release=on_release)
            _pynput_listener.start()
            log_diag("[KeyTriggers] pynput global key listener started successfully (No root required).")
            return
        except Exception as p_err:
            log_diag(f"[KeyTriggers] pynput listener failed: {p_err}. Falling back to keyboard module.")

    # Fallback to keyboard module (Windows / Root)
    if not keyboard:
        log_diag("[KeyTriggers] Warning: Neither pynput nor keyboard module is available.")
        return

    for item in parsed_triggers:
        kb_str = item["kb_str"]
        base_key = item["base_key"]
        modifiers = item["modifiers"]
        trigger_str = item["trigger_str"]
        delay_ms = item["delay_ms"]

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
            def global_listener(e):
                if e.event_type == 'down' and e.name == base_key:
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
