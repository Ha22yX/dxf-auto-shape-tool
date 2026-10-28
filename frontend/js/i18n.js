/** Interface translations. Switching language only updates text, preserving the drawing and parameters. */
const I18n = {
    storageKey: "dxf-auto-shape-language",
    language: "zh-CN",
    messages: {
    "zh-CN": {
        "appTitle": "DXF 自动图形工具",
        "language": "语言",
        "upload": "上传 DXF",
        "calculating": "计算中...",
        "emptyState": "请先上传 DXF 文件",
        "disconnected": "未连接会话",
        "session": "会话: {id}",
        "selection": "已选边: {count} | 总长: {length}",
        "generated": "生成圆: {count}",
        "coordinates": "坐标: {x}, {y}",
        "parameters": "参数设置",
        "circles": "圆圈",
        "circleRadius": "圆圈半径",
        "circlesPerRay": "每射线圆数",
        "circleSpacing": "圆间距",
        "rays": "射线",
        "rayOffset": "射线整体偏移",
        "rayCount": "射线数量",
        "rayDirection": "射线方向",
        "inward": "向内",
        "outward": "向外",
        "dedupeClosedRays": "闭合端点射线去重",
        "slotsAndGaps": "长条与间隔",
        "capsuleStart": "长条起点距离",
        "capsuleClearance": "胶囊安全间距",
        "gapAbove": "水平轴上方无长条距离",
        "gapBelow": "水平轴下方无长条距离",
        "topGap": "顶部间隔",
        "airDucts": "导风槽",
        "airDuctEnabled": "显示/导出导风槽",
        "airDuctInlet": "横向吸风口距离",
        "display": "显示",
        "showGenerated": "显示生成图",
        "compareAirDucts": "导风槽叠加对比",
        "save": "保存 DXF",
        "clearSelection": "清空选择",
        "instructions": "操作说明",
        "helpSelect": "点击线条选中外边",
        "helpAppend": "Ctrl + 点击追加相连边",
        "helpPan": "滚轮缩放，拖拽平移",
        "helpPreview": "调整参数实时预览",
        "selecting": "选择中...",
        "saving": "保存中...",
        "clearing": "清除中...",
        "loading": "加载中...",
        "uploadFailed": "上传失败",
        "svgFailed": "获取 SVG 失败",
        "selectionFailed": "选择失败",
        "toggleFailed": "切换预览失败",
        "paramsFailed": "参数同步失败",
        "downloadFailed": "下载失败",
        "websocketFailed": "WebSocket 连接失败",
        "genericError": "发生错误",
        "invalidFile": "请上传 .dxf 文件",
        "sessionMissing": "会话不存在",
        "parseFailed": "无法解析 DXF: {detail}",
        "unknownMessage": "未知消息类型: {detail}",
        "networkError": "无法连接本地服务，请确认服务正在运行",
        "outline_open": "未找到可形成有效区域的补线连接，请追加选择属于同一轮廓的边。",
        "outline_invalid": "当前轮廓存在自交、分支或无效几何，已停止生成。请先修复轮廓。",
        "outline_nonplanar": "当前轮廓不在同一水平平面，已停止生成。请先转换为平面轮廓。",
        "boundaryFiltered": "已过滤 {count} 个越界或跨越轮廓的孔，预览与导出使用相同校验。",
        "autoClosed": "已自动补全 {repaired} 处缺口（总长 {length} mm）。黄色虚线为补线，保存 DXF 时会一并导出。",
        "autoClosedFiltered": "已自动补全 {repaired} 处缺口（总长 {length} mm），并过滤 {count} 个越界孔。黄色补线会一并导出。"
    },
    "en": {
        "appTitle": "DXF Auto Shape Tool",
        "language": "Language",
        "upload": "Upload DXF",
        "calculating": "Calculating...",
        "emptyState": "Upload a DXF file to get started",
        "disconnected": "No active session",
        "session": "Session: {id}",
        "selection": "Selected edges: {count} | Length: {length}",
        "generated": "Generated circles: {count}",
        "coordinates": "Coordinates: {x}, {y}",
        "parameters": "Parameters",
        "circles": "Circles",
        "circleRadius": "Circle radius",
        "circlesPerRay": "Circles per ray",
        "circleSpacing": "Circle spacing",
        "rays": "Rays",
        "rayOffset": "Ray offset",
        "rayCount": "Ray count",
        "rayDirection": "Ray direction",
        "inward": "Inward",
        "outward": "Outward",
        "dedupeClosedRays": "Deduplicate rays at closed endpoints",
        "slotsAndGaps": "Slots and gaps",
        "capsuleStart": "Slot start distance",
        "capsuleClearance": "Slot clearance",
        "gapAbove": "No-slot gap above horizontal axis",
        "gapBelow": "No-slot gap below horizontal axis",
        "topGap": "Top gap",
        "airDucts": "Air ducts",
        "airDuctEnabled": "Show / export air ducts",
        "airDuctInlet": "Lateral air inlet distance",
        "display": "Display",
        "showGenerated": "Show generated geometry",
        "compareAirDucts": "Overlay air ducts for comparison",
        "save": "Save DXF",
        "clearSelection": "Clear selection",
        "instructions": "How to use",
        "helpSelect": "Click a line to select an outline edge",
        "helpAppend": "Ctrl + click to add connected edges",
        "helpPan": "Scroll to zoom; drag to pan",
        "helpPreview": "Adjust parameters for a live preview",
        "selecting": "Selecting...",
        "saving": "Saving...",
        "clearing": "Clearing...",
        "loading": "Loading...",
        "uploadFailed": "Upload failed",
        "svgFailed": "Could not load the SVG preview",
        "selectionFailed": "Selection failed",
        "toggleFailed": "Could not toggle the preview",
        "paramsFailed": "Could not sync parameters",
        "downloadFailed": "Download failed",
        "websocketFailed": "WebSocket connection failed",
        "genericError": "An error occurred",
        "invalidFile": "Please upload a .dxf file",
        "sessionMissing": "The session no longer exists. Please upload the DXF file again.",
        "parseFailed": "Could not parse DXF: {detail}",
        "unknownMessage": "Unknown message type: {detail}",
        "networkError": "Could not connect to the local service. Make sure it is running.",
        "outline_open": "No valid closed region could be completed. Add edges belonging to the same outline to the selection.",
        "outline_invalid": "The outline has intersections, branches, or invalid geometry. Repair it before generating.",
        "outline_nonplanar": "The outline is not in a single XY plane. Convert it to a planar outline before generating.",
        "boundaryFiltered": "Filtered {count} holes that cross or leave the selected side of the outline. Preview and export use the same checks.",
        "autoClosed": "Automatically closed {repaired} gaps ({length} mm total). Yellow dashed connections are included in the DXF export.",
        "autoClosedFiltered": "Automatically closed {repaired} gaps ({length} mm total) and filtered {count} out-of-bounds holes. Yellow connections are included in the export."
    }
},

    t(key, params = {}) {
        const template = this.messages[this.language][key] || this.messages["zh-CN"][key] || key;
        return template.replace(/\{(\w+)\}/g, (match, name) =>
            Object.prototype.hasOwnProperty.call(params, name) ? String(params[name]) : match);
    },

    setText(target, key, params = {}) {
        const element = typeof target === "string" ? document.getElementById(target) : target;
        if (!element) return;
        element.dataset.i18n = key;
        element.dataset.i18nParams = JSON.stringify(params);
        element.textContent = this.t(key, params);
    },

    setLanguage(language, persist = true) {
        if (!Object.prototype.hasOwnProperty.call(this.messages, language)) language = "zh-CN";
        this.language = language;
        document.documentElement.lang = language;
        document.querySelectorAll("[data-i18n]").forEach((element) => {
            const params = JSON.parse(element.dataset.i18nParams || "{}");
            element.textContent = this.t(element.dataset.i18n, params);
        });
        const select = document.getElementById("language-select");
        if (select) select.value = language;
        if (persist) {
            try { localStorage.setItem(this.storageKey, language); } catch (_) { /* Storage can be disabled. */ }
        }
    },

    error(message, fallback = "genericError") {
        if (typeof message !== "string" || !message) return this.t(fallback);
        if (Object.prototype.hasOwnProperty.call(this.messages[this.language], message)) return this.t(message);
        for (const [key, text] of Object.entries(this.messages["zh-CN"])) {
            if (message === text) return this.t(key);
        }
        for (const [prefix, key] of [["无法解析 DXF: ", "parseFailed"], ["未知消息类型: ", "unknownMessage"]]) {
            if (message.startsWith(prefix)) return this.t(key, { detail: message.slice(prefix.length) });
        }
        if (["Failed to fetch", "NetworkError when attempting to fetch resource.", "Load failed"].includes(message)) {
            return this.t("networkError");
        }
        return message;
    },

    init() {
        let saved = "zh-CN";
        try { saved = localStorage.getItem(this.storageKey) || saved; } catch (_) { /* Use Chinese by default. */ }
        this.setLanguage(saved, false);
        const select = document.getElementById("language-select");
        if (select) select.addEventListener("change", () => this.setLanguage(select.value));
    },
};

window.addEventListener("DOMContentLoaded", () => I18n.init());
