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
    previewLoadingReasons: new Set(),
    previewLoadingLabels: new Map(),
    chainInfo: { segment_count: 0, total_length: 0 },
    generatedCount: 0,
    currentCoords: null,
    versionStatus: null,

    init() {
        this._bindLanguage();
        this._bindUpload();
        this._bindViewer();
        this._bindParameters();
        this._bindActions();
        this._bindStatus();
        this._bindVersion();
    },

    _bindLanguage() {
        if (!window.I18N) return;

        const language = window.I18N.init();
        const select = document.getElementById("language-select");
        if (select) {
            select.value = language;
            select.addEventListener("change", () => {
                window.I18N.setLanguage(select.value);
            });
        }

        window.addEventListener("i18n:change", () => {
            this._renderStatus();
            this._renderVersionStatus();
            this._refreshLoadingText();
        });
    },

    _t(key, values = {}) {
        if (window.I18N) return window.I18N.t(key, values);
        return key;
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
                wsClient.onError = () => this._showError(this._t("error.websocket"));

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
                this._showPreviewLoadingKey("loading.selecting", "selection");
            }
        };

        svgViewer.onMouseMove = (pt) => {
            if (this.bounds) {
                const wcsX = pt.x / this.scale + this.bounds.min[0];
                const wcsY = this.bounds.max[1] - pt.y / this.scale;
                this.currentCoords = { x: wcsX, y: wcsY };
                this._renderStatus();
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
            this._showPreviewLoadingKey("loading.params", "params");
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
                this._showPreviewLoadingKey("loading.saving", "save");
                const synced = await API.updateParams(this.sessionId, parameterPanel.getParams());
                if (synced.preview_geometry) {
                    svgViewer.setOverlay(synced.preview_geometry, parameterPanel.getShowGenerated());
                    if (synced.chain_info) {
                        this._updateStatus({ chain_info: synced.chain_info });
                    }
                    if (synced.generated_count !== undefined) {
                        this._updateStatus({ generated_count: synced.generated_count });
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
                this._showError(err.message || this._t("error.download"));
            } finally {
                this._hidePreviewLoading("save");
                saveBtn.disabled = false;
            }
        });

        document
            .getElementById("clear-selection-btn")
            .addEventListener("click", () => {
                if (!this.sessionId) return;
                if (wsClient.send("clear_selection", {})) {
                    this._showPreviewLoadingKey("loading.clearing", "selection");
                }
            });
    },

    _bindStatus() {
        this._renderStatus();
    },

    async _bindVersion() {
        const currentEl = document.getElementById("current-version");
        const updateLink = document.getElementById("version-update-link");
        if (!currentEl || !updateLink) return;

        try {
            this.versionStatus = await API.getVersion();
        } catch (err) {
            console.warn("Version check failed", err);
            this.versionStatus = {
                current_version: "--",
                update_available: false,
                latest_release_url: "https://github.com/Ha22yX/dxf-auto-shape-tool/releases",
            };
        }
        this._renderVersionStatus();
    },

    _renderVersionStatus() {
        const currentEl = document.getElementById("current-version");
        const updateLink = document.getElementById("version-update-link");
        if (!currentEl || !updateLink) return;

        const status = this.versionStatus || {};
        currentEl.textContent = this._t("version.current", {
            version: status.current_version || "--",
        });

        if (status.update_available && status.latest_version) {
            updateLink.textContent = this._t("version.update", {
                version: status.latest_version,
            });
            updateLink.href = status.latest_release_url || status.release_url;
            updateLink.hidden = false;
        } else {
            updateLink.hidden = true;
        }
    },

    _handleWsMessage(msg) {
        const data = msg.data || {};
        if (msg.type === "preview_update") {
            if (data.stale_params_preview) return;
            const geometry = data.preview_geometry || {};
            svgViewer.setOverlay(geometry, data.show_generated);
            if (data.params_seq !== undefined) {
                this._hidePreviewLoading("params");
            }
            this._hidePreviewLoading("selection");

            this._updateStatus({
                chain_info: data.chain_info,
                generated_count: data.generated_count,
            });
        } else if (msg.type === "cleared") {
            svgViewer.setOverlay({}, true);
            svgViewer.clearHover();
            this._hidePreviewLoading("selection");
            this._updateStatus({
                chain_info: { segment_count: 0, total_length: 0 },
                generated_count: 0,
            });
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
            this._showError(data.message || this._t("error.generic"));
        }
    },

    _updateStatus(result = {}) {
        if (result.session_id) {
            this.sessionId = result.session_id;
        }
        if (result.chain_info) {
            this.chainInfo = result.chain_info;
        }
        if (result.generated_count !== undefined) {
            this.generatedCount = result.generated_count;
        }
        this._renderStatus();
    },

    _renderStatus() {
        const sessionEl = document.getElementById("status-session");
        const selectionEl = document.getElementById("status-selection");
        const generatedEl = document.getElementById("status-generated");
        const coordsEl = document.getElementById("status-coords");

        if (sessionEl) {
            sessionEl.textContent = this.sessionId
                ? this._t("status.session", { id: this.sessionId.slice(0, 8) })
                : this._t("status.noSession");
        }
        if (selectionEl) {
            const info = this.chainInfo || { segment_count: 0, total_length: 0 };
            selectionEl.textContent = this._t("status.selection", {
                count: info.segment_count || 0,
                length: info.total_length || 0,
            });
        }
        if (generatedEl) {
            generatedEl.textContent = this._t("status.generated", {
                count: this.generatedCount || 0,
            });
        }
        if (coordsEl) {
            coordsEl.textContent = this.currentCoords
                ? this._t("status.coords", {
                    x: this.currentCoords.x.toFixed(1),
                    y: this.currentCoords.y.toFixed(1),
                })
                : this._t("status.coordsEmpty");
        }
    },

    _setLoading(show) {
        if (show) {
            this._showPreviewLoadingKey("loading.upload", "global");
        } else {
            this._hidePreviewLoading("global");
        }
    },

    _showPreviewLoadingKey(key, reason = "global") {
        this._showPreviewLoading(this._t(key), reason, key);
    },

    _showPreviewLoading(text = null, reason = "global", key = null) {
        this.previewLoadingReasons.add(reason);
        if (key) this.previewLoadingLabels.set(reason, key);
        const overlay = this._ensurePreviewLoading();
        const label = document.getElementById("preview-loading-text");
        if (label) label.textContent = text || this._t("loading.default");
        if (overlay) overlay.classList.add("is-visible");
    },

    _hidePreviewLoading(reason = null) {
        if (reason) {
            this.previewLoadingReasons.delete(reason);
            this.previewLoadingLabels.delete(reason);
        } else {
            this.previewLoadingReasons.clear();
            this.previewLoadingLabels.clear();
        }
        if (this.previewLoadingReasons.size > 0) {
            this._refreshLoadingText();
            return;
        }
        const overlay = document.getElementById("preview-loading");
        if (overlay) overlay.classList.remove("is-visible");
    },

    _refreshLoadingText() {
        const label = document.getElementById("preview-loading-text");
        if (!label || this.previewLoadingReasons.size === 0) return;
        const reasons = Array.from(this.previewLoadingReasons);
        const key = this.previewLoadingLabels.get(reasons[reasons.length - 1]);
        label.textContent = key ? this._t(key) : this._t("loading.default");
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
                <span id="preview-loading-text">${this._t("loading.default")}</span>
            </div>
        `;
        container.appendChild(overlay);
        return overlay;
    },

    _showError(message) {
        console.error(message);
        alert(message);
    },
};

window.App = App;

window.addEventListener("DOMContentLoaded", () => {
    App.init();
});
