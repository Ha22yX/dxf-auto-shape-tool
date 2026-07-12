/**
 * Lightweight UI translation helper.
 */
(function () {
    const STORAGE_KEY = "dxf-auto-shape-language";
    const DEFAULT_LANGUAGE = "zh";

    const dictionaries = {
        zh: {
            "app.title": "DXF 自动图形工具",
            "language.label": "语言",
            "language.zh": "中文",
            "language.en": "English",
            "version.current": "当前版本 {version}",
            "version.update": "发现新版本 {version}",
            "button.upload": "上传 DXF",
            "button.save": "保存 DXF",
            "button.clear": "清空选择",
            "loading.default": "计算中...",
            "loading.upload": "加载中...",
            "loading.selecting": "选择中...",
            "loading.params": "计算中...",
            "loading.saving": "保存中...",
            "loading.clearing": "清除中...",
            "empty.upload": "请先上传 DXF 文件",
            "panel.title": "参数设置",
            "section.range": "生成范围",
            "section.holes": "圆孔",
            "section.capsules": "长条胶囊",
            "section.airduct": "导风槽与底板",
            "section.display": "预览显示",
            "section.help": "操作说明",
            "param.rayCount": "圆孔组数量",
            "tip.rayCount": "沿所选轮廓生成多少组圆孔和对应结构。数量越大越密，计算也会更慢。",
            "param.direction": "生成方向",
            "tip.direction": "控制圆孔朝所选闭合轮廓的内部或外部生成。冲浪板吸附台通常使用向内。",
            "option.inward": "向内",
            "option.outward": "向外",
            "param.rayOffset": "圆孔向内距离",
            "tip.rayOffset": "圆孔从轮廓边向内生成的总深度，必须大于 0。圆孔、长条和导风槽都会基于这段距离生成。",
            "param.topGap": "顶点留空距离",
            "tip.topGap": "从顶部顶点沿左右两侧留出的空白距离，这段不生成射线，用来避开尖头并保持左右对称。",
            "param.dedupe": "闭合端点去重",
            "tip.dedupe": "当所选线接近闭合时，避免首尾端点重复生成两条射线。设置顶点留空距离后通常不需要依赖它。",
            "param.circleRadius": "圆孔半径",
            "tip.circleRadius": "导风圆孔的半径，也是长条胶囊宽度和部分导风槽宽度计算的基础。",
            "param.circlesPerRay": "每条射线圆孔数",
            "tip.circlesPerRay": "每条射线上生成几个圆孔。设置为 0 时只保留射线和其他可生成图形。",
            "param.circleSpacing": "圆孔间距",
            "tip.circleSpacing": "同一条射线上相邻圆孔中心之间的距离。数值越大，圆孔越分散。",
            "param.capsuleStart": "长条起点距离",
            "tip.capsuleStart": "长条靠近轮廓边的一端距离射线起点的距离。这个值越大，长条越远离所选外边。",
            "param.capsuleClearance": "圆孔安全间距",
            "tip.capsuleClearance": "不同圆孔组互相靠近时，按这个最小间距自动减少外侧圆孔和长条长度，避免圆孔或长条重叠太近。",
            "param.axisGapAbove": "上方无长条区",
            "tip.axisGapAbove": "以水平对称轴为基准，向上这段距离内不生成长条胶囊，但圆孔仍会保留。用于把导风槽分成独立区域。",
            "param.axisGapBelow": "下方无长条区",
            "tip.axisGapBelow": "以水平对称轴为基准，向下这段距离内不生成长条胶囊，但圆孔仍会保留。上方和下方可以分别设置。",
            "param.airDuctEnabled": "生成导风槽",
            "tip.airDuctEnabled": "开启后生成右侧导风槽和底板；保存 DXF 时也会把导风槽模板一起导出。",
            "param.airDuctSimple": "精简版导风槽",
            "tip.airDuctSimple": "开启后只生成一个完整闭合外槽，把全部圆孔连进同一个导风槽；不再按上下区域分区，也不生成横向吸风口。",
            "param.airDuctInlet": "横向吸风口偏移",
            "tip.airDuctInlet": "控制横向吸风口相对导风槽分区靠近水平对称轴一侧的偏移距离，用来连接左右导风槽。",
            "param.basePlateMargin": "底板外扩距离",
            "tip.basePlateMargin": "在导风槽最外层边的基础上向外扩展的距离，生成用于加工导风槽的底板外轮廓。",
            "param.showGenerated": "显示生成结果",
            "tip.showGenerated": "控制是否显示圆孔、长条、导风槽等生成结果。关闭后只看导入和选中的轮廓。",
            "param.overlayCompare": "叠加对位查看",
            "tip.overlayCompare": "把左侧长条副图和右侧导风槽副图叠加回主图位置，方便检查对位；不会影响导出时三张图的独立位置。",
            "help.select": "点击线条选中外边",
            "help.append": "Ctrl + 点击追加相连边",
            "help.panZoom": "滚轮缩放，拖拽平移",
            "help.params": "调整参数实时预览",
            "status.noSession": "未连接会话",
            "status.session": "会话: {id}",
            "status.selection": "已选边: {count} | 总长: {length}",
            "status.generated": "生成圆: {count}",
            "status.coords": "坐标: {x}, {y}",
            "status.coordsEmpty": "坐标: -, -",
            "error.websocket": "WebSocket 连接失败",
            "error.generic": "发生错误",
            "error.upload": "上传失败",
            "error.version": "获取版本信息失败",
            "error.svg": "获取 SVG 失败",
            "error.select": "选择失败",
            "error.toggle": "切换预览失败",
            "error.params": "参数同步失败",
            "error.download": "下载失败",
        },
        en: {
            "app.title": "DXF Auto Shape Tool",
            "language.label": "Language",
            "language.zh": "中文",
            "language.en": "English",
            "version.current": "Current {version}",
            "version.update": "Update {version}",
            "button.upload": "Upload DXF",
            "button.save": "Save DXF",
            "button.clear": "Clear Selection",
            "loading.default": "Calculating...",
            "loading.upload": "Loading...",
            "loading.selecting": "Selecting...",
            "loading.params": "Calculating...",
            "loading.saving": "Saving...",
            "loading.clearing": "Clearing...",
            "empty.upload": "Upload a DXF file first",
            "panel.title": "Parameters",
            "section.range": "Generation",
            "section.holes": "Air Holes",
            "section.capsules": "Capsule Slots",
            "section.airduct": "Air Duct & Base Plate",
            "section.display": "Preview",
            "section.help": "How To Use",
            "param.rayCount": "Hole Group Count",
            "tip.rayCount": "How many hole groups and related structures to generate along the selected outline. More groups make the layout denser and slower to calculate.",
            "param.direction": "Generation Direction",
            "tip.direction": "Generate toward the inside or outside of the selected closed outline. Surfboard vacuum tables usually use inward.",
            "option.inward": "Inward",
            "option.outward": "Outward",
            "param.rayOffset": "Hole Inset Distance",
            "tip.rayOffset": "Total distance from the outline edge toward the inside for generated holes. Must be greater than 0.",
            "param.topGap": "Apex Empty Distance",
            "tip.topGap": "Empty distance from the top apex along both sides. No rays are generated in this area, which keeps the nose clean and symmetric.",
            "param.dedupe": "Closed Endpoint Dedup",
            "tip.dedupe": "Avoid duplicate rays at the start/end of nearly closed outlines. Usually unnecessary when apex empty distance is set.",
            "param.circleRadius": "Hole Radius",
            "tip.circleRadius": "Radius of each air hole. It also drives capsule width and part of the air duct width.",
            "param.circlesPerRay": "Holes Per Ray",
            "tip.circlesPerRay": "How many holes to place on each ray. Use 0 to keep only rays and other generated structures.",
            "param.circleSpacing": "Hole Spacing",
            "tip.circleSpacing": "Center-to-center spacing between adjacent holes on the same ray.",
            "param.capsuleStart": "Capsule Start Distance",
            "tip.capsuleStart": "Distance from the ray start to the near end of each capsule slot. Larger values move slots farther from the selected outline.",
            "param.capsuleClearance": "Hole Safety Clearance",
            "tip.capsuleClearance": "Minimum clearance used to shorten outer holes and capsule slots when neighboring groups get too close.",
            "param.axisGapAbove": "Upper No-Capsule Zone",
            "tip.axisGapAbove": "Distance above the horizontal symmetry axis where capsule slots are not generated. Holes remain. Used to split air duct regions.",
            "param.axisGapBelow": "Lower No-Capsule Zone",
            "tip.axisGapBelow": "Distance below the horizontal symmetry axis where capsule slots are not generated. Holes remain. Upper and lower values are independent.",
            "param.airDuctEnabled": "Generate Air Duct",
            "tip.airDuctEnabled": "Generate the right-side air duct and base plate. Saved DXF files include the duct template.",
            "param.airDuctSimple": "Simple Air Duct",
            "tip.airDuctSimple": "Generate one continuous closed outer duct that connects all holes. No region splitting or horizontal inlet slots.",
            "param.airDuctInlet": "Horizontal Inlet Offset",
            "tip.airDuctInlet": "Offset of the horizontal inlet from the side of a duct region nearest to the horizontal symmetry axis.",
            "param.basePlateMargin": "Base Plate Offset",
            "tip.basePlateMargin": "Outward offset from the outermost air duct edge used to generate the base plate outline.",
            "param.showGenerated": "Show Generated Result",
            "tip.showGenerated": "Show or hide generated holes, capsules, air ducts and base plates. When hidden, only imported and selected outlines remain.",
            "param.overlayCompare": "Overlay Alignment View",
            "tip.overlayCompare": "Overlay the left capsule copy and right air duct copy back onto the main drawing for alignment checks. Export positions are unchanged.",
            "help.select": "Click an outline to select it",
            "help.append": "Ctrl + click to append connected edges",
            "help.panZoom": "Mouse wheel zooms, drag pans",
            "help.params": "Adjust parameters for live preview",
            "status.noSession": "No session",
            "status.session": "Session: {id}",
            "status.selection": "Selected: {count} | Length: {length}",
            "status.generated": "Holes: {count}",
            "status.coords": "Coords: {x}, {y}",
            "status.coordsEmpty": "Coords: -, -",
            "error.websocket": "WebSocket connection failed",
            "error.generic": "Something went wrong",
            "error.upload": "Upload failed",
            "error.version": "Failed to fetch version info",
            "error.svg": "Failed to fetch SVG",
            "error.select": "Selection failed",
            "error.toggle": "Preview toggle failed",
            "error.params": "Parameter sync failed",
            "error.download": "Download failed",
        },
    };

    let currentLanguage = DEFAULT_LANGUAGE;

    function format(template, values = {}) {
        return String(template).replace(/\{(\w+)\}/g, (_, key) => {
            return values[key] === undefined ? "" : values[key];
        });
    }

    function getStoredLanguage() {
        const stored = localStorage.getItem(STORAGE_KEY);
        return dictionaries[stored] ? stored : DEFAULT_LANGUAGE;
    }

    function t(key, values = {}) {
        const dict = dictionaries[currentLanguage] || dictionaries[DEFAULT_LANGUAGE];
        const fallback = dictionaries[DEFAULT_LANGUAGE][key] || key;
        return format(dict[key] || fallback, values);
    }

    function readValues(node) {
        if (!node.dataset.i18nValues) return {};
        try {
            return JSON.parse(node.dataset.i18nValues);
        } catch {
            return {};
        }
    }

    function apply(root = document) {
        document.documentElement.lang = currentLanguage === "zh" ? "zh-CN" : "en";
        document.title = t("app.title");

        root.querySelectorAll("[data-i18n]").forEach((node) => {
            node.textContent = t(node.dataset.i18n, readValues(node));
        });
        root.querySelectorAll("[data-i18n-tooltip]").forEach((node) => {
            node.dataset.tooltip = t(node.dataset.i18nTooltip);
        });
        root.querySelectorAll("[data-i18n-title]").forEach((node) => {
            node.title = t(node.dataset.i18nTitle);
        });
        root.querySelectorAll("[data-i18n-aria-label]").forEach((node) => {
            node.setAttribute("aria-label", t(node.dataset.i18nAriaLabel));
        });
    }

    function setLanguage(language) {
        if (!dictionaries[language]) return;
        currentLanguage = language;
        localStorage.setItem(STORAGE_KEY, language);
        apply();
        window.dispatchEvent(
            new CustomEvent("i18n:change", { detail: { language } }),
        );
    }

    function init() {
        currentLanguage = getStoredLanguage();
        apply();
        return currentLanguage;
    }

    window.I18N = {
        init,
        setLanguage,
        getLanguage: () => currentLanguage,
        t,
        apply,
    };
})();
