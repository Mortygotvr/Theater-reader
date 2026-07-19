// --- settings-obs.js --- //
const OBS_STORAGE_KEY = "obs_bridge_config";
let obsConfig = {
    enabled: true, url: "ws://127.0.0.1:4455", password: "", start_minimized: false, triggers: [
        { id: 1, event: "Twitch * sub", scene: "", source: "SubAlert", duration: 5000, textScene: "", textSource: "", textPayload: "{username}" }
    ]
};
let obsScenes = [];
let obsSources = [];
let obsSceneItemsMap = {};

function obsLog(msg, isError = false) {
    const tw = document.getElementById("obs-log-window");
    if(!tw) return;
    const div = document.createElement("div");
    div.style.color = isError ? "#ff5252" : "#a8ccae";
    div.innerText = `[${new Date().toLocaleTimeString()}] ${msg}`;
    tw.prepend(div);
    if(tw.childNodes.length > 50) tw.removeChild(tw.lastChild);
}

function obsSaveState() {
    if (typeof obsSaveTriggersToMemory === "function") {
        obsSaveTriggersToMemory();
    }
    
    const enabledCheckbox = document.getElementById("obs-enabled");
    if (enabledCheckbox) obsConfig.enabled = enabledCheckbox.checked;
    
    obsConfig.url = document.getElementById("obs-url").value;
    obsConfig.password = document.getElementById("obs-pass").value;
    
    const minCheckbox = document.getElementById("obs-start-minimized");
    if (minCheckbox) {
        obsConfig.start_minimized = minCheckbox.checked;
    }
    
    try {
        localStorage.setItem(OBS_STORAGE_KEY, JSON.stringify(obsConfig));
    } catch (e) {
        console.warn("Unable to save OBS config to localStorage:", e);
    }
    
    // Also push standard updates to background server so Python knows
    if (typeof ws !== 'undefined' && ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ 
            type: "update_obs_config", 
            payload: {
                enabled: obsConfig.enabled,
                obs_url: obsConfig.url,
                obs_pass: obsConfig.password,
                start_minimized: obsConfig.start_minimized,
                triggers: obsConfig.triggers
            } 
        }));
    }
}

function obsLoadState() {
    let stored = null;
    try {
        stored = localStorage.getItem(OBS_STORAGE_KEY);
    } catch (e) {
        console.warn("Unable to read OBS config from localStorage:", e);
    }
    if (stored) {
        try {
            const parsed = JSON.parse(stored);
            if(parsed.enabled === undefined) parsed.enabled = true;
            if(!parsed.url) parsed.url = "ws://127.0.0.1:4455";
            if(parsed.start_minimized === undefined) parsed.start_minimized = false;
            if(!parsed.triggers) parsed.triggers = [];
            parsed.triggers = parsed.triggers.map((t, idx) => ({
                id: t.id || idx + 1, 
                event: t.event || t.trigger || "", 
                scene: t.scene || "", 
                source: t.source || "", 
                textScene: t.textScene || "", 
                textSource: t.textSource || "", 
                duration: t.duration || 5000, 
                textPayload: t.textPayload !== undefined ? t.textPayload : (t.textContent || "{username} triggered an event!"), 
                ...t
            }));
            obsConfig = parsed;
        } catch(e) { console.error("Could not parse obs bridge config", e); }
    }
    
    const enabledCheckbox = document.getElementById("obs-enabled");
    if (enabledCheckbox) {
        enabledCheckbox.checked = !!obsConfig.enabled;
    }
    
    document.getElementById("obs-url").value = obsConfig.url || "";
    document.getElementById("obs-pass").value = obsConfig.password || "";
    
    const minCheckbox = document.getElementById("obs-start-minimized");
    if (minCheckbox) {
        minCheckbox.checked = !!obsConfig.start_minimized;
    }
    
    obsRenderTriggers();
}

function obsUpdateDot(connected) {
    const dot = document.getElementById("obs-dot");
    if(!dot) return;
    if (connected) {
        dot.classList.remove("disconnected");
        dot.classList.add("connected");
    } else {
        dot.classList.remove("connected");
        dot.classList.add("disconnected");
    }
}

async function obsConnectOBS() {
    const btn = document.getElementById("btn-obs-connect");
    if(btn) btn.disabled = true;
    obsSaveState();
    saveConfiguration();
    
    obsLog(`Requested OBS info from backend for ${obsConfig.url}...`);
    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: "fetch_obs_info", payload: obsConfig }));
    } else {
        obsLog("Background server websocket not connected.", true);
    }

    setTimeout(() => { if(btn) btn.disabled = false; }, 2000);
}

function obsAddTriggerRow() {
    const newId = Date.now();
    obsConfig.triggers.push({ id: newId, event: "", scene: "", source: "", duration: 5000, textScene: "", textSource: "", textPayload: "{username}" });
    obsRenderTriggers();
}

function obsRemoveTriggerRow(id) {
    obsConfig.triggers = obsConfig.triggers.filter(t => t.id !== id);
    obsRenderTriggers();
}

function obsRenderTriggers() {
    const container = document.getElementById("triggers-container");
    if(!container) return;
    container.innerHTML = "";

    let sceneOptions = '<option value="">-- Current Scene --</option>';
    obsScenes.forEach(s => { sceneOptions += `<option value="${s.replace(/"/g, '&quot;')}">${s}</option>`; });

    obsConfig.triggers.forEach(t => {
        const tDiv = document.createElement("div");
        tDiv.className = "trigger-row";
        tDiv.id = `trigger-${t.id}`;
        tDiv.className = "trigger-row trigger-card";

        tDiv.innerHTML = `
<div class="trigger-row-top" style="display: flex; flex-wrap: wrap; gap: 10px; align-items: start; width: 100%; box-sizing: border-box;">
<div>
                    <label class="obs-label">Trigger Pattern(s) <small style="color:#aaa;">(comma-separated)</small></label>
                    <input type="text" class="t-event obs-input" value="${(t.event || t.trigger || '').replace(/"/g, '&quot;')}" placeholder="Twitch * sub, YouTube * member"></div>
<div>
                    <label class="obs-label">Scene Name</label>
                    <select class="t-scene obs-input" title="Select scene (leave at Current Scene if source is in active scene)">${sceneOptions}</select></div>
<div>
                    <label class="obs-label">Source Name</label>
                    <select class="t-source obs-input"></select></div>
<div>
                    <label class="obs-label">Duration (ms)</label>
                    <input type="number" class="t-duration obs-input" value="${t.duration !== undefined ? t.duration : 5000}" min="0" step="100"></div>
<div style="text-align: right;">
                    <button class="btn-red" onclick="obsRemoveTriggerRow(${t.id})" title="Remove" style="padding: 8px 15px; cursor: pointer; border-radius: 4px; font-weight: bold; margin-bottom: 3px;">✕</button></div></div>
<div class="trigger-row-bottom" style="display: flex; flex-wrap: wrap; gap: 10px; align-items: start; background: #222; padding: 10px; border-radius: 4px; border-left: 3px solid #007acc; width: 100%; box-sizing: border-box;">
<div>
                    <label class="obs-label">Text Scene (Optional)</label>
                    <select class="t-textscene obs-input" title="Text Scene (leave empty to use same as main source)">${sceneOptions}</select></div>
<div>
                    <label class="obs-label">Text Source Name (Optional)</label>
                    <select class="t-textsource obs-input"></select></div>
<div>
                    <label class="obs-label">Text Update Content</label>
                    <textarea class="t-text obs-input" style="width: 100%; min-height: 40px; resize: vertical;" placeholder="e.g. Thanks for the sub {username}!">${(t.textPayload || t.textContent || '').replace(/"/g, '&quot;')}</textarea></div></div>
        `;

        const sceneSel = tDiv.querySelector('select.t-scene');
        const sourceSel = tDiv.querySelector('select.t-source');
        const textSceneSel = tDiv.querySelector('select.t-textscene');
        const textSourceSel = tDiv.querySelector('select.t-textsource');

        function updateSourceDropdown() {
            const sVal = sceneSel.value;
            sourceSel.innerHTML = '<option value="">-- Main Source --</option>';
            let possibleSources = [];
            if (!sVal) {
                possibleSources = obsSources.map(s => ({ sourceName: s }));
            } else if (obsSceneItemsMap[sVal]) {
                possibleSources = obsSceneItemsMap[sVal];
            }
            
            possibleSources.forEach(item => {
                sourceSel.innerHTML += `<option value="${item.sourceName.replace(/"/g, '&quot;')}">${item.sourceName}</option>`;
            });
            
            if (t.source) {
                if (!Array.from(sourceSel.options).some(o => o.value === t.source)) {
                    let opt = document.createElement("option");
                    opt.value = t.source;
                    opt.text = t.source + " (Offline)";
                    sourceSel.appendChild(opt);
                }
                sourceSel.value = t.source;
            }
            sourceSel.dispatchEvent(new Event('change'));
        }

        function updateTextSourceDropdown() {
            const sVal = textSceneSel.value;
            textSourceSel.innerHTML = '<option value="">-- Optional Text Source --</option>';
            let possibleSources = [];
            
            if (!sVal) {
                let allTextSources = new Set();
                Object.values(obsSceneItemsMap).forEach(items => {
                    items.forEach(item => {
                        if (item.inputKind && item.inputKind.includes('text')) {
                            allTextSources.add(item.sourceName);
                        }
                    });
                });
                allTextSources.forEach(name => possibleSources.push({sourceName: name, inputKind: 'text'}));
            } else if (obsSceneItemsMap[sVal]) {
                possibleSources = obsSceneItemsMap[sVal].filter(item => item.inputKind && item.inputKind.includes('text'));
            }
            
            possibleSources.forEach(item => {
                textSourceSel.innerHTML += `<option value="${item.sourceName.replace(/"/g, '&quot;')}">${item.sourceName}</option>`;
            });

            if (t.textSource) {
                if (!Array.from(textSourceSel.options).some(o => o.value === t.textSource)) {
                    let opt = document.createElement("option");
                    opt.value = t.textSource;
                    opt.text = t.textSource + " (Offline)";
                    textSourceSel.appendChild(opt);
                }
                textSourceSel.value = t.textSource;
            }
            textSourceSel.dispatchEvent(new Event('change'));
        }

        if (t.scene) {
            if (!Array.from(sceneSel.options).some(o => o.value === t.scene)) {
                let opt = document.createElement("option");
                opt.value = t.scene;
                opt.text = t.scene + " (Offline)";
                sceneSel.appendChild(opt);
            }
            sceneSel.value = t.scene;
        }
        sceneSel.dispatchEvent(new Event('change'));

        if (t.textScene) {
            if (!Array.from(textSceneSel.options).some(o => o.value === t.textScene)) {
                let opt = document.createElement("option");
                opt.value = t.textScene;
                opt.text = t.textScene + " (Offline)";
                textSceneSel.appendChild(opt);
            }
            textSceneSel.value = t.textScene;
        }
        textSceneSel.dispatchEvent(new Event('change'));

        sceneSel.addEventListener('change', () => {
            t.scene = sceneSel.value;
            updateSourceDropdown();
        });

        textSceneSel.addEventListener('change', () => {
            t.textScene = textSceneSel.value;
            updateTextSourceDropdown();
        });

        updateSourceDropdown();
        updateTextSourceDropdown();

        container.appendChild(tDiv);
    });
}

function obsSaveTriggersToMemory() {
    const container = document.getElementById("triggers-container");
    if(!container) return;
    
    // Refresh obsConfig.triggers from DOM directly instead of using map over old triggers
    const rows = container.querySelectorAll('.trigger-row');
    const newTriggers = [];
    rows.forEach(row => {
        const idStr = row.id.replace('trigger-', '');
        
        const tObj = {
            id: parseInt(idStr),
            event: row.querySelector('input.t-event').value,
            scene: row.querySelector('select.t-scene').value,
            source: row.querySelector('select.t-source').value,
            duration: parseInt(row.querySelector('input.t-duration').value) || 0,
            textScene: row.querySelector('select.t-textscene').value,
            textSource: row.querySelector('select.t-textsource').value,
            textPayload: row.querySelector('.t-text').value
        };
        newTriggers.push(tObj);
    });
    
    obsConfig.triggers = newTriggers;
    return newTriggers;
}

function obsSaveTriggers() {
    obsSaveTriggersToMemory();
    obsConfig.url = document.getElementById("obs-url").value;
    obsConfig.password = document.getElementById("obs-pass").value;
    obsSaveState();
    
    saveConfiguration();

    if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ 
            type: "update_obs_config", 
            payload: {
                obs_url: obsConfig.url,
                obs_pass: obsConfig.password,
                triggers: obsConfig.triggers
            } 
        }));
        obsLog("Triggers Saved to Background Server!");
    } else {
        obsLog("Could not save to backend: WebSocket not connected.", true);
    }
}

document.addEventListener("DOMContentLoaded", () => {
    obsLoadState();
});