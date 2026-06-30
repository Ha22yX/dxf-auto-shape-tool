/**
 * SVG viewer: base layer (accurate DXF render) + overlay layer (selection &
 * generated circles), with pan/zoom and coordinate conversion.
 *
 * The base SVG is produced once by the backend (ezdxf.addons.drawing) and uses
 * a viewBox in "output units". Pan/zoom transform a wrapper group; the overlay
 * (drawn in the same output-unit space) lives inside that wrapper so it stays
 * perfectly aligned with the drawing.
 */
const SVG_NS = "http://www.w3.org/2000/svg";

class SvgViewer {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.svg = null;
        this.viewport = null;   // pan/zoom wrapper group
        this.overlay = null;    // generated circles / rays / selection highlight
        this.generatedLayer = null; // toggleable subgroup for circles + rays
        this.baseLayer = null;
        this.hoverHitLayer = null;
        this.hoverVisualLayer = null;
        this.hoverOwners = new Map();
        this.hoverPathMap = new Map();
        this.lastGeometry = null;
        this.lastShowGenerated = true;
        this.currentPreviewParams = null;
        this.capsuleGapGuideVisible = false;
        this._renderFrame = null;
        this._pendingGeneratedRender = null;
        this.airDuctCompareMode = false;

        // View transform
        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this.baseScale = 1; // viewBox -> WCS scale (set from upload response)
        this._hasSetInitialView = false;

        this.isPanning = false;
        this.panButton = -1;
        this.startMouseRawSvg = { x: 0, y: 0 };
        this.startTranslate = { x: 0, y: 0 };
        this.mouseDownPos = { clientX: 0, clientY: 0 };
        this.mouseMoved = false;

        // Hover state
        this.hoverPath = null;
        this.lastHoverHandle = null;
        this.localHoverElement = null;
        this._hoverThrottle = null;
        this._lastHoverPoint = null;
        this._hoverRequestId = 0;
        this.onHover = null;

        this.onClick = null;
        this.onMouseMove = null;

        this._bindEvents();
    }

    setBaseSvg(svgString, hoverPaths = []) {
        this.container.innerHTML = svgString;
        this.svg = this.container.querySelector("svg");
        if (!this.svg) return;

        // Wrap every existing child in a viewport group (for pan/zoom) and add
        // an overlay group inside it so the overlay transforms with the drawing.
        const viewport = document.createElementNS(SVG_NS, "g");
        viewport.setAttribute("id", "dxf-viewport");
        const baseLayer = document.createElementNS(SVG_NS, "g");
        baseLayer.setAttribute("id", "dxf-base-layer");
        while (this.svg.firstChild) {
            baseLayer.appendChild(this.svg.firstChild);
        }
        viewport.appendChild(baseLayer);
        this.svg.appendChild(viewport);

        const overlay = document.createElementNS(SVG_NS, "g");
        overlay.setAttribute("id", "preview-overlay");
        overlay.setAttribute("pointer-events", "none");
        const hoverPath = document.createElementNS(SVG_NS, "path");
        hoverPath.setAttribute("id", "hover-highlight-path");
        hoverPath.setAttribute("fill", "none");
        hoverPath.setAttribute("stroke", "#FFD166");
        hoverPath.setAttribute("stroke-width", "2.5");
        hoverPath.setAttribute("stroke-opacity", "0.95");
        hoverPath.setAttribute("stroke-linecap", "round");
        hoverPath.setAttribute("stroke-linejoin", "round");
        hoverPath.setAttribute("vector-effect", "non-scaling-stroke");
        hoverPath.setAttribute("pointer-events", "none");
        hoverPath.style.display = "none";
        const generatedLayer = document.createElementNS(SVG_NS, "g");
        generatedLayer.setAttribute("id", "generated-layer");
        const hoverVisualLayer = document.createElementNS(SVG_NS, "g");
        hoverVisualLayer.setAttribute("id", "local-hover-visual-layer");
        hoverVisualLayer.setAttribute("pointer-events", "none");
        overlay.appendChild(hoverPath);
        overlay.appendChild(generatedLayer);
        overlay.appendChild(hoverVisualLayer);

        viewport.appendChild(overlay);
        const hitLayer = this._buildLocalHoverHitLayer(viewport, hoverPaths);

        this.viewport = viewport;
        this.baseLayer = baseLayer;
        this.overlay = overlay;
        this.hoverPath = hoverPath;
        this.generatedLayer = generatedLayer;
        this.hoverHitLayer = hitLayer;
        this.hoverVisualLayer = hoverVisualLayer;
        this.lastHoverHandle = null;
        this.localHoverElement = null;

        this.svg.addEventListener("click", (e) => this._handleClick(e));
        this.svg.addEventListener("mousemove", (e) => this._handleMouseMove(e));
        this.svg.addEventListener("mouseleave", () => {
            this.clearHover();
        });

        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this._hasSetInitialView = true;
        this._applyAirDuctCompareMode();
        this._applyTransform();
        if (window.App && typeof window.App._ensurePreviewLoading === "function") {
            window.App._ensurePreviewLoading();
        }
    }

    setOverlay(geometry, showGenerated) {
        if (!this.generatedLayer) return;
        geometry = geometry || {};
        this.lastGeometry = geometry;
        this.lastShowGenerated = showGenerated;

        this._renderGeneratedGeometry(geometry, showGenerated, true);
        this._renderStaticOverlay(geometry);
    }

    previewParams(params, showGenerated = this.lastShowGenerated) {
        if (!this.lastGeometry || !this.lastGeometry.basis || !this.lastGeometry.basis.length) {
            return false;
        }
        this.currentPreviewParams = params;
        const geometry = this._geometryFromBasis(this.lastGeometry, params);
        this._renderGeneratedGeometry(geometry, showGenerated);
        if (this.capsuleGapGuideVisible) {
            this._renderCapsuleGapGuide(
                this._capsuleGapGuideFromParams(this.lastGeometry, params),
            );
        }
        return true;
    }

    _renderGeneratedGeometry(geometry, showGenerated, immediate = false) {
        if (!this.generatedLayer) return;
        this._pendingGeneratedRender = { geometry: geometry || {}, showGenerated };
        if (immediate) {
            this._flushGeneratedGeometry();
            return;
        }
        if (this._renderFrame) return;
        this._renderFrame = window.requestAnimationFrame(() => {
            this._renderFrame = null;
            this._flushGeneratedGeometry();
        });
    }

    _flushGeneratedGeometry() {
        if (!this.generatedLayer || !this._pendingGeneratedRender) return;
        const { geometry, showGenerated } = this._pendingGeneratedRender;
        this._pendingGeneratedRender = null;
        this.generatedLayer.style.display = showGenerated ? "" : "none";
        this.generatedLayer.innerHTML = this._generatedGeometryMarkup(geometry);
    }

    _generatedGeometryMarkup(geometry) {
        const parts = [];
        const airDuctBasePlates = geometry.air_duct_base_plates || [];
        const airDucts = geometry.air_ducts || [];
        if (airDuctBasePlates.length || airDucts.length) {
            const transform = this._airDuctCompareTransform(geometry);
            const attrs = transform ? ` transform="${transform}"` : "";
            parts.push(`<g class="air-duct-layer"${attrs}>`);
            for (const plate of airDuctBasePlates) {
                if (!plate || !plate.d) continue;
                parts.push(
                    `<path d="${this._escapeAttr(plate.d)}" fill="none" stroke="#A7F3D0" `
                    + `stroke-width="1.5" stroke-opacity="0.78" stroke-linecap="round" `
                    + `stroke-linejoin="round" vector-effect="non-scaling-stroke"></path>`,
                );
            }
            for (const duct of airDucts) {
                if (!duct || !duct.d) continue;
                parts.push(
                    `<path d="${this._escapeAttr(duct.d)}" fill="none" stroke="#7DD3FC" `
                    + `stroke-width="1.7" stroke-opacity="0.92" stroke-linecap="round" `
                    + `stroke-linejoin="round" vector-effect="non-scaling-stroke"></path>`,
                );
            }
            parts.push("</g>");
        }

        const capsules = geometry.capsules || [];
        for (const c of capsules) {
            if (!c || !c.d) continue;
            parts.push(
                `<path d="${this._escapeAttr(c.d)}" fill="none" stroke="#E8E8E8" `
                + `stroke-width="1.4" stroke-opacity="0.92" stroke-linecap="round" `
                + `stroke-linejoin="round" vector-effect="non-scaling-stroke"></path>`,
            );
        }
        const rays = geometry.rays || [];
        for (const r of rays) {
            parts.push(
                `<line x1="${this._fmt(r.x1)}" y1="${this._fmt(r.y1)}" `
                + `x2="${this._fmt(r.x2)}" y2="${this._fmt(r.y2)}" stroke="#B8B8B8" `
                + `stroke-width="1.2" stroke-opacity="0.45" stroke-dasharray="6 6" `
                + `vector-effect="non-scaling-stroke"></line>`,
            );
        }

        const removedCircles = geometry.removed_circles || [];
        for (const c of removedCircles) {
            parts.push(
                `<circle cx="${this._fmt(c.cx)}" cy="${this._fmt(c.cy)}" r="${this._fmt(c.r)}" `
                + `fill="rgba(160, 160, 160, 0.14)" stroke="#9A9A9A" `
                + `stroke-width="1.6" stroke-opacity="0.48" stroke-dasharray="4 4" `
                + `vector-effect="non-scaling-stroke"></circle>`,
            );
        }

        const circles = geometry.circles || [];
        for (const c of circles) {
            parts.push(
                `<circle cx="${this._fmt(c.cx)}" cy="${this._fmt(c.cy)}" r="${this._fmt(c.r)}" `
                + `fill="none" stroke="#FF6B6B" stroke-width="1.8" `
                + `vector-effect="non-scaling-stroke"></circle>`,
            );
        }
        return parts.join("");
    }

    setAirDuctCompareMode(enabled) {
        this.airDuctCompareMode = Boolean(enabled);
        this._applyAirDuctCompareMode();
        if (this.lastGeometry) {
            this._renderGeneratedGeometry(this.lastGeometry, this.lastShowGenerated, true);
        }
    }

    _applyAirDuctCompareMode() {
        if (!this.baseLayer) return;
        this.baseLayer.classList.toggle("air-duct-compare-original", this.airDuctCompareMode);
        if (this.overlay) {
            this.overlay.classList.toggle("air-duct-compare-mode", this.airDuctCompareMode);
        }
        if (this.generatedLayer) {
            this.generatedLayer.classList.toggle("air-duct-compare-original", this.airDuctCompareMode);
        }
    }

    _airDuctCompareTransform(geometry) {
        if (!this.airDuctCompareMode || !geometry || !geometry.air_duct_template_offset) {
            return "";
        }
        const offset = geometry.air_duct_template_offset;
        const dx = -Number(offset.x || 0);
        const dy = -Number(offset.y || 0);
        if (Math.abs(dx) <= 1e-9 && Math.abs(dy) <= 1e-9) return "";
        return `translate(${dx.toFixed(1)} ${dy.toFixed(1)})`;
    }

    _fmt(value) {
        return Number(value || 0).toFixed(1);
    }

    _escapeAttr(value) {
        return String(value).replace(/&/g, "&amp;").replace(/"/g, "&quot;");
    }

    _renderStaticOverlay(geometry) {
        if (!this.overlay) return;
        // Selection highlight: replace any existing chain path.
        const oldPath = this.overlay.querySelector("#selected-chain-path");
        if (oldPath) oldPath.remove();
        this.overlay.querySelectorAll(".symmetry-axis-line").forEach((line) => line.remove());
        this.overlay.querySelectorAll(".capsule-gap-guide-line").forEach((line) => line.remove());
        const oldApex = this.overlay.querySelector("#default-apex-marker");
        if (oldApex) oldApex.remove();
        const d = geometry.selected_chain_path;
        if (d) {
            const path = document.createElementNS(SVG_NS, "path");
            path.setAttribute("id", "selected-chain-path");
            path.setAttribute("d", d);
            path.setAttribute("fill", "none");
            path.setAttribute("stroke", "#00BFFF");
            path.setAttribute("stroke-width", "2.5");
            path.setAttribute("stroke-opacity", "0.9");
            path.setAttribute("vector-effect", "non-scaling-stroke");
            this.overlay.insertBefore(path, this.generatedLayer);
        }

        this._renderDefaultApexMarker(geometry.apex_marker || null);
        this._renderSymmetryAxes(geometry.symmetry_axes || null);
        if (this.capsuleGapGuideVisible) {
            this._renderCapsuleGapGuide(
                this._capsuleGapGuideFromParams(geometry, this.currentPreviewParams),
            );
        }
    }

    _renderDefaultApexMarker(marker) {
        if (!marker || !this.overlay || !this.generatedLayer) return;
        const group = document.createElementNS(SVG_NS, "g");
        group.setAttribute("id", "default-apex-marker");
        group.setAttribute("pointer-events", "none");

        const outer = document.createElementNS(SVG_NS, "circle");
        outer.setAttribute("cx", marker.cx.toFixed(1));
        outer.setAttribute("cy", marker.cy.toFixed(1));
        outer.setAttribute("r", Math.max(5, Number(marker.r || 5)).toFixed(1));
        outer.setAttribute("fill", "rgba(255, 209, 102, 0.16)");
        outer.setAttribute("stroke", "#FFD166");
        outer.setAttribute("stroke-width", "2.2");
        outer.setAttribute("vector-effect", "non-scaling-stroke");

        const dot = document.createElementNS(SVG_NS, "circle");
        dot.setAttribute("cx", marker.cx.toFixed(1));
        dot.setAttribute("cy", marker.cy.toFixed(1));
        dot.setAttribute("r", "2.8");
        dot.setAttribute("fill", "#FFD166");
        dot.setAttribute("stroke", "none");
        dot.setAttribute("vector-effect", "non-scaling-stroke");

        group.appendChild(outer);
        group.appendChild(dot);
        this.overlay.insertBefore(group, this.generatedLayer);
    }

    _renderSymmetryAxes(axes) {
        if (!axes) return;
        for (const [kind, axis] of Object.entries(axes)) {
            if (!axis) continue;
            const line = document.createElementNS(SVG_NS, "line");
            line.setAttribute("class", `symmetry-axis-line symmetry-axis-${kind}`);
            line.setAttribute("x1", axis.x1.toFixed(1));
            line.setAttribute("y1", axis.y1.toFixed(1));
            line.setAttribute("x2", axis.x2.toFixed(1));
            line.setAttribute("y2", axis.y2.toFixed(1));
            line.setAttribute("stroke", "#FF5C5C");
            line.setAttribute("stroke-width", "1.8");
            line.setAttribute("stroke-opacity", kind === "vertical" ? "0.24" : "0.16");
            line.setAttribute("stroke-dasharray", "8 7");
            line.setAttribute("vector-effect", "non-scaling-stroke");
            line.setAttribute("pointer-events", "none");
            this.overlay.insertBefore(line, this.generatedLayer);
        }
    }

    setCapsuleGapGuideVisible(visible, params = null) {
        this.capsuleGapGuideVisible = Boolean(visible);
        if (params) this.currentPreviewParams = params;
        const guide = this.capsuleGapGuideVisible
            ? this._capsuleGapGuideFromParams(this.lastGeometry, this.currentPreviewParams)
            : null;
        this._renderCapsuleGapGuide(guide);
    }

    _capsuleGapGuideFromParams(baseGeometry, params) {
        if (!baseGeometry || !baseGeometry.symmetry_axes || !baseGeometry.symmetry_axes.horizontal) {
            return null;
        }
        const h = baseGeometry.symmetry_axes.horizontal;
        const svgScale = Number(baseGeometry.scale || this.baseScale || 1);
        const aboveGap = Math.max(0, Number(params && params.capsule_axis_gap_above_distance || 0)) * svgScale;
        const belowGap = Math.max(0, Number(params && params.capsule_axis_gap_below_distance || 0)) * svgScale;
        const centerY = (Number(h.y1) + Number(h.y2)) / 2;
        return {
            upper: { x1: h.x1, y1: centerY - aboveGap, x2: h.x2, y2: centerY - aboveGap },
            lower: { x1: h.x1, y1: centerY + belowGap, x2: h.x2, y2: centerY + belowGap },
        };
    }

    _renderCapsuleGapGuide(guide) {
        if (!this.overlay || !this.generatedLayer) return;
        this.overlay.querySelectorAll(".capsule-gap-guide-line").forEach((line) => line.remove());
        if (!guide) return;
        for (const axis of [guide.upper, guide.lower]) {
            if (!axis) continue;
            const line = document.createElementNS(SVG_NS, "line");
            line.setAttribute("class", "capsule-gap-guide-line");
            line.setAttribute("x1", Number(axis.x1).toFixed(1));
            line.setAttribute("y1", Number(axis.y1).toFixed(1));
            line.setAttribute("x2", Number(axis.x2).toFixed(1));
            line.setAttribute("y2", Number(axis.y2).toFixed(1));
            line.setAttribute("stroke", "#FFD166");
            line.setAttribute("stroke-width", "2.2");
            line.setAttribute("stroke-opacity", "0.85");
            line.setAttribute("stroke-dasharray", "9 6");
            line.setAttribute("vector-effect", "non-scaling-stroke");
            line.setAttribute("pointer-events", "none");
            this.overlay.insertBefore(line, this.generatedLayer);
        }
    }

    _geometryFromBasis(baseGeometry, params) {
        const svgScale = Number(baseGeometry.scale || this.baseScale || 1);
        const basis = this._basisWithApproxTopGap(baseGeometry.basis || [], params, baseGeometry, svgScale);
        const rayCount = Math.max(0, Math.floor(Number(params.ray_count || basis.length)));
        const circlesPerRay = Math.max(0, Math.floor(Number(params.circles_per_ray || 0)));
        const radius = Math.max(0, Number(params.circle_radius || 0)) * svgScale;
        const spacing = Number(params.circle_spacing || 0) * svgScale;
        const offset = Number(params.ray_offset || 0) * svgScale;
        const capsuleClearance = Math.max(0, Number(params.capsule_clearance_distance || 0)) * svgScale;
        const aboveAxisGap = Math.max(0, Number(params.capsule_axis_gap_above_distance || 0)) * svgScale;
        const belowAxisGap = Math.max(0, Number(params.capsule_axis_gap_below_distance || 0)) * svgScale;
        const horizontalAxis = baseGeometry.symmetry_axes && baseGeometry.symmetry_axes.horizontal;
        const horizontalAxisY = horizontalAxis
            ? (Number(horizontalAxis.y1) + Number(horizontalAxis.y2)) / 2
            : null;
        const verticalAxis = baseGeometry.symmetry_axes && baseGeometry.symmetry_axes.vertical;
        const verticalAxisX = verticalAxis
            ? (Number(verticalAxis.x1) + Number(verticalAxis.x2)) / 2
            : null;
        const maxCapsuleStart = Math.max(0.1, Number(params.ray_offset || 0));
        const capsuleStart = Math.max(
            0.1,
            Math.min(Number(params.capsule_start_distance || 0.1), maxCapsuleStart),
        ) * svgScale;
        const source = this._resampleBasis(basis, rayCount);
        const allCircles = [];
        const rays = [];

        for (const [placementIndex, b] of source.entries()) {
            let nx = Number(b.nx || 0);
            let ny = Number(b.ny || 0);
            const mag = Math.hypot(nx, ny);
            if (mag <= 1e-9) continue;
            nx /= mag;
            ny /= mag;
            const rayEndDistance = offset + Math.max(0, circlesPerRay - 1) * spacing;
            rays.push({
                x1: b.x,
                y1: b.y,
                x2: b.x + nx * rayEndDistance,
                y2: b.y + ny * rayEndDistance,
            });
            for (let i = 0; i < circlesPerRay; i++) {
                const d = offset + i * spacing;
                allCircles.push({
                    cx: b.x + nx * d,
                    cy: b.y + ny * d,
                    r: radius,
                    placementIndex,
                    circleIndex: i,
                });
            }
        }

        let pruned = this._quickPruneOverlaps(allCircles, radius);
        pruned = this._quickPruneCapsuleOverlaps(
            source,
            pruned.kept,
            pruned.removed,
            radius,
            capsuleStart,
            horizontalAxisY,
            aboveAxisGap,
            belowAxisGap,
            verticalAxisX,
            capsuleClearance,
        );
        const capsules = this._capsulesFromKeptCircles(
            source,
            pruned.kept,
            radius,
            capsuleStart,
            horizontalAxisY,
            aboveAxisGap,
            belowAxisGap,
        );
        return {
            rays,
            capsules,
            circles: pruned.kept,
            removed_circles: pruned.removed,
        };
    }

    _basisWithApproxTopGap(basis, params, baseGeometry, svgScale) {
        const gap = Math.max(0, Number(params.top_gap_distance || 0)) * svgScale;
        const marker = baseGeometry.apex_marker;
        if (!basis.length || gap <= 0 || !marker) return basis;
        const cx = Number(marker.cx);
        const cy = Number(marker.cy);
        const filtered = basis.filter((b) => Math.hypot(Number(b.x || 0) - cx, Number(b.y || 0) - cy) >= gap);
        return filtered.length ? filtered : [];
    }

    _resampleBasis(basis, count) {
        if (count <= 0 || !basis.length) return [];
        if (count === basis.length) return basis.slice();
        if (count === 1) {
            return [basis[Math.floor((basis.length - 1) / 2)]];
        }
        const result = [];
        const maxSource = basis.length - 1;
        for (let i = 0; i < count; i++) {
            const t = maxSource * i / (count - 1);
            const left = Math.floor(t);
            const right = Math.min(maxSource, left + 1);
            const f = t - left;
            const a = basis[left];
            const b = basis[right];
            let nx = Number(a.nx || 0) * (1 - f) + Number(b.nx || 0) * f;
            let ny = Number(a.ny || 0) * (1 - f) + Number(b.ny || 0) * f;
            const mag = Math.hypot(nx, ny);
            if (mag > 1e-9) {
                nx /= mag;
                ny /= mag;
            }
            result.push({
                x: Number(a.x || 0) * (1 - f) + Number(b.x || 0) * f,
                y: Number(a.y || 0) * (1 - f) + Number(b.y || 0) * f,
                nx,
                ny,
            });
        }
        return result;
    }

    _capsulesFromKeptCircles(
        basis,
        keptCircles,
        radius,
        nearDistance,
        axisY = null,
        aboveAxisGap = 0,
        belowAxisGap = 0,
        axisX = null,
        clearance = 0,
    ) {
        const groups = new Map();
        for (const circle of keptCircles) {
            if (!groups.has(circle.placementIndex)) groups.set(circle.placementIndex, []);
            groups.get(circle.placementIndex).push(circle);
        }

        const capsules = [];
        for (const [placementIndex, circles] of groups.entries()) {
            if (!basis[placementIndex] || circles.length < 1) continue;
            if (axisY !== null) {
                const dy = axisY - Number(basis[placementIndex].y);
                if (dy >= 0 && aboveAxisGap > 0 && dy <= aboveAxisGap + 0.001) {
                    continue;
                }
                if (dy < 0 && belowAxisGap > 0 && Math.abs(dy) <= belowAxisGap + 0.001) {
                    continue;
                }
            }
            circles.sort((a, b) => a.circleIndex - b.circleIndex);
            const far = circles[circles.length - 1];
            capsules.push(this._capsulePathToKeptFarCircle(basis[placementIndex], far, nearDistance, radius));
        }
        return capsules;
    }

    _capsulePathToKeptFarCircle(base, far, nearDistance, radius) {
        const dx = far.cx - base.x;
        const dy = far.cy - base.y;
        const length = Math.hypot(dx, dy);
        if (length <= 1e-6) return null;
        return this._capsulePathFromRayBasis(
            base,
            dx / length,
            dy / length,
            nearDistance,
            length,
            radius,
        );
    }

    _capsulePathFromRayBasis(base, nx, ny, nearDistance, farDistance, radius) {
        if (radius <= 0 || Math.abs(farDistance - nearDistance) <= 1e-6) {
            return null;
        }
        const nearX = base.x + nx * nearDistance;
        const nearY = base.y + ny * nearDistance;
        const farX = base.x + nx * farDistance;
        const farY = base.y + ny * farDistance;
        let dx = farX - nearX;
        let dy = farY - nearY;
        const length = Math.hypot(dx, dy);
        if (length <= 1e-6) return null;
        dx /= length;
        dy /= length;
        const px = dy;
        const py = -dx;
        const nearLeft = { x: nearX + px * radius, y: nearY + py * radius };
        const farLeft = { x: farX + px * radius, y: farY + py * radius };
        const farRight = { x: farX - px * radius, y: farY - py * radius };
        const nearRight = { x: nearX - px * radius, y: nearY - py * radius };
        return {
            d: `M ${nearLeft.x.toFixed(1)} ${nearLeft.y.toFixed(1)} `
                + `L ${farLeft.x.toFixed(1)} ${farLeft.y.toFixed(1)} `
                + `A ${radius.toFixed(1)} ${radius.toFixed(1)} 0 0 1 ${farRight.x.toFixed(1)} ${farRight.y.toFixed(1)} `
                + `L ${nearRight.x.toFixed(1)} ${nearRight.y.toFixed(1)} `
                + `A ${radius.toFixed(1)} ${radius.toFixed(1)} 0 0 1 ${nearLeft.x.toFixed(1)} ${nearLeft.y.toFixed(1)} Z`,
        };
    }

    _quickPruneOverlaps(circles, radius) {
        if (!circles.length || radius <= 0) {
            return { kept: circles, removed: [] };
        }
        const minDistance = radius * 2 - 0.01;
        const minDistanceSq = minDistance * minDistance;
        const cellSize = Math.max(radius * 2, 1);
        const cells = new Map();
        const kept = [];
        const removed = [];

        const key = (ix, iy) => `${ix},${iy}`;
        for (const circle of circles) {
            const ix = Math.floor(circle.cx / cellSize);
            const iy = Math.floor(circle.cy / cellSize);
            let overlaps = false;
            for (let dx = -1; dx <= 1 && !overlaps; dx++) {
                for (let dy = -1; dy <= 1 && !overlaps; dy++) {
                    const bucket = cells.get(key(ix + dx, iy + dy)) || [];
                    for (const other of bucket) {
                        const ox = circle.cx - other.cx;
                        const oy = circle.cy - other.cy;
                        if (ox * ox + oy * oy < minDistanceSq) {
                            overlaps = true;
                            break;
                        }
                    }
                }
            }
            if (overlaps) {
                removed.push(circle);
                continue;
            }
            kept.push(circle);
            const bucketKey = key(ix, iy);
            if (!cells.has(bucketKey)) cells.set(bucketKey, []);
            cells.get(bucketKey).push(circle);
        }
        return { kept, removed };
    }

    _quickPruneCapsuleOverlaps(
        basis,
        keptCircles,
        removedCircles,
        radius,
        nearDistance,
        axisY = null,
        aboveAxisGap = 0,
        belowAxisGap = 0,
        axisX = null,
        clearance = 0,
    ) {
        if (keptCircles.length <= 1 || radius <= 0) {
            return { kept: keptCircles, removed: removedCircles };
        }
        const kept = keptCircles.slice();
        const removed = removedCircles.slice();
        const minDistance = radius * 2 + Math.max(0, clearance) - 0.01;

        for (let guard = 0; guard < 10000; guard++) {
            const capsules = this._quickCapsuleRecords(
                basis,
                kept,
                radius,
                nearDistance,
                axisY,
                aboveAxisGap,
                belowAxisGap,
            );
            let best = null;
            for (let i = 0; i < capsules.length; i++) {
                for (let j = i + 1; j < capsules.length; j++) {
                    const distance = this._segmentDistance(
                        capsules[i].near,
                        capsules[i].far,
                        capsules[j].near,
                        capsules[j].far,
                    );
                    const penetration = minDistance - distance;
                    if (penetration <= 0) continue;
                    if (!best || penetration > best.penetration) {
                        best = { penetration, first: capsules[i], second: capsules[j] };
                    }
                }
            }
            if (!best) break;

            const candidates = [best.first.outerCircle, best.second.outerCircle].filter(Boolean);
            if (!candidates.length) break;
            const loserIndex = candidates.reduce((bestIndex, circle, index) => {
                const bestCircle = candidates[bestIndex];
                if (circle.circleIndex !== bestCircle.circleIndex) {
                    return circle.circleIndex > bestCircle.circleIndex ? index : bestIndex;
                }
                return circle.placementIndex > bestCircle.placementIndex ? index : bestIndex;
            }, 0);
            const loser = candidates[loserIndex];
            const keptIndex = kept.indexOf(loser);
            if (keptIndex < 0) break;
            kept.splice(keptIndex, 1);
            removed.push(loser);
            const mirror = this._findMirrorCircle(kept, loser, axisX, radius);
            if (mirror) {
                const mirrorIndex = kept.indexOf(mirror);
                if (mirrorIndex >= 0) {
                    kept.splice(mirrorIndex, 1);
                    removed.push(mirror);
                }
            }
        }
        return { kept, removed };
    }

    _findMirrorCircle(circles, circle, axisX = null, radius = 0) {
        if (axisX === null) return null;
        const mirroredX = 2 * axisX - circle.cx;
        const candidates = circles.filter((candidate) => (
            candidate !== circle
            && candidate.circleIndex === circle.circleIndex
            && (candidate.cx - axisX) * (circle.cx - axisX) <= 0
        ));
        if (!candidates.length) return null;
        const best = candidates.reduce((current, candidate) => {
            const currentDistance = Math.hypot(current.cx - mirroredX, current.cy - circle.cy);
            const candidateDistance = Math.hypot(candidate.cx - mirroredX, candidate.cy - circle.cy);
            return candidateDistance < currentDistance ? candidate : current;
        });
        const limit = Math.max(radius * 4, 1);
        return Math.hypot(best.cx - mirroredX, best.cy - circle.cy) <= limit ? best : null;
    }

    _quickCapsuleRecords(
        basis,
        keptCircles,
        radius,
        nearDistance,
        axisY = null,
        aboveAxisGap = 0,
        belowAxisGap = 0,
    ) {
        const groups = new Map();
        for (const circle of keptCircles) {
            if (!groups.has(circle.placementIndex)) groups.set(circle.placementIndex, []);
            groups.get(circle.placementIndex).push(circle);
        }

        const capsules = [];
        for (const [placementIndex, circles] of groups.entries()) {
            const base = basis[placementIndex];
            if (!base || !circles.length) continue;
            if (this._basisInsideCapsuleAxisGap(base, axisY, aboveAxisGap, belowAxisGap)) {
                continue;
            }
            const sorted = circles.slice().sort((a, b) => a.circleIndex - b.circleIndex);
            const farCircle = sorted[sorted.length - 1];
            const dx = farCircle.cx - base.x;
            const dy = farCircle.cy - base.y;
            const farDistance = Math.hypot(dx, dy);
            if (farDistance <= nearDistance + 1e-6) continue;
            const nx = dx / farDistance;
            const ny = dy / farDistance;
            capsules.push({
                placementIndex,
                outerCircle: farCircle,
                near: {
                    x: base.x + nx * nearDistance,
                    y: base.y + ny * nearDistance,
                },
                far: {
                    x: farCircle.cx,
                    y: farCircle.cy,
                },
            });
        }
        return capsules;
    }

    _basisInsideCapsuleAxisGap(base, axisY = null, aboveAxisGap = 0, belowAxisGap = 0) {
        if (axisY === null) return false;
        const dy = axisY - Number(base.y);
        if (dy >= 0 && aboveAxisGap > 0 && dy <= aboveAxisGap + 0.001) {
            return true;
        }
        return dy < 0 && belowAxisGap > 0 && Math.abs(dy) <= belowAxisGap + 0.001;
    }

    _segmentDistance(a1, a2, b1, b2) {
        const ux = a2.x - a1.x;
        const uy = a2.y - a1.y;
        const vx = b2.x - b1.x;
        const vy = b2.y - b1.y;
        const wx = a1.x - b1.x;
        const wy = a1.y - b1.y;
        const a = ux * ux + uy * uy;
        const b = ux * vx + uy * vy;
        const c = vx * vx + vy * vy;
        const d = ux * wx + uy * wy;
        const e = vx * wx + vy * wy;
        const denominator = a * c - b * b;

        if (a <= 1e-12 && c <= 1e-12) {
            return Math.hypot(a1.x - b1.x, a1.y - b1.y);
        }
        if (a <= 1e-12) {
            const t = Math.max(0, Math.min(1, c > 1e-12 ? e / c : 0));
            return Math.hypot(a1.x - (b1.x + vx * t), a1.y - (b1.y + vy * t));
        }
        if (c <= 1e-12) {
            const s = Math.max(0, Math.min(1, -d / a));
            return Math.hypot((a1.x + ux * s) - b1.x, (a1.y + uy * s) - b1.y);
        }

        let s = denominator > 1e-12
            ? Math.max(0, Math.min(1, (b * e - c * d) / denominator))
            : 0;
        const tNumerator = b * s + e;
        let t;
        if (tNumerator < 0) {
            t = 0;
            s = Math.max(0, Math.min(1, -d / a));
        } else if (tNumerator > c) {
            t = 1;
            s = Math.max(0, Math.min(1, (b - d) / a));
        } else {
            t = tNumerator / c;
        }

        const ax = a1.x + ux * s;
        const ay = a1.y + uy * s;
        const bx = b1.x + vx * t;
        const by = b1.y + vy * t;
        return Math.hypot(ax - bx, ay - by);
    }

    resetView() {
        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this._applyTransform();
    }

    setHover(handle, pathD) {
        if (!this.hoverPath) return;
        if (!handle || !pathD) {
            this.clearHover();
            return;
        }
        if (handle === this.lastHoverHandle && this.hoverPath.getAttribute("d") === pathD) {
            return;
        }
        this.lastHoverHandle = handle;
        this.hoverPath.setAttribute("d", pathD);
        this.hoverPath.style.display = "";
        this.container.classList.add("has-selectable-hover");
    }

    clearHover() {
        if (this.localHoverElement && this.localHoverElement.classList) {
            this.localHoverElement.classList.remove("local-hover-highlight");
        }
        this.localHoverElement = null;
        this._renderLocalHover(null);
        if (!this.hoverPath) return;
        this.lastHoverHandle = null;
        this.hoverPath.removeAttribute("d");
        this.hoverPath.style.display = "none";
        this.container.classList.remove("has-selectable-hover");
    }

    setLocalHoverElement(element) {
        if (element === this.localHoverElement) return;
        if (this.localHoverElement && this.localHoverElement.classList) {
            this.localHoverElement.classList.remove("local-hover-highlight");
        }
        this.localHoverElement = element || null;
        if (this.localHoverElement) {
            if (this.localHoverElement.pathD) {
                this._renderLocalHover(null);
                this.setHover(this.localHoverElement.handle, this.localHoverElement.pathD);
            } else {
                this.localHoverElement.classList.add("local-hover-highlight");
                this._renderLocalHover(this.localHoverElement);
                this.container.classList.add("has-selectable-hover");
            }
        } else {
            this._renderLocalHover(null);
            if (this.hoverPath) {
                this.lastHoverHandle = null;
                this.hoverPath.removeAttribute("d");
                this.hoverPath.style.display = "none";
            }
            this.container.classList.remove("has-selectable-hover");
        }
    }

    _renderLocalHover(owner) {
        if (!this.hoverVisualLayer) return;
        this.hoverVisualLayer.innerHTML = "";
        if (!owner) return;

        const clone = owner.cloneNode(true);
        clone.removeAttribute("id");
        clone.removeAttribute("class");
        clone.setAttribute("data-hover-visual", "true");
        this._prepareHoverVisual(clone);
        this.hoverVisualLayer.appendChild(clone);
    }

    _prepareHoverVisual(root) {
        const shapeSelector = "path,line,polyline,polygon,circle,ellipse,rect";
        const shapes = root.matches && root.matches(shapeSelector)
            ? [root]
            : Array.from(root.querySelectorAll(shapeSelector));
        for (const shape of shapes) {
            shape.removeAttribute("id");
            shape.removeAttribute("class");
            shape.removeAttribute("style");
            shape.setAttribute("fill", "none");
            shape.setAttribute("stroke", "#FFD166");
            shape.setAttribute("stroke-opacity", "1");
            shape.setAttribute("stroke-width", "4");
            shape.setAttribute("stroke-linecap", "round");
            shape.setAttribute("stroke-linejoin", "round");
            shape.setAttribute("vector-effect", "non-scaling-stroke");
            shape.setAttribute("pointer-events", "none");
        }
        root.querySelectorAll("*").forEach((el) => {
            el.removeAttribute("id");
            el.removeAttribute("class");
            el.removeAttribute("style");
            el.setAttribute("pointer-events", "none");
        });
    }

    _buildLocalHoverHitLayer(viewport, hoverPaths = []) {
        this.hoverOwners = new Map();
        this.hoverPathMap = new Map();
        const hitLayer = document.createElementNS(SVG_NS, "g");
        hitLayer.setAttribute("id", "local-hover-hit-layer");
        hitLayer.setAttribute("pointer-events", "all");

        for (const item of hoverPaths || []) {
            if (!item || !item.handle || !item.path_d) continue;
            this.hoverPathMap.set(item.handle, item.path_d);
            const proxy = document.createElementNS(SVG_NS, "path");
            proxy.setAttribute("d", item.path_d);
            proxy.setAttribute("data-hover-proxy", "true");
            proxy.setAttribute("data-handle", item.handle);
            proxy.style.cursor = "pointer";
            this._prepareHoverProxy(proxy);
            hitLayer.appendChild(proxy);
        }

        const owners = Array.from(viewport.querySelectorAll("[data-handle]"));
        const shapeSelector = "path,line,polyline,polygon,circle,ellipse,rect";
        for (const owner of owners) {
            const handle = owner.getAttribute("data-handle");
            if (!handle || this.hoverOwners.has(handle)) continue;
            this.hoverOwners.set(handle, owner);

            const shapes = owner.matches && owner.matches(shapeSelector)
                ? [owner]
                : Array.from(owner.querySelectorAll(shapeSelector));
            for (const shape of shapes) {
                const proxy = shape.cloneNode(false);
                proxy.removeAttribute("id");
                proxy.removeAttribute("class");
                proxy.removeAttribute("style");
                proxy.setAttribute("data-hover-proxy", "true");
                proxy.setAttribute("data-handle", handle);
                proxy.style.cursor = "pointer";
                this._prepareHoverProxy(proxy);
                hitLayer.appendChild(proxy);
            }
        }

        viewport.appendChild(hitLayer);
        return hitLayer;
    }

    _prepareHoverProxy(root) {
        const shapeSelector = "path,line,polyline,polygon,circle,ellipse,rect";
        const shapes = root.matches && root.matches(shapeSelector)
            ? [root]
            : Array.from(root.querySelectorAll(shapeSelector));
        for (const shape of shapes) {
            shape.removeAttribute("id");
            shape.removeAttribute("class");
            shape.removeAttribute("style");
            shape.setAttribute("fill", "none");
            shape.setAttribute("stroke", "#ffffff");
            shape.setAttribute("stroke-opacity", "0.001");
            shape.setAttribute("stroke-width", "32");
            shape.setAttribute("stroke-linecap", "round");
            shape.setAttribute("stroke-linejoin", "round");
            shape.setAttribute("vector-effect", "non-scaling-stroke");
            shape.setAttribute("pointer-events", "stroke");
        }
        root.querySelectorAll("*").forEach((el) => {
            el.removeAttribute("id");
            el.removeAttribute("class");
            if (!el.matches(shapeSelector)) {
                el.setAttribute("pointer-events", "none");
            }
        });
    }

    _localHoverTarget(e) {
        const proxy = e.target && e.target.closest ? e.target.closest("[data-hover-proxy]") : null;
        if (proxy && this.svg.contains(proxy)) {
            const handle = proxy.getAttribute("data-handle");
            const pathD = this.hoverPathMap.get(handle);
            if (pathD) return { handle, pathD };
            return this.hoverOwners.get(handle) || null;
        }

        const direct = e.target && e.target.closest ? e.target.closest("[data-handle]") : null;
        if (direct && this.svg.contains(direct)) {
            const handle = direct.getAttribute("data-handle");
            const pathD = this.hoverPathMap.get(handle);
            if (pathD) return { handle, pathD };
            return this.hoverOwners.get(handle) || direct;
        }

        for (const element of document.elementsFromPoint(e.clientX, e.clientY)) {
            if (!this.svg.contains(element) || !element.closest) continue;
            const proxyCandidate = element.closest("[data-hover-proxy]");
            if (proxyCandidate && this.svg.contains(proxyCandidate)) {
                const handle = proxyCandidate.getAttribute("data-handle");
                const pathD = this.hoverPathMap.get(handle);
                if (pathD) return { handle, pathD };
                return this.hoverOwners.get(handle) || null;
            }
            const candidate = element.closest("[data-handle]");
            if (candidate && this.svg.contains(candidate)) {
                const handle = candidate.getAttribute("data-handle");
                const pathD = this.hoverPathMap.get(handle);
                if (pathD) return { handle, pathD };
                return this.hoverOwners.get(handle) || candidate;
            }
        }
        return null;
    }

    /**
     * Convert a screen (client) point to authored drawing viewBox coordinates.
     * The root SVG's CTM maps to the viewport-group-transformed space, so we
     * additionally undo the pan/zoom transform to get back to the drawing's
     * own coordinates (which the backend's WCS transform expects).
     */
    clientPointToSvg(clientX, clientY) {
        if (!this.svg) return { x: clientX, y: clientY };
        const v = this.clientPointToRootSvg(clientX, clientY);
        return {
            x: (v.x - this.translateX) / this.scale,
            y: (v.y - this.translateY) / this.scale,
        };
    }

    clientPointToRootSvg(clientX, clientY) {
        if (!this.svg) return { x: clientX, y: clientY };
        const pt = this.svg.createSVGPoint();
        pt.x = clientX;
        pt.y = clientY;
        return pt.matrixTransform(this.svg.getScreenCTM().inverse());
    }

    svgPointToClient(svgX, svgY) {
        if (!this.svg) return { x: svgX, y: svgY };
        const pt = this.svg.createSVGPoint();
        pt.x = svgX * this.scale + this.translateX;
        pt.y = svgY * this.scale + this.translateY;
        return pt.matrixTransform(this.svg.getScreenCTM());
    }

    /**
     * WCS units per screen pixel at the current zoom (for a pick aperture).
     */
    wcsPerPixel() {
        if (!this.svg) return 0;
        const ctm = this.svg.getScreenCTM();
        if (!ctm || Math.abs(ctm.a) < 1e-12) return 0;
        // getScreenCTM maps root viewBox units to CSS pixels. Invert it to get
        // viewBox units per pixel, then undo viewport zoom and convert to WCS.
        const viewBoxUnitsPerPixel = 1 / Math.abs(ctm.a);
        return viewBoxUnitsPerPixel / Math.max(this.scale, 1e-9) / Math.max(this.baseScale, 1e-9);
    }

    _applyTransform() {
        if (this.viewport) {
            this.viewport.setAttribute(
                "transform",
                `translate(${this.translateX.toFixed(3)}, ${this.translateY.toFixed(3)}) scale(${this.scale.toFixed(8)})`,
            );
        }
    }

    _bindEvents() {
        this.container.addEventListener("mousedown", (e) => {
            this.mouseMoved = false;
            this.mouseDownPos = { clientX: e.clientX, clientY: e.clientY };

            if (e.button !== 1) return; // middle mouse for pan
            if (e.target.closest("input, button, select, textarea")) return;

            e.preventDefault();
            this.isPanning = true;
            this.panButton = e.button;
            // Capture raw SVG root-viewBox point (unaffected by translate) for
            // stable pan-delta.  Using clientPointToSvg() creates feedback because
            // it subtracts the evolving translateX/Y.
            const pt = this.svg.createSVGPoint();
            pt.x = e.clientX;
            pt.y = e.clientY;
            this.startMouseRawSvg = pt.matrixTransform(this.svg.getScreenCTM().inverse());
            this.startTranslate = { x: this.translateX, y: this.translateY };
            this.container.classList.add("is-panning");
        });

        window.addEventListener("mousemove", (e) => {
            if (e.buttons === 0) return;

            const dx = e.clientX - this.mouseDownPos.clientX;
            const dy = e.clientY - this.mouseDownPos.clientY;
            if (Math.hypot(dx, dy) > 3) {
                this.mouseMoved = true;
            }

            if (!this.isPanning) return;
            const pt = this.svg.createSVGPoint();
            pt.x = e.clientX;
            pt.y = e.clientY;
            const currentRaw = pt.matrixTransform(this.svg.getScreenCTM().inverse());
            this.translateX = this.startTranslate.x + (currentRaw.x - this.startMouseRawSvg.x);
            this.translateY = this.startTranslate.y + (currentRaw.y - this.startMouseRawSvg.y);
            this._applyTransform();
        });

        window.addEventListener("mouseup", (e) => {
            if (!this.isPanning) return;
            if (e.button === this.panButton) {
                this.isPanning = false;
                this.panButton = -1;
                this.container.classList.remove("is-panning");
            }
        });

        this.container.addEventListener("contextmenu", (e) => e.preventDefault());

        this.container.addEventListener("wheel", (e) => {
            e.preventDefault();
            if (!this.svg) return;

            const raw = this.clientPointToRootSvg(e.clientX, e.clientY);
            const anchoredPoint = {
                x: (raw.x - this.translateX) / this.scale,
                y: (raw.y - this.translateY) / this.scale,
            };
            const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
            const newScale = Math.max(0.05, Math.min(25, this.scale * zoomFactor));

            this.translateX = raw.x - anchoredPoint.x * newScale;
            this.translateY = raw.y - anchoredPoint.y * newScale;
            this.scale = newScale;
            this._applyTransform();
        });
    }

    _handleClick(e) {
        if (this.mouseMoved) {
            this.mouseMoved = false;
            return;
        }
        if (!this.svg) return;

        const pt = this.clientPointToSvg(e.clientX, e.clientY);
        const hoverTarget = this._localHoverTarget(e);
        const hoverHandle = hoverTarget
            ? (hoverTarget.handle || (hoverTarget.getAttribute ? hoverTarget.getAttribute("data-handle") : null))
            : this.lastHoverHandle;
        if (this.onClick) {
            this.onClick({
                svgX: pt.x,
                svgY: pt.y,
                tol: 5 * this.wcsPerPixel(), // ~5px pick aperture in WCS
                hoverHandle,
                ctrlKey: e.ctrlKey || e.metaKey,
                shiftKey: e.shiftKey,
            });
        }
    }

    _handleMouseMove(e) {
        if (!this.svg || !this.onMouseMove) return;
        const pt = this.clientPointToSvg(e.clientX, e.clientY);
        this.onMouseMove({ x: pt.x, y: pt.y });
        if (this.isPanning) return;
        this.setLocalHoverElement(this._localHoverTarget(e));
    }
}

const svgViewer = new SvgViewer("svg-container");
