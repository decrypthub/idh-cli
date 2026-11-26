<script setup lang="ts">
import { computed, onMounted, ref, shallowRef, watch, type Component } from 'vue';
import {
  AlertCircleOutline,
  ArchiveOutline,
  ArrowUpOutline,
  ChevronDownOutline,
  ChevronUpOutline,
  CopyOutline,
  CubeOutline,
  DocumentOutline,
  DocumentTextOutline,
  DownloadOutline,
  FolderOpenOutline,
  FolderOutline,
  ImageOutline,
  KeyOutline,
  LinkOutline,
  RefreshOutline,
  SearchOutline,
} from '@vicons/ionicons5';
import { store, toast } from '../store';
import { fsList, fsPreview, fsDownloadUrl, type FsEntry, perfMs } from '../api';
import { fmtSize } from '../capview';

type SortKey = 'name' | 'size' | 'mtime';
type EntryKind = 'dir' | 'text' | 'image' | 'key' | 'db' | 'binary' | 'file';

interface Preview {
  name: string;
  fullPath?: string;
  text?: string;
  /** idhjd 直接给出预览形态：文本，或已经排好版的 hexdump。 */
  format?: 'text' | 'hex';
  size?: number;
  truncated?: boolean;
  message?: string;
  loading?: boolean;
  error?: boolean;
}

const path = ref('');
const pathInput = ref('');
const entries = ref<FsEntry[]>([]);
const limited = ref(false);
const state = ref<'idle' | 'loading' | 'ready' | 'error'>('idle');
const message = ref('');
const filter = ref('');
const sortKey = ref<SortKey>('name');
const sortDir = ref<1 | -1>(1);
const preview = shallowRef<Preview | null>(null);

let listSeq = 0;
const collator = new Intl.Collator('zh-CN', { numeric: true, sensitivity: 'base' });

const isDir = (e: FsEntry) => e.type === 'dir';

const parentPath = computed(() => {
  const p = path.value.replace(/\/+$/, '');
  if (!p || p === '/') return '';
  return p.replace(/\/[^/]+$/, '') || '/';
});

const filteredEntries = computed(() => {
  const q = filter.value.trim().toLowerCase();
  const list = (q ? entries.value.filter(e => e.name.toLowerCase().includes(q)) : entries.value).slice();
  return list.sort((a, b) => {
    const rank = (isDir(a) ? 0 : 1) - (isDir(b) ? 0 : 1);
    if (rank) return rank;
    let cmp = 0;
    if (sortKey.value === 'name') cmp = collator.compare(a.name, b.name);
    else if (sortKey.value === 'size') cmp = (a.size ?? 0) - (b.size ?? 0);
    else cmp = (a.mtime ?? 0) - (b.mtime ?? 0);
    return cmp * sortDir.value || collator.compare(a.name, b.name);
  });
});

const dirCount = computed(() => entries.value.filter(isDir).length);
const fileCount = computed(() => entries.value.length - dirCount.value);
const countText = computed(() => `${dirCount.value} 个目录 · ${fileCount.value} 个文件`);
const statText = computed(() => {
  // api() 的耗时标签就是 "GET <path>"，这里还原成列表请求的标签才能读到真实耗时
  const label = `GET /api/apps/${encodeURIComponent(store.chosenPkg)}/tools/files`;
  const ms = perfMs(label);
  if (state.value === 'loading') return '正在读取目录';
  if (state.value === 'error') return message.value;
  if (!store.chosenPkg) return '未选择应用';
  if (state.value === 'idle') return '等待读取';
  return `${countText.value} · ${Math.round(ms)}ms${limited.value ? ' · 已截断' : ''}`;
});

function joinPath(parent: string, name: string) {
  const base = parent.replace(/\/+$/, '');
  return `${base}/${name}` || '/';
}

function extension(name: string) {
  if (!name.includes('.')) return '';
  return name.split('.').pop()?.toLowerCase() ?? '';
}

function entryKind(e: FsEntry): EntryKind {
  if (isDir(e)) return 'dir';
  const ext = extension(e.name);
  if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'heic', 'svg'].includes(ext)) return 'image';
  if (['key', 'pem', 'crt', 'cer', 'der', 'p12', 'pfx', 'mobileprovision'].includes(ext)) return 'key';
  if (['db', 'sqlite', 'sqlite3', 'realm', 'plist', 'strings'].includes(ext)) return 'db';
  if (['txt', 'log', 'xml', 'json', 'js', 'ts', 'm', 'h', 'c', 'cc', 'cpp', 'md', 'conf', 'cfg', 'ini', 'yaml', 'yml', 'html', 'css', 'sh', 'plist'].includes(ext)) return 'text';
  if (['dylib', 'so', 'a', 'bin', 'dat', 'elf', 'car', 'nib', 'momd'].includes(ext)) return 'binary';
  return 'file';
}

function iconFor(e: FsEntry): Component {
  const kind = entryKind(e);
  if (kind === 'dir') return FolderOutline;
  if (kind === 'text') return DocumentTextOutline;
  if (kind === 'image') return ImageOutline;
  if (kind === 'key') return KeyOutline;
  if (kind === 'db') return ArchiveOutline;
  if (kind === 'binary') return CubeOutline;
  return DocumentOutline;
}

const KIND_LABEL: Record<EntryKind, string> = {
  dir: '目录', text: '文本', image: '图片', key: '证书', db: '数据库', binary: '二进制', file: '文件',
};
const kindLabel = (e: FsEntry) => KIND_LABEL[entryKind(e)];

async function load(p: string) {
  const pkg = store.chosenPkg;
  if (!pkg) { message.value = '先选择应用。'; return; }
  const token = ++listSeq;
  state.value = 'loading';
  message.value = '';
  const norm = (p || '').trim();
  try {
    const r = await fsList(pkg, norm);
    if (token !== listSeq) return;
    if (r.error) {
      state.value = 'error';
      message.value = r.error;
      return;
    }
    entries.value = r.entries ?? [];
    limited.value = !!r.limited;
    path.value = norm;
    pathInput.value = norm;
    filter.value = '';
    preview.value = null;
    state.value = 'ready';
  } catch (e) {
    if (token !== listSeq) return;
    state.value = 'error';
    message.value = e instanceof Error ? e.message : '读取目录失败';
  }
}

async function openEntry(e: FsEntry) {
  const full = joinPath(path.value, e.name);
  if (isDir(e)) { void load(full); return; }
  preview.value = { name: e.name, fullPath: full, loading: true };
  try {
    const r = await fsPreview(store.chosenPkg, full);
    if (r.error) {
      preview.value = { name: e.name, fullPath: full, error: true, message: r.error };
      return;
    }
    preview.value = {
      name: e.name,
      fullPath: full,
      text: r.text ?? '',
      format: r.format === 'hex' ? 'hex' : 'text',
      size: r.size ?? e.size,
      truncated: !!r.truncated,
      message: r.truncated ? '只预览了前部，未读完整文件' : '',
    };
  } catch {
    preview.value = { name: e.name, fullPath: full, error: true, message: '读取失败' };
  }
}

const canDownload = computed(() => !!preview.value?.fullPath && !!store.chosenPkg);
const canCopy = computed(() => !!preview.value?.text);
const previewSizeText = computed(() => {
  const pv = preview.value;
  if (!pv) return '';
  return fmtSize(pv.size);
});
const previewTypeText = computed(() => (preview.value?.format === 'hex' ? 'Hex' : '文本'));

function downloadPreview() {
  const pv = preview.value;
  if (!pv?.fullPath || !store.chosenPkg) return;
  const a = document.createElement('a');
  a.href = fsDownloadUrl(store.chosenPkg, pv.fullPath);
  a.download = pv.name;
  document.body.appendChild(a); a.click(); a.remove();
  toast(`已下载 ${pv.name}`);
}

function copyPreview() {
  const text = preview.value?.text;
  if (!text) return;
  void navigator.clipboard?.writeText(text).then(() => toast('已复制'), () => toast('复制失败'));
}

function toggleSort(key: SortKey) {
  if (sortKey.value === key) sortDir.value = sortDir.value === 1 ? -1 : 1;
  else {
    sortKey.value = key;
    sortDir.value = key === 'name' ? 1 : -1;
  }
}
function sortIcon(key: SortKey) {
  if (sortKey.value !== key) return null;
  return sortDir.value === 1 ? ChevronUpOutline : ChevronDownOutline;
}

function retryLoad() { void load(pathInput.value.trim() || path.value); }
function go(p: string) { void load(p); }
function goUp() { if (parentPath.value) void load(parentPath.value); }
function submitPath() { void load(pathInput.value.trim()); }

const fmtMtime = (m?: number) => {
  if (!m) return '';
  const ms = m < 1e12 ? m * 1000 : m;
  return new Date(ms).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
};

watch(() => store.chosenPkg, () => {
  path.value = '';
  pathInput.value = '';
  entries.value = [];
  preview.value = null;
  filter.value = '';
  state.value = 'idle';
  void load('');
});
onMounted(() => { if (store.chosenPkg) void load(''); });
</script>

<template>
  <section class="fs-board">
    <div v-if="!store.chosenPkg" class="fs-unavailable">
      <n-icon size="34" :component="FolderOpenOutline" />
      <strong>选择一个应用后浏览文件</strong>
    </div>

    <div v-else class="fs-shell">
      <header class="fs-toolbar">
        <div class="fs-path-control">
          <n-button size="small" title="上一级" aria-label="上一级" :disabled="!parentPath" @click="goUp">
            <template #icon><n-icon :component="ArrowUpOutline" /></template>
          </n-button>
          <n-input v-model:value="pathInput" size="small" placeholder="沙盒路径，留空为容器根"
            :input-props="{ 'aria-label': '文件路径' }" @keyup.enter="submitPath" />
          <n-button size="small" @click="submitPath">打开</n-button>
          <n-button size="small" @click="load(path)">
            <template #icon><n-icon :component="RefreshOutline" /></template>
            刷新
          </n-button>
        </div>
        <n-input v-model:value="filter" size="small" clearable placeholder="筛选当前目录"
          :input-props="{ 'aria-label': '筛选当前目录' }">
          <template #prefix><n-icon :component="SearchOutline" /></template>
        </n-input>
        <span class="fs-list-stat" :title="statText">{{ statText }}</span>
      </header>

      <div class="fs-split" :class="{ 'with-preview': !!preview }">
        <aside class="fs-list-pane">
          <div class="fs-column-head" aria-label="排序方式">
            <button type="button" @click="toggleSort('name')">
              <span>名称</span><n-icon v-if="sortIcon('name')" size="12" :component="sortIcon('name')" />
            </button>
            <button type="button" @click="toggleSort('size')">
              <span>大小</span><n-icon v-if="sortIcon('size')" size="12" :component="sortIcon('size')" />
            </button>
            <button type="button" class="fs-time-head" @click="toggleSort('mtime')">
              <span>修改时间</span><n-icon v-if="sortIcon('mtime')" size="12" :component="sortIcon('mtime')" />
            </button>
          </div>

          <div class="fs-rows">
            <button v-if="parentPath && state === 'ready'" type="button" class="fs-row fs-parent" @click="goUp">
              <span class="fs-file">
                <span class="fs-kind dir"><n-icon size="17" :component="ArrowUpOutline" /></span>
                <span class="fs-name"><strong>..</strong><small>上一级</small></span>
              </span>
              <span class="fs-size"></span>
              <span class="fs-time"></span>
            </button>

            <button v-for="e in filteredEntries" :key="e.name" type="button" class="fs-row"
              :class="{ selected: preview?.name === e.name }" :title="joinPath(path, e.name)" @click="openEntry(e)">
              <span class="fs-file">
                <span class="fs-kind" :class="entryKind(e)"><n-icon size="17" :component="iconFor(e)" /></span>
                <span class="fs-name">
                  <strong>{{ e.name }}{{ isDir(e) ? '/' : '' }}</strong>
                  <small>{{ kindLabel(e) }}</small>
                </span>
              </span>
              <span class="fs-size">{{ isDir(e) ? '' : fmtSize(e.size) }}</span>
              <span class="fs-time">{{ fmtMtime(e.mtime) }}</span>
            </button>

            <div v-if="state === 'loading'" class="fs-skeletons" aria-label="正在读取目录">
              <div v-for="i in 8" :key="i" class="fs-skeleton-row">
                <span></span><b></b><em></em>
              </div>
            </div>

            <div v-else-if="state === 'error'" class="fs-state error">
              <n-icon size="28" :component="AlertCircleOutline" />
              <strong>目录读取失败</strong>
              <span>{{ message }}</span>
              <n-button size="small" @click="retryLoad">重试</n-button>
            </div>

            <div v-else-if="state === 'ready' && !filteredEntries.length" class="fs-state">
              <n-icon size="28" :component="FolderOpenOutline" />
              <strong>{{ filter ? '当前目录没有匹配项' : '空目录' }}</strong>
            </div>
          </div>
        </aside>

        <section v-if="preview" class="fs-preview-pane">
          <header class="fs-preview-head">
            <span class="fs-preview-icon" :class="{ binary: preview.format === 'hex' }">
              <n-icon size="22" :component="preview.format === 'hex' ? CubeOutline : DocumentTextOutline" />
            </span>
            <div class="fs-preview-id">
              <h3>{{ preview.name }}</h3>
              <p class="mono">{{ preview.fullPath }}</p>
            </div>
            <div class="fs-preview-actions">
              <n-button size="small" :disabled="!canDownload" @click="downloadPreview">
                <template #icon><n-icon :component="DownloadOutline" /></template>
                下载
              </n-button>
              <n-button size="small" :disabled="!canCopy" @click="copyPreview">
                <template #icon><n-icon :component="CopyOutline" /></template>
                复制
              </n-button>
            </div>
          </header>

          <div v-if="preview.loading" class="fs-preview-state">
            <span class="fs-spinner"></span>
            <span>正在读取文件</span>
          </div>
          <div v-else-if="preview.error" class="fs-preview-state error">
            <n-icon size="25" :component="AlertCircleOutline" />
            <strong>文件读取失败</strong>
            <span>{{ preview.message }}</span>
          </div>
          <template v-else>
            <div class="fs-preview-meta">
              <span>{{ previewSizeText }}</span>
              <span>{{ previewTypeText }}</span>
              <span v-if="preview.truncated" class="warn">截断</span>
              <span v-if="preview.message">{{ preview.message }}</span>
            </div>
            <pre class="fs-content" :class="{ hex: preview.format === 'hex' }">{{ preview.text }}</pre>
          </template>
        </section>
      </div>
    </div>
  </section>
</template>

<style scoped>
.fs-board { flex: 1; min-width: 0; min-height: 0; display: flex; overflow: auto; padding: 16px; background: var(--bg); }
.fs-unavailable { flex: 1; display: grid; place-content: center; justify-items: center; gap: 10px; color: var(--muted); border: 1px dashed var(--line); border-radius: 12px; background: var(--surface); }
.fs-unavailable strong { color: var(--ink-2); font-size: 14px; font-weight: 600; }
.fs-shell { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; overflow: hidden; border: 1px solid var(--line-soft); border-radius: 12px; background: var(--surface); box-shadow: 0 1px 2px rgba(17, 19, 21, .025); }
.fs-toolbar { display: grid; grid-template-columns: minmax(360px, 1fr) minmax(150px, 230px) auto; gap: 10px; align-items: center; padding: 10px 12px; border-bottom: 1px solid var(--line-soft); background: var(--surface); }
.fs-path-control { display: grid; grid-template-columns: auto minmax(0, 1fr) auto auto; gap: 7px; align-items: center; min-width: 0; }
.fs-split { flex: 1; min-height: 0; display: grid; grid-template-columns: minmax(0, 1fr); }
.fs-split.with-preview { grid-template-columns: minmax(400px, 1.06fr) minmax(0, .94fr); }
.fs-list-pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; background: var(--bg); }
.fs-split.with-preview .fs-list-pane { border-right: 1px solid var(--line-soft); }
.fs-list-stat { justify-self: end; max-width: 220px; overflow: hidden; color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }
.fs-column-head { display: grid; grid-template-columns: minmax(0, 1fr) 74px 108px; gap: 8px; align-items: center; min-height: 34px; padding: 0 12px; border-bottom: 1px solid var(--line-soft); color: var(--muted); background: var(--chrome); font-size: 11px; }
.fs-column-head button { display: inline-flex; align-items: center; gap: 3px; min-width: 0; padding: 0; border: 0; color: inherit; background: transparent; font-size: inherit; font-weight: 600; text-align: left; cursor: pointer; }
.fs-column-head button:first-child { padding-left: 39px; }
.fs-column-head button:nth-child(2), .fs-column-head .fs-time-head { justify-content: flex-end; text-align: right; }
.fs-column-head button:hover { color: var(--ink); }
.fs-rows { flex: 1; min-height: 0; overflow: auto; padding: 4px 0; }
.fs-row { display: grid; grid-template-columns: minmax(0, 1fr) 74px 108px; gap: 8px; align-items: center; width: 100%; min-height: 40px; padding: 3px 12px; border: 0; border-bottom: 1px solid var(--line-soft); color: var(--ink); background: transparent; text-align: left; cursor: pointer; transition: background .14s ease, box-shadow .14s ease; }
.fs-row:hover { background: var(--surface-2); }
.fs-row.selected { background: var(--surface-2); box-shadow: inset 2px 0 0 var(--ink); }
.fs-file { display: flex; align-items: center; gap: 9px; min-width: 0; }
.fs-kind { display: inline-grid; width: 30px; height: 30px; place-items: center; flex: none; border-radius: 7px; color: var(--muted); background: var(--surface-2); }
.fs-kind.dir { color: var(--ink); background: var(--surface-3); }
.fs-kind.text { color: var(--teal); }
.fs-kind.image { color: var(--lilac); }
.fs-kind.key { color: var(--amber); }
.fs-kind.db { color: var(--coral); }
.fs-kind.binary { color: var(--ink-2); }
.fs-name { display: flex; align-items: baseline; gap: 7px; min-width: 0; }
.fs-name strong { min-width: 0; overflow: hidden; color: var(--ink); font-size: 13px; font-weight: 560; text-overflow: ellipsis; white-space: nowrap; }
.fs-name small { flex: none; color: var(--muted); font-size: 10px; }
.fs-parent .fs-name strong { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.fs-size, .fs-time { overflow: hidden; color: var(--muted); font-size: 11px; font-variant-numeric: tabular-nums; text-overflow: ellipsis; white-space: nowrap; }
.fs-size { color: var(--ink-2); text-align: right; }
.fs-time { text-align: right; }
.fs-skeletons { padding: 6px 12px; }
.fs-skeleton-row { display: grid; grid-template-columns: 30px minmax(0, 1fr) 62px; gap: 10px; align-items: center; min-height: 42px; border-bottom: 1px solid var(--line-soft); }
.fs-skeleton-row span, .fs-skeleton-row b, .fs-skeleton-row em { display: block; height: 12px; border-radius: 4px; background: var(--surface-3); animation: fs-pulse 1.4s ease-in-out infinite; }
.fs-skeleton-row span { width: 30px; height: 30px; border-radius: 7px; }
.fs-skeleton-row em { width: 62px; }
@keyframes fs-pulse { 0%, 100% { opacity: .45; } 50% { opacity: 1; } }
.fs-state { display: grid; place-content: center; justify-items: center; gap: 8px; min-height: 220px; padding: 24px; color: var(--muted); text-align: center; }
.fs-state strong { color: var(--ink-2); font-size: 14px; font-weight: 600; }
.fs-state span { max-width: 420px; overflow-wrap: anywhere; font-size: 12px; line-height: 1.55; }
.fs-state.error { color: var(--danger); }
.fs-preview-pane { display: flex; flex-direction: column; min-width: 0; min-height: 0; background: var(--surface); }
.fs-preview-head { display: flex; align-items: center; gap: 11px; padding: 14px 16px 12px; border-bottom: 1px solid var(--line-soft); }
.fs-preview-icon { display: grid; width: 42px; height: 42px; place-items: center; flex: none; border-radius: 10px; color: var(--teal); background: var(--surface-2); }
.fs-preview-icon.binary { color: var(--ink); }
.fs-preview-id { min-width: 0; flex: 1; }
.fs-preview-id h3 { margin: 0; overflow: hidden; color: var(--ink); font-size: 16px; font-weight: 650; letter-spacing: -.012em; text-overflow: ellipsis; white-space: nowrap; }
.fs-preview-id p { margin: 3px 0 0; overflow: hidden; color: var(--muted); font-size: 11px; text-overflow: ellipsis; white-space: nowrap; }
.fs-preview-actions { display: flex; gap: 7px; flex: none; }
.fs-preview-meta { display: flex; flex-wrap: wrap; gap: 6px; padding: 10px 16px 0; color: var(--muted); font-size: 11px; }
.fs-preview-meta span { padding: 3px 7px; border: 1px solid var(--line-soft); border-radius: 5px; background: var(--bg); font-variant-numeric: tabular-nums; }
.fs-preview-meta .warn { color: var(--amber); border-color: var(--amber); }
.fs-content { flex: 1; min-height: 0; margin: 12px 16px 16px; padding: 13px 14px; overflow: auto; border: 1px solid var(--line-soft); border-radius: 8px; color: var(--ink-2); background: var(--bg); font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 11px; line-height: 1.68; white-space: pre-wrap; word-break: normal; overflow-wrap: anywhere; }
.fs-content.hex { white-space: pre; overflow-wrap: normal; }
.fs-preview-state { flex: 1; display: grid; place-content: center; justify-items: center; gap: 10px; padding: 30px; color: var(--muted); text-align: center; }
.fs-preview-state strong { color: var(--ink-2); font-size: 14px; font-weight: 600; }
.fs-preview-state.error { color: var(--danger); }
.fs-preview-state span { max-width: 520px; overflow-wrap: anywhere; }
.fs-spinner { width: 22px; height: 22px; border: 2px solid var(--line); border-top-color: var(--ink); border-radius: 50%; animation: fs-spin .8s linear infinite; }
@keyframes fs-spin { to { transform: rotate(360deg); } }
.mono { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }

@media (max-width: 980px) {
  .fs-toolbar { grid-template-columns: minmax(0, 1fr) minmax(140px, 200px); padding: 9px 10px; }
  .fs-list-stat { display: none; }
  .fs-split.with-preview { grid-template-columns: minmax(320px, 1.02fr) minmax(0, .98fr); }
  .fs-time, .fs-column-head .fs-time-head { display: none; }
  .fs-column-head, .fs-row { grid-template-columns: minmax(0, 1fr) 68px; }
}

@media (max-width: 700px) {
  .fs-board { display: block; padding: 10px; }
  .fs-shell { min-height: calc(100dvh - 96px); }
  .fs-toolbar { grid-template-columns: minmax(0, 1fr); gap: 7px; padding: 8px; }
  .fs-split { display: flex; flex-direction: column; }
  .fs-list-pane { flex: 0 0 auto; max-height: 45dvh; border-right: 0; border-bottom: 1px solid var(--line-soft); }
  .fs-rows { min-height: 150px; }
  .fs-preview-pane { flex: 1; min-height: 360px; }
  .fs-preview-head { flex-wrap: wrap; }
  .fs-preview-actions { margin-left: auto; }
}

@media (prefers-reduced-motion: reduce) {
  .fs-skeleton-row span, .fs-skeleton-row b, .fs-skeleton-row em, .fs-spinner { animation: none; }
  .fs-row { transition: none; }
}
</style>
