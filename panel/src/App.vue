<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue';
import { store, toasts, refresh, loadDevices, saveLocal } from './store';
import { I } from './icons';
import DeviceMenu from './components/DeviceMenu.vue';
import AppDialog from './components/AppDialog.vue';
import EventBoard from './components/EventBoard.vue';
import InjectPanel from './components/InjectPanel.vue';
import ToolStub from './components/ToolStub.vue';
import SettingsPanel from './components/SettingsPanel.vue';
import DiagDialog from './components/DiagDialog.vue';
import McpDialog from './components/McpDialog.vue';
import WechatDialog from './components/WechatDialog.vue';

type ViewKey = 'crypto' | 'sys' | 'net' | 'keychain' | 'other' | 'inject' | 'files' | 'symbols' | 'dump' | 'settings';
const NAV: Array<{ key: ViewKey; label: string; icon: string; cats?: number[] }> = [
  { key: 'crypto', label: '加解密', icon: I.lock, cats: [0, 1, 2, 3] },
  { key: 'sys', label: '系统', icon: I.cpu, cats: [4, 5] },
  { key: 'net', label: '网络', icon: I.wifi, cats: [6] },
  { key: 'keychain', label: 'Keychain', icon: I.key, cats: [7] },
  { key: 'other', label: '其他', icon: I.list, cats: [8] },
];
const TOOLS: Array<{ key: ViewKey; label: string; icon: string }> = [
  { key: 'inject', label: '注入范围', icon: I.inject },
  { key: 'files', label: '文件', icon: I.folder },
  { key: 'symbols', label: '符号', icon: I.code },
  { key: 'dump', label: 'Dump', icon: I.dump },
];

const counts = computed(() => {
  const c: Record<string, number> = {};
  for (const item of NAV) c[item.key] = store.events.reduce((s, e) => s + Number(item.cats!.includes(e.category)), 0);
  return c;
});

const RAIL_KEY = 'idh.panel.rail';
const rail = ref(loadRail());
function loadRail() { try { return localStorage.getItem(RAIL_KEY) === '1'; } catch { return false; } }
function toggleRail() { rail.value = !rail.value; saveLocal(RAIL_KEY, rail.value ? 1 : 0); }

const netText = computed(() =>
  store.network === 'online' ? '设备在线' : store.network === 'offline' ? '设备离线' : '正在连接');
const netCls = computed(() =>
  `status-dot ${store.network === 'online' ? 'ok' : store.network === 'offline' ? 'off' : ''}`);
const appName = computed(() => {
  const a = store.apps.find(x => x.bundleId === store.selected)
    ?? store.installed.find(x => x.bundleId === store.selected);
  return a?.name || store.selected || '应用记录';
});
const appMeta = computed(() => {
  const a = store.apps.find(x => x.bundleId === store.selected);
  if (a) return [a.status === 'ended' ? '已结束' : a.status, a.sessions > 1 ? `${a.sessions} 个会话` : '', `${a.count} 条`].filter(Boolean).join(' · ');
  return store.selected ? '暂无此应用的记录' : '';
});
const appInitial = computed(() => (appName.value[0] ?? '?').toUpperCase());

let poll = 0;
onMounted(() => {
  void loadDevices();
  void refresh(true);
  poll = window.setInterval(() => { if (store.prefs.autoRefresh) void refresh(); }, 1500);
});
onUnmounted(() => clearInterval(poll));
</script>

<template>
  <div class="app-shell">
    <aside class="side" :class="{ rail }">
      <div class="side-brand">
        <span class="hdr-mark">
          <svg viewBox="0 0 100 100" width="26" height="26" aria-hidden="true"><g fill="#06070a">
            <path d="M30,18C50,10 75,14 82,30C90,48 88,70 72,82C55,95 30,90 18,72C8,55 12,30 30,18Z" fill="#fff" opacity="0"/>
            <path d="M28,38L34,38L42,36L59,36L66,37L69,41Z"/>
            <path d="M10,40L16,33L24,27L40,22L47,23L43,26L47,26L50,28L49,30L57,30L65,32L71,35L73,37L70,38L65,36L57,35L43,35L21,38L13,41Z"/>
            <path d="M89,20L92,23L92,28L89,31L84,32L80,29L79,27L87,28L89,25L85,24L85,22L87,20Z"/></g></svg>
        </span>
        <span class="side-title">IDH</span>
      </div>
      <nav class="side-nav">
        <div class="side-group">观测</div>
        <button v-for="item in NAV" :key="item.key" class="side-item" :title="item.label"
          :class="{ active: store.tab === item.key }" @click="store.tab = item.key">
          <svg class="side-icon" viewBox="0 0 20 20" v-html="item.icon" />
          <span class="side-label">{{ item.label }}</span>
          <span class="side-n">{{ counts[item.key] || '' }}</span>
        </button>
        <div class="side-group">工具</div>
        <button v-for="item in TOOLS" :key="item.key" class="side-item" :title="item.label"
          :class="{ active: store.tab === item.key }" @click="store.tab = item.key">
          <svg class="side-icon" viewBox="0 0 20 20" v-html="item.icon" />
          <span class="side-label">{{ item.label }}</span>
        </button>
      </nav>
      <div class="side-foot">
        <button class="side-item" :class="{ active: store.tab === 'settings' }" title="设置"
          @click="store.tab = 'settings'">
          <svg class="side-icon" viewBox="0 0 20 20" v-html="I.gear" />
          <span class="side-label">设置</span>
        </button>
        <button class="side-item side-collapse" :title="rail ? '展开导航' : '收起导航'" @click="toggleRail">
          <svg class="side-icon" viewBox="0 0 20 20" v-html="I.collapse" />
          <span class="side-label">收起</span>
        </button>
      </div>
    </aside>

    <div class="main-col">
      <header class="topbar">
        <div class="stats">
          <span :class="netCls"></span>
          <span>{{ netText }}</span>
          <span v-if="store.device?.version" class="protocol">会话协议 {{ store.device.version }}</span>
        </div>
        <DeviceMenu />
        <div class="header-actions">
          <section class="app-context">
            <button type="button" class="process-trigger" title="切换应用" @click="store.appDialogOpen = true">
              <span class="proc-primary">
                <span class="app-face proc-face">
                  <span class="app-dialog-letter">{{ appInitial }}</span>
                  <img v-if="store.selected" :src="'/api/apps/' + encodeURIComponent(store.selected) + '/icon'" alt=""
                    @error="($event.target as HTMLElement).style.display = 'none'" />
                </span>
                <span class="proc-text">
                  <span id="procLabel">{{ appName }}</span>
                  <span class="proc-pkg">{{ appMeta || store.selected }}</span>
                </span>
              </span>
              <span class="menu-chevron"><svg viewBox="0 0 12 12" width="10" height="10" fill="none"
                  stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">
                  <path d="M2.5 4.5l3.5 3.5 3.5-3.5" /></svg></span>
            </button>
          </section>
          <button type="button" class="hdr-btn" title="查看设备与会话诊断" @click="store.diagOpen = true">
            <svg viewBox="0 0 20 20" class="hdr-ico" v-html="I.info" />诊断</button>
          <button type="button" class="hdr-btn" title="MCP 连接" @click="store.mcpOpen = true">
            <svg viewBox="0 0 20 20" class="hdr-ico" v-html="I.terminal" />MCP</button>
        </div>
      </header>

      <div v-if="store.network === 'offline'" class="notice warn">暂时无法读取设备。已加载的摘要保留，可从更多菜单重试。</div>
      <div v-if="store.sessionNotice" class="notice">{{ store.sessionNotice }}</div>

      <main class="panel-body">
        <EventBoard v-if="['crypto', 'sys', 'net', 'keychain', 'other'].includes(store.tab)" :key="store.tab" />
        <InjectPanel v-else-if="store.tab === 'inject'" />
        <ToolStub v-else-if="store.tab === 'files'" kind="files" />
        <ToolStub v-else-if="store.tab === 'symbols'" kind="symbols" />
        <ToolStub v-else-if="store.tab === 'dump'" kind="dump" />
        <SettingsPanel v-else-if="store.tab === 'settings'" />
      </main>
    </div>

    <AppDialog v-if="store.appDialogOpen" />
    <DiagDialog v-if="store.diagOpen" />
    <McpDialog v-if="store.mcpOpen" />
    <WechatDialog v-if="store.wechatOpen" />
    <div class="toast-stack">
      <div v-for="t in toasts" :key="t.id" class="toast">{{ t.text }}</div>
    </div>
  </div>
</template>
