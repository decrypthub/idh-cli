<script setup lang="ts">
import { ref, onMounted } from 'vue';
import { store, copyText, downloadText } from '../store';

const text = ref('');
const loading = ref(false);
const error = ref('');

async function read() {
  loading.value = true; error.value = ''; text.value = '';
  try {
    // 与旧适配层一致：诊断 = 本地聚合 {device, session}
    const r = await fetch('/api/sessions');
    if (!r.ok) throw new Error('设备会话返回 ' + r.status);
    const sessions = await r.json();
    text.value = JSON.stringify({ device: store.device, session: store.session, sessions }, null, 2);
  } catch (e) { error.value = '读取失败：' + (e as Error).message; }
  finally { loading.value = false; }
}
onMounted(read);
</script>

<template>
  <div class="modal-mask show" @click.self="store.diagOpen = false">
    <div class="dialog-card" role="dialog" aria-label="设备与会话诊断">
      <div class="dialog-head"><strong>设备与会话诊断</strong>
        <button class="set-close-x" type="button" aria-label="关闭" @click="store.diagOpen = false">
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8" /></svg></button></div>
      <pre class="code-body diag-body">{{ error || (loading ? '正在读取当前设备与会话…' : text) }}</pre>
      <div class="dialog-actions">
        <button class="btn sm" type="button" :disabled="loading" @click="read">刷新</button>
        <button class="btn sm" type="button" :disabled="!text" @click="copyText(text)">复制</button>
        <button class="btn sm" type="button" :disabled="!text"
          @click="downloadText('idhjd-device-diagnostics.json', text)">下载</button>
      </div>
    </div>
  </div>
</template>
