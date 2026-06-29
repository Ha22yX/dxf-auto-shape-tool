/**
 * SVG viewer: pan, zoom, rendering, and coordinate conversion.
 */
class SvgViewer {
    constructor(containerId) {
        this.container = document.getElementById(containerId);
        this.svg = null;
        this.contentGroup = null;

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

    setSvg(svgString) {
        const parser = new DOMParser();
        const newDoc = parser.parseFromString(svgString, "image/svg+xml");
        const newSvg = newDoc.documentElement;
        const newViewBox = newSvg.getAttribute("viewBox");

        // If the viewBox is unchanged, only update the content group.
        // This prevents the original drawing from shifting when parameters change.
        if (
            this.svg &&
            this.svg.getAttribute("viewBox") === newViewBox &&
            this.contentGroup
        ) {
            const newContent = newSvg.querySelector("#dxf-content");
            if (newContent) {
                this.contentGroup.innerHTML = newContent.innerHTML;
                return;
            }
        }

        // Otherwise, replace the entire SVG (first load or viewBox changed)
        this.container.innerHTML = svgString;
        this.svg = this.container.querySelector("svg");
        if (!this.svg) return;

        this.contentGroup = this.svg.querySelector("#dxf-content");
        this._applyTransform();

        this.svg.addEventListener("click", (e) => this._handleClick(e));
        this.svg.addEventListener("mousemove", (e) => this._handleMouseMove(e));

        if (!this._hasSetInitialView) {
            this.scale = 1;
            this.translateX = 0;
            this.translateY = 0;
            this._applyTransform();
            this._hasSetInitialView = true;
        }
    }

    resetView() {
        this.scale = 1;
        this.translateX = 0;
        this.translateY = 0;
        this._applyTransform();
    }

    svgPointToClient(svgX, svgY) {
        if (!this.svg) return { x: svgX, y: svgY };
        const pt = this.svg.createSVGPoint();
        pt.x = svgX;
        pt.y = svgY;
        return pt.matrixTransform(this.svg.getScreenCTM());
    }

    clientPointToSvg(clientX, clientY) {
        if (!this.svg) return { x: clientX, y: clientY };
        const pt = this.svg.createSVGPoint();
        pt.x = clientX;
        pt.y = clientY;
        return pt.matrixTransform(this.svg.getScreenCTM().inverse());
    }

    _applyTransform() {
        if (this.contentGroup) {
            this.contentGroup.setAttribute(
                "transform",
                `translate(${this.translateX.toFixed(4)}, ${this.translateY.toFixed(4)}) scale(${this.scale.toFixed(4)})`,
            );
        }
    }

    _bindEvents() {
        this.container.addEventListener("mousedown", (e) => {
            this.mouseMoved = false;
            this.mouseDownPos = { clientX: e.clientX, clientY: e.clientY };

            // Middle mouse (button 1) for pan
            if (e.button !== 1) return;
            // Don't pan if clicking an interactive element
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

            // Track any mouse movement while button is down to distinguish drag from click
            const dx = e.clientX - this.mouseDownPos.clientX;
            const dy = e.clientY - this.mouseDownPos.clientY;
            if (Math.hypot(dx, dy) > 3) {
                this.mouseMoved = true;
            }

            if (!this.isPanning) return;
            const currentSvg = this.clientPointToSvg(e.clientX, e.clientY);
            const sdx = currentSvg.x - this.startMouseSvg.x;
            const sdy = currentSvg.y - this.startMouseSvg.y;

            this.translateX = this.startTranslate.x + sdx;
            this.translateY = this.startTranslate.y + sdy;
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

        // Prevent context menu on middle click
        this.container.addEventListener("contextmenu", (e) => e.preventDefault());

        this.container.addEventListener("wheel", (e) => {
            e.preventDefault();
            if (!this.svg) return;

            const pt = this.clientPointToSvg(e.clientX, e.clientY);
            const zoomFactor = e.deltaY < 0 ? 1.15 : 0.87;
            const newScale = Math.max(0.05, Math.min(100, this.scale * zoomFactor));

            // Zoom around mouse point
            this.translateX = pt.x - (pt.x - this.translateX) * (newScale / this.scale);
            this.translateY = pt.y - (pt.y - this.translateY) * (newScale / this.scale);
            this.scale = newScale;

            this._applyTransform();
        });
    }

    _handleClick(e) {
        if (this.mouseMoved) {
            // This was a drag, not a click
            this.mouseMoved = false;
            return;
        }

        if (!this.svg) return;

        const target = e.target.closest("[data-handle]");
        const handle = target ? target.getAttribute("data-handle") : null;

        // Only send clicks that actually hit an entity to avoid background-click errors
        if (!handle) return;

        const pt = this.clientPointToSvg(e.clientX, e.clientY);

        if (this.onClick) {
            this.onClick({
                svgX: pt.x,
                svgY: pt.y,
                handle: handle,
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

    highlight(handles) {
        if (!this.svg) return;
        this.svg.querySelectorAll(".selected-entity").forEach((el) => {
            el.classList.remove("selected-entity");
            const original = el.dataset.originalStroke;
            if (original) {
                el.setAttribute("stroke", original);
                delete el.dataset.originalStroke;
            }
        });

        handles.forEach((handle) => {
            const el = this.svg.querySelector(`[data-handle="${handle}"]`);
            if (el) {
                if (!el.dataset.originalStroke) {
                    el.dataset.originalStroke = el.getAttribute("stroke");
                }
                el.classList.add("selected-entity");
            }
        });
    }
}

const svgViewer = new SvgViewer("svg-container");
