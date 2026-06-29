/**
 * WebSocket connection management for real-time preview.
 */
class WSClient {
    constructor() {
        this.ws = null;
        this.sessionId = null;
        this.onMessage = null;
        this.onError = null;
        this.onClose = null;
    }

    connect(sessionId) {
        if (this.ws) {
            this.ws.close();
        }
        this.sessionId = sessionId;
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const url = `${protocol}//${window.location.host}/ws/${sessionId}`;
        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            console.log("WebSocket connected", sessionId);
        };

        this.ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            if (this.onMessage) this.onMessage(msg);
        };

        this.ws.onerror = (err) => {
            console.error("WebSocket error", err);
            if (this.onError) this.onError(err);
        };

        this.ws.onclose = () => {
            if (this.onClose) this.onClose();
        };
    }

    send(type, data) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
        this.ws.send(JSON.stringify({ type, data }));
    }

    sendClick(svgX, svgY, append, handle) {
        this.send("svg_click", { svg_x: svgX, svg_y: svgY, append, handle });
    }

    sendParams(params) {
        this.send("params_change", { params });
    }

    sendToggle(showGenerated) {
        this.send("toggle_preview", { show_generated: showGenerated });
    }

    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
    }
}

const wsClient = new WSClient();
