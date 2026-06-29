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
        this.hoverHitLayer = null;
        this.hoverVisualLayer = null;
        this.hoverOwners = new Map();

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
        this.apexPickMode = false;
        this.symmetrySnapPoint = null;

        this._bindEvents();
    }

    setBaseSvg(svgString) {
        this.container.innerHTML = svgString;
        this.svg = this.container.querySelector("svg");
        if (!this.svg) return;

        // Wrap every existing child in a viewport group (for pan/zoom) and add
        // an overlay group inside it so the overlay transforms with the drawing.
        const viewport = document.createElementNS(SVG_NS, "g");
        viewport.setAttribute("id", "dxf-viewport");
        while (this.svg.firstChild) {
            viewport.appendChild(this.svg.firstChild);
        }
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

        const hitLayer = this._buildLocalHoverHitLayer(viewport);
        viewport.appendChild(overlay);

        this.viewport = viewport;
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
            this._setSnapPreviewActive(false);
        });

        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this._hasSetInitialView = true;
        this._applyTransform();
    }

    setOverlay(geometry, showGenerated) {
        if (!this.generatedLayer) return;
        geometry = geometry || {};

        // Rebuild generated layer (rays + circles).
        this.generatedLayer.innerHTML = "";
        this.generatedLayer.style.display = showGenerated ? "" : "none";

        const rays = geometry.rays || [];
        for (const r of rays) {
            const line = document.createElementNS(SVG_NS, "line");
            line.setAttribute("x1", r.x1.toFixed(1));
            line.setAttribute("y1", r.y1.toFixed(1));
            line.setAttribute("x2", r.x2.toFixed(1));
            line.setAttribute("y2", r.y2.toFixed(1));
            line.setAttribute("stroke", "#B8B8B8");
            line.setAttribute("stroke-width", "1.2");
            line.setAttribute("stroke-opacity", "0.45");
            line.setAttribute("stroke-dasharray", "6 6");
            line.setAttribute("vector-effect", "non-scaling-stroke");
            this.generatedLayer.appendChild(line);
        }

        const removedCircles = geometry.removed_circles || [];
        for (const c of removedCircles) {
            const circle = document.createElementNS(SVG_NS, "circle");
            circle.setAttribute("cx", c.cx.toFixed(1));
            circle.setAttribute("cy", c.cy.toFixed(1));
            circle.setAttribute("r", c.r.toFixed(1));
            circle.setAttribute("fill", "rgba(160, 160, 160, 0.14)");
            circle.setAttribute("stroke", "#9A9A9A");
            circle.setAttribute("stroke-width", "1.6");
            circle.setAttribute("stroke-opacity", "0.48");
            circle.setAttribute("stroke-dasharray", "4 4");
            circle.setAttribute("vector-effect", "non-scaling-stroke");
            this.generatedLayer.appendChild(circle);
        }

        const circles = geometry.circles || [];
        for (const c of circles) {
            const circle = document.createElementNS(SVG_NS, "circle");
            circle.setAttribute("cx", c.cx.toFixed(1));
            circle.setAttribute("cy", c.cy.toFixed(1));
            circle.setAttribute("r", c.r.toFixed(1));
            circle.setAttribute("fill", "none");
            circle.setAttribute("stroke", "#FF6B6B");
            circle.setAttribute("stroke-width", "1.8");
            circle.setAttribute("vector-effect", "non-scaling-stroke");
            this.generatedLayer.appendChild(circle);
        }

        // Selection highlight: replace any existing chain path.
        const oldPath = this.overlay.querySelector("#selected-chain-path");
        if (oldPath) oldPath.remove();
        const oldApex = this.overlay.querySelector("#manual-apex-marker");
        if (oldApex) oldApex.remove();
        const oldAxis = this.overlay.querySelector("#symmetry-axis-line");
        if (oldAxis) oldAxis.remove();
        const oldSnap = this.overlay.querySelector("#symmetry-snap-marker");
        if (oldSnap) oldSnap.remove();
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

        const axis = geometry.symmetry_axis;
        if (axis) {
            const line = document.createElementNS(SVG_NS, "line");
            line.setAttribute("id", "symmetry-axis-line");
            line.setAttribute("x1", axis.x1.toFixed(1));
            line.setAttribute("y1", axis.y1.toFixed(1));
            line.setAttribute("x2", axis.x2.toFixed(1));
            line.setAttribute("y2", axis.y2.toFixed(1));
            line.setAttribute("stroke", "#FF5C5C");
            line.setAttribute("stroke-width", "1.8");
            line.setAttribute("stroke-opacity", "0.55");
            line.setAttribute("stroke-dasharray", "8 7");
            line.setAttribute("vector-effect", "non-scaling-stroke");
            line.setAttribute("pointer-events", "none");
            this.overlay.insertBefore(line, this.generatedLayer);
        }

        this.symmetrySnapPoint = geometry.symmetry_snap_point || null;
        if (this.symmetrySnapPoint) {
            const snap = this.symmetrySnapPoint;
            const group = document.createElementNS(SVG_NS, "g");
            group.setAttribute("id", "symmetry-snap-marker");
            group.setAttribute("pointer-events", "none");

            const ring = document.createElementNS(SVG_NS, "circle");
            ring.setAttribute("cx", snap.cx.toFixed(1));
            ring.setAttribute("cy", snap.cy.toFixed(1));
            ring.setAttribute("r", Math.max(14, snap.r || 0).toFixed(1));
            ring.setAttribute("fill", "rgba(255, 42, 42, 0.32)");
            ring.setAttribute("stroke", "#FF5C5C");
            ring.setAttribute("stroke-width", "3.4");
            ring.setAttribute("vector-effect", "non-scaling-stroke");

            const dot = document.createElementNS(SVG_NS, "circle");
            dot.setAttribute("cx", snap.cx.toFixed(1));
            dot.setAttribute("cy", snap.cy.toFixed(1));
            dot.setAttribute("r", "4.8");
            dot.setAttribute("fill", "#FF2A2A");
            dot.setAttribute("vector-effect", "non-scaling-stroke");

            const crossH = document.createElementNS(SVG_NS, "line");
            const crossSize = Math.max(22, (snap.r || 0) + 10);
            crossH.setAttribute("x1", (snap.cx - crossSize).toFixed(1));
            crossH.setAttribute("y1", snap.cy.toFixed(1));
            crossH.setAttribute("x2", (snap.cx + crossSize).toFixed(1));
            crossH.setAttribute("y2", snap.cy.toFixed(1));
            crossH.setAttribute("stroke", "#FF5C5C");
            crossH.setAttribute("stroke-width", "2.4");
            crossH.setAttribute("vector-effect", "non-scaling-stroke");

            const crossV = document.createElementNS(SVG_NS, "line");
            crossV.setAttribute("x1", snap.cx.toFixed(1));
            crossV.setAttribute("y1", (snap.cy - crossSize).toFixed(1));
            crossV.setAttribute("x2", snap.cx.toFixed(1));
            crossV.setAttribute("y2", (snap.cy + crossSize).toFixed(1));
            crossV.setAttribute("stroke", "#FF5C5C");
            crossV.setAttribute("stroke-width", "2.4");
            crossV.setAttribute("vector-effect", "non-scaling-stroke");

            group.appendChild(ring);
            group.appendChild(dot);
            group.appendChild(crossH);
            group.appendChild(crossV);
            this.overlay.insertBefore(group, this.generatedLayer);
        }

        const marker = geometry.apex_marker;
        if (marker) {
            const group = document.createElementNS(SVG_NS, "g");
            group.setAttribute("id", "manual-apex-marker");
            group.setAttribute("pointer-events", "none");

            const outer = document.createElementNS(SVG_NS, "circle");
            outer.setAttribute("cx", marker.cx.toFixed(1));
            outer.setAttribute("cy", marker.cy.toFixed(1));
            outer.setAttribute("r", marker.r.toFixed(1));
            outer.setAttribute("fill", "rgba(255, 209, 102, 0.18)");
            outer.setAttribute("stroke", "#FFD166");
            outer.setAttribute("stroke-width", "2.2");
            outer.setAttribute("vector-effect", "non-scaling-stroke");

            const dot = document.createElementNS(SVG_NS, "circle");
            dot.setAttribute("cx", marker.cx.toFixed(1));
            dot.setAttribute("cy", marker.cy.toFixed(1));
            dot.setAttribute("r", "2.8");
            dot.setAttribute("fill", "#FFD166");
            dot.setAttribute("vector-effect", "non-scaling-stroke");

            group.appendChild(outer);
            group.appendChild(dot);
            this.overlay.insertBefore(group, this.generatedLayer);
        }
    }

    setApexPickMode(active) {
        this.apexPickMode = Boolean(active);
        this.container.classList.toggle("is-picking-apex", this.apexPickMode);
        if (!this.apexPickMode) {
            this._setSnapPreviewActive(false);
        }
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
        if (this.localHoverElement) {
            this.localHoverElement.classList.remove("local-hover-highlight");
            this.localHoverElement = null;
        }
        this._renderLocalHover(null);
        if (!this.hoverPath) return;
        this.lastHoverHandle = null;
        this.hoverPath.removeAttribute("d");
        this.hoverPath.style.display = "none";
        this.container.classList.remove("has-selectable-hover");
    }

    setLocalHoverElement(element) {
        if (element === this.localHoverElement) return;
        if (this.localHoverElement) {
            this.localHoverElement.classList.remove("local-hover-highlight");
        }
        this.localHoverElement = element || null;
        if (this.localHoverElement) {
            this.localHoverElement.classList.add("local-hover-highlight");
            this._renderLocalHover(this.localHoverElement);
            this.container.classList.add("has-selectable-hover");
        } else {
            this._renderLocalHover(null);
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

    _buildLocalHoverHitLayer(viewport) {
        this.hoverOwners = new Map();
        const hitLayer = document.createElementNS(SVG_NS, "g");
        hitLayer.setAttribute("id", "local-hover-hit-layer");

        const owners = Array.from(viewport.querySelectorAll("[data-handle]"));
        for (const owner of owners) {
            const handle = owner.getAttribute("data-handle");
            if (!handle || this.hoverOwners.has(handle)) continue;
            this.hoverOwners.set(handle, owner);

            const proxy = owner.cloneNode(true);
            proxy.removeAttribute("id");
            proxy.removeAttribute("class");
            proxy.setAttribute("data-hover-proxy", "true");
            proxy.setAttribute("data-handle", handle);
            proxy.style.cursor = "pointer";
            this._prepareHoverProxy(proxy);
            hitLayer.appendChild(proxy);
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
            shape.setAttribute("fill", "none");
            shape.setAttribute("stroke", "rgba(255, 255, 255, 0.001)");
            shape.setAttribute("stroke-width", "24");
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
            return this.hoverOwners.get(proxy.getAttribute("data-handle")) || null;
        }

        const direct = e.target && e.target.closest ? e.target.closest("[data-handle]") : null;
        if (direct && this.svg.contains(direct)) {
            const handle = direct.getAttribute("data-handle");
            return this.hoverOwners.get(handle) || direct;
        }

        for (const element of document.elementsFromPoint(e.clientX, e.clientY)) {
            if (!this.svg.contains(element) || !element.closest) continue;
            const proxyCandidate = element.closest("[data-hover-proxy]");
            if (proxyCandidate && this.svg.contains(proxyCandidate)) {
                return this.hoverOwners.get(proxyCandidate.getAttribute("data-handle")) || null;
            }
            const candidate = element.closest("[data-handle]");
            if (candidate && this.svg.contains(candidate)) {
                const handle = candidate.getAttribute("data-handle");
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
                `translate(${this.translateX.toFixed(1)}, ${this.translateY.toFixed(1)}) scale(${this.scale.toFixed(6)})`,
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
            const newScale = Math.max(0.05, Math.min(100, this.scale * zoomFactor));

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
        if (this.onClick) {
            this.onClick({
                svgX: pt.x,
                svgY: pt.y,
                tol: 5 * this.wcsPerPixel(), // ~5px pick aperture in WCS
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
        this._updateApexSnapPreview(e);
    }

    _setSnapPreviewActive(active) {
        const marker = this.overlay ? this.overlay.querySelector("#symmetry-snap-marker") : null;
        if (!marker) return;
        marker.classList.toggle("is-active", Boolean(active));
    }

    _updateApexSnapPreview(e) {
        if (!this.apexPickMode || !this.symmetrySnapPoint) {
            this._setSnapPreviewActive(false);
            return;
        }
        const client = this.svgPointToClient(this.symmetrySnapPoint.cx, this.symmetrySnapPoint.cy);
        const distance = Math.hypot(client.x - e.clientX, client.y - e.clientY);
        this._setSnapPreviewActive(distance <= 42);
    }
}

const svgViewer = new SvgViewer("svg-container");
