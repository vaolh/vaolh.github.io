import {tick} from "svelte";
import COA from "../components/object/COA.svelte";
import {message} from "data/stores";
import {getURL} from "./download";

const EXPORT_SIZE = 1000;
const IDB_NAME = "armoria-heraldry";
const IDB_STORE = "handles";
const IDB_KEY = "flagsDir";
const FALLBACK_COUNTER_KEY = "armoria_heraldry_set_counter";

// physical forms a coat of arms is exported as, per set
const VARIANTS = [
  {name: "coat", shield: "oldFrench"},
  {name: "flag", shield: "flag"},
  {name: "banner", shield: "banner"},
  {name: "guidon", shield: "guidon"},
  {name: "pennon", shield: "pennon"}
];

// save the 5 heraldic forms of a coa as high-quality SVGs (+ an editable JSON sidecar)
export async function saveHeraldrySet(coa) {
  if (!coa) return;

  try {
    if (window.showDirectoryPicker) {
      const dirHandle = await getFlagsDirHandle();
      if (dirHandle) return await saveToDirectory(coa, dirHandle);
    }
    return await saveViaDownload(coa);
  } catch (error) {
    if (error?.name === "AbortError") return; // user cancelled the folder picker
    console.error(error);
    message.error(`Could not save heraldry set: ${error.message}`, 8000);
  }
}

async function saveToDirectory(coa, dirHandle) {
  const n = await nextSetNumber(dirHandle);

  for (const {name, shield} of VARIANTS) {
    const blob = await renderVariantBlob(coa, shield);
    const fileHandle = await dirHandle.getFileHandle(`${n}-${name}.svg`, {create: true});
    const writable = await fileHandle.createWritable();
    await writable.write(blob);
    await writable.close();
  }

  const jsonHandle = await dirHandle.getFileHandle(`${n}-coa.json`, {create: true});
  const jsonWritable = await jsonHandle.createWritable();
  await jsonWritable.write(JSON.stringify([coa]));
  await jsonWritable.close();

  message.success(`Saved set ${n} (coat, flag, banner, guidon, pennon) to assets/flags`, 7000);
  return n;
}

async function saveViaDownload(coa) {
  const n = nextFallbackNumber();

  for (const {name, shield} of VARIANTS) {
    const blob = await renderVariantBlob(coa, shield);
    triggerDownload(blob, `${n}-${name}.svg`);
  }

  const jsonBlob = new Blob([JSON.stringify([coa])], {type: "application/json"});
  triggerDownload(jsonBlob, `${n}-coa.json`);

  message.info(`Your browser can't save directly to a folder — set ${n} downloaded instead`, 8000);
  return n;
}

async function renderVariantBlob(coa, shieldType) {
  const variantCoa = {...coa, shield: shieldType};
  const container = document.createElement("div");
  container.style.cssText = `position:fixed; left:-99999px; top:0; width:${EXPORT_SIZE}px; height:${EXPORT_SIZE}px;`;
  document.body.appendChild(container);

  const instance = new COA({
    target: container,
    props: {coa: variantCoa, i: "Export", width: EXPORT_SIZE, height: EXPORT_SIZE}
  });
  await tick();

  try {
    const svg = container.querySelector("svg.coa");
    stripBorder(svg);
    const url = await getURL(svg, EXPORT_SIZE, EXPORT_SIZE);
    const response = await fetch(url);
    return await response.blob();
  } finally {
    instance.$destroy();
    container.remove();
  }
}

// exported sets shouldn't carry the app's global shield-outline border setting
function stripBorder(svg) {
  const gradPath = svg.querySelector("path.grad");
  if (!gradPath) return;
  gradPath.setAttribute("stroke", "none");
  gradPath.removeAttribute("stroke-width");
}

function triggerDownload(blob, filename) {
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.download = filename;
  link.href = url;
  link.click();
  window.setTimeout(() => window.URL.revokeObjectURL(url), 5000);
}

// scan the folder for existing "<n>-coat.svg" files and pick the next number
async function nextSetNumber(dirHandle) {
  let max = 0;
  for await (const name of dirHandle.keys()) {
    const match = name.match(/^(\d+)-coat\.svg$/i);
    if (match) max = Math.max(max, parseInt(match[1], 10));
  }
  return max + 1;
}

function nextFallbackNumber() {
  const current = parseInt(localStorage.getItem(FALLBACK_COUNTER_KEY) || "0", 10);
  const next = current + 1;
  localStorage.setItem(FALLBACK_COUNTER_KEY, String(next));
  return next;
}

async function getFlagsDirHandle() {
  let handle = null;
  try {
    handle = await idbGet(IDB_KEY);
  } catch (error) {
    handle = null;
  }

  if (handle) {
    const granted = await verifyPermission(handle).catch(() => false);
    if (granted) return handle;
  }

  handle = await window.showDirectoryPicker({id: "armoria-flags", mode: "readwrite"});
  await idbSet(IDB_KEY, handle).catch(() => {});
  return handle;
}

async function verifyPermission(handle) {
  const opts = {mode: "readwrite"};
  if ((await handle.queryPermission(opts)) === "granted") return true;
  if ((await handle.requestPermission(opts)) === "granted") return true;
  return false;
}

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(IDB_NAME, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(IDB_STORE);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function idbGet(key) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const request = db.transaction(IDB_STORE, "readonly").objectStore(IDB_STORE).get(key);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

async function idbSet(key, value) {
  const db = await openDb();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(IDB_STORE, "readwrite");
    tx.objectStore(IDB_STORE).put(value, key);
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}
