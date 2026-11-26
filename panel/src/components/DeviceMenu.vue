<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted } from 'vue';
import { ChevronDownOutline, RefreshOutline } from '@vicons/ionicons5';
import type { DeviceView } from '../store';
import {
  store, addDeviceByAddress, addUsbDeviceById, removeDeviceById, reconnectDeviceById, toast,
} from '../store';

const props = defineProps<{ devices: DeviceView[]; failed: boolean; selected: string }>();
const emit = defineEmits<{ select: [key: string] }>();
const open = ref(false);
const address = ref('');
const busy = ref('');
const error = ref('');

const cur = computed(() => props.devices.find(d => d.key === props.selected));
const usb = computed(() => store.usb);
function pick(key: string) { emit('select', key); open.value = false; }

// 与 ADH 同一套分组与行结构：在线/离线分组 + 行内动作
const groups = computed(() => [
  { label: '在线', rows: props.devices.filter(d => d.online !== false) },
  { label: '离线', rows: props.devices.filter(d => d.online === false) },
].filter(g => g.rows.length));

function onDocClick(e: MouseEvent) {
  if (!(e.target as HTMLElement).closest('.device-picker')) open.value = false;
}
onMounted(() => document.addEventListener('click', onDocClick));
onUnmounted(() => document.removeEventListener('click', onDocClick));

// 服务端只回错误码，这里翻成用户能看懂的一句话；原始码留在 title 里便于排障
const ERRORS: Record<string, string> = {
  invalid_address: '地址无效，例如 192.168.1.20:8088',
  invalid_device_request: '请求格式不对',
  not_a_device: '这个地址不是设备（像是某个 App 的面板）',
  unknown_device: '列表里已经没有这台设备，请刷新',
  device_unavailable: '连不上该设备',
  no_saved: '面板以 --no-saved 启动，不能修改设备列表',
  unreachable: '连接不通',
};
function describeError(e: unknown): string {
  const raw = e instanceof Error ? e.message : String(e);
  return ERRORS[raw] ?? `操作失败：${raw}`;
}

async function add() {
  error.value = '';
  busy.value = 'add';
  try {
    await addDeviceByAddress(address.value);
    toast(`已添加设备 ${address.value.trim()}`);
    address.value = '';
  } catch (e) {
    error.value = describeError(e);
  } finally {
    busy.value = '';
  }
}

async function addUsb(udid: string) {
  error.value = '';
  busy.value = `usb:${udid}`;
  try {
    await addUsbDeviceById(udid);
    toast('已添加 USB 设备');
  } catch (e) {
    error.value = describeError(e);
  } finally {
    busy.value = '';
  }
}

async function reconnect(d: DeviceView) {
  error.value = '';
  busy.value = d.key;
  try {
    const result = await reconnectDeviceById(d.key);
    toast(result.online
      ? `已重连 ${d.label}`
      : `${d.label} 仍无法连接（${ERRORS[result.error ?? ''] ?? result.error ?? 'unreachable'}）`);
  } catch (e) {
    error.value = describeError(e);
  } finally {
    busy.value = '';
  }
}

async function remove(d: DeviceView) {
  error.value = '';
  busy.value = d.key;
  try {
    await removeDeviceById(d.key);
    toast(`已删除 ${d.label}`);
  } catch (e) {
    error.value = describeError(e);
  } finally {
    busy.value = '';
  }
}
</script>

<template>
  <section class="device-picker" @keydown.esc.stop="open = false; ($event.currentTarget as HTMLElement).querySelector('button')?.focus()">
    <button type="button" class="device-context" :aria-expanded="open" title="切换设备" @click.stop="open = !open">
      <span class="context-label">设备</span>
      <strong>{{ cur?.label || (failed ? '设备读取失败' : '选择设备') }}</strong>
      <span class="device-link">{{ cur?.online === false ? '离线' : cur?.online ? '在线' : '' }}</span>
      <span class="menu-chevron"><n-icon size="11" :component="ChevronDownOutline" /></span>
    </button>
    <div class="popover device-menu" :class="{ show: open }">
      <div class="device-menu-label">设备</div>
      <template v-for="g in groups" :key="g.label">
        <div class="app-section">{{ g.label }}</div>
        <div v-for="d in g.rows" :key="d.key" class="device-row">
          <button type="button" class="app-item" :class="{ active: d.key === selected }" :disabled="busy === d.key"
            @click="pick(d.key)">
            <span class="app-copy">
              <span class="app-name">
                <span class="status-dot" :class="d.online === false ? 'bad' : 'ok'"
                  style="margin-right:7px"></span>{{ d.label }}</span>
              <span class="app-pkg">{{ d.address }}</span>
            </span>
          </button>
          <span class="device-row-actions">
            <n-button size="tiny" :disabled="!!busy" :title="`重连 ${d.label}`" :aria-label="`重连 ${d.label}`"
              @click.stop="reconnect(d)">
              <template #icon><n-icon :component="RefreshOutline" /></template>
              重连
            </n-button>
            <n-popconfirm @positive-click="remove(d)">
              <template #trigger>
                <n-button size="tiny" type="error" text :disabled="!!busy" :title="`删除 ${d.label}`"
                  :aria-label="`删除 ${d.label}`" @click.stop>删除</n-button>
              </template>
              删除设备 {{ d.label }}？只删这台电脑上的连接记录，不影响手机上的 IDH。
            </n-popconfirm>
          </span>
        </div>
      </template>
      <div v-if="!devices.length" class="app-empty">{{ store.devicesLoading ? '正在读取设备…' : '没有设备' }}</div>

      <template v-if="usb.length">
        <div class="app-section">USB 设备</div>
        <div v-for="udid in usb" :key="udid" class="device-row">
          <span class="app-pkg device-usb-id">{{ udid }}</span>
          <span class="device-row-actions">
            <n-button size="tiny" :disabled="!!busy" :aria-label="`添加 USB 设备 ${udid}`" @click.stop="addUsb(udid)">
              添加
            </n-button>
          </span>
        </div>
      </template>

      <div class="device-add">
        <n-input v-model:value="address" size="small" placeholder="设备地址，如 192.168.1.20:8088"
          :input-props="{ 'aria-label': '新设备地址' }" :disabled="busy === 'add'" @keyup.enter="add" />
        <n-button size="small" :disabled="busy === 'add' || !address.trim()" @click="add">添加</n-button>
      </div>
      <div v-if="error" class="device-error" role="alert" :title="error">{{ error }}</div>
    </div>
  </section>
</template>
