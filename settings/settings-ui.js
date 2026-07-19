// --- settings-ui.js --- //
function openTab(tabName) {
    document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));

    document.getElementById(tabName).classList.add('active');
    document.querySelector(`.tab-btn[data-tab="${tabName}"]`).classList.add('active');

}

// ----- CUSTOM DROPDOWN ENGINE (Bypass PySide6 Native White Shadows) -----
function upgradeSelectToCustom(selectEl) {
    if (selectEl.classList.contains('auto-convert') || selectEl.multiple || selectEl.size > 1) return;
    console.log(`[UI] Upgrading select: ${selectEl.id || "unnamed"}`);
    selectEl.classList.add('auto-convert');
    
    // Inheritance: Copy width and layout styles from original select to wrapper
    const wrapper = document.createElement('div');
    wrapper.className = 'custom-select-wrapper ' + selectEl.className.replace('auto-convert', '').replace('obs-input', '');
    
    // Copy essential inline styles
    wrapper.style.width = selectEl.style.width || "";
    wrapper.style.flex = selectEl.style.flex || "";
    wrapper.style.margin = selectEl.style.margin || "";
    
    // Ensure it behaves like the original in flex containers
    if (selectEl.style.width && selectEl.style.width !== "100%") {
        wrapper.style.display = "inline-block";
    }

    const display = document.createElement('div');
    display.className = 'custom-select-display obs-input';
    
    const optionsDiv = document.createElement('div');
    optionsDiv.className = 'custom-select-options';

    function syncProxy() {
        display.innerText = selectEl.options.length > 0 && selectEl.selectedIndex >= 0 
            ? selectEl.options[selectEl.selectedIndex].text : '';
        optionsDiv.innerHTML = '';
        Array.from(selectEl.options).forEach((opt, idx) => {
            const optDiv = document.createElement('div');
            optDiv.className = 'custom-select-option';
            optDiv.innerText = opt.text;
            if (idx === selectEl.selectedIndex) optDiv.style.backgroundColor = 'var(--accent)';
            
            optDiv.onclick = (e) => {
                e.stopPropagation();
                const val = opt.value;
                selectEl.value = val;
                selectEl.dispatchEvent(new Event('change'));
                wrapper.classList.remove('open');
                syncProxy();
            };
            optionsDiv.appendChild(optDiv);
        });
    }

    // Sync when the real select changes programmably
    selectEl.addEventListener('change', syncProxy);
    
    // Use an observer in case javascript changes the innerHTML (like OBS triggers do)
    const observer = new MutationObserver(syncProxy);
    observer.observe(selectEl, { childList: true, subtree: true, attributes: true, attributeFilter: ['value'] });

    syncProxy();

    display.onclick = (e) => {
        e.stopPropagation();
        const isOpen = wrapper.classList.contains('open');
        document.querySelectorAll('.custom-select-wrapper.open').forEach(w => w.classList.remove('open'));
        if (!isOpen) wrapper.classList.add('open');
    };

    selectEl.parentNode.insertBefore(wrapper, selectEl);
    wrapper.appendChild(selectEl);
    wrapper.appendChild(display);
    wrapper.appendChild(optionsDiv);
}

document.addEventListener('click', () => {
    document.querySelectorAll('.custom-select-wrapper.open').forEach(w => w.classList.remove('open'));
});

// Auto-discover all selects that are added to the page
const globalObserver = new MutationObserver((mutations) => {
    document.querySelectorAll('select:not(.auto-convert)').forEach(upgradeSelectToCustom);
});
globalObserver.observe(document.body, { childList: true, subtree: true });

// Init existing selects
window.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll('select:not(.auto-convert)').forEach(upgradeSelectToCustom);
});