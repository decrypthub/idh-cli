// 算法识别与显示筛选 —— iOS 原生。算法名是 agent 上报的干净字符串（AES/SHA256/HMAC-SHA256/RSA…），
// category 数字是服务端真源。hidden 键存 localStorage，按包隔离。

import type { DhEvent } from './api';

export const FAMILIES = Object.freeze({
  digest: '摘要', mac: '消息认证', symmetric: '对称加密', asymmetric: '非对称与签名',
  tls: '传输加密', kdf: '密钥派生', keychain: 'Keychain', other: '其他',
} as const);
export const HOOK_GROUPS = Object.freeze({ crypto: '加解密', system: '系统调用', file: '文件读写', net: '网络', keychain: 'Keychain' } as const);

type AlgoType = [family: string, name: string];

const RULES: Array<[string, string, RegExp]> = [
  ['mac', 'HMAC-SHA-3', /HMAC.?SHA3/],
  ['mac', 'HMAC-SHA-512', /HMAC.?SHA512/], ['mac', 'HMAC-SHA-384', /HMAC.?SHA384/],
  ['mac', 'HMAC-SHA-256', /HMAC.?SHA256/], ['mac', 'HMAC-SHA-224', /HMAC.?SHA224/],
  ['mac', 'HMAC-SHA-1', /HMAC.?SHA1/], ['mac', 'HMAC-MD5', /HMAC.?MD5/], ['mac', 'HMAC', /HMAC/],
  ['digest', 'SHA-3', /SHA3(?:224|256|384|512)?/],
  ['digest', 'SHA-512', /SHA512/], ['digest', 'SHA-384', /SHA384/], ['digest', 'SHA-256', /SHA256/],
  ['digest', 'SHA-224', /SHA224/], ['digest', 'SHA-1', /SHA1/], ['digest', 'MD5', /MD5/],
  ['symmetric', 'AES', /AES/], ['symmetric', 'ChaCha20', /CHACHA20/],
  ['symmetric', '3DES', /3DES|TRIPLEDES/], ['symmetric', 'DES', /^DES/],
  ['symmetric', 'CAST', /CAST/], ['symmetric', 'RC4', /RC4/], ['symmetric', 'RC2', /RC2/], ['symmetric', 'Blowfish', /BLOWFISH/],
  ['asymmetric', 'RSA', /RSA/], ['asymmetric', 'ECDSA', /ECDSA/], ['asymmetric', 'Ed25519', /ED25519/],
  ['asymmetric', 'EC', /^EC/], ['asymmetric', 'DSA', /DSA/],
  ['tls', 'TLS', /^(?:TLS|SSL)/],
  ['kdf', 'PBKDF2', /PBKDF2/], ['kdf', 'HKDF', /HKDF/],
];

function identify(record: DhEvent): AlgoType | undefined {
  if (record.category === 7) return ['keychain', 'SecItem'];
  if (record.category > 3) return undefined;
  const tag = (record.algorithm || '').slice(0, 96).replace(/[\s_/-]+/g, '').toUpperCase();
  if (!tag) return ['other', '未识别算法'];
  const match = RULES.find(([, , pattern]) => pattern.test(tag));
  return match ? [match[0], match[1]] : ['other', tag.slice(0, 32) || '未识别算法'];
}

const algorithmKeyFor = ([family, name]: AlgoType) => 'algo:' + family + ':' + name;
export function algorithmKey(record: DhEvent) {
  const type = identify(record);
  return type && algorithmKeyFor(type);
}

const CATEGORY_NAME: Record<number, keyof typeof HOOK_GROUPS> = {
  4: 'file', 5: 'system', 6: 'net', 7: 'keychain',
};
function groupOf(record: DhEvent): keyof typeof HOOK_GROUPS {
  if (record.category <= 3) return 'crypto';
  return CATEGORY_NAME[record.category] ?? 'system';
}

export interface HookIdentity { key: string; category: string; source: string; name: string }
function hookIdentity(record: DhEvent): HookIdentity | undefined {
  const category = groupOf(record);
  // iOS 事件的 hook 身份 = algorithm（钩子族），操作是 operation。
  const name = (record.algorithm || '').slice(0, 120);
  if (!name) return;
  return { key: JSON.stringify([category, name]), category, source: '', name };
}
export const hookKey = (record: DhEvent) => hookIdentity(record)?.key;
export const categoryKey = (category: string) =>
  Object.hasOwn(HOOK_GROUPS, category) ? JSON.stringify(['category', category]) : null;

export const recordVisible = (record: DhEvent, hidden: Set<string>) => {
  const ck = categoryKey(groupOf(record));
  if (ck && hidden.has(ck)) return false;
  const hk = hookKey(record);
  if (hk && hidden.has(hk)) return false;
  const ak = algorithmKey(record);
  return !(ak && hidden.has(ak));
};

const timeOf = (record: DhEvent) => Number.isFinite(record.timeMs) && record.timeMs > 0 ? record.timeMs : 0;

export interface AlgoEntry {
  key: string; family: string; name: string; count: number; shown: number; latest: number;
}
export function summarize(records: DhEvent[], hidden = new Set<string>()): AlgoEntry[] {
  const entries = new Map<string, AlgoEntry>();
  for (const record of records) {
    const type = identify(record);
    if (!type) continue;
    const [family, name] = type;
    const key = algorithmKeyFor(type);
    if (!entries.has(key)) entries.set(key, { key, family, name, count: 0, shown: 0, latest: 0 });
    const entry = entries.get(key)!;
    const hk = hookKey(record);
    const shown = !hidden.has(key) && !(hk && hidden.has(hk));
    entry.count++;
    if (shown) entry.shown++;
    entry.latest = Math.max(entry.latest, timeOf(record));
  }
  return [...entries.values()].sort((a, b) => b.latest - a.latest || b.count - a.count || a.name.localeCompare(b.name));
}

export interface HookEntry extends HookIdentity { count: number; latest: number }
export function summarizeHooks(records: DhEvent[]): HookEntry[] {
  const items = new Map<string, HookEntry>();
  for (const record of records) {
    const hook = hookIdentity(record);
    if (!hook) continue;
    const previous = items.get(hook.key);
    const ts = timeOf(record);
    items.set(hook.key, { ...hook, count: (previous?.count ?? 0) + 1, latest: Math.max(previous?.latest ?? 0, ts) });
  }
  return [...items.values()].sort((a, b) => a.name.localeCompare(b.name));
}
