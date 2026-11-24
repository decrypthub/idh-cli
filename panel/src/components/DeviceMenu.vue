<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { store, loadDevices, deviceSelect, deviceRemove, deviceAdd, toast } from '../store';

const open = ref(false);
const addr = ref('');

const current = computed(() => store.devices.find(d => d.selected));
const chipTitle = computed(() => current.value?.address ?? '未连接');
const chipLink = computed(() => {
  if (!current.value) return '';
  const t = current.value.transport === 'usb' ? 'USB' : 'LAN';
  const s = store.network === 'online' ? '在线' : store.network === 'offline' ? '离线' : '连接中';
  return `${t} · ${s}`;
});
function rowSub(d: { transport?: string; online?: boolean; selected?: boolean }) {
  const t = d.transport === 'usb' ? 'USB' : 'LAN';
  const online = d.selected ? store.network === 'online' : d.online;
  return `${t} · ${online ? '在线' : '离线'}`;
}

async function pick(id: string, selected?: boolean) {
  if (selected) { open.value = false; return; }
  const ok = await deviceSelect(id);
  if (!ok) { await loadDevices(); return; }
  location.reload();
}
async function add() {
  const v = addr.value.trim();
  if (!v) return;
  if (await deviceAdd(v)) addr.value = '';
}

function onDocClick(e: MouseEvent) {
  if (!(e.target as HTMLElement).closest('.device-picker')) open.value = false;
}
onMounted(() => document.addEventListener('click', onDocClick));
onUnmounted(() => document.removeEventListener('click', onDocClick));
</script>

<template>
  <section class="device-picker">
    <button type="button" class="device-context" :aria-expanded="open" title="切换设备"
      @click.stop="open = !open; if (open) void loadDevices()">
      <span class="context-label">设备</span>
      <strong>{{ chipTitle }}</strong>
      <span class="device-link">{{ chipLink }}</span>
      <span class="menu-chevron"><svg viewBox="0 0 12 12" width="10" height="10" fill="none"
          stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
          <path d="M2.5 4.5l3.5 3.5 3.5-3.5" /></svg></span>
    </button>
    <div class="popover device-menu" :class="{ show: open }">
      <div class="device-menu-label">设备</div>
      <div v-for="d in store.devices" :key="d.id" class="device-row">
        <button type="button" class="app-item" :class="{ active: d.selected }"
          @click="pick(d.id, d.selected)">
          <span class="app-copy">
            <span class="app-name">{{ d.address }}</span>
            <span class="app-pkg">{{ rowSub(d) }}</span>
          </span>
          <svg v-if="d.selected" viewBox="0 0 20 20" class="app-check-ico"><path d="M4.5 10.5l3.5 3.5 7.5-8" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>
        </button>
        <button type="button" class="device-remove" title="移除" @click.stop="deviceRemove(d.id)">×</button>
      </div>
      <div v-for="udid in store.usbRows" :key="udid" class="device-row">
        <button type="button" class="app-item" @click="deviceAdd(undefined, udid)">
          <span class="app-copy">
            <span class="app-name">USB 设备</span>
            <span class="app-pkg">{{ udid }}</span>
          </span>
        </button>
      </div>
      <div v-if="!store.devices.length && !store.usbRows.length" class="app-empty">没有已保存的设备</div>
      <div class="device-add">
        <input v-model="addr" type="text" placeholder="设备地址 127.0.0.1:8088" autocomplete="off"
          spellcheck="false" @keydown.enter="add" />
        <button type="button" class="btn sm" @click="add">添加</button>
      </div>
    </div>
  </section>
</template>
