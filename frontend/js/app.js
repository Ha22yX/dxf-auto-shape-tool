/**
 * Main application orchestration.
 *
 * Upload returns the accurate base SVG (rendered once). Parameter/selection
 * changes flow over WebSocket and return lightweight overlay geometry — the
 * DXF is never mutated until "Save DXF" is clicked.
 */
const App = {
    sessionId: null,
    bounds: null,
    scale: 1,
    hoverInFlight: false,
    hoverPending: null,
    hoverTimer: null,
    hoverLastSentAt: 0,
    hoverActiveRequestId: null,
    apexPickMode: false,

    init() {
        this._bindUpload();
        this._bindViewer();
        this._bindParameters();
        this._bindActions();
        this._bindStatus();
    },

    _bindUpload() {
        const uploadBtn = document.getElementById("upload-btn");
        const fileInput = document.getElementById("file-input");

        uploadBtn.addEventListener("click", () => fileInput.click());

        fileInput.addEventListener("change", async (e) => {
            const file = e.target.files[0];
            if (!file) return;

            try {
                this._setLoading(true);
                const result = await API.upload(file);
                this.sessionId = result.session_id;
                this.bounds = result.bounds;
                this.scale = result.scale || 1;
                svgViewer.baseScale = this.scale;

                if (result.params) {
                    parameterPanel.setParams(result.params);
                }
                if (result.show_generated !== undefined) {
                    parameterPanel.setShowGenerated(result.show_generated);
                }

                svgViewer.setBaseSvg(result.base_svg);

                wsClient.connect(this.sessionId);
                wsClient.onMessage = (msg) => this._handleWsMessage(msg);
                wsClient.onError = () => this._showError("WebSocket 连接失败");

                this._updateStatus(result);
                this._setLoading(false);
                document.getElementById("save-btn").disabled = false;
                document.getElementById("clear-selection-btn").disabled = false;
            } catch (err) {
                this._showError(err.message);
                this._setLoading(false);
            }
        });
    },

    _bindViewer() {
        svgViewer.onClick = (evt) => {
            if (!this.sessionId) return;
            if (this.apexPickMode) {
                wsClient.sendApex(evt.svgX, evt.svgY);
                this._setApexPickMode(false);
                return;
            }
            wsClient.sendClick(evt.svgX, evt.svgY, evt.ctrlKey, evt.tol);
        };

        svgViewer.onMouseMove = (pt) => {
            if (this.bounds) {
                const wcsX = pt.x / this.scale + this.bounds.min[0];
                const wcsY = this.bounds.max[1] - pt.y / this.scale;
                document.getElementById("status-coords").textContent =
                    `坐标: ${wcsX.toFixed(1)}, ${wcsY.toFixed(1)}`;
            }
        };

        svgViewer.onHover = (evt) => {
            if (!this.sessionId) return;
            this._queueHover(evt);
        };
    },

    _bindParameters() {
        parameterPanel.onParamsChange = (params) => {
            if (!this.sessionId) return;
            wsClient.sendParams(params);
        };

        parameterPanel.onToggleChange = (showGenerated) => {
            if (!this.sessionId) return;
            wsClient.sendToggle(showGenerated);
        };
    },

    _bindActions() {
        const pickApexBtn = document.getElementById("pick-apex-btn");
        pickApexBtn.addEventListener("click", () => {
            if (!this.sessionId || pickApexBtn.disabled) return;
            this._setApexPickMode(!this.apexPickMode);
        });

        document.getElementById("save-btn").addEventListener("click", () => {
            if (!this.sessionId) return;
            const a = document.createElement("a");
            a.href = API.downloadUrl(this.sessionId);
            a.download = `generated_${this.sessionId.slice(0, 8)}.dxf`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
        });

        document
            .getElementById("clear-selection-btn")
            .addEventListener("click", () => {
                if (!this.sessionId) return;
                this._setApexPickMode(false);
                // Ask backend to clear selection by sending an explicit clear message.
                wsClient.send("clear_selection", {});
            });
    },

    _bindStatus() {
        document.getElementById("status-session").textContent = "未连接会话";
    },

    _handleWsMessage(msg) {
        const data = msg.data || {};
        if (msg.type === "preview_update") {
            const geometry = data.preview_geometry || {};
            svgViewer.setOverlay(geometry, data.show_generated);

            if (data.chain_info) {
                this._updateStatus({ chain_info: data.chain_info });
            }
            this._updateApexButton(data);
            if (data.generated_count !== undefined) {
                document.getElementById(
                    "status-generated",
                ).textContent = `生成圆: ${data.generated_count}`;
            }
        } else if (msg.type === "cleared") {
            svgViewer.setOverlay({}, true);
            svgViewer.clearHover();
            this._setApexPickMode(false);
            this._updateApexButton({ selected_chain: [] });
            this._updateStatus({
                chain_info: { segment_count: 0, total_length: 0 },
            });
            document.getElementById("status-generated").textContent = "生成圆: 0";
        } else if (msg.type === "hover_result") {
            this._completeHoverRequest(data.request_id);
            if (data.request_id !== undefined && data.request_id !== svgViewer._hoverRequestId) {
                return;
            }
            svgViewer.setHover(data.handle, data.path_d);
        } else if (msg.type === "hover_clear") {
            this._completeHoverRequest(data.request_id);
            if (data.request_id !== undefined && data.request_id !== svgViewer._hoverRequestId) {
                return;
            }
            svgViewer.clearHover();
        } else if (msg.type === "error") {
            this._showError(data.message || "发生错误");
        }
    },

    _updateStatus(result) {
        if (result.session_id) {
            document.getElementById(
                "status-session",
            ).textContent = `会话: ${result.session_id.slice(0, 8)}`;
        }
        if (result.chain_info) {
            const info = result.chain_info;
            document.getElementById(
                "status-selection",
            ).textContent = `已选边: ${info.segment_count} | 总长: ${info.total_length}`;
        }
    },

    _setLoading(show) {
        const container = document.getElementById("svg-container");
        if (show) {
            const div = document.createElement("div");
            div.className = "svg-loading";
            div.id = "svg-loading";
            div.textContent = "加载中...";
            container.appendChild(div);
        } else {
            const el = document.getElementById("svg-loading");
            if (el) el.remove();
        }
    },

    _completeHoverRequest(requestId) {
        if (
            requestId !== undefined
            && this.hoverActiveRequestId !== null
            && requestId !== this.hoverActiveRequestId
        ) {
            return;
        }
        this.hoverActiveRequestId = null;
        this.hoverInFlight = false;
        clearTimeout(this.hoverTimer);
        this.hoverTimer = null;
        if (this.hoverPending) {
            this._scheduleHoverSend();
        }
    },

    _queueHover(evt) {
        this.hoverPending = evt;
        if (this.hoverInFlight) return;
        this._scheduleHoverSend();
    },

    _scheduleHoverSend() {
        if (this.hoverTimer) return;
        const now = performance.now();
        const delay = Math.max(0, 45 - (now - this.hoverLastSentAt));
        this.hoverTimer = window.setTimeout(() => {
            this.hoverTimer = null;
            this._sendPendingHover();
        }, delay);
    },

    _sendPendingHover() {
        if (!this.sessionId || !this.hoverPending || this.hoverInFlight) return;
        const evt = this.hoverPending;
        this.hoverPending = null;
        this.hoverInFlight = true;
        this.hoverActiveRequestId = evt.requestId;
        this.hoverLastSentAt = performance.now();
        wsClient.sendHover(evt.svgX, evt.svgY, evt.tol, evt.requestId);
        this.hoverTimer = window.setTimeout(() => {
            this.hoverInFlight = false;
            this.hoverActiveRequestId = null;
            this.hoverTimer = null;
            if (this.hoverPending) {
                this._scheduleHoverSend();
            }
        }, 350);
    },

    _setApexPickMode(active) {
        this.apexPickMode = Boolean(active);
        svgViewer.setApexPickMode(this.apexPickMode);
        const btn = document.getElementById("pick-apex-btn");
        if (btn) {
            btn.classList.toggle("is-active", this.apexPickMode);
            btn.textContent = this.apexPickMode ? "点击线上顶点" : "选择顶点";
        }
    },

    _updateApexButton(data) {
        const btn = document.getElementById("pick-apex-btn");
        if (!btn) return;
        const hasSelection = Boolean(data.selected_chain && data.selected_chain.length);
        btn.disabled = !this.sessionId || !hasSelection;
        if (!hasSelection) {
            this._setApexPickMode(false);
        }
    },

    _showError(message) {
        console.error(message);
        alert(message);
    },
};

window.addEventListener("DOMContentLoaded", () => {
    App.init();
});
