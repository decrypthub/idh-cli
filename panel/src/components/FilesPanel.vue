<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { store, toast } from '../store';
import * as A from '../api';

const path = ref('');
const entries = ref<A.FileEntry[]>([]);
const parent = ref<string | null>(null);
const preview = ref<A.FilePreview | null>(null);
const loading = ref(false);
const previewLoading = ref(false);
const error = ref('');

const app = computed(() => store.selected);
const crumbs = computed(() => {
  const parts = path.value ? path.value.split('/') : [];
  const rows: Array<{ name: string; path: string }> = [{ name: '沙盒', path: '' }];
  let cur = '';
  for (const part of parts) {
    cur = cur ? cur + '/' + part : part;
    rows.push({ name: part, path: cur });
  }
  return rows;
});

function join(name: string) { return path.value ? `${path.value}/${name}` : name; }
function fmtSize(n?: number) {
  if (n == null) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
function fmtTime(sec?: number) {
  return sec ? new Date(sec * 1000).toLocaleString('zh-CN', { hour12: false }) : '';
}

async function load(next = path.value) {
  if (!app.value) { entries.value = []; error.value = '先选择应用'; return; }
  loading.value = true; error.value = '';
  try {
    const data = await A.listFiles(app.value, next);
    if (data.error) throw new Error(data.error);
    path.value = data.path ?? next;
    parent.value = data.parent ?? null;
    entries.value = data.entries ?? [];
  } catch (e) {
    error.value = e instanceof Error ? e.message : '设备目录暂时无法读取';
    entries.value = [];
  } finally { loading.value = false; }
}

async function open(row: A.FileEntry) {
  if (row.type === 'dir') { preview.value = null; await load(join(row.name)); return; }
  await show(join(row.name));
}

async function show(file: string) {
  if (!app.value) return;
  previewLoading.value = true;
  try {
    const data = await A.readFilePreview(app.value, file);
    if (data.error) throw new Error(data.error);
    preview.value = data;
  } catch (e) {
    preview.value = { path: file, error: e instanceof Error ? e.message : '文件暂时无法读取' };
  } finally { previewLoading.value = false; }
}

function download(file?: string) {
  const target = file ?? preview.value?.path;
  if (!app.value || !target) return;
  const a = document.createElement('a');
  a.href = A.fileDownloadUrl(app.value, target);
  a.download = target.split('/').pop() ?? 'download';
  document.body.appendChild(a); a.click(); a.remove();
  toast('已开始下载');
}

watch(app, () => {
  path.value = ''; parent.value = null; preview.value = null; error.value = '';
  void load('');
}, { immediate: true });
</script>

<template>
  <main class="tool-page files-tool">
    <div class="tool-header"><div><h2>文件浏览</h2><p>{{ app || '无当前应用' }} 的 Documents / Library / tmp。</p></div>
      <span class="pill tool-status">{{ loading ? '读取中' : error ? '读取失败' : '设备目录' }}</span></div>
    <div v-if="error" class="notice warn">{{ error }}</div>
    <div class="tool-surface files-workspace">
      <section class="files-list-pane">
        <div class="files-head">
          <button type="button" :disabled="!path" @click="load(parent ?? '')">上级</button>
          <button type="button" @click="load(path)">刷新</button>
          <nav class="files-breadcrumb" aria-label="目录位置">
            <template v-for="(c, i) in crumbs" :key="c.path || 'root'">
              <a href="#" @click.prevent="load(c.path)">{{ c.name }}</a><span v-if="i < crumbs.length - 1" class="sep"> / </span>
            </template>
          </nav>
        </div>
        <div class="files-list">
          <div v-for="row in entries" :key="row.name" class="files-row" :class="{ selected: preview?.path === join(row.name) }">
            <button type="button" class="top" @click="open(row)">
              <svg class="files-glyph" :class="{ dir: row.type === 'dir' }" viewBox="0 0 20 20" aria-hidden="true">
                <path v-if="row.type === 'dir'" d="M3 5.5h5l1.6 2H17v8H3z" />
                <path v-else d="M5 3h7l3 3v11H5zM12 3v3h3" />
              </svg>
              <span class="name">{{ row.name }}</span>
            </button>
            <span class="n">{{ row.type === 'file' ? fmtSize(row.size) : '目录' }}</span>
            <span class="n">{{ fmtTime(row.mtime) }}</span>
            <div class="files-actions">
              <button v-if="row.type === 'file'" type="button" @click="show(join(row.name))">预览</button>
              <a v-if="row.type === 'file'" :href="app ? A.fileDownloadUrl(app, join(row.name)) : undefined" :download="row.name">下载</a>
            </div>
          </div>
          <p v-if="!loading && !entries.length && !error" class="tool-note" style="padding:14px">此目录为空。</p>
        </div>
      </section>
      <section class="tool-content" style="flex:1;min-width:0;overflow:auto">
        <div v-if="preview" class="files-preview-head">
          <span class="path">{{ preview.path }}</span>
          <span class="n">{{ fmtSize(preview.size) }}{{ preview.truncated ? ' · 已截断' : '' }}</span>
          <button type="button" class="hbtn" @click="download()">下载</button>
        </div>
        <p v-if="previewLoading" class="tool-note">正在读取文件。</p>
        <pre v-if="preview?.text" id="filesPreviewBody" :class="{ hex: preview.format === 'hex' }">{{ preview.text }}</pre>
        <p v-else-if="preview?.error" class="tool-note">{{ preview.error }}</p>
        <p v-else-if="!preview && !previewLoading" class="tool-note">选择左侧文件查看内容。</p>
      </section>
    </div>
  </main>
</template>
