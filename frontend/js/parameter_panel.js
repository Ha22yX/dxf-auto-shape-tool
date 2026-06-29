/**
 * Parameter panel bindings with synchronized number inputs and range sliders.
 *
 * Sliders are only quick selectors within a comfortable range. Number inputs
 * accept the authoritative value and may exceed the slider range.
 */
class ParameterPanel {
    constructor() {
        // input min/max: authoritative limits (user can type beyond slider range)
        // sliderMin/sliderMax: comfortable range shown on the slider
        this.paramConfigs = {
            circle_radius: {
                min: 0.1,
                max: 9999,
                sliderMin: 0.1,
                sliderMax: 50,
                step: 0.1,
                decimals: 1,
            },
            circles_per_ray: {
                min: 0,
                max: 10,
                sliderMin: 0,
                sliderMax: 10,
                step: 1,
                decimals: 0,
            },
            circle_spacing: {
                min: 0,
                max: 99999,
                sliderMin: 0,
                sliderMax: 200,
                step: 0.5,
                decimals: 1,
            },
            ray_offset: {
                min: -99999,
                max: 99999,
                sliderMin: -500,
                sliderMax: 500,
                step: 0.5,
                decimals: 1,
            },
            ray_count: {
                min: 0,
                max: 99999,
                sliderMin: 0,
                sliderMax: 500,
                step: 1,
                decimals: 0,
            },
        };

        this.keys = Object.keys(this.paramConfigs);
        this.inputs = {};
        this.sliders = {};

        for (const key of this.keys) {
            const baseId = `param-${key.replace(/_/g, "-")}`;
            this.inputs[key] = document.getElementById(baseId);
            this.sliders[key] = document.getElementById(`${baseId}-slider`);
        }

        this.rayDirection = document.getElementById("param-ray-direction");
        this.dedupeClosedRays = document.getElementById("param-dedupe-closed-rays");
        this.togglePreview = document.getElementById("toggle-preview");

        this.onParamsChange = null;
        this.onToggleChange = null;

        this._debounceTimer = null;
        this._bindEvents();
        this._updateInputLimits();
    }

    /**
     * Clamp and step a value to the limits of the given range type.
     * @param {"input" | "slider"} rangeType
     */
    _normalizeValue(key, value, rangeType = "input") {
        const cfg = this.paramConfigs[key];
        const min = rangeType === "slider" ? cfg.sliderMin : cfg.min;
        const max = rangeType === "slider" ? cfg.sliderMax : cfg.max;
        let clamped = Math.max(min, Math.min(max, value));
        if (rangeType === "slider") {
            clamped = Math.round(clamped / cfg.step) * cfg.step;
        }
        return Number(clamped.toFixed(cfg.decimals));
    }

    /**
     * Clamp a number input value to the authoritative input range.
     */
    _normalizeInputValue(key, value) {
        return this._normalizeValue(key, value, "input");
    }

    _isIntermediateNumber(raw) {
        return raw === "" || raw === "-" || raw === "." || raw === "-." || raw.endsWith(".");
    }

    _readInputValue(key, fallback) {
        const rawText = this.inputs[key].value.trim();
        const raw = parseFloat(rawText);
        if (this._isIntermediateNumber(rawText) || isNaN(raw)) {
            return fallback;
        }
        return this._normalizeInputValue(key, raw);
    }

    /**
     * Update the number input's min/max/step attributes to reflect the
     * authoritative input range (wider than the slider range).
     */
    _updateInputLimits() {
        for (const key of this.keys) {
            const cfg = this.paramConfigs[key];
            const input = this.inputs[key];
            const slider = this.sliders[key];
            input.min = cfg.min;
            input.max = cfg.max;
            input.step = cfg.step;
            slider.min = cfg.sliderMin;
            slider.max = cfg.sliderMax;
            slider.step = cfg.step;
        }
    }

    /**
     * Synchronize number input and slider for a parameter.
     * @param {string} key
     * @param {"input" | "slider"} source
     */
    _sync(key, source) {
        const cfg = this.paramConfigs[key];
        let value;

        if (source === "input") {
            const rawText = this.inputs[key].value.trim();
            const raw = parseFloat(rawText);
            if (this._isIntermediateNumber(rawText) || isNaN(raw)) {
                return;
            }
            value = this._normalizeInputValue(key, raw);
            const sliderValue = Math.max(cfg.sliderMin, Math.min(cfg.sliderMax, value));
            this.sliders[key].value = sliderValue;
            return;
        } else {
            const raw = parseFloat(this.sliders[key].value);
            value = isNaN(raw)
                ? cfg.sliderMin
                : this._normalizeValue(key, raw, "slider");
        }

        // Input always shows the authoritative value.
        this.inputs[key].value = Number(value.toFixed(cfg.decimals));
        // Slider visual position is clamped to its own range.
        const sliderValue = Math.max(cfg.sliderMin, Math.min(cfg.sliderMax, value));
        this.sliders[key].value = sliderValue;
    }

    _commitInput(key) {
        const cfg = this.paramConfigs[key];
        const raw = parseFloat(this.inputs[key].value);
        const value = isNaN(raw) ? cfg.min : this._normalizeInputValue(key, raw);
        this.inputs[key].value = Number(value.toFixed(cfg.decimals));
        const sliderValue = Math.max(cfg.sliderMin, Math.min(cfg.sliderMax, value));
        this.sliders[key].value = sliderValue;
    }

    getParams() {
        const parse = (key, fallback) => {
            return this._readInputValue(key, fallback);
        };

        const params = {
            circle_radius: this._normalizeInputValue(
                "circle_radius",
                parse("circle_radius", 3.5),
            ),
            circles_per_ray: this._normalizeInputValue(
                "circles_per_ray",
                parse("circles_per_ray", 3),
            ),
            circle_spacing: this._normalizeInputValue(
                "circle_spacing",
                parse("circle_spacing", 17.5),
            ),
            ray_offset: this._normalizeInputValue(
                "ray_offset",
                parse("ray_offset", 75),
            ),
            ray_count: this._normalizeInputValue(
                "ray_count",
                parse("ray_count", 200),
            ),
            ray_direction: this.rayDirection ? this.rayDirection.value : "outward",
            dedupe_closed_rays: this.dedupeClosedRays
                ? this.dedupeClosedRays.checked
                : true,
        };
        return params;
    }

    setParams(params) {
        for (const key of this.keys) {
            if (params[key] === undefined) continue;
            const cfg = this.paramConfigs[key];
            const value = this._normalizeInputValue(key, params[key]);
            this.inputs[key].value = Number(value.toFixed(cfg.decimals));
            const sliderValue = Math.max(cfg.sliderMin, Math.min(cfg.sliderMax, value));
            this.sliders[key].value = sliderValue;
        }
        if (params.ray_direction !== undefined && this.rayDirection) {
            this.rayDirection.value = params.ray_direction;
        }
        if (params.dedupe_closed_rays !== undefined && this.dedupeClosedRays) {
            this.dedupeClosedRays.checked = Boolean(params.dedupe_closed_rays);
        }
    }

    getShowGenerated() {
        return this.togglePreview ? this.togglePreview.checked : true;
    }

    setShowGenerated(value) {
        if (this.togglePreview) this.togglePreview.checked = value;
    }

    _bindEvents() {
        const triggerChange = () => {
            clearTimeout(this._debounceTimer);
            this._debounceTimer = setTimeout(() => {
                if (this.onParamsChange) this.onParamsChange(this.getParams());
            }, 100);
        };

        for (const key of this.keys) {
            this.inputs[key].addEventListener("input", () => {
                this._sync(key, "input");
                triggerChange();
            });
            this.inputs[key].addEventListener("change", () => {
                this._commitInput(key);
                triggerChange();
            });
            this.inputs[key].addEventListener("blur", () => {
                this._commitInput(key);
            });
            this.inputs[key].addEventListener("keydown", (event) => {
                if (event.key === "Enter") {
                    this._commitInput(key);
                    triggerChange();
                }
            });
            this.sliders[key].addEventListener("input", () => {
                this._sync(key, "slider");
                triggerChange();
            });
        }

        if (this.rayDirection) {
            this.rayDirection.addEventListener("change", triggerChange);
        }

        if (this.dedupeClosedRays) {
            this.dedupeClosedRays.addEventListener("change", triggerChange);
        }

        if (this.togglePreview) {
            this.togglePreview.addEventListener("change", () => {
                if (this.onToggleChange) this.onToggleChange(this.getShowGenerated());
            });
        }
    }
}

const parameterPanel = new ParameterPanel();
