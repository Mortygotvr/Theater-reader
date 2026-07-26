// --- settings-core.js --- //
window.ws = null;
let config = {};

function trackingLog(msg) {
    console.log(msg);
}

// Bulletproof Modular Registry
if (!window.configLoaders || Array.isArray(window.configLoaders)) {
    const oldList = Array.isArray(window.configLoaders) ? window.configLoaders : [];
    window.configLoaders = {
        _list: oldList,
        push: function(fn) {
            this._list.push(fn);
            if (window.lastReceivedConfig) {
                console.log("[Core] Self-triggering late loader...");
                try { fn(window.lastReceivedConfig); } catch(e) { console.error(e); }
            }
        },
        forEach: function(callback) {
            this._list.forEach(callback);
        }
    };
}
window.configSavers = window.configSavers || [];
window.lastReceivedConfig = window.lastReceivedConfig || null;
window.messageListeners = window.messageListeners || {};

function addMessageListener(type, fn) {
    if (!window.messageListeners[type]) window.messageListeners[type] = [];
    window.messageListeners[type].push(fn);
}
window.addMessageListener = addMessageListener;

function connect() {
    window.ws = new WebSocket("ws://127.0.0.1:41837");
    const status = document.getElementById('wsStatus');
    window.ws.onopen = () => {
        status.innerText = "Connected";
        status.style.background = "#2e7d32";
        // WATERFALL STEP 1: Ask for OBS data and Config state
        window.ws.send(JSON.stringify({type: "request_initial_obs"}));
        window.ws.send(JSON.stringify({type: "request_config_state"}));
        fetchPiperVoices();
    };
    window.ws.onmessage = (e) => {
        const data = JSON.parse(e.data);
        
        // Registry based dispatch
        if (window.messageListeners[data.type]) {
            window.messageListeners[data.type].forEach(fn => {
                try { fn(data.payload); } catch(err) { console.error("Listener error:", err); }
            });
        }

        if(data.type === "config_state") loadConfig(data.payload);
        if(data.type === "tts_info") loadTTSInfo(data.payload);
        if(data.type === "ffplay_installed") {
            const btn = document.getElementById('btn_install_ffplay');
            if (btn) btn.innerText = "Installed!";
            setTimeout(() => {
                const box = document.getElementById('ffplay_install_box');
                if(box) box.style.display = 'none';
            }, 2000);
        }
        if(data.type === "piper_installed") {
            const btn = document.getElementById('btn_install_piper_core');
            if (btn) btn.innerText = "Installed!";
            setTimeout(() => {
                const box = document.getElementById('piper_install_box');
                if(box) box.style.display = 'none';
            }, 2000);
        }
        if(data.type === "linux_input_authorized") {
            const btn = document.getElementById('btn_authorize_linux_input');
            if (btn) btn.innerText = "Permissions Granted!";
            alert(data.message || "Permissions granted! Please log out and back in for changes to apply.");
            setTimeout(() => {
                const box = document.getElementById('linux_permissions_box');
                if(box) box.style.display = 'none';
            }, 2000);
        }

        if(data.type === "voice_installed") {
            const btn = document.getElementById('btn_install_voice');
            if (btn) {
                btn.innerText = "Installed!!!";
                setTimeout(() => {
                    btn.innerText = "Install Voice";
                    btn.disabled = false;
                }, 2000);
            }
        }
        if(data.type === "status") {
            document.getElementById('status-msg').innerText = data.message;
            setTimeout(() => document.getElementById('status-msg').innerText = "", 3000);
        }
        if (data.type === "piper_voices_list_result") {
            let sel = document.getElementById("hf_voices_list");
            sel.innerHTML = "";
            currentHfVoices = {};
            if (!data.payload || data.payload.length === 0) {
                sel.innerHTML = '<option value="">No voices found.</option>';
                return;
            }
            data.payload.forEach(v => {
                currentHfVoices[v.key] = v;
                let opt = document.createElement("option");
                opt.value = v.key;
                opt.innerText = v.display;
                sel.appendChild(opt);
            });
            document.getElementById('status-msg').innerText = `Loaded ${data.payload.length} voices.`;
        }
        if (data.type === "obs_info") {
            obsScenes = data.payload.scenes || data.scenes || [];
            obsSources = data.payload.sources || data.sources || [];
            obsSceneItemsMap = data.payload.sceneItemsMap || data.sceneItemsMap || {};
            if (typeof obsLog === 'function') obsLog(`Fetched ${obsScenes.length} scenes and ${obsSources.length} sources from OBS.`);
            if (typeof obsUpdateDot === 'function') obsUpdateDot(true);
            const statusText = document.getElementById('obs-status-text');
            if (statusText) statusText.innerText = "Connected";
            if (typeof obsRenderTriggers === 'function') obsRenderTriggers();
        }
        if (data.type === "obs_error") {
            if (typeof obsLog === 'function') obsLog(`Error: ${data.message || data.payload?.message || "Check connection details."}`, true);
            if (typeof obsUpdateDot === 'function') obsUpdateDot(false);
            const statusText = document.getElementById('obs-status-text');
            if (statusText) statusText.innerText = "Disconnected";
        }
        if (data.type === "obs_log") {
            if (typeof obsLog === 'function') obsLog(data.message);
        }
        if (data.type === "sys_diag" && data.source === "KeyTriggers") {
            const tw = document.getElementById("key-log-window");
            if(tw) {
                const div = document.createElement("div");
                div.style.marginBottom = "4px";
                div.innerText = `[${new Date().toLocaleTimeString()}] ${data.message}`;
                tw.prepend(div);
                if(tw.childNodes.length > 50) tw.removeChild(tw.lastChild);
            }
        }
    };
    window.ws.onclose = () => {
        status.innerText = "Disconnected";
        status.style.background = "#c62828";
        setTimeout(connect, 2000);
    };
}

function loadConfig(data) {
    console.log("[Core] Received config state:", data);
    window.lastReceivedConfig = data;
    config = data;
    
    // Core Loaders
    loadChats(data);
    loadSammi(data);
    loadHotkeys(data);
    loadModeration(data);
    loadTTS(data);
    loadGeneral(data);

    // Call registered external loaders
    window.configLoaders.forEach(fn => {
        try { fn(data); } catch(e) { console.error("External loader error:", e); }
    });
}

function loadChats(data) {
    const container = document.getElementById('zones_container');
    if (!container) return;
    
    // Forced clearing
    container.innerHTML = "";
    
    const chats = data.chats || data.chat_zones || {};
    const entries = Object.entries(chats);
    
    // Assuming trackingLog is available or logging via console
    console.log(`Loading ${entries.length} Chat Zones...`);
    
    for (let i = 0; i < entries.length; i++) {
        const [id, z] = entries[i];
        renderZone(id, z.parser, z.input || "", z.event_filters || z.filters || {}, !!z.moderate, z.tts_enabled !== false, !!z.sub_cache_enabled);
    }
}

function loadSammi(data) {
    const s = data.sammi || {};
    const url = document.getElementById('sammi_url');
    const pass = document.getElementById('sammi_password');
    const enabled = document.getElementById('sammi_enabled');
    
    if (url) url.value = s.sammi_url || "";
    if (pass) pass.value = s.sammi_password || "";
    if (enabled) enabled.checked = s.sammi_enabled !== false;
    
    const f = data.st_filters || {};
    const fTts = document.getElementById('st_tts_enabled');
    const fSammi = document.getElementById('st_sammi_enabled');
    const fOverlay = document.getElementById('st_overlay_enabled');
    const fAlerts = document.getElementById('st_alerts_enabled');
    
    if (fTts) fTts.checked = f.tts !== false;
    if (fSammi) fSammi.checked = f.sammi !== false;
    if (fOverlay) fOverlay.checked = f.overlay !== false;
    if (fAlerts) fAlerts.checked = f.alerts !== false;
}

function loadHotkeys(data) {
    const hkContainer = document.getElementById('hotkeys_container');
    const k2tContainer = document.getElementById('key_to_trigger_container');
    const toggle = document.getElementById('enable_hotkeys');

    if (toggle) toggle.checked = !!data.enable_hotkeys;

    if (hkContainer) {
        hkContainer.innerHTML = "";
        const hks = data.hotkeys || [];
        for (let i = 0; i < hks.length; i++) {
            const hk = hks[i];
            renderHotkey(Date.now() + i, hk.trigger, !!hk.ctrl, !!hk.alt, !!hk.shift, hk.key, hk.delay || 0);
        }
    }

    if (k2tContainer) {
        k2tContainer.innerHTML = "";
        const k2ts = data.key_to_triggers || [];
        for (let i = 0; i < k2ts.length; i++) {
            const k = k2ts[i];
            renderKeyToTrigger(Date.now() + i, k.trigger, !!k.ctrl, !!k.alt, !!k.shift, k.key, k.delay || 0);
        }
    }
}

function loadModeration(data) {
    const m = data.moderation || {};
    const regex = document.getElementById('regex_link_enabled');
    const vader = document.getElementById('vader_enabled');
    const vThresh = document.getElementById('vader_threshold');
    const ollama = document.getElementById('ollama_enabled');
    const oUrl = document.getElementById('ollama_url');
    const oModel = document.getElementById('ollama_model');
    const oPrompt = document.getElementById('ollama_prompt');

    if (regex) regex.checked = m.regex_link_enabled !== false;
    if (vader) vader.checked = m.vader_enabled || false;
    if (vThresh) vThresh.value = m.vader_threshold || -0.5;
    if (ollama) ollama.checked = m.ollama_enabled || false;
    if (oUrl) oUrl.value = m.ollama_url || "http://localhost:11434";
    if (oModel) oModel.value = m.ollama_model || "llama3";
    if (oPrompt) oPrompt.value = m.ollama_prompt || "";
}

function loadTTS(data) {
    const t = data.tts || {};
    const enabled = document.getElementById('tts_enabled');
    const rate = document.getElementById('tts_rate');
    const voice = document.getElementById('tts_voice_id');
    const device = document.getElementById('tts_device_id');
    const readUser = document.getElementById('tts_read_user');
    const noCmd = document.getElementById('tts_ignore_commands');
    const noEmote = document.getElementById('tts_ignore_emotes');
    const noUrl = document.getElementById('tts_ignore_urls');
    const clean = document.getElementById('tts_only_clean');
    const maxLen = document.getElementById('tts_max_length');
    const nonSubs = document.getElementById('tts_allow_non_subs');
    const subs = document.getElementById('tts_allow_subs');
    const vips = document.getElementById('tts_allow_vips');
    const mods = document.getElementById('tts_allow_mods');
    const bell = document.getElementById('tts_play_bell');
    const bellPath = document.getElementById('tts_custom_bell_path');
    const ignored = document.getElementById('tts_ignored_users');

    if (enabled) enabled.checked = !!t.enabled;
    if (rate) rate.value = t.rate || 200;
    if (voice) voice.value = t.voice_id || "";
    if (device) device.value = t.device_id || "";
    if (readUser) readUser.checked = !!t.read_username;
    if (noCmd) noCmd.checked = t.ignore_commands !== false;
    if (noEmote) noEmote.checked = t.ignore_emotes !== false;
    if (noUrl) noUrl.checked = t.ignore_urls !== false;
    if (clean) clean.checked = t.only_clean !== false;
    if (maxLen) maxLen.value = t.max_length !== undefined ? t.max_length : 200;
    if (nonSubs) nonSubs.checked = t.allow_non_subs !== false;
    if (subs) subs.checked = t.allow_subs !== false;
    if (vips) vips.checked = t.allow_vips !== false;
    if (mods) mods.checked = t.allow_mods !== false;
    if (bell) bell.checked = !!t.play_bell;
    if (bellPath) bellPath.value = t.custom_bell_path || "";
    if (ignored) ignored.value = t.ignored_users ? t.ignored_users.join(", ") : "";
}

function loadGeneral(data) {
    const g = data.general || {};
    const min = document.getElementById('theater-start-minimized');
    if (min) min.checked = !!g.start_minimized;
    
    const obs = data.obs_bridge || {};
    const obsUrl = document.getElementById('obs_url');
    const obsPass = document.getElementById('obs_pass');
    if (obsUrl) obsUrl.value = obs.obs_url || obs.url || "ws://127.0.0.1:4455";
    if (obsPass) obsPass.value = obs.obs_pass || obs.password || "";
}

// loadOBSBridge removed and moved to settings-targets.js

function saveConfiguration() {
    try {
        trackingLog("!!! SAVE INITIATED !!!");
        if (typeof obsSaveState === "function") try { obsSaveState(); } catch(e) {}
        
        const newConfig = { ...config };
        
        // Core Savers
        newConfig.chats = extractChats();
        newConfig.key_to_triggers = extractKeysToTriggers();
        newConfig.hotkeys = extractHotkeys();
        newConfig.enable_hotkeys = document.getElementById('enable_hotkeys')?.checked || false;
        
        newConfig.st_filters = {
            tts: document.getElementById('st_tts_enabled')?.checked || false,
            sammi: document.getElementById('st_sammi_enabled')?.checked || false,
            overlay: document.getElementById('st_overlay_enabled')?.checked || false,
            alerts: document.getElementById('st_alerts_enabled')?.checked || false
        };

        newConfig.sammi = {
            sammi_url: document.getElementById('sammi_url')?.value || "",
            sammi_password: document.getElementById('sammi_password')?.value || "",
            sammi_enabled: document.getElementById('sammi_enabled')?.checked || false
        };

        newConfig.moderation = {
            regex_link_enabled: document.getElementById('regex_link_enabled')?.checked || false,
            vader_enabled: document.getElementById('vader_enabled')?.checked || false,
            vader_threshold: parseFloat(document.getElementById('vader_threshold')?.value || 0),
            ollama_enabled: document.getElementById('ollama_enabled')?.checked || false,
            ollama_url: document.getElementById('ollama_url')?.value || "",
            ollama_model: document.getElementById('ollama_model')?.value || "",
            ollama_prompt: document.getElementById('ollama_prompt')?.value || ""
        };

        newConfig.tts = {
            enabled: document.getElementById('tts_enabled')?.checked || false,
            rate: parseInt(document.getElementById('tts_rate')?.value || 200),
            voice_id: document.getElementById('tts_voice_id')?.value || "",
            device_id: document.getElementById('tts_device_id')?.value || "",
            read_username: document.getElementById('tts_read_user')?.checked || false,
            ignore_commands: document.getElementById('tts_ignore_commands')?.checked || false,
            ignore_emotes: document.getElementById('tts_ignore_emotes')?.checked || false,
            ignore_urls: document.getElementById('tts_ignore_urls')?.checked || false,
            only_clean: document.getElementById('tts_only_clean')?.checked || false,
            max_length: parseInt(document.getElementById('tts_max_length')?.value || 200),
            allow_non_subs: document.getElementById('tts_allow_non_subs')?.checked || false,
            allow_subs: document.getElementById('tts_allow_subs')?.checked || false,
            allow_vips: document.getElementById('tts_allow_vips')?.checked || false,
            allow_mods: document.getElementById('tts_allow_mods')?.checked || false,
            ignored_users: document.getElementById('tts_ignored_users')?.value.split(',').map(s => s.trim()).filter(s => s) || [],
            play_bell: document.getElementById('tts_play_bell')?.checked || false,
            custom_bell_path: document.getElementById('tts_custom_bell_path')?.value || ""
        };

        newConfig.general = {
            start_minimized: document.getElementById('theater-start-minimized')?.checked || false
        };

        const obsUrlVal = document.getElementById('obs_url')?.value || "ws://127.0.0.1:4455";
        const obsPassVal = document.getElementById('obs_pass')?.value || "";
        let parsedIp = "127.0.0.1";
        let parsedPort = "4455";
        try {
            const urlObj = new URL(obsUrlVal.replace("ws://", "http://").replace("wss://", "https://"));
            parsedIp = urlObj.hostname || "127.0.0.1";
            parsedPort = urlObj.port || "4455";
        } catch(e) {
            const match = obsUrlVal.match(/wss?:\/\/([^\/:]+)(?::(\d+))?/);
            if (match) {
                parsedIp = match[1];
                if (match[2]) parsedPort = match[2];
            }
        }
        newConfig.obs_bridge = {
            ...(newConfig.obs_bridge || {}),
            obs_url: obsUrlVal,
            obs_pass: obsPassVal,
            ip: parsedIp,
            port: parsedPort,
            password: obsPassVal
        };

        // Call registered external savers
        window.configSavers.forEach(fn => {
            try { fn(newConfig); } catch(e) { 
                trackingLog("CRITICAL SAVER ERROR: " + e);
                console.error("External saver error:", e); 
            }
        });

        // Log the camera_tracking part specifically for visibility
        if (newConfig.camera_tracking) {
            const ct = newConfig.camera_tracking;
            const msg = `[FinalPayload] Avatar=${ct.avatar_source}, Active=${ct.active_scene}, Secondaries=${JSON.stringify(ct.secondary_sources)}`;
            trackingLog(msg);
        }

        window.ws.send(JSON.stringify({type: "save_config", payload: newConfig}));
        document.getElementById('status-msg').innerText = "Configuration Saved! Reloading Listeners...";
        document.getElementById('status-msg').style.color = "#4caf50";
    } catch(err) {
        trackingLog("GLOBAL SAVE ERROR: " + err);
        document.getElementById('status-msg').innerText = "SAVE FAILED: " + err;
        document.getElementById('status-msg').style.color = "#ff4444";
    }
}


function extractChats() {
    const zones = {};
    document.querySelectorAll('.zone-card').forEach((el) => {
         if(el.classList.contains('hotkey-card') || el.classList.contains('key-to-trigger-card')) return;
         const parser = el.querySelector('select').value;
         const input = el.querySelector('input[type="text"]').value;
         const moderate = el.querySelector('.mod-checkbox').checked;
         const tts_enabled = el.querySelector('.tts-checkbox')?.checked ?? true;
         const sub_cache_enabled = el.querySelector('.sub-cache-checkbox')?.checked ?? false;
         const filters = {};
         el.querySelectorAll('.filter-grid input[type="checkbox"]').forEach(chk => {
             filters[chk.dataset.event] = chk.checked;
         });
         zones[el.id] = { parser, input, moderate, tts_enabled, sub_cache_enabled, filters, event_filters: filters };
    });
    return zones;
}

function extractKeysToTriggers() {
    const list = [];
    document.querySelectorAll('.key-to-trigger-card').forEach((el) => {
        list.push({
            trigger: el.querySelector('.k2t-trigger').value.trim(),
            ctrl: el.querySelector('.k2t-ctrl').checked,
            alt: el.querySelector('.k2t-alt').checked,
            shift: el.querySelector('.k2t-shift').checked,
            key: el.querySelector('select.k2t-key').value, 
            delay: parseInt(el.querySelector('.k2t-delay').value) || 0
        });
    });
    return list;
}

function extractHotkeys() {
    const list = [];
    document.querySelectorAll('.hotkey-card').forEach((el) => {
        list.push({
            trigger: el.querySelector('.hk-trigger').value.trim(),                 
            ctrl: el.querySelector('.hk-ctrl').checked,                 
            alt: el.querySelector('.hk-alt').checked,                 
            shift: el.querySelector('.hk-shift').checked,                 
            key: el.querySelector('select.hk-key').value, 
            delay: parseInt(el.querySelector('.hk-delay').value) || 0
        });
    });
    return list;
}

// Init
window.addEventListener("DOMContentLoaded", () => {
    connect();
});