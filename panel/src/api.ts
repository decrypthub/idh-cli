// IDH 面板 API 客户端。直连 idh-cli 面板服务器（同源），服务器转发到当前选中设备的 idhjd。
// 数据模型是 iOS 原生语义：事件 category 为 0-8 数字、kind 为 crypto/network/observation，
// 加密事件携带 keyHex/ivHex/inputHex/outputHex 真实字节（agent 截断到 64/32/256/256 字节）。

// ---- 类型：IDH 原生事件模型 ----
export interface DhEvent {
  seq: number; appSeq?: number; sourceSeq?: number; agentSeq?: number;
  timeMs: number; category: number; kind: string;
  algorithm?: string; operation?: string; detail?: string; preview?: string;
  publicKeyInfo?: string;
  inLen?: number; outLen?: number; keyLen?: number; ivLen?: number;
  keyHex?: string; ivHex?: string; inputHex?: string; outputHex?: string;
  phase?: string; update?: boolean;
  callId?: string; parentCallId?: string; asyncTaskId?: string;
}
// category: 0 摘要 1 HMAC 2 对称 3 非对称 4 文件 5 系统 6 网络 7 Keychain 8 其他
export const CAT = { digest: 0, hmac: 1, sym: 2, asym: 3, file: 4, system: 5, net: 6, keychain: 7, other: 8 } as const;
export const CRYPTO_CATS = '0,1,2,3';
export const SYSTEM_CATS = '4,5';

export interface EventsReply {
  ok?: boolean; events?: DhEvent[];
  hasMore?: number; hasOlder?: number;
  latestSeq?: number; oldestSeq?: number; next?: number;
  summary?: { lastSeq?: number; count?: number; updatedAtMs?: number; bundleId?: string; byCategory?: number[] };
  error?: string;
}

export interface DhDevice {
  id: string; address: string; kind: string; transport?: string | null;
  online: boolean | null; selected: boolean;
}
export interface DevicesReply { devices?: DhDevice[]; usb?: unknown[]; selected?: string }

export interface DhApp {
  bundleId: string; name?: string; execName?: string;
  kind?: string; running?: boolean;
}
/** /api/apps 的 recorded[]：idhjd 侧已记录过事件的 App 清单（服务端只返回 total>0 的，
 *  并按 updated_ms DESC 排序），含当前是否有活进程。 */
export interface DhRecordedApp {
  bundleId: string;
  /** idhjd 用 int 装箱（@(live != nil) → numberWithInt），JSON 化成 1/0；
   *  apps[] 的 running 是 BOOL 装箱，JSON 化成 true/false。两种都要认。 */
  running?: boolean | number;
  // 以下字段对应真实 payload，前端目前只消费 bundleId/running。
  pid?: number; count?: number; lastSeq?: number; updatedAtMs?: number;
  byCategory?: number[]; processGeneration?: string; httpPort?: number;
}
export interface AppsReply {
  ok?: boolean; scope?: string[]; apps?: DhApp[]; recorded?: DhRecordedApp[]; error?: string;
}
/** running 归一：recorded[] 里是 1/0，apps[] 里是 true/false。 */
export const isRunning = (v: unknown): boolean => v === true || v === 1 || v === 'true' || v === '1';

export interface FsEntry { name: string; type: string; size?: number; mtime?: number }
export interface FsListReply { path?: string; parent?: string | null; entries?: FsEntry[]; limited?: boolean; error?: string }
export interface FsPreviewReply { ok?: boolean; text?: string; hex?: string; size?: number; truncated?: boolean; binary?: boolean; error?: string }

export interface DumpStatus {
  state?: string; stage?: string; progress?: number; mode?: string;
  binReady?: boolean; ipaReady?: boolean; binName?: string; ipaName?: string; error?: string;
}

// ---- 耗时统计（保留 ADH 工艺）----
export interface PerfSample { last: number; total: number; peak: number; n: number }
const perf = new Map<string, PerfSample>();
export function perfStats() { return perf; }
export function perfMs(label: string) { return perf.get(label)?.last ?? 0; }
export function perfReport() {
  return [...perf.entries()]
    .sort((a, b) => b[1].total - a[1].total)
    .map(([k, s]) => `${k}  last=${Math.round(s.last)}ms avg=${Math.round(s.total / s.n)}ms peak=${Math.round(s.peak)}ms n=${s.n}`);
}
if (typeof window !== 'undefined') (window as unknown as { perfReport: typeof perfReport }).perfReport = perfReport;
function notePerf(label: string, ms: number) {
  const s = perf.get(label) ?? { last: 0, total: 0, peak: 0, n: 0 };
  s.last = ms; s.total += ms; s.peak = Math.max(s.peak, ms); s.n++;
  perf.set(label, s);
}

export async function api<T = unknown>(path: string, init?: RequestInit, timeoutMs = 8000): Promise<T> {
  const label = `${init?.method ?? 'GET'} ${path.split('?')[0]}`;
  const t0 = performance.now();
  try {
    const res = await fetch(path, { ...init, signal: AbortSignal.timeout(timeoutMs), cache: 'no-store' });
    const ms = performance.now() - t0;
    notePerf(label, ms);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    return (await res.json()) as T;
  } catch (e) {
    notePerf(label, performance.now() - t0);
    throw e;
  }
}
const post = <T = unknown>(path: string, body: unknown) =>
  api<T>(path, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(body) });

// ---- 设备 ----
export const getDevices = () => api<DevicesReply>('/api/devices');
export const selectDevice = (id: string) => post<DevicesReply>('/api/devices', { action: 'select', id });
export const addDevice = (address: string) => post<DevicesReply>('/api/devices', { action: 'add', address });
export const addUsbDevice = (udid: string) => post<DevicesReply>('/api/devices', { action: 'add', usb: udid });

// ---- 应用与注入范围（作用于当前选中设备）----
export const getApps = () => api<AppsReply>('/api/apps');
export const getScope = () => api<{ ok?: boolean; scope?: string[] }>('/api/injection-scope');
export const scopeAdd = (bundle: string) => post('/api/injection-scope', { add: [bundle], remove: [] });
export const scopeRemove = (bundle: string) => post('/api/injection-scope', { add: [], remove: [bundle] });
export const relaunchApp = (bundle: string) => post<{ ok?: boolean; relaunched?: boolean; error?: string }>('/api/apps/relaunch', { bundleId: bundle });
export const clearAppEvents = (bundle: string) => post<{ ok?: boolean; error?: string }>('/api/apps/clear', { bundleId: bundle });
export const appIconUrl = (bundle: string) => `/api/apps/${encodeURIComponent(bundle)}/icon`;

// ---- 事件 ----
export interface EventsQuery {
  categories?: string;   // 逗号分隔数字，如 '0,1,2,3'
  limit?: number;
  after?: number;        // 增量：取 seq > after
  before?: number;       // 分页：取 seq < before（向过去翻页）
}
export function getEvents(bundle: string, q: EventsQuery = {}) {
  const p = new URLSearchParams();
  if (q.categories) p.set('categories', q.categories);
  // idhjd 单页硬上限 200，超限直接 4xx/502；更大的分页靠 before 游标
  if (q.limit != null) p.set('limit', String(Math.min(q.limit, 200)));
  if (q.after != null) p.set('after', String(q.after));
  if (q.before != null) p.set('before', String(q.before));
  return api<EventsReply>(`/api/apps/${encodeURIComponent(bundle)}/events?${p.toString()}`);
}

// ---- 进程工具（经 idhjd 代理到进程内 agent）----
const tools = (bundle: string, path: string) => `/api/apps/${encodeURIComponent(bundle)}/tools/${path}`;
export const fsList = (bundle: string, path: string) =>
  api<FsListReply>(`${tools(bundle, 'files')}?path=${encodeURIComponent(path)}`);
export const fsPreview = (bundle: string, path: string) =>
  api<FsPreviewReply>(`${tools(bundle, 'files/preview')}?path=${encodeURIComponent(path)}`);
export const fsDownloadUrl = (bundle: string, path: string) =>
  `${tools(bundle, 'files/download')}?path=${encodeURIComponent(path)}`;

export interface SymbolsImage { idx?: number; main?: boolean; name?: string; imports?: number }
export interface DumpImage { name?: string; kind?: string; size?: number; cryptid?: number; encrypted?: boolean }
export const getImages = (bundle: string) =>
  api<{ images?: SymbolsImage[]; error?: string }>(tools(bundle, 'symbols/images'));
export const getDumpImages = (bundle: string) =>
  api<{ images?: DumpImage[]; total?: number; encryptedCount?: number; error?: string }>(tools(bundle, 'dump/images'));
export const searchSymbols = (bundle: string, q: string, image?: string) => {
  const p = new URLSearchParams({ q });
  if (image) p.set('image', image);
  return api<{ symbols?: Array<{ name?: string; address?: string; image?: string }>; error?: string }>(
    `${tools(bundle, 'symbols')}?${p.toString()}`);
};

export const getDumpStatus = (bundle: string) => api<DumpStatus>(tools(bundle, 'dump/status'));
export const startDump = (bundle: string, mode: 'bin' | 'ipa') =>
  post<{ started?: boolean; error?: string }>(`${tools(bundle, 'dump')}?mode=${mode}`, {});
export const dumpDownloadUrl = (bundle: string, kind: 'bin' | 'ipa') =>
  `${tools(bundle, 'dump/download')}?kind=${kind}`;
export const dumpImageUrl = (bundle: string, name: string) =>
  `${tools(bundle, 'dump/image')}?name=${encodeURIComponent(name)}`;
