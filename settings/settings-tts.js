// --- settings-tts.js --- //
let currentHfVoices = {};

function loadTTSInfo(info) {
    if (info.has_ffplay) {
        const ffbox = document.getElementById("ffplay_install_box");
        if (ffbox) ffbox.style.display = "none";
    } else {
        const ffbox = document.getElementById("ffplay_install_box");
        if (ffbox) ffbox.style.display = "block";
    }

    if (info.has_piper) {
        const piperbox = document.getElementById("piper_install_box");
        if (piperbox) piperbox.style.display = "none";
    } else {
        const piperbox = document.getElementById("piper_install_box");
        if (piperbox) piperbox.style.display = "block";
    }

    if (info.linux_input_permission_needed) {
        const pbox = document.getElementById("linux_permissions_box");
        if (pbox) pbox.style.display = "block";
    } else {
        const pbox = document.getElementById("linux_permissions_box");
        if (pbox) pbox.style.display = "none";
    }



    const voiceSelect = document.getElementById('tts_voice_id');

    // Clear existing options except default
    voiceSelect.innerHTML = '<option value="">Default Voice</option>';

    // Populate voices
    if (info.voices && info.voices.length > 0) {
        info.voices.forEach(v => {
            const opt = document.createElement('option');
            opt.value = v.id;
            opt.text = v.name;
            voiceSelect.appendChild(opt);
        });
    }

    const deviceSelect = document.getElementById('tts_device_id');
    if (deviceSelect) {
        // Clear existing options except default
        deviceSelect.innerHTML = '<option value="">System Default</option>';

        // Populate devices
        if (info.devices && info.devices.length > 0) {
            info.devices.forEach(d => {
                const opt = document.createElement('option');
                opt.value = d.id;
                opt.text = d.name;
                deviceSelect.appendChild(opt);
            });
        }
    }

    // Restore selections from config if they exist
    if (config && config.tts) {
        if (config.tts.voice_id) voiceSelect.value = config.tts.voice_id;
        if (config.tts.device_id && deviceSelect) deviceSelect.value = config.tts.device_id;
    }
}

function installPiper() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        alert("Not connected to background app!");
        return;
    }
    if(confirm("Are you sure you want to download Piper TTS Core? It will be downloaded securely from trusted external repositories directly into the StreamerAssistant folder.")) {
        ws.send(JSON.stringify({type: "install_piper"}));
        document.getElementById('status-msg').innerText = "Starting Piper install...";
        const btn = document.getElementById('btn_install_piper_core');
        if (btn) {
            btn.disabled = true;
            btn.innerText = "Installing...";
        }
    }
}

function fetchPiperVoices() {
    if(!ws) return;
    document.getElementById("hf_voices_list").innerHTML = '<option>Loading...</option>';
    ws.send(JSON.stringify({type: "get_piper_voices"}));
    document.getElementById('status-msg').innerText = "Fetching voice list...";
}

function installSelectedPiperVoice() {
    let sel = document.getElementById("hf_voices_list");
    let key = sel.value;
    if(!key || !currentHfVoices[key]) {
        alert("Please select a valid voice from the list first.");
        return;
    }
    if(confirm("Download voice " + key + "? This may take a minute depending on your connection.")) {
        ws.send(JSON.stringify({
            type: "install_piper_voice", voice_key: key, files: currentHfVoices[key].files
        }));
        const btn = document.getElementById('btn_install_voice');
        if (btn) {
            btn.disabled = true;
            btn.innerText = "Installing...";
        }
    }
}

function cleanupPiperVoices() {
    if(!ws) return;
    let currentVoice = document.getElementById('tts_voice_id').value;
    if(!currentVoice) {
        alert("No current active voice selected to keep!");
        return;
    }
    if(confirm("Delete all voices in 'piper' folder EXCEPT \"" + currentVoice + "\"?")) {
        ws.send(JSON.stringify({type: "cleanup_piper_voices", keep_voice_id: currentVoice}));
    }
}

function installFFplay() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        alert("Not connected to background app!");
        return;
    }
    if (confirm("Are you sure you want to download FFplay? It will be downloaded securely from a trusted external source directly into the StreamerAssistant folder.")) {
        ws.send(JSON.stringify({ type: "install_ffplay" }));
        document.getElementById('status-msg').innerText = "Starting install process...";
        const btn = document.getElementById('btn_install_ffplay');
        if (btn) {
            btn.disabled = true;
            btn.innerText = "Installing...";
        }
    }
}

function authorizeLinuxInputPermissions() {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        alert("Not connected to background application!");
        return;
    }
    if (confirm("This will trigger a system authorization window to add your user account to the 'input' group for global hotkeys.\n\nNote: After granting permission, you MUST log out and log back in (or reboot) for changes to take effect. Continue?")) {
        ws.send(JSON.stringify({ type: "authorize_linux_input" }));
        document.getElementById('status-msg').innerText = "Opening OS Authorization Window...";
        const btn = document.getElementById('btn_authorize_linux_input');
        if (btn) {
            btn.disabled = true;
            btn.innerText = "Authorizing...";
        }
    }
}