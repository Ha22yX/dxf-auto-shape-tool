/**
 * Selection state and logic.
 */
class Selector {
    constructor() {
        this.selectedHandles = [];
        this.selectedChain = [];
        this.onSelectionChange = null;
    }

    setSelection(handles, chain = null) {
        this.selectedHandles = handles || [];
        this.selectedChain = chain || handles || [];
        if (this.onSelectionChange) {
            this.onSelectionChange(this.selectedHandles, this.selectedChain);
        }
    }

    clear() {
        this.selectedHandles = [];
        this.selectedChain = [];
        if (this.onSelectionChange) {
            this.onSelectionChange([], []);
        }
    }

    isEmpty() {
        return this.selectedHandles.length === 0;
    }
}

const selector = new Selector();
