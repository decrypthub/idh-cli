<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { store, copyText, downloadText, downloadBlob, toast } from '../store';
import { I } from '../icons';
import {
  getCategory, getPhase, titleFor, operationLabel, sizeLabel, longTime, fmt,
  KIND_LABELS, SESSION_STATUS, cleanEvent, type EventItem,
} from '../model';

const TABS: Array<['data' | 'context' | 'raw', string]> = [['data', '数据详情'], ['context', '关联信息'], ['raw', '摘要 JSON']];
const byteFormats: Array<[string, string]> = [['bytes', '原始字节'], ['hex', '十六进制'], ['base64', 'Base64']];
const LIMIT = 64 * 1024;

const event = computed<EventItem | null>(() =>
  store.seq === null ? null : store.events.find(e => e.seq === store.seq) ?? null);

const kv = (rows: Array<[string, unknown]>) => rows;
const sourceRows = computed<[string, unknown][]>(() => [
  ['来源 App', store.session?.bundleId], ['会话 ID', store.session?.sessionId],
  ['会话状态', store.session?.status ? SESSION_STATUS[store.session.status] : undefined]]);
// 数据详情页的事件信息：算法/操作/输入输出 + 通用字段，一行一项
const eventRows = computed<[string, unknown][]>(() => {
  const e = event.value;
  if (!e) return [];
  const rows: Array<[string, unknown]> = [
    ['算法', e.algorithm], ['操作', operationLabel(e.operation)],
    ['输入大小', e.inLen != null ? e.inLen + ' B' : undefined],
    ['输出大小', e.outLen != null ? e.outLen + ' B' : undefined],
    ['详情', e.detail],
    ['会话序号', e.seq], ['原记录序号', e.sourceSeq], ['事件类别', getCategory(e.category)],
    ['事件类型', KIND_LABELS[e.kind ?? ''] ?? e.kind], ['事件阶段', getPhase(e.phase)],
    ['记录更新', e.update ? '是' : '否'],
  ];
  return rows.filter(([, v]) => v !== undefined && v !== '');
});
const contextRows = computed<[string, unknown][]>(() => {
  const e = event.value;
  return e ? [['关联 ID', e.callId], ['上级关联', e.parentCallId], ['异步任务', e.asyncTaskId]] : [];
});

// ---- 输入/输出摘要内容（设备会话摘要携带的有界前缀字节与文本预览）----
const hasIO = computed(() => {
  const e = event.value;
  return !!(e && (e.inLen != null || e.outLen != null || e.inputHex || e.outputHex || e.preview));
});
const spacedHex = (h?: string) => (h ?? '').replace(/(..)/g, '$1 ').trim();
/** hex 长度(字符)/2 < 真实字节数 → 摘要只带前缀 */
const inTrunc = computed(() => {
  const e = event.value;
  return !!(e?.inputHex && e.inLen != null && e.inputHex.length / 2 < e.inLen);
});
const outTrunc = computed(() => {
  const e = event.value;
  return !!(e?.outputHex && e.outLen != null && e.outputHex.length / 2 < e.outLen);
});

// ---- 本地字节预览（不关联设备数据，明确标注来源）----
interface LocalBin { name: string; bytes: Uint8Array; mode: string }
const bin = ref<LocalBin | null>(null);
const binMsg = ref('');
const binErr = ref(false);
const fileEl = ref<HTMLInputElement | null>(null);
watch(event, () => { bin.value = null; binMsg.value = ''; binErr.value = false; });

async function chooseFile(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0];
  (ev.target as HTMLInputElement).value = '';
  if (!file) return;
  if (file.size > LIMIT) { bin.value = null; binMsg.value = '文件超过 64 KiB，未载入也没有截取。'; binErr.value = true; return; }
  try {
    bin.value = { name: file.name, bytes: new Uint8Array(await file.arrayBuffer()), mode: 'bytes' };
    binMsg.value = ''; binErr.value = false;
  } catch { bin.value = null; binMsg.value = '未能读取本地文件。'; binErr.value = true; }
}
function formatBytes(bytes: Uint8Array, mode: string): string {
  if (mode === 'base64') {
    let s = '';
    for (let i = 0; i < bytes.length; i += 8192) s += String.fromCharCode(...bytes.subarray(i, i + 8192));
    return btoa(s);
  }
  const lines: string[] = [];
  for (let i = 0; i < bytes.length; i += 16) {
    const block = bytes.subarray(i, i + 16);
    if (mode === 'hex') { lines.push([...block].map(n => n.toString(16).padStart(2, '0').toUpperCase()).join(' ')); continue; }
    const off = i.toString(16).toUpperCase().padStart(8, '0');
    const vals = [...block].map(n => String(n).padStart(3, '0')).join(' ').padEnd(63, ' ');
    const printable = [...block].map(n => (n >= 32 && n <= 126 ? String.fromCharCode(n) : '.')).join('');
    lines.push(off + '  ' + vals + '  |' + printable + '|');
  }
  return lines.join('\n');
}
const binText = computed(() => bin.value ? formatBytes(bin.value.bytes, bin.value.mode) : '');
const binNote = computed(() =>
  !bin.value ? '未载入本地字节。三个视图不会把事件摘要当成原始数据。'
    : bin.value.mode === 'bytes' ? '每个字节以 0–255 的十进制值显示；左侧是偏移，右侧仅预览可打印字符。'
      : bin.value.mode === 'hex' ? '每两个十六进制字符对应一个字节。'
        : '按当前完整原始字节编码，不改变顺序或内容。');
function copyBin() {
  if (!bin.value?.bytes.length) { toast('空文件，没有可复制的字节'); return; }
  void copyText(formatBytes(bin.value.bytes, bin.value.mode));
}
function exportBin() {
  if (!bin.value) return;
  downloadBlob('preview-' + (bin.value.name || 'bytes.bin'), new Blob([new Uint8Array(bin.value.bytes)], { type: 'application/octet-stream' }));
}
const json = (x: unknown) => JSON.stringify(x, null, 2);
</script>

<template>
  <div v-if="!event" class="empty-state">
    <div class="empty-icon"><svg viewBox="0 0 20 20" width="28" height="28" v-html="I.info" /></div>
    <strong>选择一条记录</strong><p>左侧为当前设备会话的事件，详情会显示在这里。</p>
  </div>
  <template v-else>
    <header class="detail-header">
      <div>
        <div class="detail-title-row"><h2>{{ titleFor(event) }}</h2><span class="pill phase">{{ getPhase(event.phase) }}</span></div>
        <div class="detail-subtitle"><span class="mono">#{{ event.seq }}</span><span>{{ fmt(longTime, event.timeMs) }}</span><span v-if="sizeLabel(event)" class="mono">{{ sizeLabel(event) }}</span><span>{{ store.session?.bundleId }}</span></div>
      </div>
      <div class="detail-actions">
        <button class="btn sm" type="button" @click="copyText(json(cleanEvent(event)))">
          <svg class="ico sm" viewBox="0 0 20 20" v-html="I.copy" />复制摘要</button>
        <button class="btn sm icon-only" type="button" aria-label="下载摘要 JSON" title="下载摘要 JSON"
          @click="downloadText('event-' + event.seq + '.json', json(cleanEvent(event)))">
          <svg class="ico sm" viewBox="0 0 20 20" v-html="I.download" /></button>
      </div>
    </header>
    <nav class="detail-tabs" role="tablist" aria-label="事件详情方式">
      <button v-for="[key, label] in TABS" :key="key" class="detail-tab" type="button" role="tab"
        :aria-selected="store.detailTab === key" @click="store.detailTab = key">{{ label }}</button>
    </nav>
    <div class="detail-scroll"><div class="content-max">
      <!-- 数据详情 -->
      <template v-if="store.detailTab === 'data'">
        <template v-if="hasIO">
          <div class="io-panels">
            <section class="io-section in-card">
              <header class="io-card-head"><h3>输入 / INPUT</h3><span class="io-status mono">{{ event.inLen != null ? event.inLen + ' B' : '—' }}</span></header>
              <pre v-if="event.inputHex" class="io-hex mono">{{ spacedHex(event.inputHex) }}<span v-if="inTrunc" class="io-trunc">
… 前缀 32 B / 共 {{ event.inLen }} B</span></pre>
              <p v-if="event.preview" class="io-text">{{ event.preview }}</p>
              <p v-if="!event.inputHex && !event.preview" class="io-empty">该事件无输入数据</p>
            </section>
            <section class="io-section out-card">
              <header class="io-card-head"><h3>输出 / OUTPUT</h3><span class="io-status mono">{{ event.outLen != null ? event.outLen + ' B' : '—' }}</span></header>
              <pre v-if="event.outputHex" class="io-hex mono">{{ spacedHex(event.outputHex) }}<span v-if="outTrunc" class="io-trunc">
… 前缀 32 B / 共 {{ event.outLen }} B</span></pre>
              <p v-if="!event.outputHex" class="io-empty">该事件无输出数据</p>
            </section>
          </div>
        </template>
        <p v-else class="io-empty">该摘要不含输入输出内容（旧格式记录或事件本身无数据载荷）。</p>
        <section class="data-card"><header class="data-card-head">事件信息</header>
          <div v-for="[k, v] in kv(eventRows)" :key="k" class="kv-row"><span class="key">{{ k }}</span><span class="val mono">{{ v }}</span></div></section>
        <section class="byte-preview" aria-labelledby="bytePreviewHeading">
          <div class="byte-header"><div><h3 id="bytePreviewHeading">本地字节预览</h3><p class="byte-help">仅验证你选择的文件；不上传、不保存，也不归入这条设备事件。</p></div>
            <div class="hstack"><button class="btn sm" type="button" @click="fileEl?.click()">载入本地文件</button>
              <input ref="fileEl" type="file" hidden @change="chooseFile" />
              <button v-if="bin" class="btn sm ghost" type="button" @click="bin = null; binMsg = '本地预览已清除。'">清除</button></div></div>
          <div class="byte-options" role="group" aria-label="字节显示格式">
            <button v-for="[mode, label] in byteFormats" :key="mode" class="btn sm" type="button"
              :aria-pressed="bin?.mode === mode" :disabled="!bin" @click="bin && (bin.mode = mode)">{{ label }}</button>
            <button v-if="bin" class="btn sm ghost" type="button" @click="copyBin">复制当前格式</button>
            <button v-if="bin" class="btn sm ghost" type="button" @click="exportBin">下载原始字节</button>
          </div>
          <p v-if="binMsg" class="byte-note" :class="{ error: binErr }" role="status">{{ binMsg }}</p>
          <div v-if="bin" class="byte-receipt"><span>来源：本地文件</span><span class="mono">{{ bin.name }}</span><span class="mono">{{ bin.bytes.length }} B</span></div>
          <p class="byte-note">{{ binNote }}</p>
          <pre v-if="bin" tabindex="0" class="code-body byte-view" :data-format="bin.mode">{{ binText || '（0 字节）' }}</pre>
        </section>
      </template>
      <!-- 摘要 JSON -->
      <template v-else-if="store.detailTab === 'raw'">
        <h3 class="content-title">设备保存的事件摘要</h3>
        <pre class="code-body">{{ json(cleanEvent(event)) }}</pre>
      </template>
      <!-- 关联信息 -->
      <template v-else-if="store.detailTab === 'context'">
        <h3 class="content-title">关联与来源</h3>
        <div class="box-grid">
          <section class="data-card"><header class="data-card-head">关联信息</header>
            <div v-for="[k, v] in kv(contextRows)" :key="k" class="kv-row"><span class="key">{{ k }}</span><span class="val mono">{{ v ?? '—' }}</span></div></section>
          <section class="data-card"><header class="data-card-head">会话信息</header>
            <div v-for="[k, v] in kv(sourceRows)" :key="k" class="kv-row"><span class="key">{{ k }}</span><span class="val mono">{{ v ?? '—' }}</span></div></section>
        </div>
      </template>

    </div></div>
  </template>
</template>
