// 从 panel-device.js 移植的领域模型：类别、阶段、面板偏好、设备限额、可移植配置。
export const CATEGORIES = ["digest", "hmac", "sym", "asym", "file", "sys", "net", "keychain", "other"] as const;
export const CATEGORY_LABELS = ["摘要", "HMAC", "对称", "非对称", "文件", "系统", "网络", "Keychain", "其他"];
export const SUMMARY_KINDS = CATEGORIES.map((key, i) => ({ key, label: CATEGORY_LABELS[i] }));

export const PHASES: Record<string, string> = { entry: "进入", leave: "返回", complete: "完成", aborted: "中止" };
export const KIND_LABELS: Record<string, string> = { crypto: "加解密", network: "网络", observation: "观测", function: "函数" };
export const SESSION_STATUS: Record<string, string> = { waiting: "等待 Agent", observing: "观察中", closing: "确认尾部", ended: "已结束" };

export interface DeviceSession { bundleId: string; sessionId: string; status: string; count: number; lastSeq: number; createdAtMs: number; pid?: number; processGeneration?: string }
export interface InstalledApp { bundleId: string; name: string; running?: boolean; kind?: string }
export interface DeviceApp extends InstalledApp { processGeneration?: string; pid?: number }
export interface DeviceInfo { service?: string; version?: string; apps: DeviceApp[]; [k: string]: unknown }
export interface EventItem {
  seq: number; appSeq?: number; sourceSeq?: number; timeMs: number; category: number; kind?: string;
  phase?: string; update?: boolean; callId?: string; parentCallId?: string; asyncTaskId?: string; [k: string]: unknown;
}
/** 归并后的应用条目：sessionId 复用为 bundleId，count 跨会话累计。 */
export interface AppRecord extends DeviceSession { sessions: number; name: string; running: boolean; kind: "record" }
export interface DeviceRow { id: string; address: string; transport?: string; online?: boolean; selected?: boolean }

export const getCategory = (n?: number) => CATEGORY_LABELS[n ?? -1] ?? "其他";
export const getPhase = (p?: string) => (p ? PHASES[p] ?? "摘要" : "摘要");
export const titleFor = (e: EventItem) => getCategory(e.category) + "事件";

export const DISPLAY_CHOICES = [100, 150, 300, 500];
export const LIMITS: Record<string, [number, number]> = {
  maxRecords: [1, 2000], maxBytes: [512, 2097152], recordSeconds: [1, 300],
};
export const LIMIT_FIELDS: Array<{ key: string; label: string; unit: string }> = [
  { key: "maxRecords", label: "单会话摘要条数", unit: "条" },
  { key: "maxBytes", label: "单会话摘要大小", unit: "字节" },
  { key: "recordSeconds", label: "单会话观察时长", unit: "秒" },
];

export interface PanelPrefs {
  displayCap: number; autoRefresh: boolean; advancedFilters: boolean;
  summaryCategories: Record<string, boolean>;
}
export type DeviceLimits = Record<string, number>;

const PREF_KEYS = ["displayCap", "autoRefresh", "advancedFilters", "summaryCategories"];

function checkFields(data: unknown, allowed: string[], name: string): asserts data is Record<string, unknown> {
  if (!data || typeof data !== "object" || Array.isArray(data)) throw new Error(name + " 必须是对象");
  if (Object.keys(data as object).some((k) => !allowed.includes(k))) throw new Error(name + " 含有不支持的字段");
}

export function defaults(): PanelPrefs {
  return {
    displayCap: 150, autoRefresh: true, advancedFilters: false,
    summaryCategories: Object.fromEntries(CATEGORIES.map((k) => [k, true])),
  };
}

export function deviceLimits(patch: Record<string, unknown>, requireAll = false): DeviceLimits {
  checkFields(patch, Object.keys(LIMITS), "deviceSession");
  if (requireAll && Object.keys(patch).length !== Object.keys(LIMITS).length)
    throw new Error("设备返回的会话配置不完整");
  for (const [field, value] of Object.entries(patch)) {
    const [min, max] = LIMITS[field];
    if (!Number.isInteger(value) || (value as number) < min || (value as number) > max)
      throw new Error(field + " 必须是 " + min + "–" + max + " 之间的整数");
  }
  return { ...patch } as DeviceLimits;
}

export function mergePanel(base: PanelPrefs, patch: Record<string, unknown>): PanelPrefs {
  checkFields(patch, PREF_KEYS, "panel");
  const next: PanelPrefs = {
    displayCap: base.displayCap, autoRefresh: base.autoRefresh,
    advancedFilters: base.advancedFilters, summaryCategories: { ...base.summaryCategories },
  };
  for (const key of ["autoRefresh", "advancedFilters"] as const) {
    if (!Object.hasOwn(patch, key)) continue;
    if (typeof patch[key] !== "boolean") throw new Error(key + " 必须是布尔值");
    next[key] = patch[key];
  }
  if (Object.hasOwn(patch, "displayCap")) {
    if (!DISPLAY_CHOICES.includes(patch.displayCap as number)) throw new Error("displayCap 只支持 100、150、300、500");
    next.displayCap = patch.displayCap as number;
  }
  if (Object.hasOwn(patch, "summaryCategories")) {
    const sc = patch.summaryCategories;
    checkFields(sc, [...CATEGORIES], "summaryCategories");
    for (const [key, value] of Object.entries(sc as Record<string, unknown>)) {
      if (typeof value !== "boolean") throw new Error(key + " 的摘要开关必须是布尔值");
      next.summaryCategories[key] = value;
    }
  }
  return next;
}

export interface ParsedProfile {
  deviceSession: DeviceLimits; hasDevice: boolean; hasPanel: boolean; panel: PanelPrefs;
}
export function parseProfile(data: unknown, panel: PanelPrefs): ParsedProfile {
  checkFields(data, ["version", "deviceSession", "panel"], "配置");
  const hasVersion = Object.hasOwn(data, "version");
  const hasDevice = Object.hasOwn(data, "deviceSession");
  const hasPanel = Object.hasOwn(data, "panel");
  if (hasVersion && data.version !== 1) throw new Error("不支持此配置版本");
  if ((!hasVersion && (!hasDevice || hasPanel)) || (!hasDevice && !hasPanel))
    throw new Error("配置应包含 deviceSession 或带版本号的 panel");
  const deviceSession = hasDevice ? deviceLimits(data.deviceSession as Record<string, unknown>) : {};
  if (hasDevice && !Object.keys(deviceSession).length) throw new Error("deviceSession 没有可应用的字段");
  return {
    deviceSession, hasDevice, hasPanel,
    panel: mergePanel(panel, hasPanel ? (data.panel as Record<string, unknown>) : {}),
  };
}
export function portableProfile(device: DeviceLimits, panel: PanelPrefs): string {
  return JSON.stringify({ version: 1, deviceSession: deviceLimits(device, true), panel: mergePanel(defaults(), panel as unknown as Record<string, unknown>) }, null, 2);
}

const FIELD_NAMES = ["seq", "sourceSeq", "timeMs", "category", "kind", "phase", "update", "callId", "parentCallId", "asyncTaskId"];
export const cleanEvent = (e: EventItem) =>
  Object.fromEntries(FIELD_NAMES.filter((k) => Object.hasOwn(e, k)).map((k) => [k, e[k]]));

export const fmt = (formatter: Intl.DateTimeFormat, ms?: number) =>
  Number.isFinite(ms) && (ms as number) > 0 && (ms as number) <= 8640000000000000 ? formatter.format(ms as number) : "—";
export const shortTime = new Intl.DateTimeFormat("zh-CN", { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
export const longTime = new Intl.DateTimeFormat("zh-CN", { dateStyle: "medium", timeStyle: "medium" });
