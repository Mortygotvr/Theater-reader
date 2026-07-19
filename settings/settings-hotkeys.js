// --- settings-hotkeys.js --- //
document.addEventListener("DOMContentLoaded", () => {
    const hkToggle = document.getElementById('enable_hotkeys');
    if(hkToggle) {
        hkToggle.addEventListener('change', () => {
            if(typeof saveConfiguration === "function") {
                saveConfiguration();
            }
        });
    }
});

function addHotkey() {
    renderHotkey(Date.now(), "", false, false, false, "F1", 0);
}

function addKeyToTrigger() {
    renderKeyToTrigger(Date.now(), "", false, false, false, "f1", 0);
}

function renderKeyToTrigger(id, triggerStr, ctrl, alt, shift, key, delayMs=0) {
    const container = document.getElementById('key_to_trigger_container');
    const div = document.createElement('div');
    div.className = 'zone-card key-to-trigger-card';
    div.id = 'k2t_' + id;

    let keysOpt = '';
    const allKeys = ['f1','f2','f3','f4','f5','f6','f7','f8','f9','f10','f11','f12',
                     'a','b','c','d','e','f','g','h','i','j','k','l','m','n','o','p','q','r','s','t','u','v','w','x','y','z',
                     '1','2','3','4','5','6','7','8','9','0',
                     'space','enter','tab','esc','backspace','up','down','left','right',
                     'home','end','page up','page down','insert','delete','num 0','num 1','num 2','num 3','num 4','num 5','num 6','num 7','num 8','num 9','num *','num +','num -','num .','num /'];
    
    const safeKey = (key || 'f1').toLowerCase();
    for(let k of allKeys) {
        keysOpt += `<option value="${k}" ${safeKey === k ? 'selected' : ''}>${k.toUpperCase()}</option>`;
    }

    div.innerHTML = `
<div style="display: flex; gap: 15px; align-items: flex-end;">
<div>
                <label>Modifiers</label>
<div style="display: flex; gap: 10px; background: #1a1a1a; padding: 10px; border-radius: 4px; border: 1px solid #444;">
                    <label class="m-0 fw-normal" title="Control"><input type="checkbox" class="k2t-ctrl" ${ctrl ? 'checked' : ''}> Ctrl</label>
                    <label class="m-0 fw-normal" title="Alt"><input type="checkbox" class="k2t-alt" ${alt ? 'checked' : ''}> Alt</label>
                    <label class="m-0 fw-normal" title="Shift"><input type="checkbox" class="k2t-shift" ${shift ? 'checked' : ''}> Shift</label></div></div> 
<div>
                <label>Key</label>
                <select class="k2t-key" style="min-width: 100px;">
                    ${keysOpt}
                </select></div>
<div style="flex-grow: 2;">
                <label>Simulate Stream Event (e.g. 'Twitch * redeem drink')</label>
                <input type="text" class="k2t-trigger" value="${triggerStr}" placeholder="System * Event"></div>
<div>
                <label>Delay (ms)</label>
                <input type="number" class="k2t-delay" value="${delayMs || 0}" min="0" step="100" style="width: 80px; padding: 10px; background: #1a1a1a; border: 1px solid #444; color: white; border-radius: 4px; display: block; box-sizing: border-box;"></div>
<div>
                <button class="btn-red" style="padding: 10px; margin-bottom: 2px;" onclick="this.parentElement.parentElement.parentElement.remove()">✕</button></div></div>
    `;
    container.appendChild(div);
}


function renderHotkey(id, triggerStr, ctrl, alt, shift, key, delayMs=0) {
    const container = document.getElementById('hotkeys_container');
    const div = document.createElement('div');
    div.className = 'zone-card hotkey-card';
    div.id = 'hk_' + id;
    
    let keysOpt = '';
    const safeKey = (key || 'F1').toUpperCase();
    for(let i=1; i<=24; i++) {
        let k = `F${i}`;
        keysOpt += `<option value="${k}" ${safeKey === k ? 'selected' : ''}>${k}</option>`;
    }
    
    div.innerHTML = `
<div style="display: flex; gap: 15px; align-items: flex-end;">
<div style="flex-grow: 2;">
                <label>Event Trigger (e.g. 'Twitch * sub')</label>
                <input type="text" class="hk-trigger" value="${triggerStr}" placeholder="Twitch * sub"></div>
<div>
                <label>Modifiers</label>
<div style="display: flex; gap: 10px; background: #1a1a1a; padding: 10px; border-radius: 4px; border: 1px solid #444;">
                    <label class="m-0 fw-normal" title="Control"><input type="checkbox" class="hk-ctrl" ${ctrl ? 'checked' : ''}> Ctrl</label>
                    <label class="m-0 fw-normal" title="Alt"><input type="checkbox" class="hk-alt" ${alt ? 'checked' : ''}> Alt</label>
                    <label class="m-0 fw-normal" title="Shift"><input type="checkbox" class="hk-shift" ${shift ? 'checked' : ''}> Shift</label></div></div>
<div>
                <label>Key</label>
                <select class="hk-key" style="min-width: 80px;">
                    ${keysOpt}
                </select></div>
<div>
                <label>Delay (ms)</label>
                <input type="number" class="hk-delay" value="${delayMs || 0}" min="0" step="100" style="width: 80px; padding: 10px; background: #1a1a1a; border: 1px solid #444; color: white; border-radius: 4px; display: block; box-sizing: border-box;"></div>
<div>
                <button class="btn-red" style="padding: 10px; margin-bottom: 2px;" onclick="this.parentElement.parentElement.parentElement.remove()">✕</button></div></div>
    `;
    container.appendChild(div);
}