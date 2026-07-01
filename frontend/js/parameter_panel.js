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
                min: 0.1,
                max: 99999,
                sliderMin: 0.1,
                sliderMax: 500,
                step: 0.5,
                decimals: 1,
            },
            capsule_start_distance: {
                min: 0.1,
                max: 75,
                sliderMin: 0.1,
                sliderMax: 75,
                step: 0.5,
                decimals: 1,
            },
            capsule_clearance_distance: {
                min: 0,
                max: 99999,
                sliderMin: 0,
                sliderMax: 100,
                step: 0.5,
                decimals: 1,
            },
            capsule_axis_gap_above_distance: {
                min: 0,
                max: 99999,
                sliderMin: 0,
                sliderMax: 2000,
                step: 0.5,
                decimals: 1,
            },
            capsule_axis_gap_below_distance: {
                min: 0,
                max: 99999,
                sliderMin: 0,
                sliderMax: 2000,
                step: 0.5,
                decimals: 1,
            },
            air_duct_inlet_distance: {
                min: 0,
                max: 300,
                sliderMin: 0,
                sliderMax: 300,
                step: 0.5,
                decimals: 1,
            },
            air_duct_base_plate_margin: {
                min: 0,
                max: 99999,
                sliderMin: 0,
                sliderMax: 200,
                step: 0.5,
                decimals: 1,
            },
            top_gap_distance: {
                min: 0,
                max: 99999,
                sliderMin: 0,
                sliderMax: 200,
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
        this.airDuctEnabled = document.getElementById("param-air-duct-enabled");
        this.airDuctSimpleMode = document.getElementById("param-air-duct-simple-mode");
        this.airDuctCompareOverlay = document.getElementById("toggle-air-duct-compare-overlay");
        this.togglePreview = document.getElementById("toggle-preview");
        this.capsuleStartMidHint = document.getElementById("capsule-start-mid-hint");
        this.capsuleStartMaxHint = document.getElementById("capsule-start-max-hint");

        this.onParamsChange = null;
        this.onParamsPreview = null;
        this.onToggleChange = null;
        this.onAirDuctCompareChange = null;
        this.onGuideChange = null;
        this._activeGuideKey = null;

        this._debounceTimer = null;
        this._bindEvents();
        this._updateInputLimits();
    }

    /**
     * Clamp and step a value to the limits of the given range type.
     * @param {"input" | "slider"} rangeType
     */
    _normalizeValue(key, value, rangeType = "input") {
        this._updateDependentLimits();
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
        this._updateDependentLimits();
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

    _updateDependentLimits() {
        const cfg = this.paramConfigs.capsule_start_distance;
        if (!cfg || !this.inputs.ray_offset) return;
        const rawOffset = parseFloat(this.inputs.ray_offset.value);
        const maxDistance = Math.max(cfg.min, isNaN(rawOffset) ? 75 : rawOffset);
        cfg.max = maxDistance;
        cfg.sliderMax = maxDistance;

        const input = this.inputs.capsule_start_distance;
        const slider = this.sliders.capsule_start_distance;
        if (input) input.max = maxDistance;
        if (slider) slider.max = maxDistance;
        if (this.capsuleStartMaxHint) {
            this.capsuleStartMaxHint.textContent = Number(maxDistance.toFixed(1));
        }
        if (this.capsuleStartMidHint) {
            this.capsuleStartMidHint.textContent = Number(((cfg.min + maxDistance) / 2).toFixed(1));
        }
    }

    _clampCapsuleStartDisplay() {
        const input = this.inputs.capsule_start_distance;
        const slider = this.sliders.capsule_start_distance;
        if (!input || !slider) return;
        const cfg = this.paramConfigs.capsule_start_distance;
        const raw = parseFloat(input.value);
        const value = isNaN(raw) ? cfg.min : this._normalizeInputValue("capsule_start_distance", raw);
        input.value = Number(value.toFixed(cfg.decimals));
        slider.value = Math.max(cfg.sliderMin, Math.min(cfg.sliderMax, value));
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
            if (key === "ray_offset") {
                this._updateDependentLimits();
                this._clampCapsuleStartDisplay();
            }
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
        if (key === "ray_offset") {
            this._updateDependentLimits();
            this._clampCapsuleStartDisplay();
        }
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
            capsule_start_distance: this._normalizeInputValue(
                "capsule_start_distance",
                parse("capsule_start_distance", 10),
            ),
            capsule_clearance_distance: this._normalizeInputValue(
                "capsule_clearance_distance",
                parse("capsule_clearance_distance", 2),
            ),
            capsule_axis_gap_above_distance: this._normalizeInputValue(
                "capsule_axis_gap_above_distance",
                parse("capsule_axis_gap_above_distance", 0),
            ),
            capsule_axis_gap_below_distance: this._normalizeInputValue(
                "capsule_axis_gap_below_distance",
                parse("capsule_axis_gap_below_distance", 0),
            ),
            air_duct_enabled: this.airDuctEnabled
                ? this.airDuctEnabled.checked
                : true,
            air_duct_simple_mode: this.airDuctSimpleMode
                ? this.airDuctSimpleMode.checked
                : true,
            air_duct_inlet_distance: this._normalizeInputValue(
                "air_duct_inlet_distance",
                parse("air_duct_inlet_distance", 20),
            ),
            air_duct_base_plate_margin: this._normalizeInputValue(
                "air_duct_base_plate_margin",
                parse("air_duct_base_plate_margin", 20),
            ),
            top_gap_distance: this._normalizeInputValue(
                "top_gap_distance",
                parse("top_gap_distance", 40),
            ),
            ray_count: this._normalizeInputValue(
                "ray_count",
                parse("ray_count", 200),
            ),
            ray_direction: this.rayDirection ? this.rayDirection.value : "inward",
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
        if (params.air_duct_enabled !== undefined && this.airDuctEnabled) {
            this.airDuctEnabled.checked = Boolean(params.air_duct_enabled);
        }
        if (params.air_duct_simple_mode !== undefined && this.airDuctSimpleMode) {
            this.airDuctSimpleMode.checked = Boolean(params.air_duct_simple_mode);
        }
    }

    getShowGenerated() {
        return this.togglePreview ? this.togglePreview.checked : true;
    }

    setShowGenerated(value) {
        if (this.togglePreview) this.togglePreview.checked = value;
    }

    getAirDuctCompareOverlay() {
        return this.airDuctCompareOverlay ? this.airDuctCompareOverlay.checked : false;
    }

    setAirDuctCompareOverlay(value) {
        if (this.airDuctCompareOverlay) {
            this.airDuctCompareOverlay.checked = Boolean(value);
        }
    }

    _bindEvents() {
        const triggerChange = () => {
            if (this.onParamsPreview) this.onParamsPreview(this.getParams());
            this._refreshActiveGuide();
            clearTimeout(this._debounceTimer);
            this._debounceTimer = setTimeout(() => {
                if (this.onParamsChange) this.onParamsChange(this.getParams());
            }, 120);
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

            if (
                key === "capsule_axis_gap_above_distance"
                || key === "capsule_axis_gap_below_distance"
            ) {
                this._bindGuideEvents(key);
            }
        }

        if (this.rayDirection) {
            this.rayDirection.addEventListener("change", triggerChange);
        }

        if (this.dedupeClosedRays) {
            this.dedupeClosedRays.addEventListener("change", triggerChange);
        }

        if (this.airDuctEnabled) {
            this.airDuctEnabled.addEventListener("change", triggerChange);
        }

        if (this.airDuctSimpleMode) {
            this.airDuctSimpleMode.addEventListener("change", triggerChange);
        }

        if (this.togglePreview) {
            this.togglePreview.addEventListener("change", () => {
                if (this.onToggleChange) this.onToggleChange(this.getShowGenerated());
            });
        }

        if (this.airDuctCompareOverlay) {
            this.airDuctCompareOverlay.addEventListener("change", () => {
                if (this.onAirDuctCompareChange) {
                    this.onAirDuctCompareChange(this.getAirDuctCompareOverlay());
                }
            });
        }
    }

    _bindGuideEvents(key) {
        const group = document.querySelector(`[data-param="${key}"]`);
        const input = this.inputs[key];
        const slider = this.sliders[key];
        const show = () => this._setGuideVisible(key, true);
        const hide = () => this._setGuideVisible(key, false);
        const hideIfNotHovering = () => {
            if (group && group.matches(":hover")) return;
            hide();
        };

        if (group) {
            group.addEventListener("mouseenter", show);
            group.addEventListener("mouseleave", () => {
                if (document.activeElement !== input) hide();
            });
        }
        if (input) {
            input.addEventListener("focus", show);
            input.addEventListener("blur", hide);
        }
        if (slider) {
            slider.addEventListener("pointerdown", show);
            slider.addEventListener("pointerup", hideIfNotHovering);
            slider.addEventListener("pointercancel", hide);
        }
    }

    _setGuideVisible(key, visible) {
        if (visible) {
            this._activeGuideKey = key;
        } else if (this._activeGuideKey === key) {
            this._activeGuideKey = null;
        }
        if (this.onGuideChange) {
            this.onGuideChange(key, Boolean(visible), this.getParams());
        }
    }

    _refreshActiveGuide() {
        if (this._activeGuideKey && this.onGuideChange) {
            this.onGuideChange(this._activeGuideKey, true, this.getParams());
        }
    }
}

const parameterPanel = new ParameterPanel();
