<script setup lang="ts">
import { computed, ref, onMounted } from 'vue';
import { store, loadInject, toggleScope, relaunchBundle } from '../store';
import { appIconUrl } from '../api';

const q = ref('');
const system = (a: { kind?: string; bundleId: string }) =>
  a.kind === 'system' || a.bundleId.startsWith('com.apple.');
const scope = computed(() => store.injectData?.scope ?? []);
const rows = computed(() => {
  const query = q.value.trim().toLowerCase();
  return (store.injectData?.apps ?? [])
    .filter(a => !query || (a.bundleId + ' ' + (a.name ?? '')).toLowerCase().includes(query))
    .sort((a, b) => Number(system(a)) - Number(system(b))
      || String(a.name || a.bundleId).localeCompare(String(b.name || b.bundleId), 'zh-Hans-CN'));
});
onMounted(() => { void loadInject(true); });
</script>

<template>
  <main class="tool-page">
    <div class="tool-header"><div><h2>注入范围</h2></div>
      <div class="hstack">
        <input v-model="q" class="search-input" type="search" placeholder="搜索应用 / Bundle ID" spellcheck="false" />
        <button class="btn sm" type="button" @click="loadInject(true)">刷新</button>
      </div>
    </div>
    <div v-if="store.injectData?.error" class="notice" role="status">暂时无法读取注入范围。</div>
    <section class="tool-surface"><table class="tool-table" aria-label="应用注入范围">
      <thead><tr><th style="width:34%">应用</th><th>Bundle ID</th><th style="width:76px">状态</th><th style="width:150px">注入</th></tr></thead>
      <tbody>
        <tr v-for="a in rows" :key="a.bundleId">
          <td><span class="inject-app"><span class="app-face sm-face">
            <span class="app-dialog-letter">{{ (a.name || a.bundleId)[0]?.toUpperCase() }}</span>
            <img :src="appIconUrl(a.bundleId)" alt="" loading="lazy"
              @error="($event.target as HTMLElement).style.display = 'none'" /></span>
            <span class="app-name">{{ a.name || a.bundleId }}</span></span></td>
          <td class="mono">{{ a.bundleId }}</td>
          <td><span class="app-state" :class="{ on: a.running }">{{ a.running ? '运行中' : '—' }}</span></td>
          <td>
            <span class="hstack">
              <input v-if="!system(a)" class="app-inject" type="checkbox" title="允许注入"
                :checked="scope.includes(a.bundleId)" :disabled="store.injectPending.has(a.bundleId)"
                @change="toggleScope(a.bundleId, ($event.target as HTMLInputElement).checked)" />
              <span v-else class="app-inject-slot"></span>
              <button v-if="store.injectPending.has(a.bundleId)" type="button" class="compact-action"
                @click="relaunchBundle(a.bundleId)">重启生效</button>
            </span>
          </td>
        </tr>
        <tr v-if="!rows.length"><td colspan="4" class="tool-note">没有匹配的应用。</td></tr>
      </tbody>
    </table></section>
  </main>
</template>
