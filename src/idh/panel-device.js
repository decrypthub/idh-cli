/* Adapt the original IOSDecryptHub panel to the desktop idhjd session routes. */
(() => {
  const realFetch = window.fetch.bind(window);
  const endpoint = document.querySelector('meta[name="idh-device-endpoint"]').content;
  const classes = ["digest", "hmac", "sym", "asym", "file", "sys", "net", "keychain", "other"];
  const labels = ["摘要", "HMAC", "对称", "非对称", "文件", "系统", "网络", "Keychain", "其他"];
  const summaryKinds = Object.freeze(classes.map((key, index) => Object.freeze({key, label: labels[index]})));
  const allSummaries = (1 << classes.length) - 1;
  const displayChoices = Object.freeze([100, 150, 300, 500]);
  const limits = {
    maxRecords: [1, 2000], maxBytes: [512, 2097152], recordSeconds: [1, 300]
  };
  const preferenceKeys = ["displayCap", "autoRefresh", "advancedFilters", "summaryCategories"];
  const version = 1;

  function checkFields(data, allowed, name) {
    if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error(name + " 必须是对象");
    if (Object.keys(data).some((key) => !allowed.includes(key))) throw new Error(name + " 含有不支持的字段");
  }

  function defaults() {
    return {displayCap:150, autoRefresh:true, advancedFilters:false,
      summaryCategories:Object.fromEntries(classes.map((key) => [key, true]))};
  }

  function deviceLimits(patch, requireAll = false) {
    checkFields(patch, Object.keys(limits), "deviceSession");
    if (requireAll && Object.keys(patch).length !== Object.keys(limits).length)
      throw new Error("设备返回的会话配置不完整");
    for (const [field, value] of Object.entries(patch)) {
      const [min, max] = limits[field];
      if (!Number.isInteger(value) || value < min || value > max)
        throw new Error(field + " 必须是 " + min + "–" + max + " 之间的整数");
    }
    return Object.fromEntries(Object.entries(patch));
  }

  function mergePanel(base, patch) {
    checkFields(patch, preferenceKeys, "panel");
    const next = {displayCap:base.displayCap, autoRefresh:base.autoRefresh,
      advancedFilters:base.advancedFilters, summaryCategories:{...base.summaryCategories}};
    for (const key of ["autoRefresh", "advancedFilters"]) {
      if (!Object.hasOwn(patch, key)) continue;
      if (typeof patch[key] !== "boolean") throw new Error(key + " 必须是布尔值");
      next[key] = patch[key];
    }
    if (Object.hasOwn(patch, "displayCap")) {
      if (!displayChoices.includes(patch.displayCap)) throw new Error("displayCap 只支持 100、150、300、500");
      next.displayCap = patch.displayCap;
    }
    if (Object.hasOwn(patch, "summaryCategories")) {
      checkFields(patch.summaryCategories, classes, "summaryCategories");
      for (const [key, value] of Object.entries(patch.summaryCategories)) {
        if (typeof value !== "boolean") throw new Error(key + " 的摘要开关必须是布尔值");
        next.summaryCategories[key] = value;
      }
    }
    return next;
  }

  function parseProfile(data, panel) {
    checkFields(data, ["version", "deviceSession", "panel"], "配置");
    const hasVersion = Object.hasOwn(data, "version");
    const hasDevice = Object.hasOwn(data, "deviceSession");
    const hasPanel = Object.hasOwn(data, "panel");
    if (hasVersion && data.version !== version) throw new Error("不支持此配置版本");
    if ((!hasVersion && (!hasDevice || hasPanel)) || (!hasDevice && !hasPanel))
      throw new Error("配置应包含 deviceSession 或带版本号的 panel");
    const deviceSession = hasDevice ? deviceLimits(data.deviceSession) : {};
    if (hasDevice && !Object.keys(deviceSession).length) throw new Error("deviceSession 没有可应用的字段");
    return {deviceSession, hasDevice, hasPanel, panel:mergePanel(panel, hasPanel ? data.panel : {})};
  }

  function portableProfile(device, panel) {
    const config = {version, deviceSession:deviceLimits(device, true), panel:mergePanel(defaults(), panel)};
    return JSON.stringify(config, null, 2);
  }

  function summaryMask(panel) {
    return classes.reduce((mask, key, index) => mask | (panel.summaryCategories[key] ? (1 << index) : 0), 0);
  }

  const profile = Object.freeze({defaults, mergePanel, deviceLimits, parseProfile, portableProfile,
    summaryMask, summaryKinds, displayChoices});
  const phases = {entry: "进入", leave: "返回", complete: "完成", aborted: "中止"};
  const stateLabels = {waiting: "等待 Agent", observing: "观察中", closing: "确认尾部", ended: "已结束"};
  const format = new Intl.DateTimeFormat("zh-CN", {dateStyle: "short", timeStyle: "medium"});
  const unsupported = "设备会话接口提供已保存的事件摘要。此操作需要原版 App 进程接口。";
  const paused = new Set();
  const clearedThrough = new Map();
  let selected = "";
  let revision = 0;
  let catalog;
  let catalogPending;
  let loaded;
  let controls;

  function response(value, status = 200, statusText = "") {
    return new Response(JSON.stringify(value), {status, statusText, headers: {"Content-Type": "application/json"}});
  }

  function formatted(epoch) {
    return epoch > 0 && epoch <= 8640000000000000 ? format.format(epoch) : "";
  }

  function selectOptions(sessions) {
    if (controls?.sessionOptions) {
      controls.sessionOptions(sessions, selected);
      return;
    }
    const menu = document.getElementById("idh-session");
    const options = sessions.map((session) => [session.sessionId, [
      session.bundleId, formatted(session.createdAtMs), stateLabels[session.status], session.count + " 条"
    ].filter(Boolean).join(" · ")]);
    if (!options.length) options.push(["", "没有可读取的会话"]);
    if (JSON.stringify(options) !== menu.dataset.options) {
      menu.replaceChildren(...options.map(([value, label]) => new Option(label, value)));
      menu.dataset.options = JSON.stringify(options);
    }
    menu.value = selected;
    menu.disabled = !sessions.length;
  }

  function changeSelection(id) {
    if (id === selected) return;
    const old = selected;
    selected = id;
    loaded = null;
    paused.clear();
    clearedThrough.clear();
    if (old) {
      revision++;
      queueMicrotask(() => controls.change());
    }
  }

  async function inspectDevice() {
    if (catalogPending) return catalogPending;
    if (catalog && Date.now() - catalog.time < 1100) return catalog;
    catalogPending = (async () => {
      const [health, history] = await Promise.all([realFetch("/health"), realFetch("/api/sessions")]);
      if (!health.ok) throw new Error("设备连接不可用");
      const device = await health.json();
      const sessions = history.ok ? (await history.json()).sessions : [];
      if (!sessions.some((session) => session.sessionId === selected)) changeSelection(sessions[0]?.sessionId || "");
      selectOptions(sessions);
      const notice = document.getElementById("idh-session-notice");
      notice.textContent = history.status === 401 ? "请在手机 Manager 获取有效的设备会话只读凭证。"
        : history.ok ? "" : "设备在线，会话暂时无法读取。";
      notice.hidden = !notice.textContent;
      catalog = {time: Date.now(), device, sessions};
      return catalog;
    })();
    try {
      return await catalogPending;
    } finally {
      catalogPending = null;
    }
  }

  async function readEvents(session) {
    const result = [];
    const path = "/api/sessions/" + encodeURIComponent(session.sessionId) + "/events";
    const through = session.lastSeq;
    let cursor = 0;
    for (let index = 0; result.length < session.count && index < 20; ++index) {
      const page = await realFetch(path + "?limit=100&after_seq=" + cursor);
      if (!page.ok) throw new Error("设备会话摘要暂时无法读取");
      const data = await page.json();
      for (const event of data.events) {
        if (event.seq <= cursor) throw new Error("设备摘要序号重复或倒退");
        if (event.seq > through) break;
        result.push(event);
        cursor = event.seq;
      }
      if (!data.events.length || !data.hasMore || cursor >= through) break;
    }
    if (result.length !== session.count || cursor !== through) throw new Error("已保存摘要与会话快照不一致，请刷新");
    return result.reverse();
  }

  async function snapshot() {
    const {device, sessions} = await inspectDevice();
    const session = sessions.find((item) => item.sessionId === selected);
    if (!session) return {device, session: null, events: []};
    const key = [session.sessionId, session.count, session.lastSeq].join("/");
    if (loaded?.key !== key) {
      const pending = readEvents(session);
      loaded = {key, pending};
      pending.catch(() => {
        if (loaded?.pending === pending) loaded = null;
      });
    }
    const events = await loaded.pending;
    return {device, session, events};
  }

  function group(category) {
    if (category <= 3) return -2;
    if (category === 6 || category === 7) return category;
    return -3;
  }

  function matchesCategory(event, selection) {
    if (selection === -1) return true;
    return selection < -1 ? group(event.category) === selection : event.category === selection;
  }

  function asLog(event) {
    const detail = [
      ["原记录序号", event.sourceSeq], ["阶段", phases[event.phase]], ["类型", event.kind],
      ["关联 ID", event.callId], ["上级关联", event.parentCallId], ["异步任务", event.asyncTaskId],
      ["记录更新", event.update ? "是" : ""]
    ].filter(([, value]) => value !== undefined && value !== "").map(([label, value]) => label + " " + value).join("\n");
    return {
      seq: event.seq, category: event.category, categoryName: classes[event.category],
      algorithm: labels[event.category] + "事件", operation: phases[event.phase] || "摘要",
      timestamp: formatted(event.timeMs), detail, preview: ""
    };
  }

  function statsFor({device, session, events}) {
    const byCategory = classes.map(() => 0);
    for (const event of events) byCategory[event.category]++;
    const live = session
      ? device.apps.find((app) => app.processGeneration === session.processGeneration && app.bundleId === session.bundleId)
      : device.apps[0];
    return {
      categoryNames: classes, byCategory, total: events.length, paused: false,
      pausedByCat: classes.map((_, category) => paused.has(group(category))),
      deviceStatus: "设备在线", version: "会话协议 " + device.version,
      process: {
        appName: live?.bundleId || (session ? session.bundleId + " · 历史会话" : "没有在线 App"),
        bundleId: live?.bundleId || session?.bundleId || "", pid: live?.pid
      }
    };
  }

  async function deviceSettings(body) {
    const result = await realFetch("/api/session-settings", body === undefined ? {} : {
      method: "POST", headers: {"Content-Type": "application/json"}, body
    });
    const data = await result.json();
    if (result.ok) return response(data);
    const messages = {
      settings_pairing_required: "请在手机 Manager 复制设备设置凭证并传给电脑面板。",
      revision_conflict: "设备配置已被修改。请重新载入后再应用。",
      invalid_settings: "设备会话限额需要整数，支持 1–2000 条、512–2097152 字节和 1–300 秒。",
      settings_storage_error: "设备无法读取或保存设置。",
      settings_unavailable: "当前设备服务尚未提供设置接口。"
    };
    return response({error: messages[data.error] || "设备设置暂时无法读取或保存。"}, result.status);
  }

  async function request(url, options = {}) {
    const {pathname, searchParams} = new URL(url, location.origin);
    const selection = Number(searchParams.get("cat") ?? -1);
    const method = options.method || "GET";
    // 设备管理与注入范围：由本机面板服务直接处理/中转，不走会话适配
    if (/^\/api\/(apps|injection-scope|devices)(\/|$)/.test(pathname)) return realFetch(url, options);
    try {
      if (method === "GET" && pathname === "/api/settings/export") return await deviceSettings();
      if (method === "POST" && pathname === "/api/settings/import") return await deviceSettings(options.body);
      if (method === "POST" && pathname === "/api/pause") {
        if (searchParams.get("paused") === "1") paused.add(selection);
        else paused.delete(selection);
        return response({ok: true});
      }
      if (method === "POST" && pathname === "/api/clear" && searchParams.has("cat")) {
        const data = await snapshot();
        clearedThrough.set(selection, data.events[0]?.seq || 0);
        return response({ok: true});
      }
      if (method !== "GET") return response({error: unsupported}, 501, "Device session only");
      if (pathname === "/api/stats") return response(statsFor(await snapshot()));
      if (pathname === "/api/logs" || /^\/api\/logs\/\d+$/.test(pathname)) {
        const data = await snapshot();
        if (pathname !== "/api/logs") {
          const seq = Number(pathname.split("/").pop());
          const event = data.events.find((item) => item.seq === seq);
          return event ? response(asLog(event)) : response({error: "unknown_event"}, 404);
        }
        const since = Number(searchParams.get("since") || 0);
        const before = Number(searchParams.get("before") || Infinity);
        const limit = Math.min(2000, Math.max(1, Number(searchParams.get("limit") || 150)));
        const maskValue = searchParams.get("summaryMask");
        const mask = maskValue === null ? allSummaries : Number(maskValue);
        if (maskValue !== null && (!/^\d{1,3}$/.test(maskValue) || mask > allSummaries))
          return response({error:"invalid_summary_mask"}, 400);
        const board = selection < 0 ? selection : group(selection);
        if (searchParams.has("since") && paused.has(board)) return response([]);
        const minimum = Math.max(since, clearedThrough.get(board) || 0);
        const query = (searchParams.get("q") || "").trim().toLowerCase();
        const logs = data.events.filter((item) => (mask & (1 << item.category)) !== 0 &&
            matchesCategory(item, selection) && item.seq > minimum && item.seq < before)
          .map(asLog).filter((item) => !query || [
            "#" + item.seq, item.algorithm, item.operation, item.timestamp, item.detail
          ].join(" ").toLowerCase().includes(query));
        return response(logs.slice(0, limit));
      }
      if (pathname === "/api/diag") {
        const {device, session} = await snapshot();
        return new Response(JSON.stringify({device, session}, null, 2), {headers: {"Content-Type": "text/plain; charset=utf-8"}});
      }
      return response({error: unsupported}, 501, "Device session only");
    } catch {
      return response({error: "设备连接或会话读取失败"}, 502, "Device unavailable");
    }
  }

  async function download(selection, diagnose = false) {
    try {
      const {device, session, events} = await snapshot();
      if (!diagnose && !session) {
        controls.message("没有可下载的设备会话");
        return;
      }
      const data = diagnose ? {device, session} : {session, events: events.filter((event) => matchesCategory(event, selection))};
      const blob = new Blob([JSON.stringify(data, null, 2)], {type: "application/json"});
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = diagnose ? "idhjd-device-diagnostics.json" : "idh-session-" + session.sessionId + ".json";
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch {
      controls.message("设备数据暂时无法下载");
    }
  }

  function attach(callbacks) {
    controls = callbacks;
    document.getElementById("idh-session").addEventListener("change", (event) => changeSelection(event.target.value));
    document.getElementById("sizeWrap").style.setProperty("display", "none", "important");
    document.getElementById("q").placeholder = "搜索本类：序号 / 阶段 / 关联 ID…";
    document.getElementById("dlAll").addEventListener("click", (event) => {
      event.preventDefault();
      controls.close();
      download(-1);
    });
    document.getElementById("tabDownloadBtn").addEventListener("click", (event) => {
      event.stopImmediatePropagation();
      controls.close();
      download(controls.category());
    }, true);
    document.getElementById("diagDownload").addEventListener("click", (event) => {
      event.stopImmediatePropagation();
      download(-1, true);
    }, true);

    const unsupportedActions = [
      "#viewNoiseBtn", "#dumpDylib", "#dumpIpa", "#diagIssue", "#setMaxEntries", "#setMaxFile",
      "#setMask button", "#setMask input[type=checkbox]", "#setMask textarea", "#setMask select", "#setMask input[type=file]"
    ].join(",");
    const allowedSettings = [
      "#setClose", "#setNav [data-setpage]", "#setDisplayCap", "#setMaxEntries", "#setMaxFile", "#setRecordSeconds",
      "#setCapBody [data-summary-kind]", "#rawCfgText", "#rawReload", "#rawCopy", "#rawDownload", "#rawFile", "#rawSave"
    ].join(",");
    for (const name of ["click", "change", "keydown"]) {
      document.addEventListener(name, (event) => {
        if (!event.target.closest(unsupportedActions) || event.target.closest(allowedSettings) ||
            (name === "keydown" && event.key !== "Enter")) return;
        event.preventDefault();
        event.stopImmediatePropagation();
        controls.message(unsupported);
      }, true);
    }
    for (const tab of document.querySelectorAll(".tab[data-tab=files],.tab[data-tab=symbols],.tab[data-tab=dump]")) {
      tab.title = unsupported;
      tab.addEventListener("click", () => controls.message(unsupported));
    }
  }

  // The desktop workspace only changes how a committed snapshot is displayed.
  // Selection is confined to sessions returned by the same authorized catalog.
  function workspace(callbacks) {
    controls = callbacks;
    return Object.freeze({
      snapshot,
      choose(id) {
        if (!catalog?.sessions.some((session) => session.sessionId === id)) return false;
        changeSelection(id);
        return true;
      }
    });
  }

  window.IDHDevicePanel = {request, attach, workspace, endpoint, profile, get revision() { return revision; }};
})();
