/**
 * office-renderer.js — 虚拟办公室渲染器
 */
const OfficeRenderer = {
    AGENTS: {
        'team-lead': { emoji: '🧭', label: 'main', color: '#3B82F6', svg: 'agent-main.svg' },
        'scout':     { emoji: '🔎', label: 'scout', color: '#10B981', svg: 'agent-scout.svg' },
        'architect': { emoji: '📐', label: 'architect', color: '#8B5CF6', svg: 'agent-architect.svg' },
        'writer':    { emoji: '📝', label: 'writer', color: '#F59E0B', svg: 'agent-writer.svg' },
        'reviewer':  { emoji: '🛡️', label: 'reviewer', color: '#EF4444', svg: 'agent-reviewer.svg' },
        'polisher':  { emoji: '✨', label: 'polisher', color: '#EAB308', svg: 'agent-polisher.svg' },
    },

    // 活动日志缓存: {agentName: [{text, time}]}
    _activityLogs: {},
    // 活动气泡定时器: {agentName: timerId}
    _bubbleTimers: {},
    MAX_LOG_ITEMS: 3,

    /** 初始化办公室场景 */
    init() {
        this._loadSVGs();
        this._setupResize();
        this._initActivityLogs();
        // 所有工位初始为 idle
        document.querySelectorAll('.workstation').forEach(ws => {
            ws.classList.add('idle');
        });
    },

    /** 初始化活动日志容器 */
    _initActivityLogs() {
        document.querySelectorAll('.agent-task-text').forEach(el => {
            el.innerHTML = '<div class="activity-log"></div>';
        });
    },

    /** 加载 SVG 角色到各工位 */
    _loadSVGs() {
        for (const [agentId, info] of Object.entries(this.AGENTS)) {
            const charEl = document.querySelector(`[data-agent="${agentId}"] .agent-character`);
            if (charEl) {
                charEl.textContent = info.emoji;
                fetch(`/static/svg/${info.svg}`)
                    .then(r => r.text())
                    .then(svg => {
                        charEl.innerHTML = svg;
                        charEl.style.fontSize = '';
                    })
                    .catch(() => {});
            }
        }
    },

    /** 设置分隔条拖动 */
    _setupResize() {
        const handle = document.getElementById('resize-handle');
        const office = document.getElementById('office-area');
        const chat = document.getElementById('chat-panel');
        let dragging = false;

        handle.addEventListener('mousedown', (e) => {
            dragging = true;
            e.preventDefault();
        });

        document.addEventListener('mousemove', (e) => {
            if (!dragging) return;
            const container = document.getElementById('main-content');
            const rect = container.getBoundingClientRect();
            const ratio = (e.clientY - rect.top) / rect.height;
            const clamped = Math.max(0.3, Math.min(0.8, ratio));
            office.style.flex = clamped * 10;
            chat.style.flex = (1 - clamped) * 10;
        });

        document.addEventListener('mouseup', () => { dragging = false; });
    },

    /** 设置工位状态 */
    setAgentState(agentName, state) {
        const mapping = { 'main': 'team-lead', 'team-lead': 'team-lead' };
        const dataAgent = mapping[agentName] || agentName;
        const ws = document.querySelector(`[data-agent="${dataAgent}"]`);
        if (!ws) return;

        ws.classList.remove('idle', 'active', 'completed', 'talking');
        ws.classList.add(state);

        const lamp = ws.querySelector('.desk-lamp');
        if (lamp) {
            lamp.classList.toggle('on', state === 'active' || state === 'completed');
        }

        const light = ws.querySelector('.status-light');
        if (light) {
            light.classList.toggle('active', state !== 'idle');
        }
    },

    /** 设置工位任务文本（简单覆盖，用于静态状态如"已完成"） */
    setAgentTask(agentName, text) {
        const mapping = { 'main': 'team-lead', 'team-lead': 'team-lead' };
        const dataAgent = mapping[agentName] || agentName;
        const taskEl = document.querySelector(`[data-agent="${dataAgent}"] .agent-task-text`);
        if (!taskEl) return;

        const logContainer = taskEl.querySelector('.activity-log');
        if (logContainer) {
            logContainer.innerHTML = `<div class="activity-log-item">${this._escapeHtml(text)}</div>`;
        } else {
            taskEl.textContent = text;
        }
    },

    /**
     * 推送一条活动到工位（核心新功能）
     * - 工位上方弹出带配色的活动气泡（4秒后消失）
     * - 工位下方活动日志向上滚动追加，最多保留3条
     */
    pushActivity(agentName, text) {
        if (!text) return;
        const mapping = { 'main': 'team-lead', 'team-lead': 'team-lead' };
        const dataAgent = mapping[agentName] || agentName;

        // 1. 更新活动日志（向上滚动）
        this._pushLogItem(dataAgent, text);

        // 2. 弹出活动气泡
        this._showActivityBubble(dataAgent, agentName, text);
    },

    /** 活动日志：向上滚动追加 */
    _pushLogItem(dataAgent, text) {
        const taskEl = document.querySelector(`[data-agent="${dataAgent}"] .agent-task-text`);
        if (!taskEl) return;

        let logContainer = taskEl.querySelector('.activity-log');
        if (!logContainer) {
            taskEl.innerHTML = '<div class="activity-log"></div>';
            logContainer = taskEl.querySelector('.activity-log');
        }

        // 缓存
        if (!this._activityLogs[dataAgent]) this._activityLogs[dataAgent] = [];
        this._activityLogs[dataAgent].unshift({ text, time: Date.now() });
        if (this._activityLogs[dataAgent].length > this.MAX_LOG_ITEMS) {
            this._activityLogs[dataAgent].pop();
        }

        // 重绘日志
        logContainer.innerHTML = '';
        this._activityLogs[dataAgent].forEach((item, i) => {
            const el = document.createElement('div');
            el.className = 'activity-log-item';
            el.textContent = item.text;
            if (i === 0) el.style.animation = 'log-slide-in 0.3s ease';
            logContainer.appendChild(el);
        });
    },

    /** 活动气泡：工位上方弹出 */
    _showActivityBubble(dataAgent, agentName, text) {
        const ws = document.querySelector(`[data-agent="${dataAgent}"]`);
        if (!ws) return;

        // 移除已有气泡
        const existing = ws.querySelector('.activity-bubble');
        if (existing) {
            existing.remove();
        }
        // 清除上一个定时器
        if (this._bubbleTimers[dataAgent]) {
            clearTimeout(this._bubbleTimers[dataAgent]);
        }

        const info = this.getAgentInfo(agentName);
        const truncated = text.length > 35 ? text.slice(0, 35) + '...' : text;

        const bubble = document.createElement('div');
        bubble.className = 'activity-bubble';
        bubble.style.borderColor = info.color;
        bubble.style.borderLeftWidth = '3px';
        bubble.innerHTML = `<span style="color:${info.color};font-weight:600;">${info.emoji}</span> ${this._escapeHtml(truncated)}`;

        ws.style.position = 'relative';
        ws.appendChild(bubble);

        // 4秒后淡出移除
        this._bubbleTimers[dataAgent] = setTimeout(() => {
            bubble.classList.add('fading-out');
            setTimeout(() => bubble.remove(), 300);
        }, 4000);
    },

    /** 显示完成标记 */
    showCompletion(agentName) {
        const mapping = { 'main': 'team-lead', 'team-lead': 'team-lead' };
        const dataAgent = mapping[agentName] || agentName;
        const ws = document.querySelector(`[data-agent="${dataAgent}"]`);
        if (!ws) return;

        let badge = ws.querySelector('.completion-badge');
        if (!badge) {
            badge = document.createElement('div');
            badge.className = 'completion-badge';
            badge.textContent = '✅';
            ws.appendChild(badge);
        }
    },

    /** 获取工位的页面中心坐标 */
    getAgentPosition(agentName) {
        const mapping = { 'main': 'team-lead', 'team-lead': 'team-lead' };
        const dataAgent = mapping[agentName] || agentName;
        const ws = document.querySelector(`[data-agent="${dataAgent}"]`);
        if (!ws) return null;
        const rect = ws.getBoundingClientRect();
        const scene = document.getElementById('office-scene').getBoundingClientRect();
        return {
            x: rect.left + rect.width / 2 - scene.left,
            y: rect.top + rect.height / 2 - scene.top,
        };
    },

    /** 获取角色信息 */
    getAgentInfo(name) {
        const mapping = { 'main': 'team-lead', 'team-lead': 'team-lead' };
        const key = mapping[name] || name;
        return this.AGENTS[key] || { emoji: '👤', label: name, color: '#666' };
    },

    _escapeHtml(text) {
        const d = document.createElement('div');
        d.textContent = text;
        return d.innerHTML;
    },
};
