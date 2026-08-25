import asyncio
import os
import sys

if sys.platform == 'win32':
    import ctypes
    try:
        myappid = 'mortygotvr.theaterreader.backend.101'
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
    except Exception:
        pass

import queue
import re
import uuid
import aiohttp
import threading
import time


try:
    import keyboard
except ImportError:
    pass

import config
from config import (
    BASE_DIR, STATIC_DIR, SUB_DB, STOP_EVENT, RELOAD_CONFIG_ID,
    load_complete_config_state, save_complete_config_state, load_sammi_settings, load_sub_cache, save_sub_cache
)

from tts import start_tts, tts_queue, HAS_TTS
from websocket_server import start_ws_server, broadcast
from sammi_bridge import send_to_sammi
from moderation import check_moderation
from key_triggers import start_key_listener, stop_key_listener

from parsers.twitch import monitor_twitch_irc, monitor_twitch_pubsub, get_twitch_channel_id, get_twitch_user_avatar_from_id, load_badges
from parsers.kick import monitor_kick, KICK_AVATAR_CACHE
from parsers.youtube import monitor_youtube_pytchat, get_youtube_channel_avatar

import websocket_server

# Debounced Config Saving to prevent rapid file-writes during startup
_save_timer = None
_save_timer_lock = threading.Lock()

def debounced_save_config():
    global _save_timer
    with _save_timer_lock:
        if _save_timer is not None:
            _save_timer.cancel()
        
        def _do_save():
            save_complete_config_state(config.GLOBAL_CONFIG)
            
        _save_timer = threading.Timer(1.0, _do_save)
        _save_timer.start()

# Global Event Queue
event_queue = queue.Queue()

def execute_actions(actions, obs_client, broadcast_func, data=None):
    """
    Executes a list of automation actions (OBS/Audio) with variable replacement.
    Supports: toggle_source, toggle_filter, set_value, play_audio.
    """
    if not actions: return
    data = data or {}
    
    def replace_vars(text):
        if not isinstance(text, str): return text
        # Replace standard variables {username}, {tier}, etc.
        for k, v in data.items():
            if not isinstance(v, (list, dict)):
                text = text.replace(f"{{{k}}}", str(v))
        
        # Handle positional placeholders {1}, {2} etc from pattern matches
        if "_matches" in data:
            for i, val in enumerate(data["_matches"]):
                text = text.replace(f"{{{i+1}}}", str(val))
        return text

    for action in actions:
        try:
            a_type = action.get("type")
            delay = action.get("delay", 0)
            duration = action.get("duration", 0) # For toggles: auto-reverse after X ms
            
            def _do(act=action):
                if delay > 0: time.sleep(delay / 1000.0)
                
                # Resolve targets with variables
                scene = replace_vars(act.get("scene"))
                source = replace_vars(act.get("source"))
                filter_name = replace_vars(act.get("filter"))
                
                if a_type == "toggle_source":
                    if scene and source:
                        obs_client.toggle_source_visibility(scene, source)
                        if duration > 0:
                            time.sleep(duration / 1000.0)
                            obs_client.toggle_source_visibility(scene, source)
                
                elif a_type == "toggle_filter":
                    if source and filter_name:
                        obs_client.toggle_filter(source, filter_name)
                        if duration > 0:
                            time.sleep(duration / 1000.0)
                            obs_client.toggle_filter(source, filter_name)
                
                elif a_type == "set_value":
                    key = act.get("settingKey")
                    raw_val = act.get("value")
                    if source and filter_name and key:
                        # Resolve variable in the value if it's a string
                        val = replace_vars(raw_val) if isinstance(raw_val, str) else raw_val
                        # Attempt to cast back to original type if it looks like a number/bool
                        if isinstance(val, str):
                            if val.lower() == 'true': val = True
                            elif val.lower() == 'false': val = False
                            elif val.replace('.','',1).isdigit(): 
                                val = float(val) if '.' in val else int(val)
                                
                        obs_client.set_filter_setting(source, filter_name, key, val)
                

            
            threading.Thread(target=_do, daemon=True).start()
            
        except Exception as e:
            print(f"[Actions] Execution Error: {e}")

try:
    import pystray
    from PIL import Image, ImageDraw
    HAS_TRAY = True
except Exception:
    HAS_TRAY = False



async def handle_moderation_and_actions(
    msg_text,
    chat_moderate_enabled,
    sammi_payload,
    allow_sammi,
    allow_tts,
    chat_tts_enabled,
    username,
    data,
    parser_name,
    session
):
    is_suspicious = False
    vader_score = None
    if msg_text and chat_moderate_enabled:
        is_suspicious, vader_score, ai_reason = await check_moderation(msg_text, config.GLOBAL_CONFIG, session)
        if is_suspicious:
            sammi_payload["ai_reason"] = ai_reason
            
        status_tag = "FLAGGED" if is_suspicious else "CLEAN"
        if vader_score is not None:
            sammi_payload["vader_score"] = vader_score
            sammi_payload["trigger"] += f" {status_tag} {vader_score}"
        else:
            sammi_payload["trigger"] += f" {status_tag}"

    if is_suspicious:
        print(f"[MODERATION] Suspicious message from {username}: {msg_text}")
    sammi_payload["is_suspicious"] = is_suspicious
    sammi_payload["chat_moderate_enabled"] = chat_moderate_enabled

    if "other" not in sammi_payload["trigger"].lower():
        print(f"[{parser_name}] {sammi_payload['trigger']}")
    
    if allow_sammi:
        send_to_sammi(sammi_payload)

    broadcast({"type": "moderation", "payload": sammi_payload})

    tts_config = config.GLOBAL_CONFIG.get("tts", {})
    if tts_config.get("enabled") and allow_tts and chat_tts_enabled and HAS_TTS and msg_text:
        # Pre-filter emotes and URLs to get the actual text to be spoken
        clean_text = msg_text
        if tts_config.get("ignore_urls", True):
            clean_text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\\(\\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', clean_text)
        if tts_config.get("ignore_emotes", True):
            clean_text = re.sub(r'\[(twitch_emote|yt_emoji|emote):.*?\]', '', clean_text, flags=re.IGNORECASE)
            clean_text = re.sub(r'\s+', ' ', clean_text)
        clean_text = clean_text.strip()

        should_speak = True
        if tts_config.get("ignore_commands", True) and msg_text.startswith("!"):
            should_speak = False
        if tts_config.get("only_clean", True) and is_suspicious:
            should_speak = False
            
        ignored_users = [u.lower() for u in tts_config.get("ignored_users", [])]
        if username.lower() in ignored_users:
            should_speak = False
            
        user_traits = []
        if data.get("mod"): user_traits.append("mod")
        if data.get("vip"): user_traits.append("vip")
        if data.get("subscriber"): user_traits.append("sub")
        if not user_traits: user_traits.append("non_sub")

        role_allowed = False
        if "mod" in user_traits and tts_config.get("allow_mods", True): role_allowed = True
        elif "vip" in user_traits and tts_config.get("allow_vips", True): role_allowed = True
        elif "sub" in user_traits and tts_config.get("allow_subs", True): role_allowed = True
        elif "non_sub" in user_traits and tts_config.get("allow_non_subs", True): role_allowed = True
        if not role_allowed:
            should_speak = False
                
        max_len = tts_config.get("max_length", 200)
        if max_len > 0 and len(clean_text) > max_len:
            should_speak = False

        if should_speak:
            if clean_text:
                speak_text = clean_text
                if tts_config.get("read_username"):
                    speak_text = f"{username} says {speak_text}"
                tts_queue.put((speak_text, tts_config.get("volume", 1.0), tts_config.get("rate", 200), tts_config.get("voice_id", ""), tts_config.get("device_id", "")))
            elif tts_config.get("play_bell", False):
                tts_queue.put(("[BELL]", tts_config.get("volume", 1.0), 200, tts_config.get("custom_bell_path", ""), tts_config.get("device_id", "")))
        elif tts_config.get("play_bell", False):
            tts_queue.put(("[BELL]", tts_config.get("volume", 1.0), 200, tts_config.get("custom_bell_path", ""), tts_config.get("device_id", "")))

async def main():
    print("=== Theater Engine ===")
    load_complete_config_state()
    config.RELOAD_CONFIG_ID += 1
    
    load_sammi_settings()
    load_sub_cache()
    load_badges()
    
    start_tts()
    start_ws_server()
    
    overlay_path = os.path.join(STATIC_DIR, "chat_overlay.html")
    if not os.path.exists(overlay_path):
        overlay_path = os.path.join(BASE_DIR, "chat_overlay.html")

    print(f"\n[UI] Message Overlay is available at:\n     file://{overlay_path}")

    session = aiohttp.ClientSession()
    tasks = []
    
    # Initialize Physics and OBS logic (now fully decoupled to Theater-scene)
    start_key_listener(config.GLOBAL_CONFIG, event_queue)

    def _launch_parsers(cfg, current_tasks):
        chats = cfg.get("chats", {})
        for chat_id, chat_data in chats.items():
            parser_name = chat_data.get("parser")
            inp = chat_data.get("input")
            if not inp: continue
            
            print(f"[{chat_id}] Launching {parser_name} for '{inp}'")
            
            if parser_name == "twitch_parse":
                async def _start_twitch_wrapper(s, u):
                    t_irc = asyncio.create_task(monitor_twitch_irc(u, event_queue))
                    t_pub = None
                    cid = await get_twitch_channel_id(s, u)
                    if cid:
                        t_pub = asyncio.create_task(monitor_twitch_pubsub(s, u, cid, event_queue))
                    todo = [t_irc]
                    if t_pub: todo.append(t_pub)
                    try: await asyncio.gather(*todo)
                    except asyncio.CancelledError:
                        for t in todo: t.cancel()
                current_tasks.append(asyncio.create_task(_start_twitch_wrapper(session, inp)))
            
            elif parser_name == "kick_parse":
                 current_tasks.append(asyncio.create_task(monitor_kick(session, inp, event_queue)))
                 
            elif parser_name == "youtube_parse":
                 current_tasks.append(asyncio.create_task(monitor_youtube_pytchat(inp, event_queue)))

    _launch_parsers(config.GLOBAL_CONFIG, tasks)
    print("=== Monitoring Started. Press Ctrl+C or use Tray Icon to stop. ===")

    last_main_reload_id = 0
    while not STOP_EVENT.is_set():
        # Check for reload via ID
        current_reload_id = getattr(config, 'RELOAD_CONFIG_ID', 0)
        if current_reload_id > last_main_reload_id:
            last_main_reload_id = current_reload_id
            print(f"=== Reloading Configuration (ID: {current_reload_id}) ===")
            try:
                for t in tasks: t.cancel()
                tasks.clear()
                
                # Repopulate the actual root reference object from disk
                load_complete_config_state()
                
                _launch_parsers(config.GLOBAL_CONFIG, tasks)
                start_key_listener(config.GLOBAL_CONFIG, event_queue)
            except Exception as e:
                print(f"!!! CRITICAL ERROR DURING CONFIG RELOAD !!!\n{e}")
                import traceback
                traceback.print_exc()

        try:
            try:
                item = event_queue.get_nowait()
            except queue.Empty:
                await asyncio.sleep(0.1)
                continue
            
            parser_name, channel, event, trigger, data = item
            
            # System UI Diagnostics intercepts
            if parser_name == "system_diag":
                msg = data.get("message", "")
                print(f"[UI-DIAG] {msg}")
                broadcast({"type": "sys_diag", "source": channel, "message": msg})
                continue

            if parser_name == "system_command":
                if event == "update_physics_settings":
                    continue  # Physics engine removed — handled entirely in frontend JS

            msg_text = data.get("message", "")
            username = data.get("username", data.get("author", ""))
            if username.startswith("@"): username = username[1:]
                
            plat = "Unknown"
            if "twitch" in parser_name.lower(): plat = "Twitch"
            elif "kick" in parser_name.lower(): plat = "Kick"
            elif "youtube" in parser_name.lower(): plat = "YouTube"

            disp_user = channel if channel and channel != "Unknown" else "System"
            if data.get("is_shared_chat"): disp_user = "ST"

            base_type = event
            additional = ""
            
            if plat == "Twitch":
                if event.startswith("Twitch "): base_type = event[7:].replace(" (irc)", "").replace(" (pubsub)", "")
                if base_type == "cheer": additional = trigger.replace("Twitch cheer ", "").strip()
                elif base_type == "redeem": additional = trigger.replace("Twitch redeem ", "").strip()
                elif base_type == "hype train": additional = trigger.replace("Twitch hype train ", "").strip()
            elif plat == "Kick":
                if event.startswith("Kick "): base_type = event[5:]
                if base_type == "redeem": additional = trigger.replace("Kick redeem ", "").strip()
                elif base_type == "raid start": base_type = "raid"
            elif plat == "YouTube":
                if event == "paid_message": base_type, additional = "super chat", trigger.replace("Super Chat: ", "").strip()
                elif event == "sticker_message": base_type, additional = "super sticker", trigger.replace("Super Sticker: ", "").strip()
                elif event == "member_message": base_type = "member"
                elif event == "chat_message": 
                    base_type = "chat"
                    additional = msg_text

                    
            # Normalize event names for Trigger Engine
            normalized_event = base_type.title()
            if base_type == "super chat": normalized_event = "Super Chat"
            if base_type == "gift sub": normalized_event = "Gift Sub"
            if base_type == "chat message" or base_type == "chat": normalized_event = "Chat Message"
            if base_type == "cheer": normalized_event = "Cheer/Bits"
            
            # The trigger processing now happens consolidated below in the triggers loop
            
            if parser_name != "local_hotkey":
                trigger = f"{plat} {disp_user} {base_type}"
                if additional: trigger += f" {additional}"

            type_allowed = True
            chat_moderate_enabled = False
            chat_tts_enabled = True
            chat_sub_cache_enabled = False

            if parser_name != "local_hotkey":
                chats = config.GLOBAL_CONFIG.get("chats", {})
                for c_id, c_data in chats.items():
                    cfg_parser = c_data.get("parser", "").lower().replace("_parse", "").replace("parser", "")
                    evt_parser = parser_name.lower().replace("_parse", "").replace("parser", "")
                    if cfg_parser == evt_parser:
                        c_in = c_data.get("input", "")
                        if c_in and (c_in.lower() == channel.lower() or c_in in channel or channel in c_in):
                            chat_moderate_enabled = c_data.get("moderate", False)
                            chat_tts_enabled = c_data.get("tts_enabled", True)
                            chat_sub_cache_enabled = c_data.get("sub_cache_enabled", False)
                            ef = c_data.get("event_filters") or c_data.get("filters")
                            if ef and isinstance(ef, dict) and event in ef and not ef[event]:
                                type_allowed = False
                            break
            
            if not type_allowed: continue

            if chat_sub_cache_enabled and username and plat in SUB_DB:
                if channel not in SUB_DB[plat]: SUB_DB[plat][channel] = {}
                cache = SUB_DB[plat][channel]
                user_lower = username.lower()
                is_sub_event = False
                if "subscriber" in data:
                    is_sub_event = bool(data["subscriber"])
                    if cache.get(user_lower) != is_sub_event:
                        cache[user_lower] = is_sub_event
                        threading.Thread(target=save_sub_cache, daemon=True).start()
                        broadcast({"type": "sub_cache", "payload": SUB_DB})
                elif base_type in ["sub", "gift sub", "member"]:
                    if cache.get(user_lower) != True:
                        cache[user_lower] = True
                        threading.Thread(target=save_sub_cache, daemon=True).start()
                        broadcast({"type": "sub_cache", "payload": SUB_DB})
                if "subscriber" not in data and user_lower in cache:
                    data["subscriber"] = cache[user_lower]
            
            if "subscriber" not in data: data["subscriber"] = "unknown"

            msg_uuid = str(uuid.uuid4())
            
            st_filters = config.GLOBAL_CONFIG.get("st_filters", {})
            st_tts_enabled, st_sammi_enabled, st_overlay_enabled, st_alerts_enabled = (
                st_filters.get("tts", False),
                st_filters.get("sammi", False),
                st_filters.get("overlay", False),
                st_filters.get("alerts", False)
            )
            is_shared = data.get("is_shared_chat", False)

            is_chat = event in ["Twitch chat", "Kick chat", "chat_message", "Twitch whisper"]
            if is_shared and not is_chat and not st_alerts_enabled:
                continue

            allow_overlay = not (is_shared and not st_overlay_enabled)
            allow_sammi = not (is_shared and not st_sammi_enabled)
            allow_tts = not (is_shared and not st_tts_enabled)

            if allow_overlay:
                if event in ["Twitch chat", "Kick chat", "chat_message", "Twitch whisper"]:
                    bc_type = "whisper" if "whisper" in event.lower() else "chat"
                    bc_payload = {
                        "type": bc_type, "trigger": event, "msg_id": msg_uuid,
                        "source": parser_name.replace("Parser", "").replace("_parse", "").capitalize(),
                        "message": data.get("message", ""), "username": data.get("username", data.get("author", "Unknown"))
                    }
                    
                    if "Twitch" in parser_name:
                         bc_payload.update({"badges": data.get("badges_html", ""), "color": data.get("color", "")})
                         c_id = data.get("source_room_id") or data.get("room_id")
                         if c_id:
                             login, url = await get_twitch_user_avatar_from_id(session, c_id)
                             if url: bc_payload["avatar"] = url
                    elif "Kick" in parser_name:
                         bc_payload.update({"badges": data.get("badges", "")})
                         if channel in KICK_AVATAR_CACHE: bc_payload["avatar"] = KICK_AVATAR_CACHE[channel]
                    elif "YouTube" in parser_name:
                         yt_avatar = await get_youtube_channel_avatar(session, channel)
                         bc_payload["avatar"] = yt_avatar if yt_avatar else data.get("image", "")
    
                    broadcast(bc_payload)
                else:
                    broadcast({"type": "alert", "source": parser_name, "event": event, "trigger": trigger, "data": data})

            sammi_payload = {
                "trigger": trigger, "msg_id": msg_uuid, "platform": plat.lower(),
                "username": username, "message": msg_text, "customData": data
            }
            # Fire Hotkeys (instantly)
            if trigger:
                from key_triggers import check_and_fire_hotkeys
                check_and_fire_hotkeys(config.GLOBAL_CONFIG, trigger, event_queue)

            # Spawn background task for Moderation, SAMMI, and TTS
            sammi_payload = {
                "trigger": trigger, "msg_id": msg_uuid, "platform": plat.lower(),
                "username": username, "message": msg_text, "customData": data
            }
            asyncio.create_task(
                handle_moderation_and_actions(
                    msg_text,
                    chat_moderate_enabled,
                    sammi_payload,
                    allow_sammi,
                    allow_tts,
                    chat_tts_enabled,
                    username,
                    data,
                    parser_name,
                    session
                )
            )
        except asyncio.CancelledError: break
        except Exception as e:
            if not STOP_EVENT.is_set(): print(f"Main Loop Error: {e}")
            await asyncio.sleep(1)

    for t in tasks: t.cancel()
    if tasks: await asyncio.gather(*tasks, return_exceptions=True)
    await session.close()


def create_image():
    icon_paths = [
        os.path.join(STATIC_DIR, 'org.theater.TheaterReader.png'),
        os.path.join(BASE_DIR, 'org.theater.TheaterReader.png'),
    ]
    for p in icon_paths:
        if os.path.exists(p):
            try:
                img = Image.open(p).convert('RGBA')
                return img.resize((64, 64), Image.Resampling.LANCZOS)
            except Exception:
                pass

    w, h = 64, 64
    image = Image.new('RGBA', (w, h), color=(0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    d.ellipse([(4, 4), (60, 60)], fill=(0, 122, 204, 255))
    d.polygon([(24, 16), (24, 48), (48, 32)], fill=(255, 255, 255, 255))
    return image


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    
    import sys

    if HAS_TRAY:
        def run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(main())
            except Exception as e:
                print(f"\n[CRITICAL] Main Loop Thread Error: {e}", flush=True)
                import traceback
                traceback.print_exc()

        threading.Thread(target=run_loop, daemon=True).start()
        
        def on_exit_click(icon, item):
            STOP_EVENT.set()
            icon.stop()
            os._exit(0)
            
        def on_open_settings(icon, item): 
            import webbrowser
            settings_path = os.path.join(STATIC_DIR, 'settings.html')
            if not os.path.exists(settings_path):
                settings_path = os.path.join(BASE_DIR, 'settings.html')
                if not os.path.exists(settings_path):
                    settings_path = os.path.join(BASE_DIR, 'dist', 'settings.html')
            webbrowser.open(f"file:///{settings_path.replace(chr(92), '/')}")


        def is_vol_checked(item): return abs(config.GLOBAL_CONFIG.get("tts", {}).get("volume", 1.0) * 100 - int(item.text.replace('%', ''))) < 1
        def set_volume(icon, item):
            if "tts" not in config.GLOBAL_CONFIG: config.GLOBAL_CONFIG["tts"] = {}
            config.GLOBAL_CONFIG["tts"]["volume"] = int(item.text.replace('%', '')) / 100.0
            try:
                save_complete_config_state(config.GLOBAL_CONFIG)
            except Exception: pass

        vol_items = [pystray.MenuItem(f"{v}%", set_volume, radio=True, checked=is_vol_checked) for v in range(100, -1, -10)]

        def is_dev_checked(item):
            dev = config.GLOBAL_CONFIG.get("tts", {}).get("device_id", "")
            if item.text == "System Default": return dev == ""
            return dev == item.text

        def set_device(icon, item):
            if "tts" not in config.GLOBAL_CONFIG: config.GLOBAL_CONFIG["tts"] = {}
            config.GLOBAL_CONFIG["tts"]["device_id"] = "" if item.text == "System Default" else item.text
            try:
                save_complete_config_state(config.GLOBAL_CONFIG)
            except Exception: pass

        try:
            from websocket_server import _get_audio_devices
            dev_items = [pystray.MenuItem("System Default", set_device, radio=True, checked=is_dev_checked)]
            for d in _get_audio_devices(): dev_items.append(pystray.MenuItem(d, set_device, radio=True, checked=is_dev_checked))
        except Exception as e:
            print(f"[Tray] Could not load audio devices: {e}")
            dev_items = [pystray.MenuItem("Error Loading Devices", None, enabled=False)]

        menu = pystray.Menu(
            pystray.MenuItem("Open Settings", on_open_settings),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Output Sound", pystray.Menu(*dev_items)),
            pystray.MenuItem("Volume", pystray.Menu(*vol_items)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", on_exit_click)
        )
        
        # Monkey-patch pystray to open the tray icon menu on left-click as well on Windows
        if hasattr(pystray, '_win32'):
            original_on_notify = pystray._win32.Icon._on_notify
            def custom_on_notify(self, wparam, lparam):
                win32_mod = pystray._win32.win32
                if lparam == win32_mod.WM_LBUTTONUP:
                    lparam = win32_mod.WM_RBUTTONUP
                original_on_notify(self, wparam, lparam)
            pystray._win32.Icon._on_notify = custom_on_notify

        TRAY_ICON = pystray.Icon("Theater", create_image(), "Theater", menu)
        TRAY_ICON.run()
    else:
        try: asyncio.run(main())
        except KeyboardInterrupt:
            STOP_EVENT.set()
