// 面板 REST 层：全部走本机 idh 服务的 /api 中转，不直连设备。
import type { DeviceRow, DeviceSession, DeviceInfo, InstalledApp, EventItem } from './model';

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(path, init);
  const data = await r.json().catch(() => ({}));
  if (!r.ok) { (data as Record<string, unknown>).__status = r.status; }
  return data as T;
}
const post = (path: string, body: unknown) =>
  api<Record<string, unknown>>(path, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

export const getHealth = () => api<DeviceInfo>('/health');
export const getSessions = () => api<{ sessions?: DeviceSession[] }>('/api/sessions');
export const getApps = () => api<{ apps?: InstalledApp[]; scope?: string[]; error?: string }>('/api/apps');
export interface EventPage {
  events?: EventItem[]; hasMore?: boolean; hasOlder?: boolean;
  oldestSeq?: number; latestSeq?: number;
  summary?: { count?: number; lastSeq?: number; byCategory?: number[] };
}
export const getAppEvents = (bundleId: string, opts: { after?: number; before?: number; limit?: number } = {}) => {
  const q = new URLSearchParams({ limit: String(opts.limit ?? 150) });
  if (opts.after != null) q.set('after', String(opts.after));
  if (opts.before != null) q.set('before', String(opts.before));
  return api<EventPage>(`/api/apps/${encodeURIComponent(bundleId)}/events?${q}`);
};
export const clearAppEvents = (bundleId: string) =>
  api<{ ok?: boolean; error?: string }>('/api/apps/clear', {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ bundleId }),
  });
export const appIconUrl = (bundleId: string) => `/api/apps/${encodeURIComponent(bundleId)}/icon`;
export const getDevices = () => api<{ devices?: DeviceRow[]; usb?: string[] }>('/api/devices');
export const deviceAction = (body: Record<string, unknown>) => post('/api/devices', body);
export const getScope = () => api<{ scope?: string[]; error?: string }>('/api/injection-scope');
export const scopeUpdate = (bundleId: string, on: boolean) =>
  api<{ scope?: string[]; error?: string }>('/api/injection-scope',
    { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ [on ? 'add' : 'remove']: [bundleId] }) });
export const relaunchApp = (bundleId: string) => post('/api/apps/relaunch', { bundleId });

// 进程工具接口：本机面板中转 /api/apps/<bundle>/tools/...，设备 idhjd 再代理到在线进程。
const toolPath = (bundleId: string, path: string) =>
  `/api/apps/${encodeURIComponent(bundleId)}/tools/${path}`;

export interface FileEntry { name: string; type: 'dir' | 'file'; size?: number; mtime?: number }
export interface FileList { path?: string; parent?: string | null; entries?: FileEntry[]; error?: string }
export interface FilePreview { path?: string; size?: number; truncated?: boolean; format?: 'text' | 'hex'; text?: string; error?: string }
export const listFiles = (bundleId: string, path = '') =>
  api<FileList>(`${toolPath(bundleId, 'files')}?path=${encodeURIComponent(path)}`);
export const readFilePreview = (bundleId: string, path: string) =>
  api<FilePreview>(`${toolPath(bundleId, 'files/preview')}?path=${encodeURIComponent(path)}&limit=65536`);
export const fileDownloadUrl = (bundleId: string, path: string) =>
  `${toolPath(bundleId, 'files/download')}?path=${encodeURIComponent(path)}`;

export interface SymbolImage { idx: number; name: string; main?: boolean; imports?: number }
export interface SymbolImages { images?: SymbolImage[]; error?: string }
export interface SymbolRows { idx?: number; name?: string; total?: number; shown?: number; symbols?: string[]; error?: string }
export const listSymbolImages = (bundleId: string) => api<SymbolImages>(toolPath(bundleId, 'symbols/images'));
export const listSymbols = (bundleId: string, img: number, q = '', limit = 300) =>
  api<SymbolRows>(`${toolPath(bundleId, 'symbols')}?img=${img}&q=${encodeURIComponent(q)}&limit=${limit}`);

export interface DumpImage { name: string; kind?: string; cryptid?: number; encrypted?: boolean; size?: number }
export interface DumpImages { images?: DumpImage[]; encryptedCount?: number; total?: number; error?: string }
export interface DumpStatus {
  state?: 'idle' | 'running' | 'done' | 'error'; mode?: string; progress?: number; stage?: string;
  error?: string; binReady?: boolean; ipaReady?: boolean; binName?: string; ipaName?: string;
}
export const getDumpImages = (bundleId: string) => api<DumpImages>(toolPath(bundleId, 'dump/images'));
export const getDumpStatus = (bundleId: string) => api<DumpStatus>(toolPath(bundleId, 'dump/status'));
export const startDump = (bundleId: string, mode: 'bin' | 'ipa') =>
  api<{ started?: boolean; error?: string }>(`${toolPath(bundleId, 'dump')}?mode=${mode}`, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}',
  });
export const dumpDownloadUrl = (bundleId: string, kind: 'bin' | 'ipa') =>
  `${toolPath(bundleId, 'dump/download')}?kind=${kind}`;
export const dumpImageUrl = (bundleId: string, name: string) =>
  `${toolPath(bundleId, 'dump/image')}?name=${encodeURIComponent(name)}`;
// 会话设置走 /api/session-settings 中转；设备错误码在此翻成可读文案（沿用旧适配层）。
const SETTINGS_ERRORS: Record<string, string> = {
  settings_pairing_required: '设备设置暂不可用。',
  revision_conflict: '设备配置已被修改。请重新载入后再应用。',
  invalid_settings: '设备会话限额需要整数，支持 1–2000 条、512–2097152 字节和 1–300 秒。',
  settings_storage_error: '设备无法读取或保存设置。',
  settings_unavailable: '当前设备服务尚未提供设置接口。',
};
interface SettingsReply { revision?: string; deviceSession?: Record<string, unknown>; error?: string }
async function settingsRequest(body?: unknown): Promise<SettingsReply> {
  const r = await fetch('/api/session-settings', body === undefined ? {} : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({})) as { error?: string } & SettingsReply;
  if (!r.ok || data.error) {
    return { error: SETTINGS_ERRORS[data.error ?? ''] ?? '设备设置暂时无法读取或保存。' };
  }
  return data;
}
export const getSettingsExport = () => settingsRequest();
export const postSettingsImport = (body: { revision: string; deviceSession: Record<string, number> }) =>
  settingsRequest(body);
