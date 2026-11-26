<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { NModal, NVirtualList } from 'naive-ui';
import { CloseOutline, SearchOutline } from '@vicons/ionicons5';
import { store, choosePackage } from '../store';
import { appIconUrl, scopeAdd, scopeRemove, relaunchApp } from '../api';

const props = defineProps<{ show: boolean }>();
const emit = defineEmits<{ close: [] }>();
const tab = ref<'user' | 'system' | 'injected'>('user');
const q = ref('');
const toastMsg = ref('');

watch(() => props.show, open => {
  if (open) { q.value = ''; tab.value = 'user'; toastMsg.value = ''; }
});
const tabs = [['user', '应用'], ['system', '系统'], ['injected', '已注入']] as const;

const apps = computed(() => {
  let list = store.apps;
  if (tab.value === 'user') list = list.filter(a => a.kind !== 'system');
  else if (tab.value === 'system') list = list.filter(a => a.kind === 'system');
  else list = list.filter(a => store.scope.has(a.bundleId));
  const s = q.value.trim().toLowerCase();
  if (s) list = list.filter(a =>
    (a.bundleId + ' ' + (a.name ?? '')).toLowerCase().includes(s));
  return list;
});
const chosen = computed(() => store.apps.find(a => a.bundleId === store.chosenPkg));
const chosenLabel = computed(() => chosen.value?.name || store.chosenPkg || '未选择应用');
const chosenInitial = computed(() => (chosenLabel.value[0] ?? '?'));
const itemInitial = (label?: string, pkg?: string) => ((label || pkg || '?')[0] ?? '?');

function pick(pkg: string) {
  choosePackage(pkg);
  emit('close');
}
async function toggleInject(pkg: string, on: boolean) {
  try {
    const r = await (on ? scopeAdd(pkg) : scopeRemove(pkg)) as { ok?: boolean; error?: string };
    if (r?.ok === false) { toastMsg.value = r.error ?? '写入失败'; return; }
    if (on) store.scope.add(pkg); else store.scope.delete(pkg);
  } catch { toastMsg.value = '写入失败'; }
}
async function control() {
  const pkg = store.chosenPkg;
  if (!pkg) return;
  toastMsg.value = '正在重启…';
  try {
    const r = await relaunchApp(pkg);
    toastMsg.value = r?.relaunched ? '已重启' : (r?.error ?? '手机没有完成重启');
  } catch { toastMsg.value = '手机没有完成重启'; }
}
const canControl = computed(() => store.scope.has(store.chosenPkg));
</script>

<template>
  <n-modal :show="show" @update:show="!$event && emit('close')">
    <div class="app-dialog show" role="dialog" aria-modal="true" aria-label="应用">
      <aside class="app-dialog-side">
        <h2>应用</h2>
        <button v-for="[k, label] in tabs" :key="k" type="button" :aria-pressed="tab === k"
          @click="tab = k">{{ label }}</button>
      </aside>
      <div class="app-dialog-main">
        <div class="app-dialog-card">
          <span class="app-face">
            <span class="app-dialog-letter">{{ chosenInitial }}</span>
            <img v-if="store.chosenPkg && chosen" :src="appIconUrl(store.chosenPkg)" alt=""
              @error="($event.target as HTMLElement).style.display = 'none'" />
          </span>
          <div class="app-dialog-id">
            <strong>{{ chosenLabel }}</strong>
            <span>{{ store.chosenPkg || '从下方列表选择要观测的应用' }}</span>
          </div>
          <div class="app-dialog-actions">
            <template v-if="canControl">
              <n-button size="small" @click="control()">重启</n-button>
            </template>
            <n-button text aria-label="关闭应用窗口" class="app-close" @click="emit('close')">
              <n-icon size="18" :component="CloseOutline" />
            </n-button>
          </div>
        </div>
        <div class="dialog-search"><n-input v-model:value="q" clearable placeholder="搜索名称或包名" :input-props="{ 'aria-label': '搜索应用' }">
          <template #prefix><n-icon :component="SearchOutline" /></template>
        </n-input></div>
        <div class="app-choices">
          <div v-if="toastMsg" class="app-empty">{{ toastMsg }}</div>
          <n-virtual-list v-if="apps.length" class="app-virtual" :items="apps" :item-size="52" key-field="bundleId">
            <template #default="{ item: a }">
              <div class="app-row">
                <button type="button" class="app-item" :class="{ active: a.bundleId === store.chosenPkg }"
                  @click="pick(a.bundleId)">
                  <span class="app-face">
                    <span class="app-dialog-letter">{{ itemInitial(a.name, a.bundleId) }}</span>
                    <img v-if="true" :src="appIconUrl(a.bundleId)" alt="" loading="lazy"
                      @error="($event.target as HTMLElement).style.display = 'none'" />
                  </span>
                  <span class="app-copy">
                    <span class="app-name">{{ a.name || a.bundleId }}</span>
                    <span class="app-pkg">{{ a.bundleId }}</span>
                  </span>
                  <span class="app-state" :class="{ on: store.scope.has(a.bundleId) }">
                    {{ store.scope.has(a.bundleId) ? '已注入' : '' }}</span>
                </button>
                <n-switch size="small" class="app-inject-sw" aria-label="允许注入" :value="store.scope.has(a.bundleId)"
                  :disabled="a.bundleId === store.chosenPkg && store.scope.has(a.bundleId)"
                  @update:value="on => toggleInject(a.bundleId, !!on)" />
              </div>
            </template>
          </n-virtual-list>
          <div v-if="store.appsError" class="app-empty">{{ store.appsError }}</div>
          <div v-else-if="!apps.length" class="app-empty">{{ store.appsFailed ? '读取失败，保留上次清单' : '没有应用' }}</div>
        </div>
      </div>
    </div>
  </n-modal>
</template>
