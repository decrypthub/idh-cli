// 全局响应式状态。保留 ADH 面板三原则，数据模型为 IDH 原生：
//  1. 记录只在「设备+包身份」真变时清空——轮询失败、应用启停不触发。
//  2. 读失败 ≠ 设备没了——catch 保旧数据标 failed，等下次成功轮判定生死。
//  3. 增量轮询按 seq 游标合入，服务端按 App 分片，不存在跨 App 归属问题。
import { reactive, computed, watch } from 'vue';
import * as A from './api';
import { recordVisible } from './observations';

export interface DeviceView {
  key: string; id: string; address: string; label: string;
  online: boolean | null; selected: boolean; failed?: boolean;
}

export const CAP_BUFFER_LIMIT = 4500;
const BUCKET_LIMIT = 1500;

// 板块分桶：crypto 0-3 / system 4,5 / net 6 / keychain 7。各类独立限额，防止高频噪音挤空加密记录。
function bucketOf(cat: number): 'crypto' | 'net' | 'system' | 'keychain' {
  if (cat <= 3) return 'crypto';
  if (cat === 6) return 'net';
  if (cat === 7) return 'keychain';
  return 'system';
}

export const store = reactive({
  // 连接（轮询健康度，无 WebSocket）
  wsState: 'off' as 'off' | 'live' | 'fail',
  capLoading: false,
  // 设备
  devices: [] as DeviceView[],
  usb: [] as string[],
  devicesFailed: false,
  // 服务端每次要逐台探活（各 3s 超时），首屏列表可能几秒才出现；空窗期不能谎报「没有设备」
  devicesLoading: true,
  devicesUpdated: 0,
  // 应用
  apps: [] as A.DhApp[],
  appsError: '',
  appsFailed: false,
  scope: new Set<string>(),
  // 选择（设备+包身份；应用启停不动它）
  chosenPkg: '',
  selectedDeviceKey: '',
  // 记录
  capItems: [] as A.DhEvent[],
  capDropped: 0,
  capLatest: 0,
  capHasOlder: { crypto: false, system: false, net: false, keychain: false },
  // 视图
  view: 'cc' as 'cc' | 'sy' | 'nt' | 'kc' | 'files' | 'dump' | 'settings',
  appDialogOpen: false,
});

export function belongsToApp(_c: A.DhEvent): boolean {
  // 事件 API 按 App 分片，capItems 里只有当前包的记录。
  return !!store.chosenPkg;
}

// ---- 记录（按板块独立限额淘汰）----
export function capPush(c: A.DhEvent) {
  store.capItems.push(c);
  const b = bucketOf(c.category);
  let cnt = 0;
  for (let i = store.capItems.length - 1; i >= 0; i--) {
    if (bucketOf(store.capItems[i].category) !== b) continue;
    cnt++;
    if (cnt > BUCKET_LIMIT) {
      store.capItems.splice(i, 1);
      store.capHasOlder[b] = true;
    }
  }
}
/** 清空显示：只从内存列表移除匹配记录，不动设备上的数据。 */
export function capRemoveWhere(fn: (c: A.DhEvent) => boolean): number {
  const before = store.capItems.length;
  for (let i = store.capItems.length - 1; i >= 0; i--) if (fn(store.capItems[i])) store.capItems.splice(i, 1);
  return before - store.capItems.length;
}

// ---- toast ----
export const toasts = reactive<{ id: number; text: string }[]>([]);
let toastSeq = 0;
export function toast(text: string) {
  const id = ++toastSeq;
  toasts.push({ id, text });
  setTimeout(() => { const i = toasts.findIndex(t => t.id === id); if (i >= 0) toasts.splice(i, 1); }, 2600);
}

// ---- 初次加载：四个板块并行拉取 ----
export async function capLoad() {
  const pkg = store.chosenPkg;
  if (!pkg) { store.capItems = []; return; }
  store.capLoading = true;
  try {
    const [rc, rs, rn, rk] = await Promise.all([
      A.getEvents(pkg, { categories: A.CRYPTO_CATS, limit: 600 }),
      A.getEvents(pkg, { categories: A.SYSTEM_CATS, limit: 600 }),
      A.getEvents(pkg, { categories: '6', limit: 400 }),
      A.getEvents(pkg, { categories: '7', limit: 200 }),
    ]);
    if (store.chosenPkg !== pkg) return;
    const bySeq = new Map<number, A.DhEvent>();
    for (const r of [rc, rs, rn, rk]) {
      for (const c of r.events ?? []) bySeq.set(c.seq, c);
    }
    // 合并加载期间轮询到的新记录，避免往返期间丢尾部
    for (const c of store.capItems) bySeq.set(c.seq, c);
    const merged = [...bySeq.values()].sort((a, b) => a.seq - b.seq);
    store.capItems = merged;
    store.capHasOlder.crypto = !!rc.hasOlder;
    store.capHasOlder.system = !!rs.hasOlder;
    store.capHasOlder.net = !!rn.hasOlder;
    store.capHasOlder.keychain = !!rk.hasOlder;
    store.capDropped = 0;
    store.capLatest = merged.at(-1)?.seq ?? 0;
    store.wsState = 'live';
  } catch {
    // 网络瞬断保旧数据，绝不把已有列表洗成空数组
  } finally {
    if (store.chosenPkg === pkg) store.capLoading = false;
  }
}

// ---- 增量轮询：after 游标拉新，按 seq 去重合入 ----
let pollGen = 0;
export async function pollNewEvents() {
  const pkg = store.chosenPkg;
  if (!pkg) return;
  const gen = pollGen;
  try {
    const r = await A.getEvents(pkg, { after: store.capLatest, limit: 500 });
    if (store.chosenPkg !== pkg || gen !== pollGen) return;
    const fresh = (r.events ?? []).filter(e => e.seq > store.capLatest);
    if (fresh.length) {
      fresh.sort((a, b) => a.seq - b.seq);
      for (const c of fresh) capPush(c);
      store.capLatest = fresh.at(-1)!.seq;
    }
    store.wsState = 'live';
  } catch {
    store.wsState = 'fail';
  }
}

// 只按包名切作用域：设备/包身份真变才清空。
let lastLoadedPkg = '';
export async function syncCapScope() {
  if (!store.chosenPkg || store.chosenPkg === lastLoadedPkg) return;
  lastLoadedPkg = store.chosenPkg;
  pollGen++;
  store.capItems = [];
  store.capLatest = 0;
  store.capHasOlder = { crypto: false, system: false, net: false, keychain: false };
  await capLoad();
}

// ---- 设备轮询：失败保旧值。选择是服务器侧状态，选完同步本地。----
// ?device= / ?app= 深链：首次对应列表加载后自动选中，只生效一次，不覆盖之后的手动切换
let deepDeviceDone = false;
let deepAppDone = false;
// hash 传参（#app=…&device=…）：query 会被面板路由 404，fragment 不上行
const deepParam = (k: string) => {
  if (typeof location === 'undefined') return '';
  const h = location.hash.replace(/^#/, '');
  return new URLSearchParams(h.includes('=') ? h : '').get(k) || '';
};

export async function refreshDevices() {
  try {
    const r = await A.getDevices();
    const list = r.devices ?? [];
    store.usb = Array.isArray(r.usb) ? r.usb : [];
    store.devices = list.map(d => ({
      key: d.id, id: d.id, address: d.address,
      label: d.address.replace(/^https?:\/\//, ''),
      online: d.online, selected: !!d.selected,
    }));
    store.devicesFailed = false;
    store.devicesUpdated = Date.now();
    store.wsState = 'live';
    const want = deepParam('device');
    if (want && !deepDeviceDone) {
      const hit = store.devices.find(d => d.key === want || d.key.includes(want));
      if (hit || list.length) deepDeviceDone = true;
      if (hit && hit.key !== store.selectedDeviceKey) {
        void chooseDevice(hit.key);
        return;
      }
    }
    const sel = store.devices.find(d => d.selected) ?? store.devices[0];
    if (!store.selectedDeviceKey && sel) store.selectedDeviceKey = sel.key;
  } catch {
    store.devicesFailed = true;
    store.wsState = 'fail';
  } finally {
    store.devicesLoading = false;
  }
}

// 自动选应用：capLoad/pollNewEvents 都要求 chosenPkg 非空，没人赋值时四个板块永远是空的。
// 候选来自 idhjd 的 recorded[]（只含 total>0 的 App，服务端按 updated_ms DESC 排序），
// 所以 recorded[0] 就是最近还有事件写入的那个。优先正在运行的，其次最近有记录的。
// 只移动自己挑的那一个：显式选择（弹窗点选、#app= 深链）会清空 autoPickedPkg 接管选择权。
let autoPickedPkg = '';

export async function chooseDevice(key: string) {
  if (store.selectedDeviceKey === key) return;
  store.selectedDeviceKey = key;
  try {
    await A.selectDevice(key);
    // 设备切换 = 身份真变：应用列表与记录全部重载
    pollGen++;
    lastLoadedPkg = '';
    store.chosenPkg = '';
    autoPickedPkg = '';
    store.capItems = [];
    await refreshApps();
  } catch {
    store.devicesFailed = true;
  }
}

function autoPickTarget(list?: A.DhRecordedApp[]): string {
  const rec = list ?? [];
  const running = rec.find(a => a?.bundleId && A.isRunning(a.running));
  return running?.bundleId ?? rec[0]?.bundleId ?? '';
}
function applyPackage(pkg: string) {
  if (store.chosenPkg === pkg) return;
  store.chosenPkg = pkg;
  void syncCapScope();
}
/** 显式选择（弹窗点选、深链）：接管选择权，自动逻辑从此不再改动它。 */
export function choosePackage(pkg: string) {
  autoPickedPkg = '';
  applyPackage(pkg);
}

// ---- 设备管理（增删重连）：服务端 device_records 是唯一真源，每次改完按它同步 ----
/** 设备集合变动后对齐本地：服务端已经选好当前设备就直接跟随，否则只重载应用列表。 */
async function syncAfterDeviceChange() {
  await refreshDevices();
  if (!store.devices.length) {
    // 一台设备都不剩：没有任何数据源，清掉选择与记录，不要留上一台的残影
    pollGen++;
    lastLoadedPkg = '';
    store.chosenPkg = '';
    autoPickedPkg = '';
    store.selectedDeviceKey = '';
    store.capItems = [];
    store.capLatest = 0;
    return;
  }
  const serverPick = store.devices.find(d => d.selected);
  if (serverPick && serverPick.key !== store.selectedDeviceKey) {
    // 服务端把当前设备换掉了（典型：删掉的正是原来那台）——按设备切换处理，重置记录
    await chooseDevice(serverPick.key);
    return;
  }
  await refreshApps();
}

export async function addDeviceByAddress(address: string) {
  const trimmed = address.trim();
  if (!trimmed) throw new Error('请输入设备地址');
  await A.addDevice(trimmed);
  await syncAfterDeviceChange();
}

export async function addUsbDeviceById(udid: string) {
  await A.addUsbDevice(udid);
  await syncAfterDeviceChange();
}

export async function removeDeviceById(id: string) {
  await A.removeDevice(id);
  await syncAfterDeviceChange();
}

/** 重连：内核重新解析地址并探活。返回服务端的结论，离线时不抛错（由调用方提示）。 */
export async function reconnectDeviceById(id: string): Promise<A.DeviceReconnect> {
  const r = await A.reconnectDevice(id);
  await syncAfterDeviceChange();
  return r.reconnect ?? {};
}

// ---- 应用列表：失败保旧值 ----
export async function refreshScope() {
  try {
    const s = await A.getScope();
    if (s.ok && Array.isArray(s.scope)) store.scope = new Set(s.scope);
  } catch { /* scope 读取失败不遮罩主流程 */ }
}

export async function refreshApps() {
  const dev = store.selectedDeviceKey;
  try {
    const r = await A.getApps();
    // 设备已切走：这批响应属于上一台设备，不能写回——否则会把 A 设备的包选到 B 上。
    // 启动时 selectedDeviceKey 还没定（空串），此时放行：服务端自己维护 endpoint，两边一致。
    if (dev !== '' && store.selectedDeviceKey !== dev) return;
    store.apps = r.apps ?? [];
    if (Array.isArray(r.scope)) store.scope = new Set(r.scope);
    store.appsError = r.error ?? '';
    store.appsFailed = false;
    store.wsState = 'live';
    const want = deepParam('app');
    if (want && !deepAppDone) {
      const hit = store.apps.find(a => a.bundleId === want);
      if (hit || store.apps.length) deepAppDone = true;
      if (hit) choosePackage(hit.bundleId);
    }
    // 深链之后再自动选：显式 #app= 永远优先，只在没有任何选择时兜底
    const recorded = r.recorded ?? [];
    if (!store.chosenPkg) {
      const pick = autoPickTarget(recorded);
      if (pick) {
        autoPickedPkg = pick;
        applyPackage(pick);
      }
    } else if (store.chosenPkg === autoPickedPkg &&
               !recorded.some(a => a.bundleId === store.chosenPkg)) {
      // 自己挑的那个已不在记录里（移出注入范围、记录被清）：换一个，别停在空板块。
      // 仍在记录里、只是停止运行的保持不动——历史记录还能看，不能每 15s 把列表清一次。
      const pick = autoPickTarget(recorded);
      if (pick) {
        autoPickedPkg = pick;
        applyPackage(pick);
      }
    }
  } catch {
    store.appsFailed = true;
    store.wsState = 'fail';
  }
}

watch(() => store.appDialogOpen, open => { if (open) void refreshScope(); });
watch(() => store.view, v => { if (v === 'settings') void refreshScope(); });

// ---- 轮询（后台隐藏标签页暂停）----
export function connectWs() { /* 无 WebSocket，保留入口名避免壳层改动 */ }
export function startPolling() {
  const v = deepParam('view');
  if (['cc', 'sy', 'nt', 'kc', 'files', 'dump', 'settings'].includes(v)) store.view = v as typeof store.view;
  void refreshDevices();
  void refreshApps();
  void refreshScope();
  setInterval(() => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    void pollNewEvents();
  }, 2500);
  setInterval(() => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    void refreshDevices();
  }, 12000);
  setInterval(() => {
    if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
    void refreshApps();
  }, 15000);
  if (typeof document !== 'undefined') {
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'visible') {
        void refreshDevices();
        void refreshApps();
        void pollNewEvents();
      }
    });
  }
}

// ---- 面板显示偏好（localStorage，仅当前浏览器）----
export interface PanelDisplay { limit: number | null; time: 'time' | 'date'; density: 'standard' | 'compact'; rail: boolean }
const PANEL_DISPLAY_KEY = 'idh.panel.display';
export const DISPLAY_CAPS = [100, 200, 300, 500, 800];
function normalizePanelDisplay(v?: Partial<PanelDisplay> | null): PanelDisplay {
  return {
    limit: v?.limit != null && DISPLAY_CAPS.includes(v.limit) ? v.limit : null,
    time: v?.time === 'date' ? 'date' : 'time',
    density: v?.density === 'compact' ? 'compact' : 'standard',
    rail: v?.rail === true,
  };
}
function readPanelDisplay(): PanelDisplay {
  try { return normalizePanelDisplay(JSON.parse(localStorage.getItem(PANEL_DISPLAY_KEY) ?? '')); }
  catch { return normalizePanelDisplay(); }
}
export const panelDisplay = reactive<PanelDisplay>(readPanelDisplay());
export const hostDisplayCap = reactive({ value: 300 });
export const capDisplayCap = computed(() => panelDisplay.limit ?? hostDisplayCap.value);
export function savePanelDisplay(v?: Partial<PanelDisplay>) {
  Object.assign(panelDisplay, normalizePanelDisplay(v));
  try { localStorage.setItem(PANEL_DISPLAY_KEY, JSON.stringify(panelDisplay)); return true; }
  catch { return false; }
}

// ---- 记录显示：按包隐藏的算法/类别键（localStorage）----
const hiddenKeyFor = (pkg: string) => `idh.panel.hidden-hooks.v1:${pkg}`;
export const hiddenHooks = reactive(new Set<string>());
let hiddenPkg = '';
function loadHidden() {
  const pkg = store.chosenPkg;
  if (pkg === hiddenPkg) return;
  hiddenPkg = pkg;
  hiddenHooks.clear();
  if (!pkg) return;
  try {
    const saved = JSON.parse(localStorage.getItem(hiddenKeyFor(pkg)) ?? '[]') as unknown;
    if (Array.isArray(saved)) for (const k of saved) if (typeof k === 'string' && k.length < 160) hiddenHooks.add(k);
  } catch { /* 损坏当空集 */ }
}
watch(() => store.chosenPkg, loadHidden, { immediate: true });
export function setHidden(key: string, show: boolean) {
  if (show) hiddenHooks.delete(key); else hiddenHooks.add(key);
  saveHidden();
}
export function resetHidden() {
  hiddenHooks.clear();
  saveHidden();
}
function saveHidden(): boolean {
  if (!store.chosenPkg) return false;
  try {
    if (hiddenHooks.size) localStorage.setItem(hiddenKeyFor(store.chosenPkg), JSON.stringify([...hiddenHooks]));
    else localStorage.removeItem(hiddenKeyFor(store.chosenPkg));
    return true;
  } catch { return false; }
}
export const capVisible = (c: A.DhEvent) => recordVisible(c, hiddenHooks);
