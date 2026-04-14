/**
 * app.js — 主逻辑：页面初始化、WebSocket 事件分发、模式切换
 */
const App = {
    _allEvents: [],
    _currentFilter: 'all',
    _autoScroll: true,

    init() {
        OfficeRenderer.init();
        MessageAnimator.init();
        TimelinePlayer.init();
        this._setupChatPanel();
        this._setupWebSocket();
        this._loadTeams();
    },

    /** 初始化聊天面板 */
    _setupChatPanel() {
        const msgContainer = document.getElementById('chat-messages');
        msgContainer.addEventListener('scroll', () => {
            const atBottom = msgContainer.scrollHeight - msgContainer.scrollTop - msgContainer.clientHeight < 50;
            this._autoScroll = atBottom;
            document.getElementById('scroll-bottom-btn').style.display = atBottom ? 'none' : 'block';
        });

        document.getElementById('scroll-bottom-btn').addEventListener('click', () => {
            msgContainer.scrollTop = msgContainer.scrollHeight;
            this._autoScroll = true;
        });
    },

    /** 设置 WebSocket 监听 */
    _setupWebSocket() {
        const statusDot = document.getElementById('connection-status');

        wsClient.on('connecting', () => {
            statusDot.className = 'status-dot connecting';
        });

        wsClient.on('connected', () => {
            statusDot.className = 'status-dot connected';
        });

        wsClient.on('disconnected', () => {
            statusDot.className = 'status-dot disconnected';
        });

        wsClient.on('snapshot', (events) => {
            this._allEvents = events;
            AgentController.restoreFromSnapshot(events);
            MessageAnimator.reset();
            this._rebuildChatPanel(events);
            TimelinePlayer.updateEventList(events);
        });

        wsClient.on('event', (event) => {
            this._allEvents.push(event);
            this._handleEvent(event, true);
            TimelinePlayer.updateEventList(this._allEvents);
        });

        // 默认连接实时模式
        wsClient.connectLive();
    },

    /** 加载团队信息 */
    async _loadTeams() {
        try {
            const resp = await fetch('/api/teams');
            const teams = await resp.json();
            if (teams.length > 0) {
                document.getElementById('team-name').textContent = teams[0].name;
            }
        } catch (e) {
            console.warn('加载团队信息失败:', e);
        }
    },

    /** 处理单个事件 */
    _handleEvent(event, animate = false) {
        AgentController.handleEvent(event);

        const type = event.event;
        const data = event.data || {};

        // 通信动画 — 根据消息类型分发不同动画
        if (type === 'message_sent' && animate) {
            const summary = data.summary || '';
            const msgType = data.type || 'message';
            if (summary !== 'heartbeat') {
                MessageAnimator.animate(data.from, data.to, summary, msgType);
            }
        }

        // 添加到聊天面板
        if (type === 'message_sent') {
            this._addChatMessage(event);
        } else if (['team_created', 'agent_joined', 'agent_completed'].includes(type)) {
            this._addSystemMessage(event);
        }
    },

    /** 重建聊天面板 */
    _rebuildChatPanel(events) {
        const container = document.getElementById('chat-messages');
        container.innerHTML = '';
        this._buildFilterButtons(events);

        events.forEach(e => {
            if (e.event === 'message_sent') {
                this._addChatMessage(e, false);
            } else if (['team_created', 'agent_joined', 'agent_completed'].includes(e.event)) {
                this._addSystemMessage(e, false);
            }
        });

        if (this._autoScroll) {
            container.scrollTop = container.scrollHeight;
        }
    },

    /** 构建过滤按钮 */
    _buildFilterButtons(events) {
        const filters = document.getElementById('chat-filters');
        filters.innerHTML = '';

        // 全部按钮
        const allBtn = document.createElement('button');
        allBtn.className = 'filter-btn active';
        allBtn.dataset.filter = 'all';
        allBtn.textContent = '全部';
        allBtn.addEventListener('click', () => {
            this._currentFilter = 'all';
            document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
            allBtn.classList.add('active');
            this._applyFilter();
        });
        filters.appendChild(allBtn);

        // 消息类型过滤按钮
        const typeFilters = [
            { key: 'type:message', label: '✉️ 正式', icon: '✉️' },
            { key: 'type:discussion', label: '💬 讨论', icon: '💬' },
            { key: 'type:notification', label: '🔔 知会', icon: '🔔' },
        ];
        typeFilters.forEach(tf => {
            const btn = document.createElement('button');
            btn.className = 'filter-btn filter-btn-type';
            btn.dataset.filter = tf.key;
            btn.textContent = tf.label;
            btn.addEventListener('click', () => {
                this._currentFilter = this._currentFilter === tf.key ? 'all' : tf.key;
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                if (this._currentFilter === 'all') {
                    allBtn.classList.add('active');
                } else {
                    btn.classList.add('active');
                }
                this._applyFilter();
            });
            filters.appendChild(btn);
        });

        // 分隔符
        const sep = document.createElement('span');
        sep.className = 'filter-separator';
        sep.textContent = '│';
        filters.appendChild(sep);

        // Agent 过滤按钮
        const agents = new Set();
        events.forEach(e => {
            if (e.data) {
                if (e.data.from) agents.add(e.data.from);
                if (e.data.to) agents.add(e.data.to);
            }
        });

        agents.forEach(name => {
            const info = OfficeRenderer.getAgentInfo(name);
            const btn = document.createElement('button');
            btn.className = 'filter-btn';
            btn.dataset.filter = name;
            btn.textContent = `${info.emoji} ${info.label}`;
            btn.addEventListener('click', () => {
                this._currentFilter = this._currentFilter === name ? 'all' : name;
                document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
                if (this._currentFilter === 'all') {
                    allBtn.classList.add('active');
                } else {
                    btn.classList.add('active');
                }
                this._applyFilter();
            });
            filters.appendChild(btn);
        });
    },

    /** 应用消息过滤 */
    _applyFilter() {
        document.querySelectorAll('.chat-bubble, .system-message').forEach(el => {
            if (this._currentFilter === 'all') {
                el.style.display = '';
            } else if (this._currentFilter.startsWith('type:')) {
                // 按消息类型过滤
                const filterType = this._currentFilter.replace('type:', '');
                const elType = el.dataset.msgtype || 'message';
                el.style.display = (elType === filterType) ? '' : 'none';
            } else {
                // 按 agent 过滤
                const from = el.dataset.from || '';
                const to = el.dataset.to || '';
                const agent = el.dataset.agent || '';
                el.style.display = (from === this._currentFilter || to === this._currentFilter || agent === this._currentFilter) ? '' : 'none';
            }
        });
    },

    /** 添加聊天消息 */
    _addChatMessage(event, animate = true) {
        const data = event.data || {};
        const summary = data.summary || '';

        // 跳过心跳消息
        if (summary === 'heartbeat') return;

        const container = document.getElementById('chat-messages');
        const fromInfo = OfficeRenderer.getAgentInfo(data.from);
        const toInfo = OfficeRenderer.getAgentInfo(data.to);
        const msgType = data.type || 'message';

        const bubble = document.createElement('div');
        // 根据消息类型添加不同 CSS class
        let cssClass = 'chat-bubble';
        if (data.type === 'broadcast') cssClass += ' broadcast';
        if (msgType === 'discussion') cssClass += ' discussion';
        if (msgType === 'notification') cssClass += ' notification';
        bubble.className = cssClass;
        bubble.dataset.from = data.from || '';
        bubble.dataset.to = data.to || '';
        bubble.dataset.msgtype = msgType;

        const time = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : '';
        const content = data.content || '';
        const isLong = content.length > 200;

        // 消息类型标签
        const typeLabels = { discussion: '<span class="msg-type-tag discussion-tag">💬 讨论</span>', notification: '<span class="msg-type-tag notification-tag">🔔 知会</span>' };
        const typeTag = typeLabels[msgType] || '';

        bubble.innerHTML = `
            <div class="avatar" style="background:${fromInfo.color}22; color:${fromInfo.color}">${fromInfo.emoji}</div>
            <div class="bubble-body">
                <div class="bubble-header">
                    <span class="sender-name" style="color:${fromInfo.color}">${fromInfo.label}</span>
                    <span class="arrow">→</span>
                    <span class="receiver-name">${toInfo.label}</span>
                    ${data.type === 'broadcast' ? '<span class="broadcast-tag">📢 广播</span>' : ''}
                    ${typeTag}
                    <span class="msg-time">${time}</span>
                </div>
                <div class="bubble-content${isLong ? ' collapsed' : ''}">${this._escapeHtml(content)}</div>
                ${isLong ? '<button class="expand-btn" onclick="App._toggleExpand(this)">展开</button>' : ''}
            </div>
        `;

        container.appendChild(bubble);

        if (this._autoScroll) {
            container.scrollTop = container.scrollHeight;
        }
    },

    /** 添加系统消息 */
    _addSystemMessage(event, animate = true) {
        const data = event.data || {};
        const container = document.getElementById('chat-messages');
        const msg = document.createElement('div');
        msg.className = 'system-message';
        msg.dataset.agent = data.agent_name || data.team_name || '';

        const icons = {
            'team_created': '🏢',
            'agent_joined': '👋',
            'agent_completed': '✅',
        };
        const icon = icons[event.event] || '📌';

        const descs = {
            'team_created': `团队 "${data.team_name}" 已创建`,
            'agent_joined': `${data.agent_name} 加入团队 (${data.role || ''})`,
            'agent_completed': `${data.agent_name} 已完成任务`,
        };

        msg.textContent = `${icon} ${descs[event.event] || event.event}`;
        container.appendChild(msg);

        if (this._autoScroll) {
            container.scrollTop = container.scrollHeight;
        }
    },

    /** 展开/折叠消息 */
    _toggleExpand(btn) {
        const content = btn.previousElementSibling;
        if (content.classList.contains('collapsed')) {
            content.classList.remove('collapsed');
            btn.textContent = '折叠';
        } else {
            content.classList.add('collapsed');
            btn.textContent = '展开';
        }
    },

    /** HTML 转义 */
    _escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML.replace(/\n/g, '<br>');
    },
};

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', () => App.init());
