function clearChartData() {
    for (const ds of datasets) {
        ds.data = [];
    }
    state.xAutoRange = true;
    state.isPanning = false;
    chart.options.scales.x.min = undefined;
    chart.options.scales.x.max = undefined;
    chart.update("none");
}

function drawCurrentSession() {
    clearChartData();
    if (!state.currentSession) {
        return;
    }
    const baselineCurrents = Array(10).fill(null);
    let baselineReady = false;
    for (const row of state.currentSession.records) {
        if (row.ch < 0 || row.ch > 9) continue;
        if (baselineCurrents[row.ch] === null) {
            baselineCurrents[row.ch] = row.current;
        }
        if (!baselineReady) {
            baselineReady = baselineCurrents.every((v) => v !== null);
        }
        if (!baselineReady) {
            continue;
        }
        datasets[row.ch].data.push({ x: row.t, y: row.current - baselineCurrents[row.ch] });
    }
    chart.update("none");
}

function getDataBoundsX() {
    let minX = null;
    let maxX = null;
    for (const ds of datasets) {
        for (const p of ds.data) {
            if (typeof p.x !== "number") continue;
            minX = minX === null ? p.x : Math.min(minX, p.x);
            maxX = maxX === null ? p.x : Math.max(maxX, p.x);
        }
    }
    return { minX, maxX };
}

function getPixelXFromEvent(event) {
    const rect = dom.chartCanvas.getBoundingClientRect();
    return event.clientX - rect.left;
}

function onWheelZoom(event) {
    event.preventDefault();
    const xScale = chart.scales.x;
    if (!xScale) return;

    const pixelX = getPixelXFromEvent(event);
    const centerX = xScale.getValueForPixel(pixelX);
    if (typeof centerX !== "number" || Number.isNaN(centerX)) return;

    const { minX: dataMin, maxX: dataMax } = getDataBoundsX();
    if (dataMin === null || dataMax === null) return;

    const currentMin = typeof xScale.min === "number" ? xScale.min : dataMin;
    const currentMax = typeof xScale.max === "number" ? xScale.max : dataMax;
    if (currentMax - currentMin <= 0) return;

    const factor = event.deltaY < 0 ? 0.85 : 1.15;
    let nextMin = centerX - (centerX - currentMin) * factor;
    let nextMax = centerX + (currentMax - centerX) * factor;

    const minRange = 0.2;
    if (nextMax - nextMin < minRange) {
        const half = minRange / 2;
        nextMin = centerX - half;
        nextMax = centerX + half;
    }

    if (nextMin < dataMin) {
        const shift = dataMin - nextMin;
        nextMin += shift;
        nextMax += shift;
    }
    if (nextMax > dataMax) {
        const shift = nextMax - dataMax;
        nextMin -= shift;
        nextMax -= shift;
    }

    nextMin = Math.max(nextMin, dataMin);
    nextMax = Math.min(nextMax, dataMax);

    const fullRange = Math.abs(nextMin - dataMin) <= 1e-6 && Math.abs(nextMax - dataMax) <= 1e-6;
    if (event.deltaY >= 0 && fullRange) {
        state.xAutoRange = true;
        chart.options.scales.x.min = undefined;
        chart.options.scales.x.max = undefined;
    } else {
        state.xAutoRange = false;
        chart.options.scales.x.min = nextMin;
        chart.options.scales.x.max = nextMax;
    }
    chart.update("none");
}

function onPanStart(event) {
    if (event.button !== 0) return;
    state.isPanning = true;
    state.lastPanX = getPixelXFromEvent(event);
    dom.chartCanvas.style.cursor = "grabbing";
    event.preventDefault();
}

function onPanMove(event) {
    if (!state.isPanning) return;
    const xScale = chart.scales.x;
    if (!xScale) return;

    const { minX: dataMin, maxX: dataMax } = getDataBoundsX();
    if (dataMin === null || dataMax === null) return;

    const currentPixelX = getPixelXFromEvent(event);
    const currentMin = typeof xScale.min === "number" ? xScale.min : dataMin;
    const currentMax = typeof xScale.max === "number" ? xScale.max : dataMax;

    if (currentMax - currentMin <= 0 || currentMax - currentMin >= dataMax - dataMin) {
        state.lastPanX = currentPixelX;
        return;
    }

    const prevValue = xScale.getValueForPixel(state.lastPanX);
    const currValue = xScale.getValueForPixel(currentPixelX);
    if (typeof prevValue !== "number" || typeof currValue !== "number") {
        state.lastPanX = currentPixelX;
        return;
    }

    const delta = currValue - prevValue;
    let nextMin = currentMin - delta;
    let nextMax = currentMax - delta;

    if (nextMin < dataMin) {
        const shift = dataMin - nextMin;
        nextMin += shift;
        nextMax += shift;
    }
    if (nextMax > dataMax) {
        const shift = nextMax - dataMax;
        nextMin -= shift;
        nextMax -= shift;
    }

    state.xAutoRange = false;
    chart.options.scales.x.min = nextMin;
    chart.options.scales.x.max = nextMax;
    chart.update("none");
    state.lastPanX = currentPixelX;
    event.preventDefault();
}

function onPanEnd() {
    state.isPanning = false;
    dom.chartCanvas.style.cursor = "default";
}

