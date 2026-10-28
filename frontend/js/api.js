/**
 * HTTP API wrappers.
 */
const API = {
    baseUrl: "",

    async upload(file) {
        const formData = new FormData();
        formData.append("file", file);
        const res = await fetch(`${this.baseUrl}/api/upload`, {
            method: "POST",
            body: formData,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(I18n.error(err.detail, "uploadFailed"));
        }
        return res.json();
    },

    async getSvg(sessionId, generated = true) {
        const res = await fetch(
            `${this.baseUrl}/api/session/${sessionId}/svg?generated=${generated}`,
        );
        if (!res.ok) throw new Error(I18n.t("svgFailed"));
        return res.text();
    },

    async select(sessionId, svgX, svgY, append = false) {
        const res = await fetch(`${this.baseUrl}/api/session/${sessionId}/select`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ svg_x: svgX, svg_y: svgY, append }),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(I18n.error(err.detail, "selectionFailed"));
        }
        return res.json();
    },

    async togglePreview(sessionId, showGenerated) {
        const res = await fetch(
            `${this.baseUrl}/api/session/${sessionId}/toggle-preview`,
            {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ show_generated: showGenerated }),
            },
        );
        if (!res.ok) throw new Error(I18n.t("toggleFailed"));
        return res.json();
    },

    async updateParams(sessionId, params) {
        const res = await fetch(`${this.baseUrl}/api/session/${sessionId}/params`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(params),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(I18n.error(err.detail, "paramsFailed"));
        }
        return res.json();
    },

    async download(sessionId) {
        const res = await fetch(this.downloadUrl(sessionId), {
            cache: "no-store",
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(I18n.error(err.detail, "downloadFailed"));
        }
        return res.blob();
    },

    downloadUrl(sessionId) {
        return `${this.baseUrl}/api/session/${sessionId}/download`;
    },
};
