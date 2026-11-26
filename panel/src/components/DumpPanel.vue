<script setup lang="ts">
import { computed, ref, watch, onMounted, onUnmounted } from 'vue';
import { store, toast } from '../store';
import { getDumpStatus, startDump, dumpDownloadUrl, dumpImageUrl, getDumpImages, type DumpStatus, type DumpImage } from '../api';
import { fmtSize } from '../capview';

const status = ref<DumpStatus>({});
const state = ref<'idle' | 'loading' | 'ready' | 'error'>('idle');
const message = ref('');
const starting = ref(false);
const images = ref<DumpImage[]>([]);
const imagesError = ref('');

const running = computed(() => status.value.state === 'running' || status.value.state === 'dumping');

async function refresh() {
  const pkg = store.chosenPkg;
  if (!pkg) { state.value = 'idle'; message.value = '先选择应用。'; return; }
  state.value = 'loading';
  try {
    const r = await getDumpStatus(pkg);
    status.value = r ?? {};
    state.value = 'ready';
    message.value = '';
  } catch (e) {
    state.value = 'error';
    message.value = e instanceof Error ? e.message : '读取 Dump 状态失败';
  }
}

async function refreshImages() {
  const pkg = store.chosenPkg;
  if (!pkg) { images.value = []; return; }
  try {
    const r = await getDumpImages(pkg);
    images.value = r.images ?? [];
    imagesError.value = r.error ?? '';
  } catch {
    imagesError.value = '模块列表读取失败（进程不在线？）';
  }
}

async function run(mode: 'bin' | 'ipa') {
  const pkg = store.chosenPkg;
  if (!pkg || starting.value) return;
  starting.value = true;
  try {
    const r = await startDump(pkg, mode);
    if (r?.started) {
      toast(`已开始 ${mode === 'ipa' ? 'IPA' : '主二进制'} Dump`);
      setTimeout(() => void refresh(), 1500);
    } else {
      toast(r?.error || 'Dump 启动失败');
    }
  } catch {
    toast('Dump 请求失败（进程不在线？）');
  } finally {
    starting.value = false;
  }
}

function download(kind: 'bin' | 'ipa') {
  const pkg = store.chosenPkg;
  if (!pkg) return;
  const a = document.createElement('a');
  a.href = dumpDownloadUrl(pkg, kind);
  document.body.appendChild(a); a.click(); a.remove();
  toast('开始下载');
}

function downloadImage(img: DumpImage) {
  const pkg = store.chosenPkg;
  if (!pkg || !img.name) return;
  const a = document.createElement('a');
  a.href = dumpImageUrl(pkg, img.name);
  document.body.appendChild(a); a.click(); a.remove();
  toast(`开始下载 ${img.name}`);
}

const stateText = computed(() => {
  const s = status.value;
  if (state.value === 'error') return message.value;
  if (s.state === 'idle' || !s.state) return '空闲';
  if (s.state === 'done') return '完成';
  if (s.error) return `失败：${s.error}`;
  return `${s.state}${s.stage ? ' · ' + s.stage : ''}${s.progress ? ` · ${Math.round(s.progress * 100)}%` : ''}`;
});

let poll = 0;
onMounted(() => {
  void refresh(); void refreshImages();
  poll = window.setInterval(() => { if (running.value) void refresh(); }, 2000);
});
onUnmounted(() => clearInterval(poll));
watch(() => store.chosenPkg, () => { void refresh(); void refreshImages(); });
</script>

<template>
  <div class="dumppane">
    <h1 class="sr-only">Dump</h1>
    <p v-if="!store.chosenPkg" class="directory-unavailable">选择应用后对它执行解密 Dump。</p>
    <template v-else>
      <section class="dump-card">
        <div class="dump-card-head">
          <h3>任务状态</h3>
          <button type="button" class="compact-action" @click="refresh">刷新</button>
        </div>
        <p class="set-status">{{ stateText }}</p>
        <div class="dump-actions">
          <n-button size="small" type="primary" secondary :disabled="starting || running" @click="run('bin')">Dump 主二进制</n-button>
          <n-button size="small" secondary :disabled="starting || running" @click="run('ipa')">Dump IPA</n-button>
          <n-button v-if="status.binReady" size="small" tertiary @click="download('bin')">下载 {{ status.binName || 'bin' }}</n-button>
          <n-button v-if="status.ipaReady" size="small" tertiary @click="download('ipa')">下载 {{ status.ipaName || 'ipa' }}</n-button>
        </div>
      </section>

      <section class="dump-card">
        <div class="dump-card-head">
          <h3>进程模块 · {{ images.length }}</h3>
          <button type="button" class="compact-action" @click="refreshImages">刷新</button>
        </div>
        <p v-if="imagesError" class="set-status">{{ imagesError }}</p>
        <table v-if="images.length" class="directory-list-table">
          <thead><tr><th>模块</th><th>大小</th><th></th></tr></thead>
          <tbody>
            <tr v-for="img in images" :key="img.name">
              <td><span class="mono">{{ img.name }}</span><span v-if="img.encrypted" class="enc-tag">加密</span></td>
              <td>{{ fmtSize(img.size) }}</td>
              <td><button type="button" class="compact-action" @click="downloadImage(img)">下载</button></td>
            </tr>
          </tbody>
        </table>
      </section>
    </template>
  </div>
</template>

<style scoped>
.dumppane { padding: 18px 22px; overflow: auto; display: flex; flex-direction: column; gap: 14px; }
.dump-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px 16px;
  background: var(--surface);
}
.dump-card-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; }
.dump-card-head h3 { margin: 0; font-size: 13px; }
.dump-actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.mono { font-family: ui-monospace, Consolas, monospace; font-size: 12px; }
</style>
