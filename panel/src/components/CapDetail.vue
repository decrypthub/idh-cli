<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import type { DhEvent } from '../api';
import { catClass, cryptoView, CATLABEL } from '../capview';
import { toast } from '../store';
import { CopyOutline } from '@vicons/ionicons5';

const props = defineProps<{ detail: DhEvent }>();
const c = computed(() => props.detail);
type FmtMode = 'auto' | 'utf8' | 'hex' | 'b64' | 'hexdump';
const FMTS: [FmtMode, string][] = [['auto', '自动'], ['utf8', 'UTF-8'], ['hex', 'Hex'], ['b64', 'Base64'], ['hexdump', 'Hexdump']];
const ioTab = ref<'in' | 'out'>('in');
const fmtIn = ref<FmtMode>('auto');
const fmtOut = ref<FmtMode>('auto');
const infoOpen = ref(false);

function hexToBytes(h: string): Uint8Array {
  const clean = h.length % 2 === 0 ? h : h.slice(0, -1);
  const out = new Uint8Array(clean.length / 2);
  for (let i = 0; i < out.length; i++) out[i] = parseInt(clean.slice(i * 2, i * 2 + 2), 16);
  return out;
}

function hexToBase64(h: string): string {
  if (!h) return '';
  const b = hexToBytes(h);
  let bin = '';
  for (let i = 0; i < b.length; i++) bin += String.fromCharCode(b[i]);
  return btoa(bin);
}

function tryUtf8(h?: string): { text: string; readable: boolean } {
  if (!h) return { text: '', readable: false };
  try {
    const bytes = hexToBytes(h);
    const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    let ctrl = 0;
    for (let i = 0; i < text.length; i++) {
      const code = text.charCodeAt(i);
      if (code < 32 && code !== 9 && code !== 10 && code !== 13) ctrl++;
    }
    return { text, readable: text.length > 0 && ctrl / text.length < 0.05 };
  } catch {
    return { text: '', readable: false };
  }
}

function hexdump(hexStr: string): string {
  let out = '';
  for (let i = 0; i < hexStr.length; i += 32) {
    const row = hexStr.slice(i, i + 32);
    const off = (i / 2).toString(16).padStart(8, '0');
    let hp = '', ascii = '';
    for (let j = 0; j < row.length; j += 2) {
      const b = parseInt(row.slice(j, j + 2), 16);
      hp += row.slice(j, j + 2) + ' ';
      if (j / 2 === 7) hp += ' ';
      ascii += b >= 0x20 && b < 0x7f ? String.fromCharCode(b) : '.';
    }
    out += `${off}: ${hp.padEnd(50)} |${ascii}|\n`;
  }
  return out;
}

function resolveMode(mode: FmtMode, rawHex?: string): Exclude<FmtMode, 'auto'> {
  if (mode !== 'auto') return mode;
  return tryUtf8(rawHex).readable ? 'utf8' : 'hexdump';
}

function formatBlock(mode: FmtMode, rawHex?: string, fallbackText?: string): { display: string; copyVal: string; mono: boolean } {
  if (!rawHex) {
    const t = fallbackText || '';
    return { display: t || '（未捕获字节）', copyVal: t, mono: false };
  }
  const m = resolveMode(mode, rawHex);
  if (m === 'hex') return { display: rawHex, copyVal: rawHex, mono: true };
  if (m === 'b64') {
    const b = hexToBase64(rawHex);
    return { display: b, copyVal: b, mono: true };
  }
  if (m === 'utf8') {
    const u = tryUtf8(rawHex);
    if (u.text) return { display: u.text, copyVal: u.text, mono: false };
    const lossy = new TextDecoder('utf-8', { fatal: false }).decode(hexToBytes(rawHex));
    return { display: lossy, copyVal: lossy, mono: false };
  }
  const u = tryUtf8(rawHex);
  return { display: hexdump(rawHex), copyVal: u.readable ? u.text : rawHex, mono: true };
}

function formatKey(mode: FmtMode, rawHex: string): { display: string; copyVal: string } {
  if (mode === 'b64') {
    const b = hexToBase64(rawHex);
    return { display: b, copyVal: b };
  }
  if (mode === 'utf8') {
    const u = tryUtf8(rawHex);
    if (u.readable) return { display: u.text, copyVal: u.text };
  }
  if (mode === 'hex') return { display: rawHex, copyVal: rawHex };
  return { display: hexdump(rawHex), copyVal: rawHex };
}

const isCrypto = computed(() => c.value.category <= 3);
const isNet = computed(() => c.value.category === 6);
const isFileLike = computed(() => c.value.category === 4 || c.value.category === 5);
const isKeychain = computed(() => c.value.category === 7);
const cv = computed(() => (isCrypto.value ? cryptoView(c.value) : null));

const inLabel = computed(() => (isNet.value ? (/write|send/i.test(String(c.value.operation || '')) ? '发送' : '接收') : '输入'));
const outLabel = computed(() => (isNet.value ? '响应' : '输出'));
// 数据块语义标签：明文/密文/摘要/MAC/签名值 必须一眼分清，不笼统叫输入输出
const inDataLabel = computed(() => {
  if (!isCrypto.value) return inLabel.value;
  const d = cv.value?.direction;
  if (d === '加密') return '明文';
  if (d === '解密') return '密文';
  if (d === '签名') return '待签数据';
  if (d === '验签') return '待验数据';
  return '输入数据';
});
const outDataLabel = computed(() => {
  if (!isCrypto.value) return outLabel.value;
  const d = cv.value?.direction;
  if (d === '加密') return '密文';
  if (d === '解密') return '明文';
  if (d === '哈希') return '摘要';
  if (d === '认证') return 'MAC';
  if (d === '签名' || d === '验签') return '签名值';
  return '输出数据';
});
const hasDetailText = computed(() => !isCrypto.value && !!(c.value.detail || c.value.preview));
const hasInBlock = computed(() => !!(c.value.inputHex || (c.value.inLen ?? 0) > 0));
const hasInput = computed(() => hasDetailText.value || hasInBlock.value || !!c.value.keyHex || !!c.value.ivHex);
const hasOutput = computed(() => !!(c.value.outputHex || (c.value.outLen ?? 0) > 0));
const curHasData = computed(() => (ioTab.value === 'in' ? hasInput.value : hasOutput.value));
const activeFmt = computed(() => (ioTab.value === 'in' ? fmtIn.value : fmtOut.value));
function setFmt(k: FmtMode) { if (ioTab.value === 'in') fmtIn.value = k; else fmtOut.value = k; }
const bytes = (n?: number) => (n == null ? '未记录' : `${n} B`);
const outBytes = computed(() => c.value.outLen ?? (c.value.outputHex ? c.value.outputHex.length / 2 : undefined));
const inBytes = computed(() => c.value.inLen ?? (c.value.inputHex ? c.value.inputHex.length / 2 : undefined));
// agent 上报的 hex 封顶 256B（key 64B / iv 32B）；真实长度大于 hex 长度即被截断，如实标注
const inTruncated = computed(() => !!c.value.inputHex && (c.value.inLen ?? 0) > c.value.inputHex.length / 2);
const outTruncated = computed(() => !!c.value.outputHex && (c.value.outLen ?? 0) > c.value.outputHex.length / 2);

watch(() => c.value.seq, () => {
  infoOpen.value = false;
  ioTab.value = hasInput.value ? 'in' : 'out';
});

function copy(text: string) {
  void navigator.clipboard?.writeText(text).then(() => toast('已复制'), () => toast('复制失败'));
}
function onMenuSelect(key: string) {
  if (key === 'info') infoOpen.value = !infoOpen.value;
}
</script>

<template>
  <div class="detail-anim" :key="String(c.seq)">
    <div class="detail-head">
      <div class="detail-head-main">
        <h2>
          <span class="cat-dot" :class="catClass(c)"></span>
          <template v-if="isCrypto">{{ cv?.title }}<template v-if="cv?.direction"> · {{ cv.direction }}</template></template>
          <template v-else>#{{ c.seq }} {{ c.algorithm || c.operation }}</template>
        </h2>
        <div class="sub">
          {{ [c.operation, new Date(c.timeMs).toLocaleString(), inTruncated || outTruncated ? '字节已截断' : ''].filter(Boolean).join(' · ') }}
        </div>
      </div>
      <div class="detail-menu">
        <n-dropdown trigger="click" :options="[{ label: '事件信息', key: 'info' }]" @select="onMenuSelect">
          <n-button quaternary size="small" class="menu-btn" title="记录操作">⋯</n-button>
        </n-dropdown>
      </div>
    </div>

    <div v-if="infoOpen" class="capture-overview">
      <h3>事件信息</h3>
      <dl class="capture-facts">
        <div><dt>事件编号</dt><dd>#{{ c.seq ?? '未记录' }}</dd></div>
        <div><dt>类别</dt><dd>{{ CATLABEL[catClass(c)] }}</dd></div>
        <div><dt>输入大小</dt><dd>{{ bytes(c.inLen) }}</dd></div>
        <div><dt>输出大小</dt><dd>{{ bytes(c.outLen) }}</dd></div>
        <div><dt>时间</dt><dd>{{ new Date(c.timeMs).toLocaleString() }}</dd></div>
        <div v-if="c.phase"><dt>阶段</dt><dd>{{ c.phase }}</dd></div>
        <div v-if="c.callId"><dt>调用</dt><dd class="mono">{{ c.callId }}</dd></div>
        <div v-if="c.parentCallId"><dt>父调用</dt><dd class="mono">{{ c.parentCallId }}</dd></div>
        <div v-if="c.publicKeyInfo"><dt>公钥信息</dt><dd>{{ c.publicKeyInfo }}</dd></div>
      </dl>
    </div>

    <div class="io-toolbar">
      <n-radio-group v-model:value="ioTab" size="small">
        <n-radio-button value="in">{{ inLabel }}<span v-if="c.inLen != null" class="seg-meta"> {{ bytes(inBytes) }}</span></n-radio-button>
        <n-radio-button value="out">{{ outLabel }}<span v-if="hasOutput" class="seg-meta"> {{ bytes(outBytes) }}</span></n-radio-button>
      </n-radio-group>
      <n-radio-group v-if="curHasData" :value="activeFmt" size="small" @update:value="setFmt">
        <n-radio-button v-for="[k, lbl] in FMTS" :key="k" :value="k">{{ lbl }}</n-radio-button>
      </n-radio-group>
    </div>

    <div v-if="ioTab === 'in'" class="io-panel">
      <template v-if="hasDetailText">
        <div class="io-field">
          <div class="io-field-label">详情</div>
          <div class="io-data">
            <pre>{{ [c.operation, c.detail].filter(Boolean).join('\n') || c.preview }}</pre>
            <button type="button" class="blk-copy" title="复制"
              @click="copy([c.operation, c.detail].filter(Boolean).join('\n') || c.preview || '')"><n-icon size="16" :component="CopyOutline" /></button>
          </div>
        </div>
      </template>

      <template v-if="c.keyHex">
        <div class="io-field">
          <div class="io-field-label">KEY · {{ c.keyLen ?? c.keyHex.length / 2 }}B{{ (c.keyLen ?? 0) > c.keyHex.length / 2 ? '（截断）' : '' }}</div>
          <div class="io-data">
            <pre class="mono">{{ formatKey(fmtIn, c.keyHex).display }}</pre>
            <button type="button" class="blk-copy" title="复制" @click="copy(formatKey(fmtIn, c.keyHex).copyVal)"><n-icon size="16" :component="CopyOutline" /></button>
          </div>
        </div>
      </template>
      <template v-if="c.ivHex">
        <div class="io-field">
          <div class="io-field-label">IV · {{ c.ivLen ?? c.ivHex.length / 2 }}B{{ (c.ivLen ?? 0) > c.ivHex.length / 2 ? '（截断）' : '' }}</div>
          <div class="io-data">
            <pre class="mono">{{ formatKey(fmtIn, c.ivHex).display }}</pre>
            <button type="button" class="blk-copy" title="复制" @click="copy(formatKey(fmtIn, c.ivHex).copyVal)"><n-icon size="16" :component="CopyOutline" /></button>
          </div>
        </div>
      </template>

      <template v-if="hasInBlock">
        <div class="io-field">
          <div class="io-field-label">{{ inDataLabel }} · {{ bytes(inBytes) }}{{ inTruncated ? '（ hex 截断至 256B）' : '' }}</div>
          <div class="io-data main">
            <pre :class="{ mono: formatBlock(fmtIn, c.inputHex, c.preview).mono }">{{ formatBlock(fmtIn, c.inputHex, c.preview).display }}</pre>
            <button type="button" class="blk-copy" title="复制内容"
              @click="copy(formatBlock(fmtIn, c.inputHex, c.preview).copyVal)"><n-icon size="16" :component="CopyOutline" /></button>
          </div>
        </div>
      </template>
      <div v-if="!hasInput" class="detail-empty">这条记录没有输入数据。</div>
    </div>

    <div v-else class="io-panel">
      <template v-if="hasOutput">
        <div class="io-field">
          <div class="io-field-label">{{ outDataLabel }} · {{ bytes(outBytes) }}{{ outTruncated ? '（hex 截断至 256B）' : '' }}</div>
          <div class="io-data main">
            <pre :class="{ mono: formatBlock(fmtOut, c.outputHex).mono }">{{ formatBlock(fmtOut, c.outputHex).display }}</pre>
            <button type="button" class="blk-copy" title="复制内容"
              @click="copy(formatBlock(fmtOut, c.outputHex).copyVal)"><n-icon size="16" :component="CopyOutline" /></button>
          </div>
        </div>
      </template>
      <div v-else class="detail-empty">这条记录没有输出数据。</div>
    </div>
  </div>
</template>

<style scoped>
.detail-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}
.detail-head-main { min-width: 0; }
.detail-menu { position: relative; flex: none; }

/* 记录切换入场：按 c.seq 重建元素触发 */
.detail-anim { animation: detail-in .14s ease-out; }
@keyframes detail-in { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }

.io-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  flex-wrap: wrap;
  margin: 14px 0 10px;
}
.seg-meta { opacity: 0.6; font-weight: 400; font-size: 11px; }

.io-panel { display: flex; flex-direction: column; gap: 12px; }
.io-field-label {
  font-size: 11px;
  letter-spacing: 0.04em;
  opacity: 0.55;
  margin-bottom: 4px;
}
.io-data {
  position: relative;
  border: 1px solid var(--border, rgba(128, 128, 128, 0.22));
  border-radius: 8px;
  background: rgba(128, 128, 128, 0.05);
}
.io-data pre {
  margin: 0;
  padding: 10px 12px;
  font-size: 12px;
  line-height: 1.55;
  white-space: pre-wrap;
  word-break: break-all;
  max-height: 46vh;
  overflow: auto;
}
.io-data pre.mono { font-family: ui-monospace, Consolas, 'Cascadia Mono', monospace; }
.blk-copy {
  position: absolute; top: 6px; right: 6px;
  width: 30px; height: 28px;
  border: 0; border-radius: 6px;
  background: transparent; color: inherit;
  cursor: pointer; opacity: 0;
  display: flex; align-items: center; justify-content: center;
}
.io-data:hover .blk-copy { opacity: 0.65; }
.blk-copy:hover { opacity: 1 !important; background: rgba(128, 128, 128, 0.18); }
.blk-copy .n-icon { display: flex; align-items: center; }
</style>
