import asyncio
import json
import os
import sys
import threading
import websockets
import urllib.request
import re
import time
import zipfile
import shutil
import base64
HAS_OPENCV = False

import config
from config import BASE_DIR, load_complete_config_state, save_complete_config_state
from sammi_bridge import send_to_sammi
from tts import HAS_TTS

CLIENTS = set()
_ws_loop = None
_camera_active = False
_obs_connected = False

from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn

def broadcast(message: dict):
    """Thread-safe: schedule a broadcast on the WS event loop from any thread."""
    global _ws_loop
    if _ws_loop and _ws_loop.is_running():
        asyncio.run_coroutine_threadsafe(_broadcast_internal(message), _ws_loop)
    elif _ws_loop and not _ws_loop.is_closed():
        # Fallback for initialization phase
        try:
            _ws_loop.call_soon_threadsafe(asyncio.create_task, _broadcast_internal(message))
        except:
            pass


# -------------------------------------

def _get_audio_devices():
    devices = []
    import sys
    import subprocess
    if sys.platform == "win32":
        try:
            import winreg
            path = r"SOFTWARE\Microsoft\Windows\CurrentVersion\MMDevices\Audio\Render"
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                num_subkeys = winreg.QueryInfoKey(key)[0]
                for i in range(num_subkeys):
                    subkey_name = winreg.EnumKey(key, i)
                    subkey_path = f"{path}\\{subkey_name}"
                    try:
                        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey_path) as subkey:
                            state, _ = winreg.QueryValueEx(subkey, "DeviceState")
                            # DeviceState 1 = DEVICE_STATE_ACTIVE
                            if state == 1:
                                prop_path = f"{subkey_path}\\Properties"
                                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, prop_path) as prop_key:
                                    try:
                                        friendly_name, _ = winreg.QueryValueEx(prop_key, "{a45c254e-df1c-4efd-8020-67d146a850e0},2")
                                        if friendly_name:
                                            try:
                                                driver_desc, _ = winreg.QueryValueEx(prop_key, "{b3f8fa53-0004-438e-9003-51a46e139bfc},6")
                                            except FileNotFoundError:
                                                driver_desc = None
                                            
                                            full_name = f"{friendly_name} ({driver_desc})" if driver_desc else friendly_name
                                            if full_name not in devices:
                                                devices.append(full_name)
                                    except FileNotFoundError:
                                        pass
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Device List] Error getting devices via winreg: {e}")
    elif sys.platform.startswith("linux"):
        try:
            res = subprocess.run(["pactl", "list", "sinks"], capture_output=True, text=True, timeout=3)
            if res.returncode == 0:
                current_name = None
                current_desc = None
                for line in res.stdout.splitlines():
                    l = line.strip()
                    if l.startswith("Nom") or l.startswith("Name:"):
                        current_name = l.split(":", 1)[1].strip()
                    elif l.startswith("Description"):
                        current_desc = l.split(":", 1)[1].strip()
                    
                    if current_name and current_desc:
                        fmt = f"{current_desc} [{current_name}]"
                        if fmt not in devices:
                            devices.append(fmt)
                        current_name = None
                        current_desc = None
        except Exception as e:
            print(f"[Device List] Error getting Linux audio devices: {e}")
    return devices


# Camera probing removed (moved to Theater-scene tracker)

async def get_tts_info():
    import platform
    import shutil
    import sys
    import glob
    info = {"voices": [], "devices": [], "cameras": [], "os": platform.system()}
    
    ffplay_exe = "ffplay.exe" if platform.system() == "Windows" else "ffplay"
    ffplay_path = os.path.join(BASE_DIR, ffplay_exe)
    info["has_ffplay"] = os.path.exists(ffplay_path) or shutil.which("ffplay") is not None

    piper_exe = "piper.exe" if platform.system() == "Windows" else "piper"
    piper_path = os.path.join(BASE_DIR, "piper", piper_exe)
    info["has_piper"] = os.path.exists(piper_path) or shutil.which("piper") is not None

    if sys.platform.startswith("linux"):
        events = glob.glob('/dev/input/event*')
        has_access = any(os.access(e, os.R_OK) for e in events) if events else True
        info["linux_input_permission_needed"] = not has_access
    else:
        info["linux_input_permission_needed"] = False

    if HAS_TTS:
        info["voices"].append({"id": "en_US-lessac-low.onnx", "name": "en_US-lessac-low (en-US)"})
        piper_dir = os.path.join(BASE_DIR, "piper")
        if os.path.exists(piper_dir):
            for f in os.listdir(piper_dir):
                if f.endswith(".onnx") and f != "en_US-lessac-low.onnx":
                    voice_name = f.replace(".onnx", "")
                    info["voices"].append({"id": f, "name": voice_name})
            
    import asyncio
    audio_devices = await asyncio.to_thread(_get_audio_devices)
    for d in audio_devices:
        info["devices"].append({"id": d, "name": d})
        
    info["cameras"] = [{"id": "obs", "name": "OBS Virtual Camera"}]
    
    return info

async def _authorize_linux_input_task(websocket):
    try:
        import sys
        import getpass
        import shutil
        import subprocess

        if not sys.platform.startswith("linux"):
            await websocket.send(json.dumps({"type": "status", "message": "Authorization is only applicable on Linux."}))
            return

        username = getpass.getuser()
        await websocket.send(json.dumps({"type": "status", "message": "Opening Linux OS Authorization Window..."}))

        def _run_pkexec():
            if shutil.which("pkexec"):
                cmd = ["pkexec", "usermod", "-aG", "input", username]
                res = subprocess.run(cmd, capture_output=True, text=True)
                return res.returncode == 0, res.stderr
            return False, "pkexec command not found."

        success, err = await asyncio.to_thread(_run_pkexec)
        if success:
            msg = f"Permissions Granted! Added user '{username}' to the 'input' group.\n\n⚠️ IMPORTANT: You MUST log out and log back in (or reboot) for Linux group permissions to take effect!"
            await websocket.send(json.dumps({"type": "status", "message": msg}))
            await websocket.send(json.dumps({"type": "linux_input_authorized", "message": msg}))

        else:
            await websocket.send(json.dumps({"type": "status", "message": f"Authorization cancelled or failed: {err}"}))
    except Exception as e:
        await websocket.send(json.dumps({"type": "status", "message": f"Authorization error: {e}"}))


async def _install_piper_task(websocket):
    try:
        import platform
        import tarfile

        system = platform.system()
        machine = platform.machine().lower()

        if system == "Windows":
            PIPER_URL = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_windows_amd64.zip"
        elif system == "Darwin":
            PIPER_URL = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_macos_x86_64.tar.gz"
        else: # Linux
            if "arm" in machine or "aarch64" in machine:
                PIPER_URL = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_aarch64.tar.gz"
            elif "armv7" in machine:
                PIPER_URL = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_armv7l.tar.gz"
            else:
                PIPER_URL = "https://github.com/rhasspy/piper/releases/download/2023.11.14-2/piper_linux_x86_64.tar.gz"

        archive_name = "piper_temp.zip" if PIPER_URL.endswith(".zip") else "piper_temp.tar.gz"
        archive_path = os.path.join(BASE_DIR, archive_name)
        MODEL_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/low/en_US-lessac-low.onnx"
        JSON_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/low/en_US-lessac-low.onnx.json"

        await websocket.send(json.dumps({"type": "status", "message": "Downloading Piper TTS..."}))
        await asyncio.to_thread(urllib.request.urlretrieve, PIPER_URL, archive_path)

        await websocket.send(json.dumps({"type": "status", "message": "Extracting Piper..."}))
        def _extract_and_download():
            if archive_name.endswith(".zip"):
                with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                    zip_ref.extractall(BASE_DIR)
            else:
                with tarfile.open(archive_path, 'r:gz') as tar_ref:
                    tar_ref.extractall(BASE_DIR)
            if os.path.exists(archive_path):
                os.remove(archive_path)
            
            piper_dir = os.path.join(BASE_DIR, "piper")
            os.makedirs(piper_dir, exist_ok=True)

            piper_bin = os.path.join(piper_dir, "piper")
            if os.path.exists(piper_bin):
                try:
                    os.chmod(piper_bin, 0o755)
                except Exception as e:
                    print(f"[Piper Install] Failed to chmod piper: {e}")

            model_path = os.path.join(piper_dir, "en_US-lessac-low.onnx")
            json_path = os.path.join(piper_dir, "en_US-lessac-low.onnx.json")
            
            if not os.path.exists(model_path):
                urllib.request.urlretrieve(MODEL_URL, model_path)
            if not os.path.exists(json_path):
                urllib.request.urlretrieve(JSON_URL, json_path)

        await websocket.send(json.dumps({"type": "status", "message": "Downloading default voice..."}))
        await asyncio.to_thread(_extract_and_download)

        await websocket.send(json.dumps({"type": "status", "message": "Piper TTS Installed Successfully!"}))
        await websocket.send(json.dumps({"type": "piper_installed"}))

    except Exception as e:
        await websocket.send(json.dumps({"type": "status", "message": f"Error installing Piper: {e}"}))



async def _get_piper_voices_list(websocket):
    try:
        url = "https://huggingface.co/rhasspy/piper-voices/raw/main/voices.json"
        def _fetch():
            req = urllib.request.urlopen(url, timeout=10)
            return req.read().decode('utf-8')
            
        data = await asyncio.to_thread(_fetch)
        voices_dict = json.loads(data)
        
        voices_out = []
        for key, info in voices_dict.items():
            lang = info.get("language", {}).get("name_english", "Unknown")
            name = info.get("name", key)
            quality = info.get("quality", "")
            voices_out.append({
                "key": key,
                "display": f"{name} ({lang} - {quality})",
                "files": info.get("files", {})
            })
            
        voices_out.sort(key=lambda x: (x["display"]))
        
        await websocket.send(json.dumps({
            "type": "piper_voices_list_result",
            "payload": voices_out
        }))
    except Exception as e:
        await websocket.send(json.dumps({"type": "status", "message": f"Failed to fetch voices list: {e}"}))

async def _install_piper_voice_task(websocket, voice_key, files_dict):
    try:
        piper_dir = os.path.join(BASE_DIR, "piper")
        os.makedirs(piper_dir, exist_ok=True)
        base_url = "https://huggingface.co/rhasspy/piper-voices/resolve/main/"

        await websocket.send(json.dumps({"type": "status", "message": f"Downloading voice {voice_key}..."}))

        def _download():
            for f in files_dict.keys():
                if f.endswith(".onnx") or f.endswith(".json"):
                    filename = os.path.basename(f)
                    out_path = os.path.join(piper_dir, filename)
                    urllib.request.urlretrieve(base_url + f, out_path)
        await asyncio.to_thread(_download)
        
        await websocket.send(json.dumps({"type": "status", "message": f"Voice {voice_key} downloaded!"}))
        await websocket.send(json.dumps({"type": "voice_installed", "message": "Voice installed successfully"}))

        tts_info = await get_tts_info()
        await websocket.send(json.dumps({"type": "tts_info", "payload": tts_info}))
    except Exception as e:
        await websocket.send(json.dumps({"type": "status", "message": f"Error downloading voice: {e}"}))

async def _cleanup_piper_voices(websocket, keep_voice_id):
    try:
        piper_dir = os.path.join(BASE_DIR, "piper")
        if not os.path.exists(piper_dir):
            return

        keep_base = keep_voice_id.replace(".onnx", "")

        for f in os.listdir(piper_dir):
            if f.endswith(".onnx") or f.endswith(".json"):
                if not f.startswith(keep_base):
                    os.remove(os.path.join(piper_dir, f))
        
        tts_info = await get_tts_info()
        await websocket.send(json.dumps({"type": "tts_info", "payload": tts_info}))
    except Exception as e:
        await websocket.send(json.dumps({"type": "status", "message": f"Error cleaning voices: {e}"}))

async def _install_ffplay_task(websocket):
    try:
        url = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"
        zip_path = os.path.join(BASE_DIR, "ffmpeg_temp.zip")

        await websocket.send(json.dumps({"type": "status", "message": "Downloading FFplay (this may take a minute)..."}))

        await asyncio.to_thread(urllib.request.urlretrieve, url, zip_path)
        await websocket.send(json.dumps({"type": "status", "message": "Extracting FFplay..."}))

        def _extract():
            with zipfile.ZipFile(zip_path, 'r') as z:
                for fname in z.namelist():
                    if fname.endswith("ffplay.exe"):
                        ffplay_out = os.path.join(BASE_DIR, "ffplay.exe")
                        with z.open(fname) as source, open(ffplay_out, "wb") as target:
                            shutil.copyfileobj(source, target)
                        break

        await asyncio.to_thread(_extract)
        if os.path.exists(zip_path):
            os.remove(zip_path)

        await websocket.send(json.dumps({"type": "status", "message": "FFplay Installed Successfully!"}))
        await websocket.send(json.dumps({"type": "ffplay_installed"}))
    except Exception as e:
        print(f"[Install] FFplay install error: {e}")
        await websocket.send(json.dumps({"type": "status", "message": f"Error installing FFplay: {e}"}))

async def ws_register(websocket):
    global _ws_loop
    global _camera_active, _obs_connected
    if _ws_loop is None:
        try:
            _ws_loop = asyncio.get_running_loop()
        except AttributeError:
             _ws_loop = asyncio.get_event_loop()

    headers = getattr(websocket, "request_headers", None)
    if headers is None and hasattr(websocket, "request"):
        headers = getattr(websocket.request, "headers", None)
    if headers is None:
        headers = {}

    referer = headers.get("Referer", "")
    client_name = "Unknown Client"
    
    # Check path if available to identify specific requested paths
    path = getattr(websocket, "path", None)
    if path is None and hasattr(websocket, "request"):
        path = getattr(websocket.request, "path", "/")
        
    if path and path != "/":
        client_name = path.lstrip("/")
    elif referer:
        client_name = referer.split("/")[-1].split("?")[0]
    else:
        origin = headers.get("Origin", "")
        ua = headers.get("User-Agent", "").lower()
        if origin == "http://absolute" or "obs/" in ua:
            client_name = "index.html (OBS)"
        elif origin == "null":
            if "qtwebengine" in ua or "pyside" in ua:
                client_name = "index.html (Overlay)"
            else:
                client_name = "control_panel.html"
        elif origin:
            client_name = origin.split("/")[-1]
            
    print(f"[Connection] {client_name} connected to WebSocket Server.")

    CLIENTS.add(websocket)
    try:
        try:
            # 1. SEND OTHER METADATA
            await websocket.send(json.dumps({"type": "sub_cache", "payload": config.SUB_DB}))
            tts_info = await get_tts_info()
            await websocket.send(json.dumps({"type": "tts_info", "payload": tts_info}))

        except Exception as e:
            print(f"[WS] Error sending initial config: {e}")
            
        # Send initial state
        await websocket.send(json.dumps({
            "type": "vision_status",
            "payload": {
                "installed": False,
                "active": False
            }
        }))
        
        async for message in websocket:
            try:
                data = json.loads(message)
                if data.get("type") == "install_ffplay":
                    asyncio.create_task(_install_ffplay_task(websocket))
                elif data.get("type") == "install_piper":
                    asyncio.create_task(_install_piper_task(websocket))
                elif data.get("type") == "get_piper_voices":
                    asyncio.create_task(_get_piper_voices_list(websocket))
                elif data.get("type") == "install_piper_voice":
                    asyncio.create_task(_install_piper_voice_task(websocket, data.get("voice_key"), data.get("files_dict")))
                elif data.get("type") == "authorize_linux_input":
                    asyncio.create_task(_authorize_linux_input_task(websocket))

                
                # --- WATERFALL LOADING HANDLERS ---
                elif data.get("type") == "request_initial_obs":
                    current = load_complete_config_state()
                    obs_payload = {
                        "scenes": current.get("obs_scenes", []),
                        "sources": current.get("obs_sources", []),
                        "filters": current.get("obs_filters", {}),
                        "connected": _obs_connected
                    }
                    await websocket.send(json.dumps({"type": "obs_info", "payload": obs_payload}))
                    # Relay to tracker to fetch fresh connection status/sources
                    await _broadcast_internal({"type": "fetch_obs_info"})
                    
                elif data.get("type") == "request_config_state":
                    current = load_complete_config_state()
                    # print(f"[WS] Sending Config State. Camera Tracking Mode: {current.get('camera_tracking', {}).get('mode')}")
                    await websocket.send(json.dumps({"type": "config_state", "payload": current}))
                # ----------------------------------

                elif data.get("type") == "cleanup_piper_voices":
                    asyncio.create_task(_cleanup_piper_voices(websocket, data.get("keep_voice")))


                elif data.get("type") == "update_physics_settings":
                    import __main__
                    q = getattr(__main__, 'event_queue', None)
                    if q:
                        q.put(("system_command", "WS", "update_physics_settings", "update_physics_settings", data.get("settings")))
                
                elif data.get("type") == "update_resolution":
                    # Broadcast to all clients (including other browser windows & Tracker)
                    await _broadcast_internal(data)

                elif data.get("type") == "save_config":
                    new_cfg = data.get("payload")
                    if new_cfg:
                        print("\n" + "!"*60)
                        print("!!! BACKEND RECEIVED CONFIG SAVE !!!")
                        print("!"*60 + "\n")
                        
                        save_complete_config_state(new_cfg)
                        
                        # Notify all connected clients (especially index.html & scene_tracker)
                        await _broadcast_internal({"type": "config_updated", "payload": new_cfg})
                        
                        await websocket.send(json.dumps({"type": "status", "message": "Configuration Saved! Reloading Listeners..."}))
                        config.RELOAD_CONFIG_ID += 1
                elif data.get("type") == "native_export_config":
                    filename = data.get("filename", "Control.panel.json")
                    content = data.get("content", "")
                    
                    def _write_file():
                        sibling_cp = os.path.join(os.path.dirname(BASE_DIR), "Control Panel")
                        if os.path.exists(sibling_cp) and os.path.isdir(sibling_cp):
                            save_path = os.path.join(sibling_cp, filename)
                        else:
                            save_path = os.path.join(BASE_DIR, filename)
                        with open(save_path, "w", encoding="utf-8") as f:
                            f.write(content)
                        return save_path
                        
                    try:
                        save_path = await asyncio.to_thread(_write_file)
                        print(f"[Export] Saved backup configuration to: {save_path}")
                        await websocket.send(json.dumps({
                            "type": "status",
                            "message": f"Configuration exported successfully to {filename}"
                        }))
                    except Exception as e:
                        print(f"[Export Error] Failed to write backup: {e}")
                        await websocket.send(json.dumps({
                            "type": "status",
                            "message": f"Export failed: {str(e)}",
                            "error": True
                        }))
                elif data.get("type") == "update_obs_config":
                    new_obs_cfg = data.get("payload")
                    if new_obs_cfg is not None:
                        curr = load_complete_config_state()
                        curr["obs_bridge"] = new_obs_cfg
                        save_complete_config_state(curr)
                        await websocket.send(json.dumps({"type": "status", "message": "OBS Configuration Saved! Reloading Listeners..."}))
                        print("[CONFIG] New OBS configuration saved via WebSocket. Reloading Listeners...")
                        await asyncio.sleep(1)
                        config.RELOAD_CONFIG_ID += 1
                elif data.get("type") == "update_gpu":
                    is_enabled = data.get("enabled", True)
                    curr = load_complete_config_state()
                    curr["gpu_acceleration"] = is_enabled
                    save_complete_config_state(curr)
                    print(f"[CONFIG] GPU Acceleration set to {is_enabled}. (Requires Restart)")
                elif data.get("type") == "get_sub_cache":
                    await websocket.send(json.dumps({"type": "sub_cache", "payload": config.SUB_DB}))
                elif data.get("type") == "refresh_obs_sources":
                    await _broadcast_internal(data)
                elif data.get("type") == "fetch_obs_info":
                    await _broadcast_internal(data)
                elif data.get("type") == "system_diag":
                    import __main__
                    q = getattr(__main__, 'event_queue', None)
                    if q:
                        q.put(("system_diag", "WS", "diag", "diag", data.get("payload", {})))
                elif data.get("type") == "test_sammi_trigger":
                    trigger_val = data.get("trigger", "Test Trigger")
                    user_val = data.get("user", "TestUser")
                    channel_val = data.get("channel", "TestChannel")
                    var_val = data.get("var", "500")
                    if trigger_val:
                        print(f"[WS] Sending test SAMMI trigger: {trigger_val}")
                        platform_val = "Test"
                        if trigger_val.lower().startswith("twitch "): platform_val = "Twitch"
                        elif trigger_val.lower().startswith("kick "): platform_val = "Kick"
                        elif trigger_val.lower().startswith("youtube "): platform_val = "YouTube"

                        if platform_val != "Test" and "testserver" not in trigger_val.lower():
                            trigger_suffix = trigger_val[len(platform_val):].strip()
                            trigger_val = f"{platform_val} testserver {trigger_suffix}"
                        elif "testserver" not in trigger_val.lower():
                            trigger_val = f"testserver {trigger_val}"

                        test_sub_status = "unknown"
                        payload = {
                            "trigger": trigger_val,
                            "msg_id": f"test-uuid-{int(time.time())}",
                            "platform": platform_val,
                            "username": user_val,
                            "message": str(var_val),
                            "customData": {
                                "is_test": True, 
                                "username": user_val, 
                                "badges_html": "", 
                                "color": "#FF5733",
                                "amount": var_val,
                                "tier": var_val,
                                "months": var_val,
                                "gifted": False
                            }
                        }
                        send_to_sammi(payload)
                        curr = load_complete_config_state()
                        
                        try:
                            from key_triggers import check_and_fire_hotkeys
                            import __main__
                            q = getattr(__main__, 'event_queue', None)
                            if q:
                                check_and_fire_hotkeys(curr, trigger_val, q)
                        except Exception as e:
                            print(f"[WS] Error testing hotkey bridge: {e}")
                        
                        # Fix: Send the trigger back to the web UI overlay!
                        await _broadcast_internal({"type": "moderation", "payload": payload})
                        
                        # also send as an alert and chat to test overlay UI properly
                        is_chat = False
                        bc_event = trigger_val
                        if "chat" in trigger_val.lower():
                            is_chat = True
                            
                        if is_chat:
                            await _broadcast_internal({
                                "type": "chat", 
                                "trigger": trigger_val, 
                                "msg_id": payload["msg_id"],
                                "source": "Test UI",
                                "message": str(var_val), 
                                "username": user_val,
                                "avatar": "https://pystray.readthedocs.io/en/latest/_static/pystray.png"
                            })
                        else:
                            await _broadcast_internal({
                                "type": "alert",
                                "source": "Test UI",
                                "event": trigger_val,
                                "trigger": trigger_val,
                                "data": payload["customData"]
                            })
                            
                elif data.get("type") in ["obs_info", "obs_sources", "obs_filters", "obs_error"]:
                    if data.get("type") == "obs_info":
                        payload = data.get("payload", {})
                        if isinstance(payload, dict):
                            _obs_connected = payload.get("connected", False)
                    # Broadcast OBS info to all other clients (e.g. settings.html)
                    await _broadcast_internal(data)
                elif data.get("type") == "refresh_devices":
                    tts_info = await get_tts_info()
                    await websocket.send(json.dumps({"type": "tts_info", "payload": tts_info}))
                elif data.get("type") == "execute_trigger":
                    # This is the "Simulator" for the Test button in the UI
                    # We inject a simulated event into the main queue so the WHOLE system is tested
                    trig = data.get("payload")
                    mock_data = data.get("data", {})
                    if trig and trig.get("events"):
                        # Get the first pattern from the trigger
                        pattern = [s.strip() for s in trig.get("events").split(",")][0]
                        # Replace wildcards with our mock data if available
                        sim_trigger = pattern.replace("*", str(mock_data.get("_matches", ["TestVal"])[0]))
                        
                        import __main__
                        q = getattr(__main__, 'event_queue', None)
                        if q:
                            # (parser, channel, event, trigger_str, data)
                            q.put(("system_simulator", "TestChannel", "TestEvent", sim_trigger, mock_data))
                            print(f"[WS] Injected simulated event for trigger: {sim_trigger}")

                elif data.get("type") == "execute_actions":
                    # Relay direct actions execution list to the Tracker client
                    await _broadcast_internal(data)

                elif data.get("type") == "run_obs_setup":
                    print("[WS] Relaying manual OBS Setup Request to tracker.")
                    await _broadcast_internal(data)
            except Exception as e:
                print(f"[WS] Message Error: {e}")
    except Exception:
        pass
    finally:
        try:
            CLIENTS.remove(websocket)
            print(f"[Connection] {client_name} disconnected.")
        except KeyError:
            pass

async def _broadcast_internal(message_dict):
    if not CLIENTS:
        return
    payload = json.dumps(message_dict)
    dead_clients = set()
    for ws in list(CLIENTS):
        try:
            await ws.send(payload)
        except Exception:
            dead_clients.add(ws)
    for ws in dead_clients:
        CLIENTS.discard(ws)



async def ws_main_server(host, port):
    async with websockets.serve(ws_register, host, port):
        await asyncio.Future()

def start_ws_server(host="0.0.0.0", port=41837):
    def run():
        global _ws_loop
        _ws_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_ws_loop)
        print(f"[WS] Starting WebSocket Server on ws://{host}:{port}")
        try:
            _ws_loop.run_until_complete(ws_main_server(host, port))
        except Exception as e:
            print(f"[WS] Server Error: {e}")
        finally:
            _ws_loop.close()

    t = threading.Thread(target=run, daemon=True, name="WebSocketServer")
    t.start()
