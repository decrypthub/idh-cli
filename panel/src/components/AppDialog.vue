<script setup lang="ts">
import { computed, ref, onMounted } from 'vue';
import { store, chooseApp, loadInject, toggleScope, relaunchBundle } from '../store';
import { SESSION_STATUS, fmt, longTime } from '../model';
import { appIconUrl } from '../api';
import type { InstalledApp } from '../model';

type TabKey = 'record' | 'user' | 'system' | 'injected';
const TABS: Array<[TabKey, string]> = [['record', '记录'], ['user', '应用'], ['system', '系统'], ['injected', '已注入']];
const tab = ref<TabKey>('record');
const q = ref('');

const system = (a: { kind?: string; bundleId: string }) =>
  a.kind === 'system' || a.bundleId.startsWith('com.apple.');
const scope = computed(() => store.injectData?.scope ?? []);

interface Row extends InstalledApp { state: string; count?: number; recorded?: boolean }
const rows = computed<Row[]>(() => {
  const query = q.value.trim().toLowerCase();
  const match = (a: { bundleId: string; name?: string }) =>
    !query || (a.bundleId + ' ' + (a.name ?? '')).toLowerCase().includes(query);
  const recordedIds = new Set(store.apps.map(a => a.bundleId));
  const recRows: Row[] = store.apps.map(a => ({
    ...a, recorded: true, state: (a.running ? '运行中' : SESSION_STATUS[a.status] ?? '会话') + (a.count ? ' · ' + a.count + ' 条' : ''),
  }));
  const instRows: Row[] = store.installed
    .filter(a => !recordedIds.has(a.bundleId))
    .map(a => ({ ...a, state: a.running ? '运行中' : '' }));
  const inScope = (a: Row) => scope.value.includes(a.bundleId);
  const pick = (list: Row[]) => list.filter(match)
    .sort((a, b) => String(a.name || a.bundleId).localeCompare(String(b.name || b.bundleId), 'zh-Hans-CN'));
  if (tab.value === 'record') return pick(recRows);
  if (tab.value === 'user') return pick([...recRows, ...instRows].filter(a => !system(a)));
  if (tab.value === 'system') return pick(instRows.filter(system));
  return pick([...recRows, ...instRows].filter(inScope));
});

const chosen = computed(() =>
  store.apps.find(a => a.bundleId === store.selected)
  ?? store.installed.find(a => a.bundleId === store.selected));
const chosenLabel = computed(() => chosen.value?.name || store.selected || '未选择应用');
const chosenInitial = computed(() => (chosenLabel.value[0] ?? '?').toUpperCase());
const chosenState = computed(() => {
  const a = store.apps.find(x => x.bundleId === store.selected);
  if (a) return [a.running ? '运行中' : SESSION_STATUS[a.status] ?? '会话', a.count + ' 条', fmt(longTime, a.createdAtMs)].join(' · ');
  return store.selected ? '没有此应用的记录' : '从下方列表选择要查看的应用';
});
const chosenFoot = computed(() => {
  const a = store.apps.find(x => x.bundleId === store.selected);
  const live = store.device?.apps?.find(x => x.bundleId === store.selected && x.running);
  const label = live ? '在线，已登记' : a?.status === 'ended' ? '历史会话，未见对应进程在线' : a ? '未见登记' : '无在线进程';
  return [label,
    (live?.pid ?? a?.pid) ? 'PID ' + (live?.pid ?? a?.pid) : null,
    a ? a.sessions + ' 个会话' : null,
    a ? a.count + ' 条' : null].filter(Boolean).join(' · ');
});

function pick(bundleId: string) { if (chooseApp(bundleId)) store.appDialogOpen = false; }
async function toggle(bundleId: string, on: boolean) {
  await toggleScope(bundleId, on);
}
const injectable = (a: Row) => !system(a);

onMounted(() => { void loadInject(); });
</script>

<template>
  <div class="modal-mask show" @click.self="store.appDialogOpen = false">
    <div class="app-dialog show">
      <aside class="app-dialog-side">
        <h2>应用</h2>
        <button v-for="[k, label] in TABS" :key="k" type="button" :aria-pressed="tab === k"
          @click="tab = k">{{ label }}</button>
      </aside>
      <div class="app-dialog-main">
        <div class="app-dialog-card">
          <span class="app-face">
            <span class="app-dialog-letter">{{ chosenInitial }}</span>
            <img v-if="store.selected" :src="appIconUrl(store.selected)" alt=""
              @error="($event.target as HTMLElement).style.display = 'none'" />
          </span>
          <div class="app-dialog-id">
            <strong>{{ chosenLabel }}</strong>
            <span>{{ store.selected || '从下方列表选择要查看的应用' }}</span>
            <span>{{ chosenState }}</span>
          </div>
          <button type="button" class="set-close-x" @click="store.appDialogOpen = false">
            <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8"
              stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8" /></svg>
          </button>
        </div>
        <input v-model="q" class="app-menu-search" placeholder="搜索应用" />
        <div class="app-choices">
          <div v-for="a in rows" :key="a.bundleId" class="app-row">
            <input v-if="injectable(a)" class="app-inject" type="checkbox" title="允许注入"
              :checked="scope.includes(a.bundleId)" :disabled="!store.injectData || store.injectPending.has(a.bundleId)"
              @change="toggle(a.bundleId, ($event.target as HTMLInputElement).checked)" />
            <span v-else class="app-inject-slot"></span>
            <button type="button" class="app-item" :class="{ active: a.bundleId === store.selected }"
              @click="pick(a.bundleId)">
              <span class="app-face">
                <span class="app-dialog-letter">{{ (a.name || a.bundleId)[0]?.toUpperCase() }}</span>
                <img :src="appIconUrl(a.bundleId)" alt="" loading="lazy"
                  @error="($event.target as HTMLElement).style.display = 'none'" />
              </span>
              <span class="app-copy">
                <span class="app-name">{{ a.name || a.bundleId }}</span>
                <span class="app-pkg">{{ a.bundleId }}</span>
              </span>
              <span class="app-state" :class="{ on: a.running || a.recorded }">{{ a.state }}</span>
            </button>
            <button v-if="store.injectPending.has(a.bundleId)" type="button" class="compact-action"
              @click="relaunchBundle(a.bundleId)">重启生效</button>
          </div>
          <div v-if="store.injectData?.error" class="app-empty">已安装清单读取失败，仅显示记录</div>
          <div v-else-if="!rows.length" class="app-empty">没有匹配的应用</div>
        </div>
        <div class="app-dialog-foot">{{ chosenFoot }}</div>
      </div>
    </div>
  </div>
</template>
