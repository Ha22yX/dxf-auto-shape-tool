/**
 * Main application orchestration.
 */
const App = {
    sessionId: null,
    generatedCount: 0,

    init() {
        this._bindUpload();
        this._bindViewer();
        this._bindSelector();
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
                this.generatedCount = 0;

                wsClient.connect(this.sessionId);
                wsClient.onMessage = (msg) => this._handleWsMessage(msg);
                wsClient.onError = (err) => this._showError("WebSocket 连接失败");

                const svg = await API.getSvg(this.sessionId, true);
                svgViewer.setSvg(svg);
                svgViewer.resetView();

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
            wsClient.sendClick(evt.svgX, evt.svgY, evt.ctrlKey, evt.handle);
        };

        svgViewer.onMouseMove = (pt) => {
            document.getElementById("status-coords").textContent =
                `坐标: ${pt.x.toFixed(1)}, ${pt.y.toFixed(1)}`;
        };
    },

    _bindSelector() {
        // Backend already highlights selected entities in the SVG it sends,
        // so no additional frontend highlighting is needed here.
        selector.onSelectionChange = (handles, chain) => {
            // State is updated; UI highlight comes from backend SVG.
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
                selector.clear();
                if (this.sessionId) {
                    wsClient.sendParams(parameterPanel.getParams());
                }
            });
    },

    _bindStatus() {
        document.getElementById("status-session").textContent = "未连接会话";
    },

    _handleWsMessage(msg) {
        const data = msg.data || {};
        if (msg.type === "svg_update") {
            if (data.svg_content) {
                svgViewer.setSvg(data.svg_content);
            }
            if (data.selected_chain) {
                selector.setSelection(
                    data.selected_handles || [],
                    data.selected_chain,
                );
            }
            if (data.chain_info) {
                this._updateStatus({ chain_info: data.chain_info });
            }
            if (data.generated_count !== undefined) {
                this.generatedCount = data.generated_count;
                document.getElementById(
                    "status-generated",
                ).textContent = `生成圆: ${this.generatedCount}`;
            }
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

    _showError(message) {
        console.error(message);
        alert(message);
    },
};

window.addEventListener("DOMContentLoaded", () => {
    App.init();
});
