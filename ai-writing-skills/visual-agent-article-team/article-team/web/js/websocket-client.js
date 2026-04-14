/**
 * websocket-client.js — WebSocket 连接管理
 */
class WebSocketClient {
    constructor() {
        this._ws = null;
        this._mode = 'live'; // 'live' | 'replay'
        this._listeners = {};
        this._reconnectTimer = null;
        this._reconnectDelay = 2000;
    }

    /** 注册事件监听 */
    on(event, callback) {
        if (!this._listeners[event]) this._listeners[event] = [];
        this._listeners[event].push(callback);
    }

    _emit(event, data) {
        (this._listeners[event] || []).forEach(cb => cb(data));
    }

    /** 连接到实时模式端点 */
    connectLive() {
        this._mode = 'live';
        this._connect('/ws/live');
    }

    /** 连接到回放模式端点 */
    connectReplay() {
        this._mode = 'replay';
        this._connect('/ws/replay');
    }

    /** 发送回放控制命令 */
    sendCommand(cmd) {
        if (this._ws && this._ws.readyState === WebSocket.OPEN) {
            this._ws.send(JSON.stringify(cmd));
        }
    }

    /** 断开连接 */
    disconnect() {
        if (this._reconnectTimer) {
            clearTimeout(this._reconnectTimer);
            this._reconnectTimer = null;
        }
        if (this._ws) {
            this._ws.close();
            this._ws = null;
        }
    }

    get mode() { return this._mode; }
    get connected() { return this._ws && this._ws.readyState === WebSocket.OPEN; }

    _connect(path) {
        this.disconnect();

        const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
        const url = `${protocol}//${location.host}${path}`;

        this._emit('connecting', { mode: this._mode });

        this._ws = new WebSocket(url);

        this._ws.onopen = () => {
            this._reconnectDelay = 2000;
            this._emit('connected', { mode: this._mode });
        };

        this._ws.onclose = () => {
            this._emit('disconnected', { mode: this._mode });
            // 自动重连（仅实时模式）
            if (this._mode === 'live') {
                this._reconnectTimer = setTimeout(() => {
                    this._connect(path);
                }, this._reconnectDelay);
                this._reconnectDelay = Math.min(this._reconnectDelay * 1.5, 30000);
            }
        };

        this._ws.onerror = () => {
            this._emit('error', { mode: this._mode });
        };

        this._ws.onmessage = (evt) => {
            try {
                const msg = JSON.parse(evt.data);
                this._emit('message', msg);

                // 按消息类型分发
                if (msg.type === 'event') {
                    this._emit('event', msg.event);
                } else if (msg.type === 'snapshot') {
                    this._emit('snapshot', msg.events);
                } else if (msg.type === 'connected') {
                    this._emit('server_connected', msg);
                } else if (msg.type === 'progress') {
                    this._emit('progress', msg);
                } else if (msg.type === 'replay_complete') {
                    this._emit('replay_complete', msg);
                } else if (msg.type === 'seek_complete') {
                    this._emit('seek_complete', msg);
                }
            } catch (e) {
                console.error('消息解析失败:', e);
            }
        };
    }
}

// 全局单例
window.wsClient = new WebSocketClient();
