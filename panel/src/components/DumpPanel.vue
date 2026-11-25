<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from 'vue';
import { store, toast } from '../store';
import * as A from '../api';

const app = computed(() => store.selected);
const images = ref<A.DumpImage[]>([]);
const status = ref<A.DumpStatus | null>(null);
const loading = ref(false);
const starting = ref('');
const error = ref('');
let poll = 0;

function fmtSize(n?: number) {
  if (n == null) return '—';
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}
function stateText(s?: string) {
  return { idle: '空闲', running: '运行中', done: '已完成', error: '失败' }[s ?? ''] ?? '未读取';
}

async function load() {
  if (!app.value) { images.value = []; status.value = null; error.value = '先选择应用'; return; }
  loading.value = true; error.value = '';
  try {
    const [imgs, st] = await Promise.all([A.getDumpImages(app.value), A.getDumpStatus(app.value)]);
    if (imgs.error) throw new Error(imgs.error);
    images.value = imgs.images ?? [];
    status.value = st;
    schedule(st);
  } catch (e) {
    error.value = e instanceof Error ? e.message : 'Dump 状态暂时无法读取';
  } finally { loading.value = false; }
}

function schedule(st: A.DumpStatus | null) {
  window.clearTimeout(poll);
  if (st?.state === 'running') poll = window.setTimeout(() => void load(), 1200);
}

async function start(mode: 'bin' | 'ipa') {
  if (!app.value || starting.value) return;
  starting.value = mode; error.value = '';
  try {
    const data = await A.startDump(app.value, mode);
    if (data.error || data.started === false) throw new Error(data.error || '已有任务在进行');
    toast(mode === 'bin' ? '已开始导出解密二进制' : '已开始导出 IPA');
    await load();
  } catch (e) {
    error.value = e instanceof Error ? e.message : '无法启动 Dump';
  } finally { starting.value = ''; }
}

watch(app, () => { window.clearTimeout(poll); void load(); }, { immediate: true });
onUnmounted(() => window.clearTimeout(poll));
</script>

<template>
  <main class="tool-page dumppane">
    <div class="tool-header"><div><h2>Dump</h2><p>{{ app || '无当前应用' }} 的进程镜像和砸壳产物。</p></div>
      <span class="pill tool-status">{{ loading ? '读取中' : error ? '读取失败' : stateText(status?.state) }}</span></div>
    <div v-if="error" class="notice warn">{{ error }}</div>

    <section class="tool-surface" style="margin-bottom:12px">
      <h3>任务</h3>
      <div class="tool-content">
        <div class="dump-actions">
          <button type="button" class="hbtn" :disabled="!!starting || status?.state === 'running'" @click="start('bin')">
            {{ starting === 'bin' ? '启动中' : '导出解密二进制 zip' }}</button>
          <button type="button" class="hbtn" :disabled="!!starting || status?.state === 'running'" @click="start('ipa')">
            {{ starting === 'ipa' ? '启动中' : '导出 IPA' }}</button>
          <button type="button" class="hbtn" @click="load">刷新</button>
        </div>
        <p class="tool-note" style="margin-top:10px">
          状态：{{ stateText(status?.state) }}<template v-if="status?.stage"> · {{ status.stage }}</template>
          <template v-if="status?.state === 'running'"> · {{ status.progress ?? 0 }}%</template>
          <template v-if="status?.error"> · {{ status.error }}</template>
        </p>
        <div class="dump-downloads">
          <a v-if="status?.binReady && app" class="hbtn" :href="A.dumpDownloadUrl(app, 'bin')" :download="status.binName || 'decrypted.zip'">下载 {{ status.binName || 'bin 产物' }}</a>
          <a v-if="status?.ipaReady && app" class="hbtn" :href="A.dumpDownloadUrl(app, 'ipa')" :download="status.ipaName || 'decrypted.ipa'">下载 {{ status.ipaName || 'IPA 产物' }}</a>
        </div>
      </div>
    </section>

    <section class="tool-surface">
      <h3>进程镜像</h3>
      <table class="tool-table">
        <thead><tr><th>名称</th><th>类型</th><th>加密</th><th>大小</th><th>操作</th></tr></thead>
        <tbody>
          <tr v-for="img in images" :key="img.name">
            <td class="mono">{{ img.name }}</td>
            <td>{{ img.kind || '—' }}</td>
            <td>{{ img.encrypted ? '加密' : '明文' }}</td>
            <td>{{ fmtSize(img.size) }}</td>
            <td><a v-if="app" class="dl" :href="A.dumpImageUrl(app, img.name)" :download="img.name + '-decrypted'">即时下载</a></td>
          </tr>
          <tr v-if="!loading && !images.length"><td colspan="5" class="tool-note">没有可导出的进程镜像。</td></tr>
        </tbody>
      </table>
    </section>
  </main>
</template>
