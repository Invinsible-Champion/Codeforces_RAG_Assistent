document.addEventListener('DOMContentLoaded', () => {
    // ═══════════════════════════════════════════════════════════════
    // ELEMENTS
    // ═══════════════════════════════════════════════════════════════
    const authScreen    = document.getElementById('auth-screen');
    const mainApp       = document.getElementById('main-app');
    const toastContainer = document.getElementById('toast-container');

    // Auth toggle
    const toggleLogin    = document.getElementById('toggle-login');
    const toggleRegister = document.getElementById('toggle-register');
    const toggleSlider   = document.getElementById('toggle-slider');
    const loginForm      = document.getElementById('login-form');
    const registerForm   = document.getElementById('register-form');
    const switchToReg    = document.getElementById('switch-to-register');
    const authSwitchMsg  = document.getElementById('auth-switch-msg');

    // Nav tabs
    const navTabs        = document.querySelectorAll('.nav-tab');
    const tabViews       = document.querySelectorAll('.tab-view');
    const topHandleDisp  = document.getElementById('top-handle-display');
    const logoutBtn      = document.getElementById('logout-btn');

    // Practice tab
    const gpBtn          = document.getElementById('gp-btn');

    // Analytics tab
    const analyzeBtn     = document.getElementById('analyze-btn');

    // Global state
    let currentHandle    = null;
    let currentProfile   = null;


    // ═══════════════════════════════════════════════════════════════
    // TOAST SYSTEM
    // ═══════════════════════════════════════════════════════════════
    function showToast(message, type = 'info', duration = 3500) {
        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        const icons = { success: '✓', error: '✕', info: 'ℹ' };
        toast.innerHTML = `<span style="font-weight:700;font-size:1.1rem;">${icons[type] || '•'}</span> ${message}`;
        toastContainer.appendChild(toast);
        setTimeout(() => {
            toast.classList.add('toast-out');
            toast.addEventListener('animationend', () => toast.remove());
        }, duration);
    }


    // ═══════════════════════════════════════════════════════════════
    // AUTH TOGGLE (Login ↔ Register)
    // ═══════════════════════════════════════════════════════════════
    function setAuthMode(mode) {
        if (mode === 'register') {
            toggleRegister.classList.add('active');
            toggleLogin.classList.remove('active');
            toggleSlider.classList.add('right');
            registerForm.classList.add('active');
            loginForm.classList.remove('active');
            authSwitchMsg.innerHTML = 'Already have an account? <button class="link-btn" id="switch-to-login">Sign In</button>';
            document.getElementById('switch-to-login').addEventListener('click', () => setAuthMode('login'));
        } else {
            toggleLogin.classList.add('active');
            toggleRegister.classList.remove('active');
            toggleSlider.classList.remove('right');
            loginForm.classList.add('active');
            registerForm.classList.remove('active');
            authSwitchMsg.innerHTML = 'Don\'t have an account? <button class="link-btn" id="switch-to-register-link">Sign Up</button>';
            document.getElementById('switch-to-register-link').addEventListener('click', () => setAuthMode('register'));
        }
    }

    toggleLogin.addEventListener('click', () => setAuthMode('login'));
    toggleRegister.addEventListener('click', () => setAuthMode('register'));
    if (switchToReg) switchToReg.addEventListener('click', () => setAuthMode('register'));


    // ═══════════════════════════════════════════════════════════════
    // PASSWORD VISIBILITY TOGGLE
    // ═══════════════════════════════════════════════════════════════
    document.querySelectorAll('.toggle-password').forEach(btn => {
        btn.addEventListener('click', () => {
            const targetId = btn.getAttribute('data-target');
            const input = document.getElementById(targetId);
            const eyeOpen = btn.querySelector('.eye-open');
            const eyeClosed = btn.querySelector('.eye-closed');
            if (input.type === 'password') {
                input.type = 'text';
                eyeOpen.classList.add('hidden');
                eyeClosed.classList.remove('hidden');
            } else {
                input.type = 'password';
                eyeOpen.classList.remove('hidden');
                eyeClosed.classList.add('hidden');
            }
        });
    });


    // ═══════════════════════════════════════════════════════════════
    // SESSION CHECK — on page load
    // ═══════════════════════════════════════════════════════════════
    async function checkSession() {
        try {
            const res = await fetch('/api/me', { credentials: 'include' });
            if (res.ok) {
                const data = await res.json();
                enterApp(data.cf_handle);
                return;
            }
        } catch (_) { /* not logged in */ }
        authScreen.classList.remove('hidden');
        mainApp.classList.add('hidden');
    }

    function enterApp(handle) {
        currentHandle = handle;
        authScreen.classList.add('hidden');
        mainApp.classList.remove('hidden');
        mainApp.classList.add('app-reveal');
        topHandleDisp.textContent = handle;
    }

    checkSession();


    // ═══════════════════════════════════════════════════════════════
    // LOGIN
    // ═══════════════════════════════════════════════════════════════
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const handle   = document.getElementById('login-handle').value.trim();
        const password = document.getElementById('login-password').value;
        const errorEl  = document.getElementById('login-error');
        const btnText  = loginForm.querySelector('.btn-text');
        const btnLoad  = loginForm.querySelector('.btn-loader');
        if (!handle || !password) return;
        errorEl.classList.add('hidden');
        btnText.classList.add('hidden');
        btnLoad.classList.remove('hidden');
        try {
            const res = await fetch('/api/login', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ cf_handle: handle, password })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Login failed.');
            showToast(`Welcome back, ${data.cf_handle}!`, 'success');
            enterApp(data.cf_handle);
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.classList.remove('hidden');
        } finally {
            btnText.classList.remove('hidden');
            btnLoad.classList.add('hidden');
        }
    });


    // ═══════════════════════════════════════════════════════════════
    // REGISTER
    // ═══════════════════════════════════════════════════════════════
    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const handle   = document.getElementById('register-handle').value.trim();
        const password = document.getElementById('register-password').value;
        const confirm  = document.getElementById('register-confirm').value;
        const errorEl  = document.getElementById('register-error');
        const successEl= document.getElementById('register-success');
        const btnText  = registerForm.querySelector('.btn-text');
        const btnLoad  = registerForm.querySelector('.btn-loader');
        errorEl.classList.add('hidden');
        successEl.classList.add('hidden');
        if (!handle || !password) return;
        if (password !== confirm) {
            errorEl.textContent = 'Passwords do not match.';
            errorEl.classList.remove('hidden');
            return;
        }
        btnText.classList.add('hidden');
        btnLoad.classList.remove('hidden');
        try {
            const res = await fetch('/api/register', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ cf_handle: handle, password })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || 'Registration failed.');
            showToast('Account created successfully!', 'success');
            enterApp(data.cf_handle);
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.classList.remove('hidden');
        } finally {
            btnText.classList.remove('hidden');
            btnLoad.classList.add('hidden');
        }
    });


    // ═══════════════════════════════════════════════════════════════
    // LOGOUT
    // ═══════════════════════════════════════════════════════════════
    logoutBtn.addEventListener('click', async () => {
        try { await fetch('/api/logout', { method: 'POST', credentials: 'include' }); } catch (_) {}
        currentHandle = null;
        currentProfile = null;
        mainApp.classList.add('hidden');
        mainApp.classList.remove('app-reveal');
        authScreen.classList.remove('hidden');
        loginForm.reset();
        registerForm.reset();
        setAuthMode('login');
        document.getElementById('profile-setup').classList.remove('hidden');
        document.getElementById('profile-main').classList.add('hidden');
        document.getElementById('gp-result-area').classList.add('hidden');
        document.getElementById('gp-result-area').innerHTML = '';
        showToast('Logged out successfully.', 'info');
    });


    // ═══════════════════════════════════════════════════════════════
    // NAV TABS
    // ═══════════════════════════════════════════════════════════════
    navTabs.forEach(tab => {
        tab.addEventListener('click', () => {
            navTabs.forEach(t => t.classList.remove('active'));
            tabViews.forEach(v => { v.classList.remove('active'); v.classList.add('hidden'); });
            tab.classList.add('active');
            const targetId = tab.getAttribute('data-target');
            document.getElementById(targetId).classList.remove('hidden');
            document.getElementById(targetId).classList.add('active');

            // Auto-load data when switching tabs
            if (targetId === 'tab-history') loadHistory();
            if (targetId === 'tab-leaderboard') loadLeaderboard();
        });
    });


    // ═══════════════════════════════════════════════════════════════
    // HELPERS
    // ═══════════════════════════════════════════════════════════════

    function getRatingClass(rating) {
        if (!rating) return 'rating-green';
        if (rating < 1200)  return 'rating-green';
        if (rating < 1400)  return 'rating-cyan';
        if (rating < 1800)  return 'rating-blue';
        if (rating < 2100)  return 'rating-purple';
        if (rating < 2400)  return 'rating-orange';
        return 'rating-red';
    }

    function buildCFLink(contestId, index) {
        return `https://codeforces.com/problemset/problem/${contestId}/${index}`;
    }

    function buildTagPills(tagsRaw) {
        if (!tagsRaw) return '';
        const tags = typeof tagsRaw === 'string' ? tagsRaw.split(',').map(t => t.trim()).filter(Boolean) : tagsRaw;
        return tags.map(t => `<span class="tag-pill">${t}</span>`).join('');
    }

    function formatDate(isoStr) {
        if (!isoStr) return '';
        const d = new Date(isoStr);
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    }


    // ═══════════════════════════════════════════════════════════════
    // PRACTICE TAB — Get Problem (uses session handle)
    // ═══════════════════════════════════════════════════════════════
    gpBtn.addEventListener('click', async () => {
        const loadingEl  = document.getElementById('gp-loading');
        const errorEl    = document.getElementById('gp-error');
        const resultArea = document.getElementById('gp-result-area');

        errorEl.classList.add('hidden');
        resultArea.classList.add('hidden');
        resultArea.innerHTML = '';
        loadingEl.classList.remove('hidden');
        gpBtn.classList.add('hidden');

        animatePipelineSteps();

        try {
            const res = await fetch('/api/get_problem', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({})
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || data.error || 'Failed to fetch problem.');
            currentProfile = data.profile;
            renderProblemCard(data.message, data.problem_details);
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.classList.remove('hidden');
        } finally {
            loadingEl.classList.add('hidden');
            gpBtn.classList.remove('hidden');
            resetPipelineSteps();
        }
    });


    // ═══════════════════════════════════════════════════════════════
    // RENDER PROBLEM CARD (beautiful card with accordion)
    // ═══════════════════════════════════════════════════════════════
    function renderProblemCard(markdownText, meta) {
        const area = document.getElementById('gp-result-area');
        area.innerHTML = '';
        area.classList.remove('hidden');

        const pName      = meta?.name || 'Practice Problem';
        const pRating    = meta?.rating;
        const pContestId = meta?.contest_id;
        const pIndex     = meta?.index || 'A';
        const pTags      = meta?.tags || '';
        const cfUrl      = pContestId ? buildCFLink(pContestId, pIndex) : '#';
        const ratingCls  = getRatingClass(pRating);

        const card = document.createElement('div');
        card.className = 'problem-card';

        card.innerHTML = `
            <div class="problem-card-header">
                <div class="problem-card-top">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>
                    Recommended for you
                </div>
                <a href="${cfUrl}" target="_blank" rel="noopener" class="problem-name-link">
                    ${pName}
                    <svg class="link-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6"/><polyline points="15 3 21 3 21 9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>
                </a>
                <div class="problem-meta-row">
                    <span class="rating-badge ${ratingCls}">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z"/></svg>
                        ${pRating || 'Unrated'}
                    </span>
                    ${buildTagPills(pTags)}
                </div>
            </div>
            <button class="accordion-trigger" id="why-trigger">
                <span class="trigger-left">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>
                    Why I chose this problem for you
                </span>
                <svg class="accordion-chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
            </button>
            <div class="accordion-body" id="why-body">
                <div class="accordion-content markdown-body" id="why-content"></div>
            </div>
        `;

        area.appendChild(card);

        // Render markdown
        document.getElementById('why-content').innerHTML = marked.parse(markdownText);

        // Accordion toggle
        const trigger = document.getElementById('why-trigger');
        const body    = document.getElementById('why-body');
        trigger.addEventListener('click', () => {
            trigger.classList.toggle('open');
            body.classList.toggle('open');
        });
    }


    // ═══════════════════════════════════════════════════════════════
    // ANALYTICS TAB — Analyze Profile
    // ═══════════════════════════════════════════════════════════════
    analyzeBtn.addEventListener('click', async () => {
        const loadingEl = document.getElementById('profile-loading');
        const errorEl   = document.getElementById('profile-error');
        errorEl.classList.add('hidden');
        loadingEl.classList.remove('hidden');
        analyzeBtn.classList.add('hidden');
        try {
            const res = await fetch('/api/analyze', {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                credentials: 'include', body: JSON.stringify({})
            });
            const data = await res.json();
            if (!res.ok || data.error) throw new Error(data.detail || data.error || 'Failed to analyze profile.');
            currentProfile = data;
            document.getElementById('profile-setup').classList.add('hidden');
            document.getElementById('profile-main').classList.remove('hidden');
            renderProfile(data);
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.classList.remove('hidden');
        } finally {
            loadingEl.classList.add('hidden');
            analyzeBtn.classList.remove('hidden');
        }
    });


    // ═══════════════════════════════════════════════════════════════
    // RENDERERS
    // ═══════════════════════════════════════════════════════════════
    function renderProfile(data) {
        document.getElementById('profile-handle-title').textContent = data.handle;
        document.getElementById('profile-cluster').textContent = data.cluster;
        const p = data.metrics || {};
        document.getElementById('profile-rating').textContent = data.avg_rating ? Math.round(data.avg_rating) : 'N/A';
        document.getElementById('profile-oneshot').textContent = p.one_shot_rate ? (p.one_shot_rate * 100).toFixed(1) + '%' : 'N/A';
        document.getElementById('profile-tilt').textContent = p.tilt_speed_seconds ? Math.round(p.tilt_speed_seconds) + 's' : 'N/A';
        document.getElementById('profile-abandonment').textContent = p.abandonment_rate ? (p.abandonment_rate * 100).toFixed(1) + '%' : 'N/A';

        const prefKeys = ['math_pref','dp_pref','graph_pref','brute_pref','greedy_pref','binary_pref','cons_pref','datastruct_pref'];
        const prefLabels = {
            'math_pref': 'Math & Number Theory', 'dp_pref': 'Dynamic Programming',
            'graph_pref': 'Graphs & Trees', 'brute_pref': 'Brute Force & Implementation',
            'greedy_pref': 'Greedy & Two Pointers', 'binary_pref': 'Binary Search',
            'cons_pref': 'Constructive & Strings', 'datastruct_pref': 'Data Structures'
        };
        let maxKey = null, maxVal = -1, minKey = null, minVal = Infinity;
        for (let k of prefKeys) {
            const val = p[k] || 0;
            if (val > maxVal) { maxVal = val; maxKey = k; }
            if (val < minVal) { minVal = val; minKey = k; }
        }
        document.getElementById('profile-strengths').textContent = maxKey ? prefLabels[maxKey] : 'N/A';
        document.getElementById('profile-weakness').textContent = minKey ? prefLabels[minKey] : 'N/A';
    }


    // ═══════════════════════════════════════════════════════════════
    // HISTORY TAB
    // ═══════════════════════════════════════════════════════════════
    async function loadHistory() {
        const list    = document.getElementById('history-list');
        const empty   = document.getElementById('history-empty');
        const statsEl = document.getElementById('history-stats');

        try {
            const res = await fetch('/api/history', { credentials: 'include' });
            if (!res.ok) throw new Error('Failed to load history.');
            const items = await res.json();

            if (items.length === 0) {
                list.innerHTML = '';
                empty.classList.remove('hidden');
                statsEl.innerHTML = '';
                return;
            }

            empty.classList.add('hidden');
            const done = items.filter(i => i.is_completed).length;
            const pending = items.length - done;

            statsEl.innerHTML = `
                <span class="history-stat"><span class="stat-dot dot-total"></span> ${items.length} Total</span>
                <span class="history-stat"><span class="stat-dot dot-done"></span> ${done} Completed</span>
                <span class="history-stat"><span class="stat-dot dot-pending"></span> ${pending} Pending</span>
            `;

            list.innerHTML = items.map(item => renderHistoryCard(item)).join('');

            // Attach event listeners
            list.querySelectorAll('.history-checkbox').forEach(cb => {
                cb.addEventListener('change', (e) => toggleComplete(e.target.dataset.id, e.target.checked));
            });
            list.querySelectorAll('.history-delete-btn').forEach(btn => {
                btn.addEventListener('click', () => deleteHistoryItem(btn.dataset.id));
            });
            list.querySelectorAll('.history-expand-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    const msgEl = document.getElementById(`coach-msg-${btn.dataset.id}`);
                    btn.classList.toggle('open');
                    msgEl.classList.toggle('open');
                });
            });

        } catch (err) {
            showToast(err.message, 'error');
        }
    }

    function renderHistoryCard(item) {
        const cfUrl = buildCFLink(item.contest_id, item.problem_index);
        const ratingCls = getRatingClass(item.rating);
        const completedCls = item.is_completed ? 'completed' : '';
        const checkedAttr = item.is_completed ? 'checked' : '';
        const dateStr = formatDate(item.created_at);

        return `
            <div class="history-card ${completedCls}" id="hcard-${item.id}">
                <label class="custom-checkbox">
                    <input type="checkbox" class="history-checkbox" data-id="${item.id}" ${checkedAttr} />
                    <span class="checkbox-visual">
                        <svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"/></svg>
                    </span>
                </label>
                <div class="history-card-body">
                    <div class="history-card-top">
                        <a href="${cfUrl}" target="_blank" rel="noopener" class="history-card-name">${item.problem_name}</a>
                        <span class="rating-badge ${ratingCls}">${item.rating || 'N/A'}</span>
                        <span class="history-card-date">${dateStr}</span>
                    </div>
                    <div class="history-card-tags">${buildTagPills(item.tags)}</div>
                    ${item.coach_message ? `
                        <div class="history-coach-msg" id="coach-msg-${item.id}">
                            <div class="history-coach-content markdown-body">${marked.parse(item.coach_message)}</div>
                        </div>
                    ` : ''}
                </div>
                <div class="history-card-actions">
                    ${item.coach_message ? `
                        <button class="history-expand-btn" data-id="${item.id}" title="Show coach analysis">
                            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="6 9 12 15 18 9"/></svg>
                        </button>
                    ` : ''}
                    <button class="history-delete-btn" data-id="${item.id}" title="Remove">
                        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                    </button>
                </div>
            </div>
        `;
    }

    async function toggleComplete(id, isCompleted) {
        try {
            const res = await fetch(`/api/history/${id}`, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                credentials: 'include',
                body: JSON.stringify({ is_completed: isCompleted })
            });
            if (!res.ok) throw new Error('Failed to update.');
            const card = document.getElementById(`hcard-${id}`);
            if (isCompleted) {
                card.classList.add('completed');
                showToast('Marked as completed! 🎉', 'success');
            } else {
                card.classList.remove('completed');
            }
            // Refresh stats
            loadHistory();
        } catch (err) {
            showToast(err.message, 'error');
        }
    }

    async function deleteHistoryItem(id) {
        try {
            const res = await fetch(`/api/history/${id}`, {
                method: 'DELETE', credentials: 'include'
            });
            if (!res.ok) throw new Error('Failed to delete.');
            const card = document.getElementById(`hcard-${id}`);
            if (card) {
                card.style.transition = 'all 0.3s ease';
                card.style.opacity = '0';
                card.style.transform = 'translateX(30px)';
                setTimeout(() => { card.remove(); loadHistory(); }, 300);
            }
            showToast('Problem removed from history.', 'info');
        } catch (err) {
            showToast(err.message, 'error');
        }
    }


    // ═══════════════════════════════════════════════════════════════
    // LEADERBOARD TAB
    // ═══════════════════════════════════════════════════════════════
    let lbDebounce = null;
    const lbSearch = document.getElementById('lb-search');

    if (lbSearch) {
        lbSearch.addEventListener('input', () => {
            clearTimeout(lbDebounce);
            lbDebounce = setTimeout(() => loadLeaderboard(lbSearch.value), 300);
        });
    }

    async function loadLeaderboard(search = '') {
        const podium   = document.getElementById('lb-podium');
        const tbody    = document.getElementById('lb-tbody');
        const myRankEl = document.getElementById('lb-my-rank');
        const emptyEl  = document.getElementById('lb-empty');
        const tableWrap = document.getElementById('lb-table-wrap');
        const loadEl   = document.getElementById('lb-loading');

        loadEl.classList.remove('hidden');
        tableWrap.classList.remove('hidden');

        try {
            const url = search.trim()
                ? `/api/leaderboard?search=${encodeURIComponent(search.trim())}`
                : '/api/leaderboard';
            const res = await fetch(url, { credentials: 'include' });
            if (!res.ok) throw new Error('Failed to load leaderboard.');
            const data = await res.json();

            const lb = data.leaderboard;
            const myHandle = data.my_handle;
            const myRank   = data.my_rank;

            if (lb.length === 0) {
                podium.innerHTML = '';
                tbody.innerHTML = '';
                myRankEl.classList.add('hidden');
                tableWrap.classList.add('hidden');
                emptyEl.classList.remove('hidden');
                return;
            }

            emptyEl.classList.add('hidden');

            // My rank card
            if (myRank && myHandle) {
                const myEntry = lb.find(e => e.cf_handle === myHandle);
                myRankEl.classList.remove('hidden');
                myRankEl.innerHTML = `
                    <div class="my-rank-left">
                        <span class="my-rank-number">#${myRank}</span>
                        <div>
                            <div class="my-rank-label">Your Ranking</div>
                            <div class="my-rank-handle">${myHandle}</div>
                        </div>
                    </div>
                    <span class="my-rank-score">${myEntry ? myEntry.score.toLocaleString() : '—'} pts</span>
                `;
            } else {
                myRankEl.classList.add('hidden');
            }

            // Podium (only top 3 with score > 0, only when not searching)
            const top3 = lb.filter(e => e.score > 0).slice(0, 3);
            if (top3.length >= 1 && !search.trim()) {
                const medals = ['🥇', '🥈', '🥉'];
                const classes = ['podium-gold', 'podium-silver', 'podium-bronze'];
                // Show in order: 2nd, 1st, 3rd for visual podium effect
                const order = top3.length >= 3 ? [1, 0, 2] : (top3.length === 2 ? [1, 0] : [0]);
                podium.innerHTML = order.map(i => {
                    const e = top3[i];
                    return `
                        <div class="podium-card ${classes[i]}">
                            <span class="podium-medal">${medals[i]}</span>
                            <span class="podium-handle">${e.cf_handle}</span>
                            <span class="podium-score">${e.score.toLocaleString()} pts</span>
                            <span class="podium-detail">${e.total_solves} solved · avg ${Math.round(e.avg_rating)}</span>
                        </div>
                    `;
                }).join('');
            } else {
                podium.innerHTML = '';
            }

            // Max score for bar width calculation
            const maxScore = lb.reduce((max, e) => Math.max(max, e.score), 1);

            // Table rows
            const medalMap = { 1: '🥇', 2: '🥈', 3: '🥉' };
            tbody.innerHTML = lb.map(e => {
                const isMe = e.cf_handle === myHandle;
                const medal = medalMap[e.rank] || '';
                const barWidth = Math.max(2, (e.score / maxScore) * 80);
                return `
                    <tr class="${isMe ? 'is-me' : ''}">
                        <td class="lb-rank-cell">${medal ? `<span class="rank-medal">${medal}</span>` : e.rank}</td>
                        <td class="lb-user-cell">${e.cf_handle}${isMe ? ' <span style="color:var(--accent);font-size:0.75rem;">(you)</span>' : ''}</td>
                        <td class="lb-rating-cell">${e.avg_rating > 0 ? Math.round(e.avg_rating) : '—'}</td>
                        <td class="lb-solves-cell">${e.total_solves}</td>
                        <td class="lb-score-cell">${e.score > 0 ? e.score.toLocaleString() : '—'}<span class="score-bar" style="width:${e.score > 0 ? barWidth : 0}px;"></span></td>
                    </tr>
                `;
            }).join('');

        } catch (err) {
            showToast(err.message, 'error');
        } finally {
            loadEl.classList.add('hidden');
        }
    }


    // ═══════════════════════════════════════════════════════════════
    // PIPELINE STEP ANIMATION
    // ═══════════════════════════════════════════════════════════════
    const stepIds = ['step-ml', 'step-retrieve', 'step-rank', 'step-present'];
    let stepInterval = null;

    function animatePipelineSteps() {
        let idx = 0;
        stepInterval = setInterval(() => {
            for (let i = 0; i < idx; i++) {
                const el = document.getElementById(stepIds[i]);
                if (el) { el.classList.remove('active'); el.classList.add('done'); }
            }
            if (idx < stepIds.length) {
                const el = document.getElementById(stepIds[idx]);
                if (el) { el.classList.add('active'); }
            }
            idx++;
            if (idx > stepIds.length) clearInterval(stepInterval);
        }, 2500);
    }

    function resetPipelineSteps() {
        if (stepInterval) clearInterval(stepInterval);
        for (let id of stepIds) {
            const el = document.getElementById(id);
            if (el) { el.classList.remove('active', 'done'); }
        }
    }
});
