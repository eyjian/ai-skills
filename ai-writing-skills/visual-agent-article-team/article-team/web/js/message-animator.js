/**
 * message-animator.js — 通信动画（纸飞机、气泡、飞线）
 * 支持三种消息类型：message（正式交付）、discussion（即时讨论）、notification（知会/FYI）
 */
const MessageAnimator = {
    _commLayer: null,
    _bubbleQueue: {}, // {agentName: [bubbleElement]}
    _commCounts: {},  // {from-to: count}

    init() {
        this._commLayer = document.getElementById('comm-layer');
    },

    /** 统一动画入口 — 根据消息类型分发不同动画 */
    animate(fromAgent, toAgent, summary, msgType = 'message') {
        switch (msgType) {
            case 'discussion':
                this._animateDiscussion(fromAgent, toAgent, summary);
                break;
            case 'notification':
                this._animateNotification(fromAgent, toAgent, summary);
                break;
            default:
                this._animateMessage(fromAgent, toAgent, summary);
                break;
        }
    },

    /** 正式交付动画 — ✉️ 纸飞机 + 实线弧线 */
    _animateMessage(fromAgent, toAgent, summary) {
        this._flyPaperPlane(fromAgent, toAgent, '✉️');
        this._drawCommLine(fromAgent, toAgent, 'message');
        setTimeout(() => {
            this._showSpeechBubble(toAgent, summary);
        }, 800);
        this._updateCommFrequency(fromAgent, toAgent);
    },

    /** 即时讨论动画 — 💬 对话气泡 + 虚线弧线 */
    _animateDiscussion(fromAgent, toAgent, summary) {
        this._flyPaperPlane(fromAgent, toAgent, '💬');
        this._drawCommLine(fromAgent, toAgent, 'discussion');
        setTimeout(() => {
            this._showSpeechBubble(toAgent, summary, 'discussion');
        }, 800);
        this._updateCommFrequency(fromAgent, toAgent);
    },

    /** 知会/FYI 动画 — 🔔 通知图标 + 点线弧线 */
    _animateNotification(fromAgent, toAgent, summary) {
        this._flyPaperPlane(fromAgent, toAgent, '🔔');
        this._drawCommLine(fromAgent, toAgent, 'notification');
        setTimeout(() => {
            this._showSpeechBubble(toAgent, summary, 'notification');
        }, 800);
        this._updateCommFrequency(fromAgent, toAgent);
    },

    /** 纸飞机飞行动画（支持不同图标） */
    _flyPaperPlane(from, to, icon = '✉️') {
        const fromPos = OfficeRenderer.getAgentPosition(from);
        const toPos = OfficeRenderer.getAgentPosition(to);
        if (!fromPos || !toPos) return;

        const plane = document.createElement('div');
        plane.className = 'paper-plane';
        plane.textContent = icon;
        plane.style.left = fromPos.x + 'px';
        plane.style.top = fromPos.y + 'px';

        // CSS 动画：移动到目标位置
        const dx = toPos.x - fromPos.x;
        const dy = toPos.y - fromPos.y;

        plane.style.transition = 'all 1.2s cubic-bezier(0.25, 0.1, 0.25, 1)';
        const scene = document.getElementById('office-scene');
        scene.appendChild(plane);

        requestAnimationFrame(() => {
            plane.style.left = toPos.x + 'px';
            plane.style.top = (toPos.y - 20) + 'px';
            plane.style.opacity = '0';
            plane.style.transform = `rotate(${Math.atan2(dy, dx) * 180 / Math.PI}deg)`;
        });

        setTimeout(() => plane.remove(), 1300);
    },

    /** SVG 飞线（支持三种样式） */
    _drawCommLine(from, to, lineType = 'message') {
        if (!this._commLayer) return;
        const fromPos = OfficeRenderer.getAgentPosition(from);
        const toPos = OfficeRenderer.getAgentPosition(to);
        if (!fromPos || !toPos) return;

        const fromInfo = OfficeRenderer.getAgentInfo(from);
        const toInfo = OfficeRenderer.getAgentInfo(to);
        const ns = 'http://www.w3.org/2000/svg';

        // 弧线路径
        const midX = (fromPos.x + toPos.x) / 2;
        const midY = (fromPos.y + toPos.y) / 2 - 30;
        const path = document.createElementNS(ns, 'path');
        path.setAttribute('d', `M${fromPos.x},${fromPos.y} Q${midX},${midY} ${toPos.x},${toPos.y}`);
        path.setAttribute('fill', 'none');
        path.setAttribute('stroke-opacity', '0');

        // 根据消息类型设置不同样式
        switch (lineType) {
            case 'discussion':
                // 虚线 — 混合色 — 较细
                path.setAttribute('stroke', this._blendColors(fromInfo.color || '#8B5CF6', toInfo.color || '#8B5CF6'));
                path.setAttribute('stroke-width', '1.5');
                path.setAttribute('stroke-dasharray', '5,5');
                path.style.animation = 'dashed-line-glow 2s ease forwards';
                break;
            case 'notification':
                // 点线 — 淡灰色 — 最细
                path.setAttribute('stroke', '#64748B');
                path.setAttribute('stroke-width', '1');
                path.setAttribute('stroke-dasharray', '2,4');
                path.style.animation = 'line-glow 2s ease forwards';
                break;
            default:
                // 实线 — 发送者颜色 — 标准粗细
                path.setAttribute('stroke', fromInfo.color || '#666');
                path.setAttribute('stroke-width', '2');
                path.style.animation = 'line-glow 2s ease forwards';
                break;
        }

        this._commLayer.appendChild(path);
        setTimeout(() => path.remove(), 2100);
    },

    /** 对话气泡（支持不同类型样式） */
    _showSpeechBubble(agentName, text, bubbleType = 'message') {
        if (!text || text === 'heartbeat') return;

        const pos = OfficeRenderer.getAgentPosition(agentName);
        if (!pos) return;

        const truncated = text.length > 30 ? text.slice(0, 30) + '...' : text;

        // 根据类型添加前缀图标
        const prefixes = { discussion: '💬 ', notification: '🔔 ', message: '' };
        const prefix = prefixes[bubbleType] || '';

        const bubble = document.createElement('div');
        bubble.className = `speech-bubble ${bubbleType !== 'message' ? 'speech-' + bubbleType : ''}`;
        bubble.textContent = prefix + truncated;
        bubble.style.left = (pos.x - 80) + 'px';
        bubble.style.top = (pos.y - 60) + 'px';

        // 检查是否已有气泡，堆叠
        const existing = this._bubbleQueue[agentName] || [];
        if (existing.length > 0) {
            bubble.style.top = (pos.y - 60 - existing.length * 30) + 'px';
        }
        if (existing.length >= 2) {
            // 移除最旧的
            const old = existing.shift();
            old.classList.add('fading');
            setTimeout(() => old.remove(), 500);
        }
        existing.push(bubble);
        this._bubbleQueue[agentName] = existing;

        const scene = document.getElementById('office-scene');
        scene.appendChild(bubble);

        // 3 秒后淡出
        setTimeout(() => {
            bubble.classList.add('fading');
            const idx = existing.indexOf(bubble);
            if (idx >= 0) existing.splice(idx, 1);
            setTimeout(() => bubble.remove(), 500);
        }, 3000);
    },

    /** 混合两种颜色 */
    _blendColors(c1, c2) {
        const parse = (c) => {
            const hex = c.replace('#', '');
            return [parseInt(hex.slice(0, 2), 16), parseInt(hex.slice(2, 4), 16), parseInt(hex.slice(4, 6), 16)];
        };
        try {
            const [r1, g1, b1] = parse(c1);
            const [r2, g2, b2] = parse(c2);
            const r = Math.round((r1 + r2) / 2);
            const g = Math.round((g1 + g2) / 2);
            const b = Math.round((b1 + b2) / 2);
            return `#${r.toString(16).padStart(2, '0')}${g.toString(16).padStart(2, '0')}${b.toString(16).padStart(2, '0')}`;
        } catch (e) {
            return '#8B5CF6'; // 默认紫色
        }
    },

    /** 通信频率 */
    _updateCommFrequency(from, to) {
        const key = [from, to].sort().join('-');
        this._commCounts[key] = (this._commCounts[key] || 0) + 1;
    },

    /** 兼容旧接口 */
    animateMessage(fromAgent, toAgent, summary) {
        this.animate(fromAgent, toAgent, summary, 'message');
    },

    /** 重置 */
    reset() {
        this._bubbleQueue = {};
        this._commCounts = {};
        if (this._commLayer) {
            this._commLayer.innerHTML = '';
        }
        document.querySelectorAll('.speech-bubble, .paper-plane').forEach(el => el.remove());
    },
};
