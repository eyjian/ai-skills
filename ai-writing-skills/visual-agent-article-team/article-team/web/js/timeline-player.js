/**
 * timeline-player.js — 回放控制器
 */
const TimelinePlayer = {
    _playing: false,
    _speed: 1,
    _eventIndex: 0,
    _totalEvents: 0,

    init() {
        this._bindControls();
    },

    _bindControls() {
        // 播放/暂停
        document.getElementById('btn-play-pause').addEventListener('click', () => {
            if (this._playing) this.pause();
            else this.play();
        });

        // 步进
        document.getElementById('btn-step-back').addEventListener('click', () => {
            wsClient.sendCommand({ action: 'step_backward' });
        });
        document.getElementById('btn-step-forward').addEventListener('click', () => {
            wsClient.sendCommand({ action: 'step_forward' });
        });

        // 倍速
        document.querySelectorAll('.speed-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                const speed = parseInt(btn.dataset.speed);
                this._speed = speed;
                document.querySelectorAll('.speed-btn').forEach(b => b.classList.remove('active'));
                btn.classList.add('active');
                wsClient.sendCommand({ action: 'speed', speed });
            });
        });

        // 时间线拖动
        const slider = document.getElementById('timeline-slider');
        slider.addEventListener('input', () => {
            // 拖动时暂停
            if (this._playing) this.pause();
        });
        slider.addEventListener('change', () => {
            const ratio = parseInt(slider.value) / 100;
            // 需要将 ratio 转换为 timestamp，这里用索引近似
            const targetIndex = Math.floor(ratio * this._totalEvents);
            // 通过 REST API 获取对应事件的 timestamp
            wsClient.sendCommand({ action: 'seek', index: targetIndex });
        });

        // 事件列表
        document.getElementById('btn-event-list').addEventListener('click', () => {
            document.getElementById('event-sidebar').classList.toggle('hidden');
        });
        document.getElementById('close-sidebar').addEventListener('click', () => {
            document.getElementById('event-sidebar').classList.add('hidden');
        });

        // 模式切换
        document.getElementById('mode-toggle').addEventListener('click', () => {
            if (wsClient.mode === 'live') {
                this.switchToReplay();
            } else {
                this.switchToLive();
            }
        });

        // 监听 WebSocket 进度事件
        wsClient.on('progress', (data) => this._onProgress(data));
        wsClient.on('replay_complete', () => this._onReplayComplete());
    },

    play() {
        this._playing = true;
        document.getElementById('btn-play-pause').textContent = '⏸️';
        if (wsClient.mode === 'replay') {
            wsClient.sendCommand({ action: 'play', speed: this._speed });
        }
    },

    pause() {
        this._playing = false;
        document.getElementById('btn-play-pause').textContent = '▶️';
        if (wsClient.mode === 'replay') {
            wsClient.sendCommand({ action: 'pause' });
        }
    },

    switchToReplay() {
        wsClient.disconnect();
        wsClient.connectReplay();
        document.getElementById('mode-toggle').querySelector('.mode-icon').textContent = '⏯️';
        document.getElementById('mode-toggle').querySelector('.mode-label').textContent = '回放';
    },

    switchToLive() {
        this.pause();
        wsClient.disconnect();
        wsClient.connectLive();
        document.getElementById('mode-toggle').querySelector('.mode-icon').textContent = '🔴';
        document.getElementById('mode-toggle').querySelector('.mode-label').textContent = '实时';
    },

    /** 更新事件列表侧边栏 */
    updateEventList(events) {
        const list = document.getElementById('event-list');
        list.innerHTML = '';
        this._totalEvents = events.length;

        const icons = {
            'team_created': '🏢',
            'agent_joined': '👋',
            'agent_activated': '🟢',
            'message_sent': '✉️',
            'message_read': '👁️',
            'agent_completed': '✅',
        };

        events.forEach((e, i) => {
            const item = document.createElement('div');
            item.className = 'event-item';
            item.dataset.index = i;

            const time = e.timestamp ? new Date(e.timestamp).toLocaleTimeString() : '';
            const icon = icons[e.event] || '📌';
            const desc = this._describeEvent(e);

            item.innerHTML = `
                <span class="event-icon">${icon}</span>
                <span class="event-time">${time}</span>
                <span class="event-desc">${desc}</span>
            `;

            item.addEventListener('click', () => {
                if (e.timestamp) {
                    wsClient.sendCommand({ action: 'seek', timestamp: e.timestamp });
                }
            });

            list.appendChild(item);
        });
    },

    _describeEvent(e) {
        const d = e.data || {};
        switch (e.event) {
            case 'team_created': return `团队创建: ${d.team_name || ''}`;
            case 'agent_joined': return `${d.agent_name} 加入`;
            case 'agent_activated': return `${d.agent_name} 开始工作`;
            case 'message_sent': return `${d.from} → ${d.to}: ${(d.summary || d.content || '').slice(0, 20)}`;
            case 'agent_completed': return `${d.agent_name} 完成`;
            default: return e.event;
        }
    },

    _onProgress(data) {
        this._eventIndex = data.index || 0;
        this._totalEvents = data.total || 0;

        // 更新进度条
        const slider = document.getElementById('timeline-slider');
        if (this._totalEvents > 0) {
            slider.value = Math.round((this._eventIndex / this._totalEvents) * 100);
        }

        // 更新时间显示
        document.getElementById('time-current').textContent = `${this._eventIndex}`;
        document.getElementById('time-total').textContent = `${this._totalEvents}`;

        // 高亮当前事件
        document.querySelectorAll('.event-item').forEach(item => {
            item.classList.toggle('active', parseInt(item.dataset.index) === this._eventIndex - 1);
        });
    },

    _onReplayComplete() {
        this._playing = false;
        document.getElementById('btn-play-pause').textContent = '▶️';
    },
};
