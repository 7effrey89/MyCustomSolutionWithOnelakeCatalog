"use strict";

const chart = document.getElementById("chart");
const canvas = document.getElementById("canvas");
const status = document.getElementById("status");
const error = document.getElementById("error");
const warnings = document.getElementById("warnings");
let renderer;
let revision = 0;
let svg;
let bounds;
let view;
let drag;

function send(type, extra = {}) {
  window.parent.postMessage({ isStreamlitMessage: true, type, ...extra }, "*");
}

function showError(problem) {
  status.hidden = true;
  error.textContent = `Unable to render lineage: ${problem.message}`;
  error.hidden = false;
}

function setView(next) {
  view = next;
  svg.setAttribute("viewBox", [view.x, view.y, view.width, view.height].join(" "));
}

function zoom(factor) {
  if (!svg) return;
  const width = Math.min(bounds.width * 4, Math.max(bounds.width / 10, view.width * factor));
  const height = view.height * width / view.width;
  setView({
    x: view.x + (view.width - width) / 2,
    y: view.y + (view.height - height) / 2,
    width, height,
  });
}

function point(event) {
  const result = svg.createSVGPoint();
  result.x = event.clientX;
  result.y = event.clientY;
  return result.matrixTransform(svg.getScreenCTM().inverse());
}

function installNavigation() {
  svg.addEventListener("wheel", event => {
    event.preventDefault();
    zoom(event.deltaY < 0 ? 0.85 : 1.15);
  }, { passive: false });
  svg.addEventListener("pointerdown", event => {
    if (event.button !== 0) return;
    drag = { id: event.pointerId, start: point(event) };
    svg.setPointerCapture(event.pointerId);
  });
  svg.addEventListener("pointermove", event => {
    if (!drag || drag.id !== event.pointerId) return;
    const current = point(event);
    setView({ ...view, x: view.x + drag.start.x - current.x, y: view.y + drag.start.y - current.y });
  });
  for (const name of ["pointerup", "pointercancel", "lostpointercapture"]) {
    svg.addEventListener(name, () => { drag = undefined; });
  }
  svg.addEventListener("keydown", event => {
    const steps = { ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1] };
    if (event.key in steps) {
      event.preventDefault();
      const [x, y] = steps[event.key];
      setView({ ...view, x: view.x + x * view.width / 10, y: view.y + y * view.height / 10 });
    } else if (["+", "=", "-", "Home"].includes(event.key)) {
      event.preventDefault();
      if (event.key === "Home") setView({ ...bounds });
      else zoom(event.key === "-" ? 1.2 : 1 / 1.2);
    }
  });
}

async function render(args) {
  const current = ++revision;
  renderer ??= Viz.instance();
  const viz = await renderer;
  if (current !== revision) return;
  const result = viz.render(args.dot, {
    format: "svg",
    images: Object.keys(args.icons).map(name => ({ name, width: 20, height: 20 })),
  });
  if (result.status !== "success" || result.errors.some(item => item.level === "error")) {
    throw new Error(result.errors.map(item => item.message).join("; ") || "Graphviz returned no graph.");
  }
  const parsed = new DOMParser().parseFromString(result.output, "image/svg+xml");
  if (parsed.querySelector("parsererror")) throw new Error("Graphviz returned invalid SVG.");
  const next = parsed.documentElement;
  // Resolve only locally bundled icon bytes before the SVG enters the document.
  for (const image of next.querySelectorAll("image")) {
    const name = image.getAttribute("href") || image.getAttributeNS("http://www.w3.org/1999/xlink", "href");
    const uri = args.icons[name];
    if (!uri || !uri.startsWith("data:image/svg+xml;base64,")) {
      throw new Error(`Missing bundled icon: ${name}`);
    }
    image.removeAttributeNS("http://www.w3.org/1999/xlink", "href");
    image.setAttribute("href", uri);
    image.setAttribute("aria-hidden", "true");
  }
  next.setAttribute("role", "img");
  next.setAttribute("aria-label", args.description);
  next.setAttribute("aria-describedby", "help");
  next.setAttribute("tabindex", "0");
  svg = next;
  drag = undefined;
  const box = svg.viewBox.baseVal;
  bounds = { x: box.x, y: box.y, width: box.width, height: box.height };
  view = { ...bounds };
  canvas.replaceChildren(svg);
  status.hidden = true;
  error.hidden = true;
  warnings.textContent = result.errors.map(item => item.message).join("; ");
  warnings.hidden = result.errors.length === 0;
  installNavigation();
}

document.getElementById("zoom-in").addEventListener("click", () => zoom(1 / 1.2));
document.getElementById("zoom-out").addEventListener("click", () => zoom(1.2));
document.getElementById("fit").addEventListener("click", () => { if (svg) setView({ ...bounds }); });
document.getElementById("fullscreen").addEventListener("click", () => {
  const action = document.fullscreenElement ? document.exitFullscreen() : chart.requestFullscreen();
  action.catch(showError);
});
window.addEventListener("message", event => {
  if (event.source !== window.parent || event.data.type !== "streamlit:render") return;
  canvas.replaceChildren();
  svg = undefined;
  error.hidden = true;
  warnings.hidden = true;
  status.hidden = false;
  render(event.data.args).catch(showError);
  send("streamlit:setFrameHeight", { height: 520 });
});
send("streamlit:componentReady", { apiVersion: 1 });
send("streamlit:setFrameHeight", { height: 520 });
