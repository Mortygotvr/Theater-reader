import os
import sys
import json
import threading


def get_base_path():
    try:
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        else:
            return os.path.dirname(os.path.abspath(__file__))
    except Exception:
        return os.getcwd()

def get_static_path():
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        return sys._MEIPASS
    return get_base_path()

BASE_DIR = get_base_path()
STATIC_DIR = get_static_path()

def get_user_data_dir():
    if os.access(BASE_DIR, os.W_OK):
        return BASE_DIR
    xdg_config = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
    user_dir = os.path.join(xdg_config, "TheaterReader")
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

USER_DATA_DIR = get_user_data_dir()
CONFIG_FILE = os.path.join(USER_DATA_DIR, "config.json")
SUB_CACHE_FILE = os.path.join(USER_DATA_DIR, "sub_cache.json")



# Global Databases
BADGE_DB = {}
SUB_DB = {"Twitch": {}, "Kick": {}, "YouTube": {}}

# Control Flags
STOP_EVENT = threading.Event()

# These will be updated dynamically
GLOBAL_CONFIG = {}
RELOAD_CONFIG_ID = 0
CONFIG_LOCK = threading.Lock()

# SAMMI Globals
SAMMI_URL = "http://localhost:9450/webhook"
SAMMI_PASS = None

def load_sammi_settings():
    global SAMMI_URL, SAMMI_PASS
    try:
        sammi = GLOBAL_CONFIG.get("sammi", {})
        SAMMI_URL = sammi.get("sammi_url", SAMMI_URL)
        SAMMI_PASS = sammi.get("sammi_password", None)
        print(f"[SAMMI] Settings loaded. URL: {SAMMI_URL}")
    except Exception as e:
        print(f"[SAMMI] Error loading settings: {e}")

def load_sub_cache():
    global SUB_DB
    try:
        if os.path.exists(SUB_CACHE_FILE):
            with open(SUB_CACHE_FILE, "r") as f:
                data = json.load(f)
                for plat in ["Twitch", "Kick", "YouTube"]:
                    plat_data = data.get(plat, {})
                    is_flat = any(isinstance(v, bool) for v in plat_data.values()) if plat_data else False
                    if is_flat:
                        SUB_DB[plat] = {"Default_Migrated_Channel": plat_data}
                    else:
                        SUB_DB[plat] = plat_data
            
            count = sum(sum(len(channel_db) for channel_db in db.values()) for db in SUB_DB.values())
            print(f"[SubCache] Loaded {count} cached sub records.")
    except Exception as e:
        print(f"[SubCache] Error loading sub cache: {e}")

def save_sub_cache():
    try:
        with open(SUB_CACHE_FILE, "w") as f:
            json.dump(SUB_DB, f, indent=4)
    except Exception as e:
        print(f"[SubCache] Error saving cache: {e}")

def load_complete_config_state():
    with CONFIG_LOCK:
        return _load_complete_config_state_impl()

def _load_complete_config_state_impl():
    global GLOBAL_CONFIG
    
    # Capture live data from memory before loading from disk
    try:
        live_scenes = GLOBAL_CONFIG.get("obs_scenes", [])
        live_sources = GLOBAL_CONFIG.get("obs_sources", [])
        live_filters = GLOBAL_CONFIG.get("obs_filters", {})
    except Exception:
        live_scenes, live_sources, live_filters = [], [], {}

    state = {
        "sammi": {"sammi_url": "http://localhost:9450/webhook", "sammi_password": "", "sammi_enabled": True},
        "chats": {},
        "moderation": {
            "vader_enabled": False,
            "vader_threshold": -0.5,
            "ollama_enabled": False,
            "ollama_url": "http://localhost:11434",
            "ollama_model": "llama3",
            "ollama_prompt": 'Analyze the following chat message. If it contains hate speech, severe toxicity, or spam, reply with "FLAGGED". Otherwise, reply with "CLEAN".'
        },
        "tts": {"enabled": False, "rate": 200, "ignore_commands": True, "read_username": False, "voice_id": ""},
        "key_to_triggers": [],
        "obs_bridge": {"obs_url": "ws://localhost:4455", "obs_pass": "", "enabled": True},
        "hotkeys_enabled": False,
        "obs_sources": live_sources,
        "obs_scenes": live_scenes,
        "obs_filters": live_filters,
        "camera_tracking": {
            "avatar_source": "",
            "active_scene": "",
            "mode": "brightness",
            "threshold": 40,
            "chroma_r": 0,
            "chroma_g": 255,
            "chroma_b": 0,
            "secondary_sources": [],
            "fps_limit": 30
        },
        "st_filters": {"tts": False, "sammi": False, "overlay": False, "alerts": False}
    }
    
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding='utf-8') as f:
                data = json.load(f)
                
                # Bulk update from file
                for key in data:
                    state[key] = data[key]
                
                # Ensure we didn't overwrite the live OBS lists with empty ones from disk
                if not state.get("obs_scenes") and live_scenes: state["obs_scenes"] = live_scenes
                if not state.get("obs_sources") and live_sources: state["obs_sources"] = live_sources
                if not state.get("obs_filters") and live_filters: state["obs_filters"] = live_filters
                
                if "zones" in data and "chats" not in data:
                    state["chats"] = data["zones"]
                    
        except Exception as e:
            print(f"!!! CRITICAL LOAD ERROR in config.py: {e}", flush=True)
    else:
        try:
            print(f"[CONFIG] Initializing new default configuration at {CONFIG_FILE}")
            _save_complete_config_state_impl(state)
        except Exception as save_err:
            print(f"[CONFIG] Warning saving initial default config: {save_err}")

            
    GLOBAL_CONFIG.clear()
    GLOBAL_CONFIG.update(state)
    return GLOBAL_CONFIG

def save_complete_config_state(new_state):
    with CONFIG_LOCK:
        return _save_complete_config_state_impl(new_state)

def _save_complete_config_state_impl(new_state):
    try:
        BACKEND_KEYS = {
            "sammi", "chats", "zones", "moderation", "tts", "key_to_triggers",
            "obs_bridge", "hotkeys_enabled", "enable_hotkeys", "hotkeys",
            "obs_sources", "obs_scenes", "obs_filters", "camera_tracking",
            "st_filters", "general", "gpu_acceleration", "targets"
        }
        
        # Save only backend-specific configuration keys to config.json
        filtered_state = {k: v for k, v in new_state.items() if k in BACKEND_KEYS}
        
        with open(CONFIG_FILE, "w", encoding='utf-8') as f:
            json.dump(filtered_state, f, indent=4)
        
        global SAMMI_URL, SAMMI_PASS
        sammi = new_state.get("sammi", {})
        SAMMI_URL = sammi.get("sammi_url", SAMMI_URL)
        SAMMI_PASS = sammi.get("sammi_password", SAMMI_PASS)
        
    except Exception as e:
        print(f"[CONFIG] Error saving config: {e}", flush=True)
