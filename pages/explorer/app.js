const PLUGIN = "astrbot_plugin_file_explorer";

function unwrap(payload) {
  if (payload && payload.status === "error") {
    throw new Error(payload.message || "请求失败");
  }
  if (payload && payload.status === "ok" && Object.prototype.hasOwnProperty.call(payload, "data")) {
    return payload.data;
  }
  return payload;
}

function formatSize(bytes) {
  const n = Number(bytes) || 0;
  if (n < 1024) return n + " B";
  const units = ["KB", "MB", "GB", "TB"];
  let value = n / 1024;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  return value.toFixed(value >= 10 ? 0 : 1) + " " + units[idx];
}

function kindIcon(kind) {
  if (kind === "dir") return "📁";
  if (kind === "image") return "🖼️";
  if (kind === "text") return "📄";
  if (kind === "audio") return "🎵";
  if (kind === "video") return "🎬";
  if (kind === "archive") return "📦";
  return "📎";
}

function splitPath(path) {
  const raw = String(path || "").replace(/\\/g, "/");
  const parts = [];
  if (/^[A-Za-z]:/.test(raw)) {
    parts.push(raw.slice(0, 2) + "/");
    const rest = raw.slice(3).split("/").filter(Boolean);
    let acc = raw.slice(0, 2) + "/";
    for (const part of rest) {
      acc = acc.endsWith("/") ? acc + part : acc + "/" + part;
      parts.push(acc);
    }
    return parts;
  }
  if (raw.startsWith("/")) {
    parts.push("/");
    const rest = raw.split("/").filter(Boolean);
    let acc = "";
    for (const part of rest) {
      acc += "/" + part;
      parts.push(acc);
    }
    return parts;
  }
  return [raw];
}

class ApiClient {
  constructor() {
    this.bridge = window.AstrBotPluginPage || null;
    this.ctx = {};
  }

  async ready() {
    if (this.bridge) {
      try {
        this.ctx = await this.bridge.ready();
      } catch (err) {
        this.ctx = {};
      }
    }
    const dark = this.ctx && typeof this.ctx.isDark === "boolean"
      ? this.ctx.isDark
      : window.matchMedia("(prefers-color-scheme: dark)").matches;
    document.documentElement.setAttribute("data-theme", dark ? "dark" : "light");
  }

  token() {
    return localStorage.getItem("token") || "";
  }

  async get(path, params = {}) {
    if (this.bridge) {
      return unwrap(await this.bridge.apiGet(path, params));
    }
    const qs = new URLSearchParams(params).toString();
    const url = `/api/plug/${PLUGIN}/${path}` + (qs ? `?${qs}` : "");
    const res = await fetch(url, {
      headers: { Authorization: "Bearer " + this.token() },
    });
    if (res.status === 401) throw new Error("未登录或 Token 失效，请先打开 AstrBot 管理面板登录");
    return unwrap(await res.json());
  }

  async post(path, body = {}) {
    if (this.bridge) {
      return unwrap(await this.bridge.apiPost(path, body));
    }
    const res = await fetch(`/api/plug/${PLUGIN}/${path}`, {
      method: "POST",
      headers: {
        Authorization: "Bearer " + this.token(),
        "Content-Type": "application/json",
      },
      body: JSON.stringify(body),
    });
    if (res.status === 401) throw new Error("未登录或 Token 失效，请先打开 AstrBot 管理面板登录");
    return unwrap(await res.json());
  }

  async upload(file, dest) {
    if (this.bridge) {
      const prep = await this.post("upload-prepare", { path: dest, name: file.name });
      return unwrap(await this.bridge.upload("upload/" + prep.ticket, file));
    }
    const fd = new FormData();
    fd.append("file", file);
    fd.append("path", dest);
    const res = await fetch(`/api/plug/${PLUGIN}/upload`, {
      method: "POST",
      headers: { Authorization: "Bearer " + this.token() },
      body: fd,
    });
    if (res.status === 401) throw new Error("未登录或 Token 失效，请先打开 AstrBot 管理面板登录");
    return unwrap(await res.json());
  }

  async download(path, filename) {
    if (this.bridge) {
      await this.bridge.download("download", { path }, filename);
      return;
    }
    const url = `/api/plug/${PLUGIN}/download?path=` + encodeURIComponent(path);
    const res = await fetch(url, { headers: { Authorization: "Bearer " + this.token() } });
    if (!res.ok) {
      const errJson = await res.json().catch(() => null);
      throw new Error((errJson && errJson.message) || "下载失败");
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filename || "download";
    a.click();
    URL.revokeObjectURL(a.href);
  }

  async previewUrl(path) {
    if (this.bridge) {
      const blobLike = await this.bridge.apiGet("preview", { path });
      return blobLike;
    }
    const url = `/api/plug/${PLUGIN}/preview?path=` + encodeURIComponent(path);
    const res = await fetch(url, { headers: { Authorization: "Bearer " + this.token() } });
    if (!res.ok) throw new Error("预览失败");
    const blob = await res.blob();
    return URL.createObjectURL(blob);
  }
}

const api = new ApiClient();
const state = {
  path: "",
  items: [],
  roots: [],
  selected: new Set(),
  lastIndex: -1,
  clipboard: null,
  previewPath: "",
  previewKind: "",
};

const els = {
  roots: document.getElementById("root-list"),
  body: document.getElementById("file-body"),
  empty: document.getElementById("empty-hint"),
  crumbs: document.getElementById("crumbs"),
  search: document.getElementById("search"),
  count: document.getElementById("status-count"),
  sel: document.getElementById("status-sel"),
  path: document.getElementById("status-path"),
  disk: document.getElementById("status-disk"),
  preview: document.getElementById("preview"),
  previewTitle: document.getElementById("preview-title"),
  previewBody: document.getElementById("preview-body"),
  previewActions: document.getElementById("preview-actions"),
  toast: document.getElementById("toast"),
  modal: document.getElementById("modal"),
  modalTitle: document.getElementById("modal-title"),
  modalDesc: document.getElementById("modal-desc"),
  modalInput: document.getElementById("modal-input"),
  checkAll: document.getElementById("check-all"),
  dropzone: document.getElementById("dropzone"),
  fileInput: document.getElementById("file-input"),
};

function toast(message, isError) {
  els.toast.hidden = false;
  els.toast.textContent = message;
  els.toast.classList.toggle("error", Boolean(isError));
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => {
    els.toast.hidden = true;
  }, 2800);
}

function promptModal({ title, desc, value, danger }) {
  return new Promise((resolve) => {
    els.modal.hidden = false;
    els.modalTitle.textContent = title;
    els.modalDesc.textContent = desc || "";
    const needInput = value !== undefined;
    els.modalInput.hidden = !needInput;
    els.modalInput.value = needInput ? value : "";
    document.getElementById("modal-ok").classList.toggle("danger", Boolean(danger));
    const finish = (result) => {
      els.modal.hidden = true;
      document.getElementById("modal-ok").onclick = null;
      document.getElementById("modal-cancel").onclick = null;
      resolve(result);
    };
    document.getElementById("modal-cancel").onclick = () => finish(null);
    document.getElementById("modal-ok").onclick = () => {
      finish(needInput ? els.modalInput.value : true);
    };
    if (needInput) {
      els.modalInput.focus();
      els.modalInput.select();
    }
  });
}

function visibleItems() {
  const q = els.search.value.trim().toLowerCase();
  if (!q) return state.items;
  return state.items.filter((item) => item.name.toLowerCase().includes(q));
}

function selectedItems() {
  return state.items.filter((item) => state.selected.has(item.path));
}

function renderRoots(roots, current) {
  els.roots.innerHTML = "";
  for (const root of roots) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "root-item" + (current.startsWith(root.path) ? " active" : "");
    btn.innerHTML = `<div>${escapeHtml(root.label)}</div><small>${escapeHtml(root.path)}</small>`;
    btn.onclick = () => loadDir(root.path);
    els.roots.appendChild(btn);
  }
}

function renderCrumbs(path) {
  els.crumbs.innerHTML = "";
  const parts = splitPath(path);
  parts.forEach((full, idx) => {
    if (idx > 0) {
      const sep = document.createElement("span");
      sep.className = "sep";
      sep.textContent = "/";
      els.crumbs.appendChild(sep);
    }
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "crumb";
    const label = idx === 0 ? full : full.replace(/\\/g, "/").split("/").filter(Boolean).pop();
    btn.textContent = label;
    btn.onclick = () => loadDir(full);
    els.crumbs.appendChild(btn);
  });
}

function renderTable() {
  const items = visibleItems();
  els.body.innerHTML = "";
  els.empty.hidden = items.length > 0;
  for (const [index, item] of items.entries()) {
    const tr = document.createElement("tr");
    tr.className = "file-row" + (state.selected.has(item.path) ? " selected" : "");
    tr.innerHTML = `
      <td class="col-check"><input type="checkbox" ${state.selected.has(item.path) ? "checked" : ""} /></td>
      <td><div class="name-cell"><span class="kind ${item.kind}">${kindIcon(item.kind)}</span><span>${escapeHtml(item.name)}</span></div></td>
      <td class="col-size">${item.is_dir ? "—" : formatSize(item.size)}</td>
      <td class="col-time">${escapeHtml(item.mtime_text || "")}</td>
    `;
    tr.querySelector("input").onclick = (ev) => {
      ev.stopPropagation();
      toggleSelect(item.path, ev.shiftKey, index);
    };
    tr.onclick = (ev) => toggleSelect(item.path, ev.shiftKey, index, !ev.ctrlKey && !ev.metaKey);
    tr.ondblclick = () => {
      if (item.is_dir) loadDir(item.path);
      else openPreview(item);
    };
    els.body.appendChild(tr);
  }
  els.checkAll.checked = items.length > 0 && items.every((item) => state.selected.has(item.path));
  els.count.textContent = `${items.length} 项`;
  const sel = selectedItems();
  els.sel.textContent = sel.length ? `已选 ${sel.length}` : "";
}

function toggleSelect(path, shift, index, exclusive) {
  if (exclusive && !shift) {
    state.selected.clear();
    state.selected.add(path);
  } else if (shift && state.lastIndex >= 0) {
    const items = visibleItems();
    const [a, b] = [state.lastIndex, index].sort((x, y) => x - y);
    for (let i = a; i <= b; i += 1) state.selected.add(items[i].path);
  } else if (state.selected.has(path)) {
    state.selected.delete(path);
  } else {
    state.selected.add(path);
  }
  state.lastIndex = index;
  renderTable();
}

function escapeHtml(text) {
  return String(text)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

async function loadDir(path) {
  const data = await api.get("list", { path: path || state.path || "" });
  state.path = data.path;
  state.items = data.items || [];
  state.selected = new Set();
  els.path.textContent = data.path;
  if (data.usage) {
    els.disk.textContent = `可用 ${formatSize(data.usage.free)} / ${formatSize(data.usage.total)}`;
  } else {
    els.disk.textContent = "";
  }
  renderCrumbs(data.path);
  renderTable();
  renderRoots(state.roots, data.path);
}

async function openPreview(item) {
  state.previewPath = item.path;
  state.previewKind = item.kind;
  els.preview.hidden = false;
  els.previewTitle.textContent = item.name;
  els.previewActions.hidden = item.kind !== "text";
  els.previewBody.innerHTML = "加载中…";
  try {
    const data = await api.get("preview-data", { path: item.path });
    if (data.kind === "image") {
      els.previewBody.innerHTML = "";
      const img = document.createElement("img");
      img.src = data.data_url;
      els.previewBody.appendChild(img);
      return;
    }
    if (data.kind === "text") {
      const area = document.createElement("textarea");
      area.id = "editor";
      area.value = data.content || "";
      els.previewBody.innerHTML = "";
      els.previewBody.appendChild(area);
      return;
    }
    els.previewBody.innerHTML = `<p>该类型不支持预览，请下载查看。</p>`;
  } catch (err) {
    els.previewBody.textContent = err.message || String(err);
  }
}

async function run(action) {
  try {
    await action();
  } catch (err) {
    toast(err.message || String(err), true);
  }
}

async function uploadFiles(files) {
  for (const file of files) {
    await api.upload(file, state.path);
  }
  toast(`已上传 ${files.length} 个文件`);
  await loadDir(state.path);
}

function bind() {
  document.getElementById("btn-up").onclick = () => {
    const parts = splitPath(state.path);
    if (parts.length > 1) loadDir(parts[parts.length - 2]).catch((err) => toast(err.message, true));
  };
  document.getElementById("btn-refresh").onclick = () => run(() => loadDir(state.path));
  document.getElementById("theme-btn").onclick = () => {
    const cur = document.documentElement.getAttribute("data-theme") === "dark" ? "light" : "dark";
    document.documentElement.setAttribute("data-theme", cur);
  };
  document.getElementById("btn-upload").onclick = () => els.fileInput.click();
  els.fileInput.onchange = () => run(async () => {
    await uploadFiles(Array.from(els.fileInput.files || []));
    els.fileInput.value = "";
  });
  document.getElementById("btn-mkdir").onclick = () => run(async () => {
    const name = await promptModal({ title: "新建文件夹", desc: "输入文件夹名称", value: "新建文件夹" });
    if (!name) return;
    await api.post("mkdir", { path: state.path, name });
    await loadDir(state.path);
  });
  document.getElementById("btn-newfile").onclick = () => run(async () => {
    const name = await promptModal({ title: "新建文件", desc: "输入文件名", value: "untitled.txt" });
    if (!name) return;
    await api.post("create", { path: state.path, name });
    await loadDir(state.path);
  });
  document.getElementById("btn-download").onclick = () => run(async () => {
    const items = selectedItems();
    if (!items.length) throw new Error("请选择要下载的文件或文件夹");
    for (const item of items) {
      const filename = item.is_dir ? `${item.name}.zip` : item.name;
      await api.download(item.path, filename);
    }
  });
  document.getElementById("btn-rename").onclick = () => run(async () => {
    const items = selectedItems();
    if (items.length !== 1) throw new Error("请选择一个文件或文件夹");
    const name = await promptModal({ title: "重命名", desc: "输入新名称", value: items[0].name });
    if (!name) return;
    await api.post("rename", { path: items[0].path, name });
    await loadDir(state.path);
  });
  document.getElementById("btn-copy").onclick = () => {
    state.clipboard = { mode: "copy", paths: selectedItems().map((item) => item.path) };
    toast(`已复制 ${state.clipboard.paths.length} 项`);
  };
  document.getElementById("btn-cut").onclick = () => {
    state.clipboard = { mode: "cut", paths: selectedItems().map((item) => item.path) };
    toast(`已剪切 ${state.clipboard.paths.length} 项`);
  };
  document.getElementById("btn-paste").onclick = () => run(async () => {
    if (!state.clipboard || !state.clipboard.paths.length) throw new Error("剪贴板为空");
    await api.post("move", {
      paths: state.clipboard.paths,
      dest: state.path,
      copy: state.clipboard.mode === "copy",
    });
    if (state.clipboard.mode === "cut") state.clipboard = null;
    await loadDir(state.path);
  });
  document.getElementById("btn-delete").onclick = () => run(async () => {
    const items = selectedItems();
    if (!items.length) throw new Error("请选择要删除的项目");
    const ok = await promptModal({
      title: "确认删除",
      desc: `将删除 ${items.length} 个项目，此操作不可恢复。`,
      danger: true,
    });
    if (!ok) return;
    await api.post("delete", { paths: items.map((item) => item.path) });
    await loadDir(state.path);
  });
  document.getElementById("btn-save").onclick = () => run(async () => {
    const editor = document.getElementById("editor");
    if (!editor || !state.previewPath) return;
    await api.post("write", { path: state.previewPath, content: editor.value });
    toast("已保存");
  });
  document.getElementById("preview-close").onclick = () => {
    els.preview.hidden = true;
  };
  els.search.oninput = renderTable;
  els.checkAll.onclick = () => {
    const items = visibleItems();
    if (els.checkAll.checked) items.forEach((item) => state.selected.add(item.path));
    else state.selected.clear();
    renderTable();
  };
  ["dragenter", "dragover"].forEach((type) => {
    els.dropzone.addEventListener(type, (ev) => {
      ev.preventDefault();
      els.dropzone.classList.add("dragover");
    });
  });
  ["dragleave", "drop"].forEach((type) => {
    els.dropzone.addEventListener(type, (ev) => {
      ev.preventDefault();
      els.dropzone.classList.remove("dragover");
    });
  });
  els.dropzone.addEventListener("drop", (ev) => {
    const files = Array.from(ev.dataTransfer?.files || []);
    if (files.length) run(() => uploadFiles(files));
  });
  document.addEventListener("keydown", (ev) => {
    if (ev.key === "F2") document.getElementById("btn-rename").click();
    if (ev.key === "Delete") document.getElementById("btn-delete").click();
    if (ev.key === "Enter" && selectedItems()[0]?.is_dir) loadDir(selectedItems()[0].path);
    if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "a") {
      ev.preventDefault();
      visibleItems().forEach((item) => state.selected.add(item.path));
      renderTable();
    }
  });
}

async function main() {
  bind();
  await api.ready();
  const info = await api.get("info");
  state.roots = info.roots || [];
  renderRoots(state.roots, info.default_path || "");
  await loadDir(info.default_path || "");
}

main().catch((err) => toast(err.message || String(err), true));
