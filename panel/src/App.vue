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
          <svg class="hdr-raven" viewBox="0 0 281 251" fill="currentColor" aria-hidden="true"><g fill-rule="evenodd"><path d="M8,36L4,46L19,45L33,48L41,48L50,50L50,52L53,51L55,53L54,56L58,57L57,65L59,66L58,72L54,78L56,77L60,78L56,90L54,93L49,97L53,97L57,95L60,92L60,95L58,98L55,107L55,112L54,114L56,110L60,109L58,115L58,129L61,138L62,127L64,121L66,119L68,121L68,132L70,141L77,158L82,165L80,156L81,137L84,147L90,158L92,160L100,177L101,181L101,188L103,182L103,169L101,163L102,159L106,164L110,172L109,166L111,165L124,178L127,184L127,189L110,205L106,207L96,206L90,207L86,211L86,215L89,212L95,213L125,212L128,211L154,211L165,212L169,214L168,210L165,207L146,204L156,196L163,189L164,194L167,186L169,188L171,180L175,180L184,183L191,187L205,202L223,227L232,236L238,240L247,244L257,246L266,246L268,245L268,242L264,237L267,236L276,237L276,233L263,220L236,189L239,189L247,193L249,193L256,197L265,200L273,201L258,185L228,157L231,156L234,158L239,159L239,156L237,151L224,134L207,115L196,95L188,84L176,73L160,64L158,62L155,61L150,56L145,46L147,46L139,37L142,36L146,38L129,21L127,20L130,19L128,17L122,14L120,12L106,6L95,4L79,5L69,8L61,15L50,17L44,17L27,22L16,28Z"/>
    <path d="M151,180L153,184L153,189L138,204L135,206L123,207L118,205L125,198L131,194L140,186L143,179L147,176Z"/>
    <path d="M97,114L104,135L98,129L96,125L95,116Z"/>
    <path d="M125,68L140,68L147,71L130,72L126,73L122,75L119,78L115,86L115,99L117,108L122,118L128,127L133,133L148,147L146,148L135,140L123,128L114,115L114,113L111,108L108,98L108,88L110,81L113,76L117,72Z"/>
    <path d="M88,53L100,60L104,66L103,70L99,64L101,77L99,80L97,76L97,72L95,68L95,79L90,94L89,101L87,98L87,83L82,93L81,98L82,113L81,116L76,107L75,102L76,86L70,96L69,92L71,88L71,84L68,85L68,83L73,79L74,73L76,69L78,72L78,78L80,71L79,67L80,64L84,70L84,77L84,64L83,59L86,62L89,68L89,71L89,67L87,62L89,59L92,62L87,55Z"/>
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
