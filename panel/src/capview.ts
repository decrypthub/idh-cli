// 事件 → 视图模型。iOS 原生语义：category 数字是服务端真源，算法/操作直接用 agent 上报字符串。
import type { DhEvent } from './api';
import { panelDisplay } from './store';

export type CatKey = 'digest' | 'hmac' | 'sym' | 'asym' | 'file' | 'sys' | 'net' | 'keychain' | 'other';
export const CATLABEL: Record<CatKey, string> = {
  digest: '摘要', hmac: 'HMAC', sym: '对称', asym: '非对称',
  file: '文件读写', sys: '系统', net: '网络', keychain: 'Keychain', other: '其它',
};

// category 数字直接映射，不猜测。0 摘要 1 HMAC 2 对称 3 非对称 4 文件 5 系统 6 网络 7 Keychain 8 其他
const CAT_BY_INDEX: CatKey[] = ['digest', 'hmac', 'sym', 'asym', 'file', 'sys', 'net', 'keychain', 'other'];
export function catClass(e: DhEvent): CatKey {
  return CAT_BY_INDEX[e.category] ?? 'other';
}

export interface CryptoView {
  title: string; direction: string; hook: string; show: boolean;
  preview: string; hasKey: boolean; sizeLabel: string;
}

const DIRECTIONS: Array<[RegExp, string]> = [
  [/^(encrypt|seal)/i, '加密'], [/^(decrypt|open)/i, '解密'],
  [/^sign/i, '签名'], [/^verify/i, '验签'],
  [/^(digest|hash|final|update)/i, '哈希'],
  [/^(mac|hmac)/i, '认证'],
  [/^(derive|kdf)/i, '密钥派生'],
  [/^(wrap)/i, '密钥包装'], [/^(unwrap)/i, '密钥解包'],
  [/^(generate|random)/i, '随机数'],
];

function directionOf(op: string): string {
  for (const [re, label] of DIRECTIONS) if (re.test(op)) return label;
  return '';
}

// 加密事件展示：标题 = 算法名（原样），方向 = 由 operation 推导，hook = 原始 operation。
// 不做 Android 式的 API 名猜测；agent 上报什么就显示什么。
export function cryptoView(e: DhEvent): CryptoView {
  const algo = (e.algorithm || '').trim();
  const op = (e.operation || '').trim();
  const inl = e.inLen ?? 0;
  const outl = e.outLen ?? 0;
  return {
    title: algo || '未识别算法',
    direction: directionOf(op),
    hook: op,
    show: true,
    preview: (e.preview || e.detail || '').slice(0, 120),
    hasKey: !!(e.keyLen || e.keyHex),
    sizeLabel: inl || outl ? (outl ? `${inl} → ${outl}` : `${inl}`) : '',
  };
}

// 输入 → 输出长度（加解密行尾）；没有长度信息时留空
export function rowLens(e: DhEvent): string {
  const inl = e.inLen ?? 0;
  const outl = e.outLen ?? 0;
  if (!inl && !outl) return '';
  if (e.category <= 3) return outl ? `${inl} → ${outl}` : `${inl}`;
  return inl ? `${inl}` : '';
}

export function fmtTime(ms: number): string {
  if (!ms) return '';
  const d = new Date(ms);
  const p = (n: number, w = 2) => String(n).padStart(w, '0');
  const clock = `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${p(d.getMilliseconds(), 3)}`;
  if (panelDisplay.time === 'date') return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${clock}`;
  return clock;
}

export function fmtSize(n?: number): string {
  if (n == null) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
