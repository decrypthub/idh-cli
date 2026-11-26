// 响应式数据层：panel-device.js 的 inspectDevice/readEvents/snapshot + 面板状态。
import { reactive, computed } from 'vue';
import * as A from './api';
import {
  type AppRecord, type DeviceInfo, type DeviceRow, type DeviceSession, type EventItem,
  type InstalledApp, type PanelPrefs, BOARD_CATS, defaults, mergePanel,
} from './model';

export interface Catalog { device: DeviceInfo; sessions: DeviceSession[]; installed: InstalledApp[] }
interface BoardDisplay { pauseAt: number | null; clearThrough: number | null }

const PREF_KEY = 'idh_panel_preferences_v1';
const VIEW_KEY = 'idh_workspace_view_v1';

function loadLocal<T>(key: string): T | null {
  try { return JSON.parse(localStorage.getItem(key) ?? '') as T; } catch { return null; }
}
export function saveLocal(key: string, value: unknown): boolean {
  try { localStorage.setItem(key, JSON.stringify(value)); return true; } catch { return false; }
}

function loadPrefs(): PanelPrefs {
  try {
    const old = Number(localStorage.getItem('dh_displayCap'));
    const prev: Record<string, unknown> = { advancedFilters: localStorage.getItem('dh_filters_open') === '1' };
    if ([100, 150, 300, 500].includes(old)) prev.displayCap = old;
    return mergePanel(defaults(), (loadLocal<Record<string, unknown>>(PREF_KEY) ?? prev) as Record<string, unknown>);
  } catch { return defaults(); }
}

export const store = reactive({
  // 设备与连接
  network: 'loading' as 'loading' | 'online' | 'offline',
  device: null as DeviceInfo | null,
  devices: [] as DeviceRow[],
  usbRows: [] as string[],
  // 应用目录
  apps: [] as AppRecord[],
  installed: [] as InstalledApp[],
  selected: '',
  // 当前应用数据
  session: null as (DeviceSession & { sessions?: number }) | null,
  events: [] as EventItem[],
  sessionNotice: '',
  // 已加载窗口之外设备上还有更早记录
  hasOlder: false,
  eventTotal: 0,
  loadingOlder: false,
  // 设备侧按类别真实总数（summary.byCategory），空数组表示未取得
  catTotals: [] as number[],
  // 板块与展示
  tab: 'crypto',
  displayByBoard: new Map<string, BoardDisplay>(),
  prefs: loadPrefs(),
  limit: 0, // 由 prefs.displayCap 初始化
  seq: null as number | null,
  detailTab: 'data' as 'data' | 'context' | 'raw',
  // 注入范围
  injectData: null as { apps?: InstalledApp[]; scope?: string[]; error?: string } | null,
  injectAt: 0,
  injectPending: new Set<string>(),
  // 对话框开关
  appDialogOpen: false,
  diagOpen: false,
  mcpOpen: false,
  settingsOpen: false,
  wechatOpen: false,
  settingsPage: 'capture',
});
store.limit = store.prefs.displayCap;

// ---- toast ----
export const toasts = reactive<{ id: number; text: string }[]>([]);
let toastSeq = 0;
export function toast(text: string) {
  const id = ++toastSeq;
  toasts.push({ id, text });
  setTimeout(() => { const i = toasts.findIndex(t => t.id === id); if (i >= 0) toasts.splice(i, 1); }, 1500);
}
export async function copyText(text: string) {
  if (!text) return;
  try { await navigator.clipboard.writeText(text); }
  catch {
    const ta = document.createElement('textarea');
    (document.querySelector('dialog[open]') ?? document.body).appendChild(ta);
    ta.value = text; ta.select();
    try { document.execCommand('copy'); } catch { toast('无法复制，请手动选中内容'); ta.remove(); return; }
    ta.remove();
  }
  toast('已复制');
}
export function downloadText(filename: string, text: string) {
  downloadBlob(filename, new Blob([text], { type: 'application/json' }));
}
export function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url; a.download = filename;
  document.body.appendChild(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  toast('已下载 ' + filename);
}

// ---- 板块显示状态（暂停/清空，跨页签保留）----
export function displayState(board = store.tab): BoardDisplay {
  if (!store.displayByBoard.has(board)) store.displayByBoard.set(board, { pauseAt: null, clearThrough: null });
  return store.displayByBoard.get(board)!;
}

// ---- 应用归并：会话按 bundleId 合并 + 已安装元数据 ----
export function appsFrom(sessions: DeviceSession[], installed: InstalledApp[]): AppRecord[] {
  const meta = new Map(installed.map((a) => [a.bundleId, a]));
  const map = new Map<string, AppRecord>();
  for (const s of sessions) {
    let app = map.get(s.bundleId);
    if (!app) {
      const m = meta.get(s.bundleId);
      app = {
        sessionId: s.bundleId, bundleId: s.bundleId, createdAtMs: s.createdAtMs,
        status: s.status, count: 0, sessions: 0, lastSeq: 0,
        name: m?.name ?? '', running: m?.running === true, kind: 'record',
      };
      map.set(s.bundleId, app);
    }
    app.count += s.count;
    app.sessions += 1;
    if (s.createdAtMs > app.createdAtMs) { app.createdAtMs = s.createdAtMs; app.status = s.status; }
  }
  return [...map.values()];
}

let catalog: Catalog | null = null;
let catalogPending: Promise<Catalog> | null = null;

export async function inspectDevice(): Promise<Catalog> {
  if (catalogPending) return catalogPending;
  if (catalog && Date.now() - (catalog as { time?: number }).time! < 1100) return catalog;
  catalogPending = (async () => {
    const [health, history, installedRes] = await Promise.all([
      A.getHealth(), A.getSessions(), A.getApps()]);
    if (!(health as unknown as { ok?: boolean }).ok && !(health as DeviceInfo).service)
      throw new Error('设备连接不可用');
    const device = health;
    const sessions = history.sessions ?? [];
    const installed = installedRes.apps ?? [];
    const known = store.selected
      && (sessions.some((s) => s.bundleId === store.selected)
        || installed.some((a) => a.bundleId === store.selected));
    if (!known) changeSelection(sessions[0]?.bundleId ?? installed[0]?.bundleId ?? '');
    store.apps = appsFrom(sessions, installed);
    store.installed = installed;
    store.sessionNotice = history.sessions ? '' : '设备在线，会话暂时无法读取。';
    catalog = { device, sessions, installed };
    (catalog as { time?: number }).time = Date.now();
    return catalog;
  })();
  try { return await catalogPending; } finally { catalogPending = null; }
}

export function changeSelection(id: string) {
  if (id === store.selected) return;
  const had = !!store.selected;
  store.selected = id;
  eventWindow = null;
  store.hasOlder = false;
  store.eventTotal = 0;
  store.loadingOlder = false;
  store.catTotals = [];
  store.displayByBoard.clear();
  store.seq = null;
  store.detailTab = 'data';
  store.limit = store.prefs.displayCap;
  if (had) void refresh(true);
}

// ---- 按 App 读时间线：默认只取设备最新一页；向前翻页由「加载更早」手动触发 ----
// 窗口按当前板块类别过滤拉取（设备端 SQL 过滤）：噪声类别不会把本板块事件挤出窗口。
const EVENT_PAGE = 200;
interface EventWindow {
  bundle: string;
  cats: number[];        // 窗口绑定的类别过滤
  events: EventItem[];   // appSeq 升序
  oldestSeq: number;
  hasOlder: boolean;
  total: number;         // 设备侧该应用保存总数（summary.count，全类别）
  boardTotal: number;    // 本板块类别在设备侧的总数（byCategory 求和）
}
let eventWindow: EventWindow | null = null;
let windowGen = 0;

// 当前事件板块的类别；非事件板块（注入/文件/符号/Dump/设置）返回 null
export function boardCats(tab = store.tab): number[] | null {
  return BOARD_CATS[tab] ?? null;
}
const sameCats = (a: number[], b: number[]) => a.length === b.length && a.every((v, i) => v === b[i]);
const boardTotalOf = (byCat: number[] | undefined, cats: number[], fallback: number) =>
  Array.isArray(byCat) && byCat.length ? cats.reduce((sum, c) => sum + (byCat[c] ?? 0), 0) : fallback;

const normEvent = (e: EventItem): EventItem => {
  const seq = e.appSeq ?? e.seq;
  return { ...e, seq, appSeq: seq };
};

async function loadLatestPage(bundle: string, cats: number[]): Promise<void> {
  const page = await A.getAppEvents(bundle, { limit: EVENT_PAGE, categories: cats });
  if ((page as { __status?: number }).__status) throw new Error('设备摘要暂时无法读取');
  const events = (page.events ?? []).map(normEvent);
  eventWindow = {
    bundle, cats: cats.slice(), events,
    oldestSeq: events[0]?.appSeq ?? 0,
    hasOlder: !!page.hasOlder,
    total: Number(page.summary?.count ?? events.length),
    boardTotal: boardTotalOf(page.summary?.byCategory, cats, events.length),
  };
  if (Array.isArray(page.summary?.byCategory)) store.catTotals = page.summary.byCategory;
}

export async function loadOlder(): Promise<void> {
  const w = eventWindow;
  if (!w?.hasOlder || store.loadingOlder) return;
  store.loadingOlder = true;
  try {
    const page = await A.getAppEvents(w.bundle, { before: w.oldestSeq, limit: EVENT_PAGE, categories: w.cats });
    if ((page as { __status?: number }).__status) throw new Error('设备摘要暂时无法读取');
    // 轮询快照不挡手动翻页；只在窗口整体被换（切应用/切板块/外部清理重建）时丢弃结果
    if (eventWindow !== w) return;
    const older = (page.events ?? []).map(normEvent).filter((e) => (e.appSeq ?? 0) < w.oldestSeq);
    if (older.length) w.events.unshift(...older);
    w.oldestSeq = Number(page.oldestSeq) || w.oldestSeq;
    w.hasOlder = !!page.hasOlder;
    w.total = Number(page.summary?.count ?? w.total);
    w.boardTotal = boardTotalOf(page.summary?.byCategory, w.cats, w.boardTotal);
    store.events = w.events.slice();
    store.hasOlder = w.hasOlder;
    store.eventTotal = w.boardTotal;
    if (Array.isArray(page.summary?.byCategory)) store.catTotals = page.summary.byCategory;
  } finally { store.loadingOlder = false; }
}

export async function clearDeviceEvents(): Promise<boolean> {
  if (!store.selected) return false;
  const res = await A.clearAppEvents(store.selected);
  if (res.error || (res as { __status?: number }).__status) return false;
  eventWindow = null;
  store.events = [];
  store.seq = null;
  store.detailTab = 'data';
  await refresh(true);
  return true;
}

export async function snapshot(): Promise<{ device: DeviceInfo; session: typeof store.session; events: EventItem[] }> {
  const { device, sessions } = await inspectDevice();
  const appSessions = sessions.filter((s) => s.bundleId === store.selected);
  if (!appSessions.length) {
    eventWindow = null;
    store.hasOlder = false;
    store.eventTotal = 0;
    return { device, session: null, events: [] };
  }
  const latest = appSessions[0];
  const live = device.apps.find((a) => a.bundleId === store.selected);
  const gen = ++windowGen;
  // 切到另一事件板块后窗口类别不再匹配 → 整窗按新板块类别重读；非事件板块保持现有窗口继续增量
  const wanted = boardCats();
  if (!eventWindow || eventWindow.bundle !== store.selected ||
      (wanted !== null && eventWindow.cats.length > 0 && !sameCats(eventWindow.cats, wanted))) {
    await loadLatestPage(store.selected, wanted ?? eventWindow?.cats ?? []);
  } else {
    const tail = eventWindow.events[eventWindow.events.length - 1]?.appSeq ?? 0;
    const page = await A.getAppEvents(store.selected, { after: tail, limit: 500, categories: eventWindow.cats });
    if ((page as { __status?: number }).__status) throw new Error('设备摘要暂时无法读取');
    if (gen !== windowGen || !eventWindow) throw new Error('stale');
    const fresh = (page.events ?? []).map(normEvent).filter((e) => (e.appSeq ?? 0) > tail);
    if (fresh.length) eventWindow.events.push(...fresh);
    const total = Number(page.summary?.count ?? NaN);
    if (Number.isFinite(total)) {
      // 设备记录在外部被清理（MCP/其他客户端）→ 已加载数据可能越界，整窗重读最新页
      if (total < eventWindow.events.length) await loadLatestPage(store.selected, eventWindow.cats);
      else {
        eventWindow.total = total;
        eventWindow.boardTotal = boardTotalOf(page.summary?.byCategory, eventWindow.cats, eventWindow.boardTotal);
      }
    }
    if (Array.isArray(page.summary?.byCategory)) store.catTotals = page.summary.byCategory;
  }
  if (gen !== windowGen || !eventWindow) throw new Error('stale');
  const w = eventWindow;
  store.hasOlder = w.hasOlder;
  store.eventTotal = w.boardTotal;
  return {
    device,
    session: {
      ...latest, count: w.total, lastSeq: w.events[w.events.length - 1]?.appSeq ?? latest.lastSeq,
      sessions: appSessions.length,
      processGeneration: live?.processGeneration ?? latest.processGeneration,
    },
    events: w.events.slice(),
  };
}

// ---- 轮询 ----
let inFlight = false;
export async function refresh(force = false) {
  if (inFlight && !force) return;
  inFlight = true;
  try {
    const next = await snapshot();
    const changed = store.session?.sessionId !== next.session?.sessionId;
    if (changed) {
      store.displayByBoard.clear();
      store.seq = null;
      store.detailTab = 'data';
      store.limit = store.prefs.displayCap;
    }
    store.device = next.device;
    store.session = next.session;
    store.events = next.events;
    store.network = 'online';
  } catch {
    store.network = 'offline';
  } finally {
    inFlight = false;
  }
}

export function chooseApp(bundleId: string): boolean {
  const known = catalog?.sessions.some((s) => s.bundleId === bundleId)
    || catalog?.installed?.some((a) => a.bundleId === bundleId)
    || store.apps.some((a) => a.bundleId === bundleId)
    || store.installed.some((a) => a.bundleId === bundleId);
  if (!known) return false;
  changeSelection(bundleId);
  return true;
}

// ---- 设备列表 ----
export async function loadDevices() {
  try {
    const data = await A.getDevices();
    store.devices = data.devices ?? [];
    store.usbRows = data.usb ?? [];
  } catch { store.devices = []; store.usbRows = []; }
}
export async function deviceSelect(id: string): Promise<boolean> {
  const data = await A.deviceAction({ action: 'select', id });
  return !data.error;
}
export async function deviceRemove(id: string) { await A.deviceAction({ action: 'remove', id }); await loadDevices(); }
export async function deviceAdd(address?: string, usb?: string) {
  const body: Record<string, unknown> = { action: 'add' };
  if (address) body.address = address;
  if (usb) body.usb = usb;
  const data = await A.deviceAction(body);
  await loadDevices();
  return !data.error;
}
export const currentDevice = computed(() => store.devices.find((d) => d.selected));

// ---- 注入范围 ----
export async function loadInject(force = false) {
  if (!force && Date.now() - store.injectAt < 3000) return;
  store.injectAt = Date.now();
  try { store.injectData = await A.getApps(); }
  catch { store.injectData = { error: 'device_unavailable' }; }
}
export async function toggleScope(bundleId: string, on: boolean): Promise<boolean> {
  let data: { scope?: string[]; error?: string };
  try { data = await A.scopeUpdate(bundleId, on); }
  catch { toast('注入范围更新失败'); return false; }
  if (data.error) { toast('注入范围更新失败'); return false; }
  const app = (store.injectData?.apps ?? []).find((a) => a.bundleId === bundleId);
  if (app?.running) store.injectPending.add(bundleId); else store.injectPending.delete(bundleId);
  if (store.injectData) store.injectData.scope = data.scope ?? store.injectData.scope;
  return true;
}
export async function relaunchBundle(bundleId: string) {
  await A.relaunchApp(bundleId).catch(() => undefined);
  store.injectPending.delete(bundleId);
  setTimeout(() => void loadInject(true), 1500);
}

export function savePrefs(next: PanelPrefs) {
  store.prefs = next;
  saveLocal(PREF_KEY, next);
}
export const currentApp = computed(() =>
  store.apps.find((a) => a.bundleId === store.selected)
  ?? store.installed.find((a) => a.bundleId === store.selected));
export const selectedName = computed(() => currentApp.value?.name || store.selected || '应用记录');
