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
    safetyBlocked: false,
    previewLoadingReasons: new Set(),

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

                svgViewer.setBaseSvg(result.base_svg, result.hover_paths || []);

                wsClient.connect(this.sessionId);
                wsClient.onMessage = (msg) => this._handleWsMessage(msg);
                wsClient.onError = () => this._showError(I18n.t("websocketFailed"));

                this._updateGeometryNotice({});
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
            if (wsClient.sendClick(evt.svgX, evt.svgY, evt.ctrlKey, evt.tol, evt.hoverHandle)) {
                this._showPreviewLoading("selecting", "selection");
            }
        };

        svgViewer.onMouseMove = (pt) => {
            if (this.bounds) {
                const wcsX = pt.x / this.scale + this.bounds.min[0];
                const wcsY = this.bounds.max[1] - pt.y / this.scale;
                I18n.setText("status-coords", "coordinates", { x: wcsX.toFixed(1), y: wcsY.toFixed(1) });
            }
        };

        svgViewer.onHover = null;
    },

    _bindParameters() {
        // Generated geometry is rendered only from backend preview_geometry.
        // This keeps the web preview identical to the saved DXF geometry.
        parameterPanel.onParamsPreview = null;

        parameterPanel.onParamsChange = (params) => {
            if (!this.sessionId) return;
            this._showPreviewLoading("calculating", "params");
            wsClient.sendParams(params);
        };

        parameterPanel.onToggleChange = (showGenerated) => {
            if (!this.sessionId) return;
            wsClient.sendToggle(showGenerated);
        };

        parameterPanel.onAirDuctCompareChange = (enabled) => {
            svgViewer.setAirDuctCompareMode(enabled);
        };

        parameterPanel.onGuideChange = (key, visible, params) => {
            if (
                key === "capsule_axis_gap_above_distance"
                || key === "capsule_axis_gap_below_distance"
            ) {
                svgViewer.setCapsuleGapGuideVisible(visible, params);
            }
        };
    },

    _bindActions() {
        document.getElementById("save-btn").addEventListener("click", async () => {
            if (!this.sessionId) return;
            const saveBtn = document.getElementById("save-btn");
            try {
                saveBtn.disabled = true;
                this._showPreviewLoading("saving", "save");
                const synced = await API.updateParams(this.sessionId, parameterPanel.getParams());
                if (synced.preview_geometry) {
                    svgViewer.setOverlay(synced.preview_geometry, parameterPanel.getShowGenerated());
                    this._updateGeometryNotice(synced.preview_geometry);
                    if (this.safetyBlocked) throw new Error(I18n.t(`outline_${synced.preview_geometry.safety.status}`));
                    if (synced.chain_info) {
                        this._updateStatus({ chain_info: synced.chain_info });
                    }
                }
                const blob = await API.download(this.sessionId);
                const url = URL.createObjectURL(blob);
                const a = document.createElement("a");
                a.href = url;
                a.download = `generated_${this.sessionId.slice(0, 8)}.dxf`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            } catch (err) {
                this._showError(err.message || I18n.t("downloadFailed"));
            } finally {
                this._hidePreviewLoading("save");
                saveBtn.disabled = this.safetyBlocked;
            }
        });

        document
            .getElementById("clear-selection-btn")
            .addEventListener("click", () => {
                if (!this.sessionId) return;
                // Ask backend to clear selection by sending an explicit clear message.
                if (wsClient.send("clear_selection", {})) {
                    this._showPreviewLoading("clearing", "selection");
                }
            });
    },

    _bindStatus() {
        I18n.setText("status-session", "disconnected");
    },

    _handleWsMessage(msg) {
        const data = msg.data || {};
        if (msg.type === "preview_update") {
            if (data.stale_params_preview) return;
            const geometry = data.preview_geometry || {};
            svgViewer.setOverlay(geometry, data.show_generated);
            this._updateGeometryNotice(geometry);
            if (data.params_seq !== undefined) {
                this._hidePreviewLoading("params");
            }
            this._hidePreviewLoading("selection");

            if (data.chain_info) {
                this._updateStatus({ chain_info: data.chain_info });
            }
            if (data.generated_count !== undefined) {
                I18n.setText("status-generated", "generated", { count: data.generated_count });
            }
        } else if (msg.type === "cleared") {
            svgViewer.setOverlay({}, true);
            this._updateGeometryNotice({});
            svgViewer.clearHover();
            this._hidePreviewLoading("selection");
            this._updateStatus({
                chain_info: { segment_count: 0, total_length: 0 },
            });
            I18n.setText("status-generated", "generated", { count: 0 });
        } else if (msg.type === "hover_result") {
            if (data.request_id !== undefined && data.request_id !== svgViewer._hoverRequestId) {
                return;
            }
            svgViewer.setHover(data.handle, data.path_d);
        } else if (msg.type === "hover_clear") {
            if (data.request_id !== undefined && data.request_id !== svgViewer._hoverRequestId) {
                return;
            }
            svgViewer.clearHover();
        } else if (msg.type === "no_selection") {
            this._hidePreviewLoading("selection");
            return;
        } else if (msg.type === "error") {
            this._hidePreviewLoading();
            this._showError(data.message || I18n.t("genericError"));
        }
    },

    _updateGeometryNotice(geometry) {
        const safety = geometry.safety || {};
        this.safetyBlocked = Boolean(safety.blocked);
        const notice = document.getElementById("geometry-notice");
        const count = safety.boundary_rejected_count || 0;
        const repaired = safety.repaired_edge_count || 0;
        notice.hidden = !this.safetyBlocked && count === 0 && repaired === 0;
        notice.dataset.tone = this.safetyBlocked ? "warning" : "info";
        if (this.safetyBlocked) {
            I18n.setText(notice, `outline_${safety.status}`);
        } else if (repaired > 0) {
            I18n.setText(notice, count > 0 ? "autoClosedFiltered" : "autoClosed", { repaired, length: safety.repair_total_length, count });
        } else if (count > 0) {
            I18n.setText(notice, "boundaryFiltered", { count });
        }
        document.getElementById("save-btn").disabled = !this.sessionId || this.safetyBlocked;
    },

    _updateStatus(result) {
        if (result.session_id) {
            I18n.setText("status-session", "session", { id: result.session_id.slice(0, 8) });
        }
        if (result.chain_info) {
            const info = result.chain_info;
            I18n.setText("status-selection", "selection", { count: info.segment_count, length: info.total_length });
        }
    },

    _setLoading(show) {
        if (show) {
            this._showPreviewLoading("loading", "global");
        } else {
            this._hidePreviewLoading("global");
        }
    },

    _showPreviewLoading(text = "calculating", reason = "global") {
        this.previewLoadingReasons.add(reason);
        const overlay = this._ensurePreviewLoading();
        const label = document.getElementById("preview-loading-text");
        I18n.setText(label, text);
        if (overlay) overlay.classList.add("is-visible");
    },

    _hidePreviewLoading(reason = null) {
        if (reason) {
            this.previewLoadingReasons.delete(reason);
        } else {
            this.previewLoadingReasons.clear();
        }
        if (this.previewLoadingReasons.size > 0) return;
        const overlay = document.getElementById("preview-loading");
        if (overlay) overlay.classList.remove("is-visible");
    },

    _ensurePreviewLoading() {
        let overlay = document.getElementById("preview-loading");
        if (overlay) return overlay;

        const container = document.getElementById("svg-container");
        if (!container) return null;

        overlay = document.createElement("div");
        overlay.id = "preview-loading";
        overlay.className = "preview-loading";
        overlay.setAttribute("aria-hidden", "true");
        overlay.innerHTML = `
            <div class="preview-loading-indicator">
                <span class="preview-loading-spinner"></span>
                <span id="preview-loading-text" data-i18n="calculating">${I18n.t("calculating")}</span>
            </div>
        `;
        container.appendChild(overlay);
        return overlay;
    },

    _showError(message) {
        console.error(message);
        alert(I18n.error(message));
    },
};

window.App = App;

window.addEventListener("DOMContentLoaded", () => {
    App.init();
});

