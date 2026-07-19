// --- settings-chat.js --- //
const PARSERS = {
    "twitch_parse": {
        name: "Twitch", color: "#9146FF", events: [
            "Twitch chat", "Twitch cheer", "Twitch redeem (irc)", "Twitch redeem (pubsub)", "Twitch sub", "Twitch raid", "Twitch ban", "Twitch timeout", "Twitch message delete", "Twitch notice", "Twitch roomstate", "Twitch other"
        ]
    }, "kick_parse": {
        name: "Kick", color: "#53fc18", events: [
            "Kick chat", "Kick redeem", "Kick follow", "Kick sub", "Kick gift sub", "Kick raid start", "Kick raid end", "Kick ban", "Kick timeout", "Kick stream start", "Kick stream end", "Kick other"
        ]
    }, "youtube_parse": {
        name: "YouTube", color: "#ff0000", events: ["chat_message", "paid_message", "sticker_message", "member_message", "gift_message"]
    }
};

function addZone() {
    let timestamp = Date.now();
    renderZone('chat_' + timestamp, 'twitch_parse', '', {}, false, true);
}

function renderZone(id, parser, input, filters, moderate, tts_enabled, sub_cache_enabled) {
    const container = document.getElementById('zones_container');
    
    const validParser = PARSERS[parser] ? parser : 'twitch_parse';
    
    // Build Select Options
    let parserOptions = '';
    Object.keys(PARSERS).forEach(pKey => {
         parserOptions += `<option value="${pKey}" ${pKey === validParser ? 'selected' : ''}>${PARSERS[pKey].name}</option>`;
    });

    const color = PARSERS[validParser].color;
    const placeholder = validParser === 'youtube_parse' ? 'https://studio.youtube.com/...' : 'Username';

    const rootDiv = document.createElement('div');
    rootDiv.className = 'zone-card';
    rootDiv.id = id;
    rootDiv.dataset.parser = validParser;
    rootDiv.style.borderLeftColor = color;
    
    rootDiv.innerHTML = `
<div class="zone-header">
            <select class="w-150 p-0 m-0 parser-select">${parserOptions}</select>
            <button class="btn-red p-5-10" onclick="this.closest('.zone-card').remove()">Remove</button></div>
        <input type="text" class="input-field" value="${input}" placeholder="${placeholder}">
<div class="checkbox-row mt-10 mb-5 p-4-8">
            <input type="checkbox" class="mod-checkbox" ${moderate ? 'checked' : ''}>
            <label class="m-0">Enable AI Moderation for this chat</label></div>
<div class="checkbox-row mb-10 p-4-8">
            <input type="checkbox" class="tts-checkbox" ${tts_enabled !== false ? 'checked' : ''}>
            <label class="m-0">Enable TTS for this chat</label></div>
<div class="checkbox-row mb-10 p-4-8">
            <input type="checkbox" class="sub-cache-checkbox" ${sub_cache_enabled ? 'checked' : ''}>
            <label class="m-0">Enable Subscriber Caching</label></div>
<div class="filter-grid"></div>
    `;
    
    container.appendChild(rootDiv);

    // Bind parser change
    rootDiv.querySelector('.parser-select').onchange = (e) => {
        rootDiv.dataset.parser = e.target.value;
        rootDiv.querySelector('.input-field').placeholder = e.target.value === 'youtube_parse' ? 'https://studio.youtube.com/...' : 'Username';
        renderFilters(rootDiv, e.target.value, {}); 
    };

    renderFilters(rootDiv, parser, filters);
}

function renderFilters(zoneDiv, parserName, filtersState) {
    const container = zoneDiv.querySelector('.filter-grid');
    container.innerHTML = "";
    // Fallback to twitch_parse if parserName is invalid or missing
    const validParser = PARSERS[parserName] ? parserName : 'twitch_parse';
    const events = PARSERS[validParser].events;

    events.forEach(ev => {
        const item = document.createElement('label');
        item.className = 'filter-item';
        item.style.marginTop = "0";

        const checkbox = document.createElement('input');
        checkbox.type = 'checkbox';
        checkbox.dataset.event = ev;
        checkbox.checked = filtersState[ev] !== undefined ? filtersState[ev] : true;

        item.appendChild(checkbox);
        item.appendChild(document.createTextNode(ev));
        container.appendChild(item);
    });
}