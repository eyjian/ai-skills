/**
 * agent-controller.js — 角色状态控制器
 * 增强版：从心跳和消息中提取活动描述，推送到工位的活动气泡和日志
 */
const AgentController = {
    _states: {}, // {agentName: 'idle'|'active'|'completed'|'talking'}

    /** 处理事件，更新角色状态 */
    handleEvent(event) {
        const type = event.event;
        const data = event.data || {};

        switch (type) {
            case 'team_created':
                this._onTeamCreated(data);
                break;
            case 'agent_joined':
                this._onAgentJoined(data);
                break;
            case 'agent_activated':
                this._onAgentActivated(data);
                break;
            case 'message_sent':
                this._onMessageSent(data);
                break;
            case 'agent_completed':
                this._onAgentCompleted(data);
                break;
            case 'team_deleted':
                this._onTeamDeleted(data);
                break;
        }
    },

    /** 从快照恢复状态 */
    restoreFromSnapshot(events) {
        this.reset();
        events.forEach(e => this.handleEvent(e));
    },

    /** 重置所有状态 */
    reset() {
        this._states = {};
        document.querySelectorAll('.workstation').forEach(ws => {
            ws.classList.remove('active', 'completed', 'talking');
            ws.classList.add('idle');
            const badge = ws.querySelector('.completion-badge');
            if (badge) badge.remove();
        });
        // 重新初始化活动日志容器
        document.querySelectorAll('.agent-task-text').forEach(el => {
            el.innerHTML = '<div class="activity-log"></div>';
        });
    },

    _onTeamCreated(data) {
        const members = data.members || [];
        members.forEach(m => {
            const name = m.name || '';
            this._states[name] = 'idle';
            OfficeRenderer.setAgentState(name, 'idle');
        });
    },

    _onAgentJoined(data) {
        const name = data.agent_name;
        this._states[name] = 'idle';
        OfficeRenderer.setAgentState(name, 'idle');
        OfficeRenderer.pushActivity(name, `👋 已加入团队 (${data.role || ''})`);
    },

    _onAgentActivated(data) {
        const name = data.agent_name;
        this._states[name] = 'active';
        OfficeRenderer.setAgentState(name, 'active');
        OfficeRenderer.pushActivity(name, '⚡ 开始工作');
    },

    _onMessageSent(data) {
        const from = data.from;
        const to = data.to;
        const summary = data.summary || '';
        const content = data.content || '';
        const msgType = data.type || 'message';

        // ─── 1. 从心跳消息中提取步骤描述 ───
        if (summary === 'heartbeat') {
            const activity = this._extractHeartbeatActivity(content);
            if (activity && from) {
                OfficeRenderer.pushActivity(from, activity);
            }
            return; // 心跳不触发 talking 状态切换
        }

        // ─── 2. 短暂切换发送者为 talking 状态 ───
        if (from && this._states[from] === 'active') {
            OfficeRenderer.setAgentState(from, 'talking');
            setTimeout(() => {
                if (this._states[from] === 'active') {
                    OfficeRenderer.setAgentState(from, 'active');
                }
            }, 2000);
        }

        // ─── 3. 从正式消息中提取活动描述 ───
        if (from) {
            const activity = this._extractMessageActivity(from, to, summary, content, msgType);
            OfficeRenderer.pushActivity(from, activity);
        }

        // ─── 4. 接收者也显示一条收到消息的活动 ───
        if (to && to !== from) {
            const fromInfo = OfficeRenderer.getAgentInfo(from);
            const briefSummary = summary ? summary.slice(0, 15) : '新消息';
            OfficeRenderer.pushActivity(to, `📨 收到 ${fromInfo.label}: ${briefSummary}`);
        }
    },

    _onAgentCompleted(data) {
        const name = data.agent_name;
        this._states[name] = 'completed';
        OfficeRenderer.setAgentState(name, 'completed');
        OfficeRenderer.pushActivity(name, '🎉 任务完成！');
        OfficeRenderer.showCompletion(name);
    },

    _onTeamDeleted(data) {
        // 兜底：将所有未 completed 的 agent 标记为 completed
        for (const [name, state] of Object.entries(this._states)) {
            if (state !== 'completed') {
                this._states[name] = 'completed';
                OfficeRenderer.setAgentState(name, 'completed');
                OfficeRenderer.pushActivity(name, '🎉 任务完成！');
                OfficeRenderer.showCompletion(name);
            }
        }
    },

    /**
     * 从心跳内容中提取活动描述
     * 心跳格式: "💓 {步骤描述}"
     */
    _extractHeartbeatActivity(content) {
        if (!content) return null;
        // 去掉 💓 前缀
        let text = content.replace(/^💓\s*/, '').trim();
        if (!text) return null;
        // 截断过长文本
        if (text.length > 40) text = text.slice(0, 40) + '...';
        return '💓 ' + text;
    },

    /**
     * 从正式消息中提取活动描述
     */
    _extractMessageActivity(from, to, summary, content, msgType) {
        const toInfo = OfficeRenderer.getAgentInfo(to);
        const toLabel = toInfo.label || to;

        // shutdown_request
        if (msgType === 'shutdown_request') {
            return `🔌 收到关闭请求`;
        }

        // 根据消息类型选择图标
        const icons = { discussion: '💬', notification: '🔔', message: '📤' };
        const icon = icons[msgType] || '📤';

        // 有 summary 的消息，优先用 summary
        if (summary) {
            const briefSummary = summary.length > 25 ? summary.slice(0, 25) + '...' : summary;
            return `${icon} → ${toLabel}: ${briefSummary}`;
        }

        // 从 content 前几十个字符提取关键信息
        if (content) {
            const firstLine = content
                .replace(/^#+\s*/gm, '')
                .replace(/^\s*[-*]\s*/gm, '')
                .replace(/\[STATUS:.*?\]/g, '')
                .split('\n')
                .map(l => l.trim())
                .filter(l => l.length > 0)[0] || '';

            if (firstLine) {
                const brief = firstLine.length > 25 ? firstLine.slice(0, 25) + '...' : firstLine;
                return `${icon} → ${toLabel}: ${brief}`;
            }
        }

        return `${icon} → ${toLabel}`;
    },

    getState(agentName) {
        return this._states[agentName] || 'idle';
    },
};
