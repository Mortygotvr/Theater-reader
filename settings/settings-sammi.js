// --- settings-sammi.js --- //
function testSammiTrigger(triggerName, user = "", variable = "", channel = "") {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
        alert("Not connected to background app!");
        return;
    }
    if (!triggerName) return;

    ws.send(JSON.stringify({
        type: "test_sammi_trigger", trigger: triggerName, user: user, channel: channel, var: variable
    }));
    
    const msgDiv = document.getElementById('status-msg');
    msgDiv.innerText = `Test trigger sent: ${triggerName}`;
    setTimeout(() => { if (msgDiv.innerText.includes(triggerName)) msgDiv.innerText = ""; }, 3000);
}

function generateTestTrigger(platform, action) {
    let user = document.getElementById('sammi_test_user').value.trim() || 'TestUser';
    let channel = document.getElementById('sammi_test_channel').value.trim() || 'TestChannel';
    let variable = document.getElementById('sammi_test_var').value.trim() || '500';

    if (action === 'hype train') {
        user = document.getElementById('sammi_test_user').value.trim() || 'System'; 
    }

    let triggerName = `${platform} testserver ${action}`;

    if (action === 'cheer') {
        if (!variable.toLowerCase().includes('bits')) triggerName += ` ${variable} bits`;
        else triggerName += ` ${variable}`;
    }
    else if (action === 'hype train' || action === 'super chat' || action === 'super sticker' || action === 'redeem') {
        triggerName += ` ${variable}`;
    }

    testSammiTrigger(triggerName, user, variable, channel);
}

function testCustomSammiTrigger() {
    const val = document.getElementById('sammi_custom_test').value.trim();
    const user = document.getElementById('sammi_test_user').value.trim() || 'TestUser';
    const channel = document.getElementById('sammi_test_channel').value.trim() || 'TestChannel';
    const variable = document.getElementById('sammi_test_var').value.trim();
    if (val) {
        testSammiTrigger(val, user, variable, channel);
    } else {
        alert("Please enter a custom trigger string to test.");
    }
}