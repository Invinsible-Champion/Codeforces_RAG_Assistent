document.addEventListener('DOMContentLoaded', () => {
    // Nav elements
    const navTabs = document.querySelectorAll('.nav-tab');
    const tabViews = document.querySelectorAll('.tab-view');
    const topHandleDisplay = document.getElementById('top-handle-display');

    // Global state
    let currentHandle = null;
    let currentUserProfile = null;

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

    // --- PRACTICE TAB: Get Problem ---
    const gpForm = document.getElementById('problem-form');

    gpForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const inputEl = document.getElementById('gp-handle');
        const handle = inputEl.value.trim();
        if (!handle) return;

        const loadingEl = document.getElementById('gp-loading');
        const errorEl = document.getElementById('gp-error');
        const resultArea = document.getElementById('gp-result-area');

        errorEl.classList.add('hidden');
        resultArea.classList.add('hidden');
        loadingEl.classList.remove('hidden');

        // Animate pipeline steps
        animatePipelineSteps();

        try {
            const res = await fetch('/api/get_problem', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ handle })
            });
            const data = await res.json();
            if (!res.ok) throw new Error(data.detail || data.error || 'Failed to fetch problem.');

            updateGlobalState(handle, data.profile);
            renderProblem(data.message, data.problem_details);
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.classList.remove('hidden');
        } finally {
            loadingEl.classList.add('hidden');
            resetPipelineSteps();
        }
    });

    // --- ANALYTICS TAB: Analyze Profile ---
    const profileSetupForm = document.getElementById('profile-handle-form');

    profileSetupForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const inputEl = document.getElementById('profile-setup-handle');
        const handle = inputEl.value.trim();
        if (!handle) return;

        const loadingEl = document.getElementById('profile-loading');
        const errorEl = document.getElementById('profile-error');

        errorEl.classList.add('hidden');
        loadingEl.classList.remove('hidden');

        try {
            const res = await fetch('/api/analyze', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ handle })
            });
            const data = await res.json();
            if (!res.ok || data.error) throw new Error(data.detail || data.error || 'Failed to analyze profile.');
            updateGlobalState(handle, data);
        } catch (err) {
            errorEl.textContent = err.message;
            errorEl.classList.remove('hidden');
        } finally {
            loadingEl.classList.add('hidden');
        }
    });

    // --- Shared State ---
    function updateGlobalState(handle, profileData) {
        currentHandle = handle;
        currentUserProfile = profileData;
        topHandleDisplay.textContent = handle;

        // Auto-fill other inputs
        document.getElementById('gp-handle').value = handle;
        document.getElementById('profile-setup-handle').value = handle;

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
        
        // Compute strength/weakness dynamically from metrics
        const prefKeys = ['math_pref','dp_pref','graph_pref','brute_pref','greedy_pref','binary_pref','cons_pref','datastruct_pref'];
        const prefLabels = {
            'math_pref': 'Math & Number Theory',
            'dp_pref': 'Dynamic Programming',
            'graph_pref': 'Graphs & Trees',
            'brute_pref': 'Brute Force & Implementation',
            'greedy_pref': 'Greedy & Two Pointers',
            'binary_pref': 'Binary Search',
            'cons_pref': 'Constructive & Strings',
            'datastruct_pref': 'Data Structures'
        };

        let maxKey = null, maxVal = -1;
        let minKey = null, minVal = Infinity;

        for (let k of prefKeys) {
            const val = p[k] || 0;
            if (val > maxVal) { maxVal = val; maxKey = k; }
            if (val < minVal) { minVal = val; minKey = k; }
        }

        document.getElementById('profile-strengths').textContent = maxKey ? prefLabels[maxKey] : 'N/A';
        document.getElementById('profile-weakness').textContent = minKey ? prefLabels[minKey] : 'N/A';
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

    // --- Pipeline Step Animation ---
    const stepIds = ['step-ml', 'step-retrieve', 'step-rank', 'step-present'];
    let stepInterval = null;

    function animatePipelineSteps() {
        let idx = 0;
        stepInterval = setInterval(() => {
            // Mark previous steps as done
            for (let i = 0; i < idx; i++) {
                const el = document.getElementById(stepIds[i]);
                if (el) { el.classList.remove('active'); el.classList.add('done'); }
            }
            // Mark current step as active
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
