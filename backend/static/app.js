document.addEventListener('DOMContentLoaded', () => {
    // Nav elements
    const navTabs = document.querySelectorAll('.nav-tab');
    const tabViews = document.querySelectorAll('.tab-view');
    const topHandleDisplay = document.getElementById('top-handle-display');

    // Global state
    let currentHandle = null;
    let currentUserProfile = null;
    let chatHistory = [];

    // Switch Tabs Logic
    navTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            navTabs.forEach(t => t.classList.remove('active'));
            tabViews.forEach(v => {
                v.classList.remove('active');
                v.classList.add('hidden');
            });

            tab.classList.add('active');
            const targetId = tab.getAttribute('data-target');
            document.getElementById(targetId).classList.remove('hidden');
            document.getElementById(targetId).classList.add('active');
        });
    });

    // Handle Forms logic
    const gpForm = document.getElementById('problem-form');
    const chatSetupForm = document.getElementById('chat-handle-form');
    const profileSetupForm = document.getElementById('profile-handle-form');

    const handleFormSubmit = async (e, formType, inputId, loadingId, errorId) => {
        e.preventDefault();
        const inputEl = document.getElementById(inputId);
        const handle = inputEl.value.trim();
        if (!handle) return;

        const loadingEl = document.getElementById(loadingId);
        const errorEl = document.getElementById(errorId);

        errorEl.classList.add('hidden');
        loadingEl.classList.remove('hidden');

        try {
            if (formType === 'problem') {
                const res = await fetch('/api/get_problem', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ handle })
                });
                const data = await res.json();
                if (!res.ok) throw new Error(data.detail || data.error || 'Failed to fetch problem.');
                
                updateGlobalState(handle, data.profile);
                renderProblem(data.message, data.problem_details);
            } else {
                // Profile & Chat setup use analyze endpoint
                if (currentHandle !== handle || !currentUserProfile) {
                    const res = await fetch('/api/analyze', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ handle })
                    });
                    const data = await res.json();
                    if (!res.ok || data.error) throw new Error(data.detail || data.error || 'Failed to analyze profile.');
                    updateGlobalState(handle, data);
                    
                    if (formType === 'chat') {
                        appendMessage('bot', `Hello **${handle}**! I've analyzed your Codeforces history. It looks like you're Archetype **${data.cluster}**. How can I help you train today?`);
                        chatHistory.push({ role: 'model', content: `Hello ${handle}! I've analyzed your Codeforces history. It looks like you're Archetype ${data.cluster}. How can I help you train today?` });
                    }
                }
            }
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.classList.remove('hidden');
        } finally {
            loadingEl.classList.add('hidden');
        }
    };

    gpForm.addEventListener('submit', e => handleFormSubmit(e, 'problem', 'gp-handle', 'gp-loading', 'gp-error'));
    chatSetupForm.addEventListener('submit', e => handleFormSubmit(e, 'chat', 'chat-setup-handle', 'chat-loading', 'chat-error'));
    profileSetupForm.addEventListener('submit', e => handleFormSubmit(e, 'profile', 'profile-setup-handle', 'profile-loading', 'profile-error'));

    function updateGlobalState(handle, profileData) {
        currentHandle = handle;
        currentUserProfile = profileData;
        topHandleDisplay.textContent = handle;

        // Auto-fill other inputs
        document.getElementById('gp-handle').value = handle;
        document.getElementById('chat-setup-handle').value = handle;
        document.getElementById('profile-setup-handle').value = handle;

        // Enable Chat Layout
        document.getElementById('chat-setup').classList.add('hidden');
        document.getElementById('chat-main').classList.remove('hidden');

        // Enable Profile Layout
        document.getElementById('profile-setup').classList.add('hidden');
        document.getElementById('profile-main').classList.remove('hidden');

        renderProfile(profileData);
    }

    function renderProfile(data) {
        document.getElementById('profile-handle-title').textContent = data.handle;
        document.getElementById('profile-cluster').textContent = data.cluster;
        
        const p = data.metrics || {};
        document.getElementById('profile-rating').textContent = data.avg_rating ? Math.round(data.avg_rating) : 'N/A';
        document.getElementById('profile-oneshot').textContent = p.one_shot_rate ? (p.one_shot_rate * 100).toFixed(1) + '%' : 'N/A';
        document.getElementById('profile-tilt').textContent = p.tilt_speed_seconds ? Math.round(p.tilt_speed_seconds) + 's' : 'N/A';
        document.getElementById('profile-abandonment').textContent = p.abandonment_rate ? (p.abandonment_rate * 100).toFixed(1) + '%' : 'N/A';
        
        // Compute pseudo strength/weakness dynamically from metrics struct (simplified logic to just avoid crashing)
        let maxPrefName = 'None';
        let maxPrefVal = -1;
        let pkeys = ['math_pref','dp_pref','graph_pref','brute_pref','greedy_pref','binary_pref','cons_pref','datastruct_pref'];
        for (let k of pkeys) {
            if(p[k] && p[k] > maxPrefVal) { maxPrefVal = p[k]; maxPrefName = k.replace('_pref',''); }
        }
        document.getElementById('profile-strengths').textContent = maxPrefName !== 'None' ? maxPrefName.toUpperCase() : 'None';
        document.getElementById('profile-weakness').textContent = p.optimization_struggle > 0.3 ? 'Time Limit Exc / High Abandonment' : 'Standard Algorithmic Challenges';
    }

    function renderProblem(markdownText, meta) {
        const area = document.getElementById('gp-result-area');
        const content = document.getElementById('gp-content');
        area.classList.remove('hidden');
        
        if (meta) {
            document.getElementById('pb-rating').textContent = `Rating: ${meta.rating || 'Unrated'}`;
            document.getElementById('pb-tags').textContent = `Tags: ${meta.tags || 'General'}`;
        } else {
            document.getElementById('pb-rating').textContent = 'Generic Pick';
            document.getElementById('pb-tags').textContent = 'N/A';
        }

        content.innerHTML = marked.parse(markdownText);
    }

    // --- CHAT LOGIC ---
    const chatForm = document.getElementById('chat-form');
    const chatInput = document.getElementById('chat-input');
    const chatMessages = document.getElementById('chat-messages');

    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const msg = chatInput.value.trim();
        if (!msg) return;

        appendMessage('user', msg);
        chatHistory.push({ role: 'user', content: msg });
        chatInput.value = '';

        const loadingId = appendLoading();

        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: msg,
                    history: chatHistory.slice(0, -1),
                    profile: currentUserProfile
                })
            });

            const data = await res.json();
            removeLoading(loadingId);

            if (!res.ok) throw new Error(data.detail || 'Chat request failed.');

            appendMessage('bot', data.message);
            chatHistory.push({ role: 'model', content: data.message });

        } catch (err) {
            removeLoading(loadingId);
            appendMessage('bot', `⚠️ Error: ${err.message}`);
        }
    });

    function appendMessage(sender, text) {
        const div = document.createElement('div');
        div.className = `message ${sender} fade-in`;
        
        const htmlText = sender === 'bot' ? marked.parse(text) : escapeHtml(text);
        
        div.innerHTML = `
            <div class="avatar">${sender === 'user' ? 'U' : 'AI'}</div>
            <div class="bubble">${htmlText}</div>
        `;
        chatMessages.appendChild(div);
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function appendLoading() {
        const id = 'loading-' + Date.now();
        const div = document.createElement('div');
        div.className = `message bot`;
        div.id = id;
        div.innerHTML = `
            <div class="avatar">AI</div>
            <div class="bubble"><div class="jumping-dots"><span>.</span><span>.</span><span>.</span></div></div>
        `;
        chatMessages.appendChild(div);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return id;
    }

    function removeLoading(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    function escapeHtml(unsafe) {
        return unsafe.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
});
