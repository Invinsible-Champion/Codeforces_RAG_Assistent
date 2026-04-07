/**
 * CF Assist — Codeforces RAG Assistant
 * Main application logic: routing, state, chat, explorer, ingestion
 */

const API_BASE = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    ? 'http://localhost:8000'
    : '';

// ── State ──────────────────────────────────────────────────
const state = {
    currentView: 'chat',
    currentMode: 'chat',
    currentConversationId: null,
    conversations: [],
    messages: [],
    isStreaming: false,
    explorerPage: 1,
    explorerFilters: {},
};

// ── DOM Elements ───────────────────────────────────────────
const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

// ── Initialization ─────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initNavigation();
    initChat();
    initExplorer();
    initIngestion();
    initSidebar();
    loadConversations();
    loadStats();
});

// ── Navigation ─────────────────────────────────────────────
function initNavigation() {
    $$('.nav-item').forEach(btn => {
        btn.addEventListener('click', () => {
            const view = btn.dataset.view;
            switchView(view);
        });
    });
}

function switchView(view) {
    state.currentView = view;
    $$('.view').forEach(v => v.classList.remove('active'));
    $(`#${view}-view`).classList.add('active');
    $$('.nav-item').forEach(n => n.classList.remove('active'));
    $(`.nav-item[data-view="${view}"]`).classList.add('active');

    if (view === 'explorer') loadProblems();
    if (view === 'ingest') loadStats();
}

// ── Sidebar ────────────────────────────────────────────────
function initSidebar() {
    $('#sidebar-toggle').addEventListener('click', () => {
        $('#sidebar').classList.toggle('collapsed');
    });

    $('#new-chat-btn').addEventListener('click', () => {
        startNewChat();
    });
}

async function loadConversations() {
    try {
        const res = await fetch(`${API_BASE}/api/chat/conversations`);
        if (!res.ok) return;
        state.conversations = await res.json();
        renderConversationList();
    } catch (e) {
        console.log('Could not load conversations:', e);
    }
}

function renderConversationList() {
    const list = $('#conversation-list');
    const header = list.querySelector('.conversation-list-header');
    list.innerHTML = '';
    list.appendChild(header);

    state.conversations.forEach(conv => {
        const btn = document.createElement('button');
        btn.className = `conv-item${conv.id === state.currentConversationId ? ' active' : ''}`;
        btn.textContent = conv.title;
        btn.title = conv.title;
        btn.addEventListener('click', () => loadConversation(conv.id));
        list.appendChild(btn);
    });
}

async function loadConversation(conversationId) {
    try {
        const res = await fetch(`${API_BASE}/api/chat/conversations/${conversationId}`);
        if (!res.ok) return;
        const data = await res.json();

        state.currentConversationId = conversationId;
        state.messages = data.messages || [];

        // Switch to chat view
        switchView('chat');
        renderMessages();
        renderConversationList();
    } catch (e) {
        console.error('Error loading conversation:', e);
    }
}

function startNewChat() {
    state.currentConversationId = null;
    state.messages = [];
    switchView('chat');
    renderMessages();
    renderConversationList();
}

// ── Chat ───────────────────────────────────────────────────
function initChat() {
    const input = $('#chat-input');
    const sendBtn = $('#send-btn');

    // Auto-resize textarea
    input.addEventListener('input', () => {
        input.style.height = 'auto';
        input.style.height = Math.min(input.scrollHeight, 120) + 'px';
    });

    // Send on Enter (Shift+Enter for newline)
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    sendBtn.addEventListener('click', sendMessage);

    // Mode selector
    $$('.mode-btn').forEach(btn => {
        btn.addEventListener('click', () => {
            $$('.mode-btn').forEach(b => b.classList.remove('active'));
            btn.classList.add('active');
            state.currentMode = btn.dataset.mode;
        });
    });

    // Quick actions
    $$('.quick-action').forEach(btn => {
        btn.addEventListener('click', () => {
            input.value = btn.dataset.query;
            input.dispatchEvent(new Event('input'));
            sendMessage();
        });
    });
}

async function sendMessage() {
    const input = $('#chat-input');
    const query = input.value.trim();
    if (!query || state.isStreaming) return;

    // Clear welcome screen
    const welcome = $('#welcome-screen');
    if (welcome) welcome.remove();

    // Add user message
    addMessage('user', query);
    input.value = '';
    input.style.height = 'auto';

    // Disable input during streaming
    state.isStreaming = true;
    $('#send-btn').disabled = true;

    try {
        const response = await fetch(`${API_BASE}/api/chat`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                query,
                conversation_id: state.currentConversationId,
                mode: state.currentMode,
                stream: true,
            }),
        });

        if (!response.ok) {
            const err = await response.text();
            addMessage('assistant', `❌ Error: ${err}`);
            return;
        }

        // Check if SSE stream
        const contentType = response.headers.get('content-type') || '';

        if (contentType.includes('text/event-stream')) {
            await handleSSEStream(response);
        } else {
            // Non-streaming JSON response
            const data = await response.json();
            state.currentConversationId = data.conversation_id;

            let content = data.response;
            if (data.retrieved_problems?.length) {
                addMessage('assistant', content, data.retrieved_problems);
            } else {
                addMessage('assistant', content);
            }
        }
    } catch (e) {
        addMessage('assistant', `❌ Connection error: ${e.message}`);
    } finally {
        state.isStreaming = false;
        $('#send-btn').disabled = false;
        loadConversations();
    }
}

async function handleSSEStream(response) {
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let assistantContent = '';
    let retrievedProblems = [];
    let messageEl = null;

    // Show typing indicator
    const typingEl = createTypingIndicator();
    $('#chat-messages').appendChild(typingEl);
    scrollToBottom();

    try {
        while (true) {
            const { done, value } = await reader.read();
            if (done) break;

            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';

            for (const line of lines) {
                if (line.startsWith('event:')) {
                    var eventType = line.slice(6).trim();
                } else if (line.startsWith('data:')) {
                    const data = line.slice(5).trim();

                    if (eventType === 'metadata') {
                        try {
                            const meta = JSON.parse(data);
                            state.currentConversationId = meta.conversation_id;
                            retrievedProblems = meta.retrieved_problems || [];
                        } catch (e) { }
                    } else if (eventType === 'token') {
                        // Remove typing indicator on first token
                        if (typingEl.parentNode) typingEl.remove();

                        assistantContent += data;
                        if (!messageEl) {
                            messageEl = createStreamingMessage();
                            $('#chat-messages').appendChild(messageEl);
                        }
                        updateStreamingMessage(messageEl, assistantContent, retrievedProblems);
                        scrollToBottom();
                    } else if (eventType === 'done') {
                        if (typingEl.parentNode) typingEl.remove();
                    } else if (eventType === 'error') {
                        if (typingEl.parentNode) typingEl.remove();
                        addMessage('assistant', `❌ Error: ${data}`);
                    }
                }
            }
        }
    } catch (e) {
        console.error('SSE stream error:', e);
    }

    if (typingEl.parentNode) typingEl.remove();

    // Store final message
    if (assistantContent) {
        state.messages.push({
            role: 'assistant',
            content: assistantContent,
        });
    }
}

function addMessage(role, content, retrievedProblems = null) {
    state.messages.push({ role, content });
    const msgEl = createMessageElement(role, content, retrievedProblems);
    $('#chat-messages').appendChild(msgEl);
    scrollToBottom();
}

function createMessageElement(role, content, retrievedProblems = null) {
    const msg = document.createElement('div');
    msg.className = `message ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = role === 'user' ? '👤' : '✦';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    const roleLabel = document.createElement('div');
    roleLabel.className = 'message-role';
    roleLabel.textContent = role === 'user' ? 'You' : 'CF Assist';

    const body = document.createElement('div');
    body.className = 'message-body';

    if (role === 'assistant') {
        if (retrievedProblems?.length) {
            const badge = document.createElement('div');
            badge.className = 'retrieved-badge';
            badge.textContent = `📚 ${retrievedProblems.length} problems retrieved`;
            body.appendChild(badge);
        }
        body.innerHTML += renderMarkdown(content);
    } else {
        body.textContent = content;
    }

    contentDiv.appendChild(roleLabel);
    contentDiv.appendChild(body);
    msg.appendChild(avatar);
    msg.appendChild(contentDiv);

    return msg;
}

function createStreamingMessage() {
    const msg = document.createElement('div');
    msg.className = 'message assistant';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = '✦';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';

    const roleLabel = document.createElement('div');
    roleLabel.className = 'message-role';
    roleLabel.textContent = 'CF Assist';

    const body = document.createElement('div');
    body.className = 'message-body';
    body.id = 'streaming-body';

    contentDiv.appendChild(roleLabel);
    contentDiv.appendChild(body);
    msg.appendChild(avatar);
    msg.appendChild(contentDiv);

    return msg;
}

function updateStreamingMessage(messageEl, content, retrievedProblems) {
    const body = messageEl.querySelector('.message-body');
    let html = '';
    if (retrievedProblems?.length) {
        html += `<div class="retrieved-badge">📚 ${retrievedProblems.length} problems retrieved</div>`;
    }
    html += renderMarkdown(content);
    body.innerHTML = html;
}

function createTypingIndicator() {
    const msg = document.createElement('div');
    msg.className = 'message assistant';
    msg.innerHTML = `
        <div class="message-avatar">✦</div>
        <div class="message-content">
            <div class="message-role">CF Assist</div>
            <div class="message-body">
                <div class="typing-indicator">
                    <span></span><span></span><span></span>
                </div>
            </div>
        </div>
    `;
    return msg;
}

function renderMessages() {
    const container = $('#chat-messages');
    container.innerHTML = '';

    if (state.messages.length === 0) {
        // Show welcome screen
        container.innerHTML = `
            <div id="welcome-screen" class="welcome-screen">
                <div class="welcome-icon">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="url(#gradient)" stroke-width="1.5">
                        <defs>
                            <linearGradient id="gradient" x1="0%" y1="0%" x2="100%" y2="100%">
                                <stop offset="0%" style="stop-color:#8b5cf6"/>
                                <stop offset="100%" style="stop-color:#06b6d4"/>
                            </linearGradient>
                        </defs>
                        <polygon points="12 2 15.09 8.26 22 9.27 17 14.14 18.18 21.02 12 17.77 5.82 21.02 7 14.14 2 9.27 8.91 8.26 12 2"/>
                    </svg>
                </div>
                <h1 class="welcome-title">Codeforces RAG Assistant</h1>
                <p class="welcome-subtitle">Ask me anything about Codeforces problems — find problems by rating, tags, or topic, get explanations, hints, and recommendations.</p>
                <div class="quick-actions">
                    <button class="quick-action" data-query="Give me 5 greedy problems rated 1200">
                        <span class="qa-icon">🎯</span>
                        <span class="qa-text">1200 rated greedy problems</span>
                    </button>
                    <button class="quick-action" data-query="Explain the approach for a classic DP problem">
                        <span class="qa-icon">💡</span>
                        <span class="qa-text">Explain a DP approach</span>
                    </button>
                    <button class="quick-action" data-query="Give me a difficulty progression for graph problems starting from 800">
                        <span class="qa-icon">📈</span>
                        <span class="qa-text">Graph difficulty progression</span>
                    </button>
                    <button class="quick-action" data-query="What are some easy binary search problems for beginners?">
                        <span class="qa-icon">🔍</span>
                        <span class="qa-text">Beginner binary search</span>
                    </button>
                </div>
            </div>
        `;
        // Re-bind quick actions
        container.querySelectorAll('.quick-action').forEach(btn => {
            btn.addEventListener('click', () => {
                $('#chat-input').value = btn.dataset.query;
                $('#chat-input').dispatchEvent(new Event('input'));
                sendMessage();
            });
        });
        return;
    }

    state.messages.forEach(msg => {
        const el = createMessageElement(msg.role, msg.content);
        container.appendChild(el);
    });
    scrollToBottom();
}

function scrollToBottom() {
    const container = $('#chat-messages');
    container.scrollTop = container.scrollHeight;
}

function renderMarkdown(text) {
    if (!text) return '';
    try {
        if (typeof marked !== 'undefined') {
            marked.setOptions({
                breaks: true,
                gfm: true,
                highlight: function (code, lang) {
                    if (typeof hljs !== 'undefined' && lang && hljs.getLanguage(lang)) {
                        return hljs.highlight(code, { language: lang }).value;
                    }
                    return code;
                },
            });
            return marked.parse(text);
        }
    } catch (e) {
        console.error('Markdown render error:', e);
    }
    // Fallback: basic escaping + line breaks
    return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
}

// ── Explorer ───────────────────────────────────────────────
function initExplorer() {
    $('#apply-filters').addEventListener('click', () => {
        state.explorerPage = 1;
        loadProblems();
    });

    // Enter key in filter inputs
    ['filter-rating-min', 'filter-rating-max', 'filter-tags', 'filter-search'].forEach(id => {
        $(`#${id}`).addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                state.explorerPage = 1;
                loadProblems();
            }
        });
    });
}

async function loadProblems() {
    const grid = $('#problems-grid');
    grid.innerHTML = '<div class="empty-state"><div class="loading-spinner"></div><p>Loading problems...</p></div>';

    const params = new URLSearchParams();
    params.set('page', state.explorerPage);
    params.set('page_size', 20);

    const ratingMin = $('#filter-rating-min').value;
    const ratingMax = $('#filter-rating-max').value;
    const tags = $('#filter-tags').value;
    const search = $('#filter-search').value;

    if (ratingMin) params.set('rating_min', ratingMin);
    if (ratingMax) params.set('rating_max', ratingMax);
    if (tags) params.set('tags', tags);
    if (search) params.set('search', search);

    try {
        const res = await fetch(`${API_BASE}/api/problems?${params}`);
        if (!res.ok) throw new Error('Failed to load problems');
        const data = await res.json();

        if (data.problems.length === 0) {
            grid.innerHTML = `
                <div class="empty-state" style="grid-column: 1 / -1;">
                    <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                        <circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>
                    </svg>
                    <p>No problems found. Try adjusting your filters or ingest some problems first.</p>
                </div>
            `;
            $('#pagination').innerHTML = '';
            return;
        }

        grid.innerHTML = data.problems.map(p => createProblemCard(p)).join('');

        // Bind card clicks
        grid.querySelectorAll('.problem-card').forEach(card => {
            card.addEventListener('click', () => openProblemDetail(card.dataset.id));
        });

        // Render pagination
        renderPagination(data.total, data.page, data.page_size);
    } catch (e) {
        grid.innerHTML = `<div class="empty-state" style="grid-column: 1 / -1;"><p>Error loading problems: ${e.message}</p></div>`;
    }
}

function createProblemCard(problem) {
    const ratingClass = getRatingClass(problem.rating);
    const tags = (problem.tags || []).slice(0, 4).map(t => `<span class="tag-chip">${t}</span>`).join('');
    const moreTagsCount = (problem.tags || []).length - 4;
    const moreTags = moreTagsCount > 0 ? `<span class="tag-chip">+${moreTagsCount}</span>` : '';

    return `
        <div class="problem-card" data-id="${problem.id}">
            <div class="problem-card-header">
                <span class="problem-card-id">${problem.contest_id}${problem.problem_index}</span>
                <span class="rating-badge ${ratingClass}">${problem.rating || 'N/A'}</span>
            </div>
            <div class="problem-card-title">${escapeHtml(problem.name)}</div>
            <div class="problem-card-tags">${tags}${moreTags}</div>
            <div class="problem-card-footer">
                <span class="solved-count">✓ ${formatNumber(problem.solved_count || 0)} solved</span>
                <a class="problem-link" href="${problem.url}" target="_blank" onclick="event.stopPropagation()">Open on CF →</a>
            </div>
        </div>
    `;
}

function renderPagination(total, currentPage, pageSize) {
    const totalPages = Math.ceil(total / pageSize);
    const pagination = $('#pagination');

    if (totalPages <= 1) {
        pagination.innerHTML = '';
        return;
    }

    let html = '';
    html += `<button class="page-btn" ${currentPage <= 1 ? 'disabled' : ''} onclick="goToPage(${currentPage - 1})">← Prev</button>`;

    for (let i = 1; i <= Math.min(totalPages, 7); i++) {
        html += `<button class="page-btn ${i === currentPage ? 'active' : ''}" onclick="goToPage(${i})">${i}</button>`;
    }

    html += `<button class="page-btn" ${currentPage >= totalPages ? 'disabled' : ''} onclick="goToPage(${currentPage + 1})">Next →</button>`;

    pagination.innerHTML = html;
}

window.goToPage = function (page) {
    state.explorerPage = page;
    loadProblems();
};

async function openProblemDetail(problemId) {
    const modal = $('#problem-modal');
    const content = $('#problem-detail-content');
    modal.classList.remove('hidden');
    content.innerHTML = '<div class="empty-state"><div class="loading-spinner"></div><p>Loading problem...</p></div>';

    try {
        const res = await fetch(`${API_BASE}/api/problems/${problemId}`);
        if (!res.ok) throw new Error('Problem not found');
        const p = await res.json();
        const ratingClass = getRatingClass(p.rating);

        content.innerHTML = `
            <div class="problem-detail-title">${p.contest_id}${p.problem_index} — ${escapeHtml(p.name)}</div>
            <div class="problem-detail-meta">
                <div class="meta-item"><strong>Rating:</strong> <span class="rating-badge ${ratingClass}">${p.rating || 'N/A'}</span></div>
                <div class="meta-item"><strong>Time:</strong> ${p.time_limit || 'N/A'}</div>
                <div class="meta-item"><strong>Memory:</strong> ${p.memory_limit || 'N/A'}</div>
                <div class="meta-item"><strong>Solved:</strong> ${formatNumber(p.solved_count || 0)}</div>
            </div>
            <div class="problem-card-tags" style="margin-bottom: 20px;">
                ${(p.tags || []).map(t => `<span class="tag-chip">${t}</span>`).join('')}
            </div>
            ${p.statement_text ? `<div class="problem-detail-section"><h3>Statement</h3><p>${escapeHtml(p.statement_text)}</p></div>` : ''}
            ${p.input_spec ? `<div class="problem-detail-section"><h3>Input</h3><p>${escapeHtml(p.input_spec)}</p></div>` : ''}
            ${p.output_spec ? `<div class="problem-detail-section"><h3>Output</h3><p>${escapeHtml(p.output_spec)}</p></div>` : ''}
            ${p.sample_tests?.length ? `
                <div class="problem-detail-section">
                    <h3>Examples</h3>
                    ${p.sample_tests.map((t, i) => `
                        <pre style="margin-bottom: 8px;"><code><strong>Input ${i + 1}:</strong>\n${escapeHtml(t.input)}\n\n<strong>Output ${i + 1}:</strong>\n${escapeHtml(t.output)}</code></pre>
                    `).join('')}
                </div>
            ` : ''}
            ${p.note ? `<div class="problem-detail-section"><h3>Note</h3><p>${escapeHtml(p.note)}</p></div>` : ''}
            <div style="margin-top: 20px; display: flex; gap: 10px;">
                <a href="${p.url}" target="_blank" class="filter-apply-btn" style="text-decoration: none;">Open on Codeforces →</a>
                <button class="filter-apply-btn" style="background: var(--bg-tertiary); color: var(--text-primary);" onclick="askAboutProblem('${p.contest_id}${p.problem_index}', '${escapeHtml(p.name).replace(/'/g, "\\'")}')">💬 Ask about this</button>
            </div>
        `;
    } catch (e) {
        content.innerHTML = `<p>Error: ${e.message}</p>`;
    }
}

window.askAboutProblem = function (problemId, problemName) {
    $('#problem-modal').classList.add('hidden');
    switchView('chat');
    const query = `Explain the approach for problem ${problemId} (${problemName})`;
    $('#chat-input').value = query;
    sendMessage();
};

// Modal close handlers
$('#modal-close').addEventListener('click', () => {
    $('#problem-modal').classList.add('hidden');
});
$('.modal-backdrop').addEventListener('click', () => {
    $('#problem-modal').classList.add('hidden');
});

// ── Ingestion ──────────────────────────────────────────────
function initIngestion() {
    $('#start-ingest-btn').addEventListener('click', startIngestion);
}

async function startIngestion() {
    const btn = $('#start-ingest-btn');
    btn.disabled = true;

    const tags = $('#ingest-tags').value.trim();
    const ratingMin = $('#ingest-rating-min').value;
    const ratingMax = $('#ingest-rating-max').value;
    const limit = parseInt($('#ingest-limit').value) || 50;

    const payload = { limit };
    if (tags) payload.tags = tags.split(',').map(t => t.trim());
    if (ratingMin) payload.rating_min = parseInt(ratingMin);
    if (ratingMax) payload.rating_max = parseInt(ratingMax);

    try {
        const res = await fetch(`${API_BASE}/api/ingest/start`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        const data = await res.json();

        if (data.status === 'already_running') {
            alert('Ingestion is already running!');
            btn.disabled = false;
            return;
        }

        // Show status card and start polling
        $('#ingest-status-card').classList.remove('hidden');
        pollIngestionStatus();
    } catch (e) {
        alert(`Error starting ingestion: ${e.message}`);
        btn.disabled = false;
    }
}

async function pollIngestionStatus() {
    const poll = async () => {
        try {
            const res = await fetch(`${API_BASE}/api/ingest/status`);
            const status = await res.json();

            const percent = status.total > 0 ? Math.round((status.processed / status.total) * 100) : 0;
            $('#progress-fill').style.width = `${percent}%`;
            $('#progress-text').textContent = `${status.processed} / ${status.total}`;
            $('#progress-percent').textContent = `${percent}%`;
            $('#ingest-message').textContent = status.message;

            if (status.errors > 0) {
                $('#ingest-errors').classList.remove('hidden');
                $('#error-count').textContent = status.errors;
            }

            if (status.running) {
                setTimeout(poll, 2000);
            } else {
                $('#start-ingest-btn').disabled = false;
                loadStats();
            }
        } catch (e) {
            console.error('Status poll error:', e);
            setTimeout(poll, 3000);
        }
    };
    poll();
}

async function loadStats() {
    try {
        const res = await fetch(`${API_BASE}/api/problems/stats`);
        if (!res.ok) return;
        const stats = await res.json();

        // Update sidebar badge
        $('#stats-text').textContent = `${stats.embedded_problems} problems indexed`;

        // Update stats grid
        const grid = $('#db-stats');
        if (grid) {
            grid.innerHTML = `
                <div class="stat-item">
                    <div class="stat-value">${stats.total_problems}</div>
                    <div class="stat-label">Total Problems</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${stats.embedded_problems}</div>
                    <div class="stat-label">Embedded</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${stats.total_chunks}</div>
                    <div class="stat-label">Chunks</div>
                </div>
                <div class="stat-item">
                    <div class="stat-value">${stats.total_vectors}</div>
                    <div class="stat-label">Vectors</div>
                </div>
            `;
        }
    } catch (e) {
        console.log('Could not load stats:', e);
        $('#stats-text').textContent = 'Backend offline';
    }
}

// ── Helpers ────────────────────────────────────────────────
function getRatingClass(rating) {
    if (!rating) return 'rating-newbie';
    if (rating < 1200) return 'rating-newbie';
    if (rating < 1400) return 'rating-pupil';
    if (rating < 1600) return 'rating-specialist';
    if (rating < 1900) return 'rating-expert';
    if (rating < 2100) return 'rating-cm';
    if (rating < 2400) return 'rating-master';
    if (rating < 2600) return 'rating-gm';
    return 'rating-legendary';
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatNumber(num) {
    if (num >= 1000000) return (num / 1000000).toFixed(1) + 'M';
    if (num >= 1000) return (num / 1000).toFixed(1) + 'K';
    return num.toString();
}
