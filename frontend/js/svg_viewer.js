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

        // View transform
        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this._hasSetInitialView = false;

        this.isPanning = false;
        this.panButton = -1;
        this.startMouseSvg = { x: 0, y: 0 };
        this.startTranslate = { x: 0, y: 0 };
        this.mouseDownPos = { clientX: 0, clientY: 0 };
        this.mouseMoved = false;

        this.onClick = null;
        this.onMouseMove = null;

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
        const generatedLayer = document.createElementNS(SVG_NS, "g");
        generatedLayer.setAttribute("id", "generated-layer");
        overlay.appendChild(generatedLayer);
        viewport.appendChild(overlay);

        this.viewport = viewport;
        this.overlay = overlay;
        this.generatedLayer = generatedLayer;

        this.svg.addEventListener("click", (e) => this._handleClick(e));
        this.svg.addEventListener("mousemove", (e) => this._handleMouseMove(e));

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
            line.setAttribute("stroke", "#00BFFF");
            line.setAttribute("stroke-width", "1500");
            line.setAttribute("stroke-opacity", "0.6");
            this.generatedLayer.appendChild(line);
        }

        const circles = geometry.circles || [];
        for (const c of circles) {
            const circle = document.createElementNS(SVG_NS, "circle");
            circle.setAttribute("cx", c.cx.toFixed(1));
            circle.setAttribute("cy", c.cy.toFixed(1));
            circle.setAttribute("r", c.r.toFixed(1));
            circle.setAttribute("fill", "none");
            circle.setAttribute("stroke", "#FF6B6B");
            circle.setAttribute("stroke-width", "1500");
            this.generatedLayer.appendChild(circle);
        }

        // Selection highlight: replace any existing chain path.
        const oldPath = this.overlay.querySelector("#selected-chain-path");
        if (oldPath) oldPath.remove();
        const d = geometry.selected_chain_path;
        if (d) {
            const path = document.createElementNS(SVG_NS, "path");
            path.setAttribute("id", "selected-chain-path");
            path.setAttribute("d", d);
            path.setAttribute("fill", "none");
            path.setAttribute("stroke", "#00BFFF");
            path.setAttribute("stroke-width", "2500");
            path.setAttribute("stroke-opacity", "0.9");
            this.overlay.insertBefore(path, this.generatedLayer);
        }
    }

    resetView() {
        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this._applyTransform();
    }

    clientPointToSvg(clientX, clientY) {
        if (!this.svg) return { x: clientX, y: clientY };
        const pt = this.svg.createSVGPoint();
        pt.x = clientX;
        pt.y = clientY;
        return pt.matrixTransform(this.svg.getScreenCTM().inverse());
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
            this.startMouseSvg = this.clientPointToSvg(e.clientX, e.clientY);
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
            const currentSvg = this.clientPointToSvg(e.clientX, e.clientY);
            this.translateX = this.startTranslate.x + (currentSvg.x - this.startMouseSvg.x);
            this.translateY = this.startTranslate.y + (currentSvg.y - this.startMouseSvg.y);
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

            const pt = this.clientPointToSvg(e.clientX, e.clientY);
            const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
            const newScale = Math.max(0.05, Math.min(100, this.scale * zoomFactor));

            this.translateX = pt.x - (pt.x - this.translateX) * (newScale / this.scale);
            this.translateY = pt.y - (pt.y - this.translateY) * (newScale / this.scale);
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
                ctrlKey: e.ctrlKey || e.metaKey,
                shiftKey: e.shiftKey,
            });
        }
    }

    _handleMouseMove(e) {
        if (!this.svg || !this.onMouseMove) return;
        const pt = this.clientPointToSvg(e.clientX, e.clientY);
        this.onMouseMove({ x: pt.x, y: pt.y });
    }
}

const svgViewer = new SvgViewer("svg-container");
