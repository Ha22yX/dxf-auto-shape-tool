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
        this._paramSeq = 0;
        this._activeParamSeq = null;
        this._paramsInFlight = false;
        this._pendingParams = null;
    }

    connect(sessionId) {
        if (this.ws) {
            this.ws.close();
        }
        this._resetParamQueue();
        this.sessionId = sessionId;
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const url = `${protocol}//${window.location.host}/ws/${sessionId}`;
        this.ws = new WebSocket(url);

        this.ws.onopen = () => {
            console.log("WebSocket connected", sessionId);
        };

        this.ws.onmessage = (event) => {
            const msg = JSON.parse(event.data);
            this._handleInternalMessage(msg);
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

    sendClick(svgX, svgY, append, tol) {
        this.send("svg_click", { svg_x: svgX, svg_y: svgY, append, tol });
    }

    sendHover(svgX, svgY, tol, requestId) {
        this.send("svg_hover", { svg_x: svgX, svg_y: svgY, tol, request_id: requestId });
    }

    sendParams(params) {
        if (this._paramsInFlight) {
            this._pendingParams = params;
            return;
        }
        this._sendParamsNow(params);
    }

    _sendParamsNow(params) {
        if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
            this._pendingParams = params;
            return;
        }
        this._paramsInFlight = true;
        this._activeParamSeq = ++this._paramSeq;
        this.ws.send(JSON.stringify({
            type: "params_change",
            data: { params, seq: this._activeParamSeq },
        }));
    }

    _handleInternalMessage(msg) {
        const data = msg.data || {};
        if (msg.type === "error") {
            this._resetParamQueue();
            return;
        }
        if (msg.type !== "preview_update" || data.params_seq === undefined) return;
        if (data.params_seq !== this._activeParamSeq) return;

        this._paramsInFlight = false;
        this._activeParamSeq = null;
        if (this._pendingParams) {
            const nextParams = this._pendingParams;
            this._pendingParams = null;
            data.stale_params_preview = true;
            this._sendParamsNow(nextParams);
        }
    }

    _resetParamQueue() {
        this._paramsInFlight = false;
        this._activeParamSeq = null;
        this._pendingParams = null;
    }

    sendToggle(showGenerated) {
        this.send("toggle_preview", { show_generated: showGenerated });
    }

    disconnect() {
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this._resetParamQueue();
    }
}

const wsClient = new WSClient();
