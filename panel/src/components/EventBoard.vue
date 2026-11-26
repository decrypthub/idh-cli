<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted, nextTick } from 'vue';
import { store, displayState, refresh, saveLocal, toast, downloadText, loadOlder, clearDeviceEvents } from '../store';
import { I } from '../icons';
import {
  CATEGORIES, PHASES, BOARD_CATS, getCategory, getPhase, titleFor, sizeLabel, shortTime, longTime, fmt,
  cleanEvent, type EventItem,
} from '../model';
import EventDetail from './EventDetail.vue';

// 板块 → 类别（共享定义在 model.ts；设备拉取按同一类别过滤，见 store.ts）
const cats = computed(() => BOARD_CATS[store.tab] ?? []);

const q = ref('');
const phase = ref('all');
const category = ref('all');
const sort = ref<'asc' | 'desc'>('desc');
const hideUpdates = ref(false);
const compact = ref(loadView().compact);
const width = ref(loadView().width);
const menu = ref<'' | 'filter' | 'more'>('');
const filterOpen = ref(store.prefs.advancedFilters);
const clearConfirm = ref(false);
const deviceClearConfirm = ref(false);
const clearing = ref(false);
// 设备上未加载的更早记录数（总数 − 已加载）
const olderLeft = computed(() => Math.max(0, store.eventTotal - store.events.length));

async function confirmDeviceClear() {
  clearing.value = true;
  const ok = await clearDeviceEvents();
  clearing.value = false;
  deviceClearConfirm.value = false;
  toast(ok ? '设备记录已清理' : '清理失败，请重试');
}

const VIEW_KEY = 'idh_workspace_view_v1';
function loadView() {
  const v = (() => { try { return JSON.parse(localStorage.getItem(VIEW_KEY) ?? '{}'); } catch { return {}; } })();
  return { compact: v.compact === true, width: Number.isFinite(v.width) ? v.width : 410 };
}
function persistView() { saveLocal(VIEW_KEY, { compact: compact.value, width: width.value }); }

const board = computed(() => displayState());
const highWater = () => store.session?.lastSeq ?? 0;

const filtered = computed(() => {
  const query = q.value.trim().toLowerCase();
  const { pauseAt, clearThrough } = board.value;
  return store.events.filter((e) =>
    cats.value.includes(e.category) && store.prefs.summaryCategories[CATEGORIES[e.category]] !== false &&
    (pauseAt === null || e.seq <= pauseAt) && (clearThrough === null || e.seq > clearThrough) &&
    (category.value === 'all' || Number(category.value) === e.category) &&
    (!hideUpdates.value || !e.update) &&
    (phase.value === 'all' || phase.value === e.phase) &&
    (!query || ['#' + e.seq, e.sourceSeq, getCategory(e.category), getPhase(e.phase), e.phase,
      e.kind, e.callId, e.parentCallId, e.asyncTaskId, e.algorithm, e.operation, e.detail, e.preview,
      e.inputHex, e.outputHex, fmt(longTime, e.timeMs)]
      .some((v) => String(v ?? '').toLowerCase().includes(query))))
    .sort((a, b) => (sort.value === 'asc' ? 1 : -1) * ((a.timeMs - b.timeMs) || (a.seq - b.seq)));
});
const shown = computed(() => filtered.value.slice(0, store.limit));
const filterCount = computed(() =>
  Number(category.value !== 'all') + Number(phase.value !== 'all') + Number(sort.value !== 'desc'));
const paused = computed(() => board.value.pauseAt !== null);
const cleared = computed(() => board.value.clearThrough !== null);
const emptyTitle = computed(() =>
  store.network === 'loading' && !store.session ? '正在读取设备会话'
    : cleared.value ? '本板块显示已清空'
      : store.session ? '当前筛选没有结果' : '暂无会话摘要');
const emptyDesc = computed(() =>
  cleared.value ? '设备记录未删除。在更多菜单可恢复显示。'
    : store.session ? '切换分类或清除筛选可查看其他摘要。' : '已保存的摘要会在这里列出。');
const footerMode = computed(() =>
  paused.value ? '本板块已暂停' : cleared.value ? '本板块显示已清空'
    : store.session?.status === 'ended' ? '历史会话 · 只读'
      : store.network === 'online' ? (store.session ? '设备会话' : '暂无会话') : '正在连接');

/** 行内预览：有内容预览用预览（输入 utf8/hex），否则用详情（文件路径、请求行等） */
const previewFor = (e: EventItem) => e.preview || e.detail || '';

function select(seq: number) {
  if (!shown.value.some(e => e.seq === seq)) return;
  if (store.seq !== seq) { store.seq = seq; store.detailTab = 'data'; }
}
function togglePause() {
  if (!store.session) return;
  const b = board.value;
  b.pauseAt = b.pauseAt === null ? highWater() : null;
  if (b.pauseAt === null && store.prefs.autoRefresh) void refresh(true);
}
function confirmClear() {
  board.value.clearThrough = board.value.pauseAt ?? highWater();
  store.seq = null; store.detailTab = 'data'; store.limit = store.prefs.displayCap;
  clearConfirm.value = false; menu.value = '';
  toast('已清空本板块显示，设备记录未删除');
}
function restore() { board.value.clearThrough = null; store.limit = store.prefs.displayCap; menu.value = ''; }
function resetFilters() {
  category.value = 'all'; phase.value = 'all'; sort.value = 'desc'; hideUpdates.value = false; q.value = '';
  store.limit = store.prefs.displayCap; menu.value = '';
}
function exportEvents(scope: 'board' | 'filtered' | 'session') {
  if (!store.session) { toast('没有可导出的会话'); return; }
  const events = (scope === 'filtered' ? filtered.value
    : scope === 'board' ? store.events.filter(e => cats.value.includes(e.category))
      : store.events).map(cleanEvent);
  const suffix = scope === 'board' ? '-' + store.tab : scope === 'filtered' ? '-filtered' : '';
  downloadText('idh-app-' + store.session.bundleId + suffix + '.json',
    JSON.stringify({ session: store.session, events }, null, 2));
  menu.value = '';
}
function setPhase(v: string) { phase.value = v; menu.value = ''; store.limit = store.prefs.displayCap; }
function setSort(v: 'asc' | 'desc') { sort.value = v; menu.value = ''; store.limit = store.prefs.displayCap; }
function toggleMenu(which: 'filter' | 'more') { menu.value = menu.value === which ? '' : which; }
function onDocClick(e: MouseEvent) {
  if (!(e.target as HTMLElement).closest('.anchor')) menu.value = '';
}

// ---- 分栏拖动 ----
const workarea = ref<HTMLElement | null>(null);
const splitterEl = ref<HTMLElement | null>(null);
function setWidth(px: number, persist = false) {
  const area = workarea.value?.clientWidth ?? 0;
  if (!area) return;
  const max = Math.max(260, Math.min(Math.round(area * 0.65), area - 245));
  const min = window.innerWidth <= 880 ? 215 : 260;
  width.value = Math.min(max, Math.max(min, Math.round(px)));
  if (persist) persistView();
}
function splitDown(e: PointerEvent) {
  if (e.button !== 0) return;
  splitterEl.value?.setPointerCapture(e.pointerId);
  e.preventDefault();
}
function splitMove(e: PointerEvent) {
  if (!splitterEl.value?.hasPointerCapture(e.pointerId)) return;
  setWidth(e.clientX - (workarea.value?.getBoundingClientRect().left ?? 0));
}
function splitUp() { setWidth(width.value, true); }
function splitKey(e: KeyboardEvent) {
  if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
    e.preventDefault(); e.stopPropagation();
    setWidth(width.value + (e.key === 'ArrowLeft' ? -20 : 20), true);
  }
}

// ---- 键盘导航 ----
const searchEl = ref<HTMLInputElement | null>(null);
function onKey(e: KeyboardEvent) {
  if (document.querySelector('.modal-mask')) return;
  if ((e.target as HTMLElement).closest('input,textarea,select,[contenteditable]')) return;
  if (e.key === '/' && !e.ctrlKey && !e.metaKey) { e.preventDefault(); searchEl.value?.focus(); return; }
  if (!shown.value.length || menu.value || !['j', 'k', 'ArrowDown', 'ArrowUp'].includes(e.key)) return;
  if (e.key.startsWith('Arrow') && !(e.target as HTMLElement).closest('.event-list,.splitter,body')) return;
  const prev = shown.value.findIndex(r => r.seq === store.seq);
  const dir = (e.key === 'j' || e.key === 'ArrowDown') ? 1 : -1;
  e.preventDefault();
  const row = shown.value[Math.max(0, Math.min(shown.value.length - 1, prev < 0 ? 0 : prev + dir))];
  select(row.seq);
  nextTick(() => document.querySelector(`.event-row[data-seq="${row.seq}"]`)?.scrollIntoView({ block: 'nearest' }));
}
onMounted(() => {
  document.addEventListener('click', onDocClick);
  document.addEventListener('keydown', onKey);
  void refresh(true);
});
onUnmounted(() => { document.removeEventListener('click', onDocClick); document.removeEventListener('keydown', onKey); });
</script>

<template>
  <div class="board-wrap">
    <h1 class="board-heading">{{ ({ crypto:'加解密',sys:'系统',net:'网络',keychain:'Keychain',other:'其他' } as Record<string,string>)[store.tab] }}</h1>
    <div class="toolbar">
      <div class="toolbar-group toolbar-left">
        <label class="search-wrap">
          <svg class="ico sm" viewBox="0 0 20 20" v-html="I.search" />
          <input ref="searchEl" v-model="q" type="search" class="search-input" aria-label="搜索事件"
            placeholder="搜索序号、类别、阶段、关联 ID…" autocomplete="off" @input="store.limit = store.prefs.displayCap" />
          <kbd class="search-kbd" aria-hidden="true">/</kbd>
        </label>
        <div class="anchor">
          <button class="btn" type="button" :aria-expanded="menu === 'filter'" @click="toggleMenu('filter')">
            <svg class="ico sm" viewBox="0 0 20 20" v-html="I.filter" /><span>{{ filterCount ? '筛选 · ' + filterCount : '筛选' }}</span>
            <svg class="ico sm" viewBox="0 0 20 20" v-html="I.chevron" />
          </button>
          <div class="dropdown" :hidden="menu !== 'filter'">
            <label class="dropdown-head" for="catFilter">事件类别</label>
            <select id="catFilter" class="filter-select" v-model="category" @change="store.limit = store.prefs.displayCap">
              <option value="all">全部类别</option>
              <option v-for="c in cats" :key="c" :value="String(c)">{{ getCategory(c) }}</option>
            </select>
            <div class="dropdown-divider"></div>
            <div class="dropdown-head">事件阶段</div>
            <div role="group" aria-label="事件阶段">
              <button class="dropdown-item" type="button" @click="setPhase('all')">全部阶段
                <svg v-if="phase === 'all'" class="ico sm" viewBox="0 0 20 20" v-html="I.check" /></button>
              <button v-for="(label, key) in PHASES" :key="key" class="dropdown-item" type="button" @click="setPhase(key)">
                {{ label }}<svg v-if="phase === key" class="ico sm" viewBox="0 0 20 20" v-html="I.check" /></button>
            </div>
            <div class="dropdown-divider"></div>
            <div class="dropdown-head">列表排序</div>
            <div role="group" aria-label="列表排序">
              <button class="dropdown-item" type="button" @click="setSort('desc')">最新优先
                <svg v-if="sort === 'desc'" class="ico sm" viewBox="0 0 20 20" v-html="I.check" /></button>
              <button class="dropdown-item" type="button" @click="setSort('asc')">最早优先
                <svg v-if="sort === 'asc'" class="ico sm" viewBox="0 0 20 20" v-html="I.check" /></button>
            </div>
          </div>
        </div>
      </div>
      <div class="toolbar-group toolbar-right">
        <span class="toolbar-stat"><strong>{{ filtered.length }}</strong> / {{ store.events.length }} 条</span>
        <button class="btn sm" type="button" :disabled="!store.session" :aria-pressed="paused" @click="togglePause">
          <svg class="ico sm" viewBox="0 0 20 20" v-html="paused ? I.play : I.pause" />{{ paused ? '继续刷新' : '暂停刷新' }}</button>
        <div class="anchor">
          <button class="btn icon-only" type="button" aria-label="更多操作" :aria-expanded="menu === 'more'" @click="toggleMenu('more')">
            <svg class="ico" viewBox="0 0 20 20" v-html="I.more" /></button>
          <div class="dropdown right" :hidden="menu !== 'more'">
<button class="dropdown-item" type="button" :aria-pressed="compact" @click="compact = !compact; persistView(); menu = ''">{{ compact ? '使用标准行距' : '使用紧凑行距' }}</button>
        <button class="dropdown-item" type="button" :aria-pressed="hideUpdates"
          title="只影响当前列表，不修改设备记录" @click="hideUpdates = !hideUpdates; menu = ''">{{ hideUpdates ? '显示更新' : '隐藏更新' }}</button>

            <button class="dropdown-item" type="button" :disabled="!store.session" @click="exportEvents('board')">下载当前板块</button>
            <button class="dropdown-item" type="button" :disabled="!store.session" @click="exportEvents('filtered')">导出当前筛选结果</button>
            <button class="dropdown-item" type="button" :disabled="!store.session" @click="exportEvents('session')">下载完整应用记录</button>
            <div class="dropdown-divider"></div>
            <button class="dropdown-item" type="button" :disabled="!store.session" @click="clearConfirm = true; menu = ''">清空本板块显示</button>
            <button v-if="cleared" class="dropdown-item" type="button" @click="restore">恢复本板块显示</button>
            <button class="dropdown-item" type="button" :disabled="!store.session" @click="deviceClearConfirm = true; menu = ''">清理设备上该应用记录</button>
            <button class="dropdown-item" type="button" @click="resetFilters">清空搜索与筛选</button>
            <button class="dropdown-item" type="button" @click="refresh(true); menu = ''">重新读取设备</button>
            <div class="dropdown-divider"></div>
            <button class="dropdown-item" type="button" @click="store.tab = 'settings'; store.settingsPage = 'rawcfg'; menu = ''">配置 JSON</button>
            <button class="dropdown-item" type="button" @click="store.wechatOpen = true; menu = ''">公众号</button>
          </div>
        </div>
      </div>
    </div>

    <div ref="workarea" class="workarea" :class="{ reading: store.seq !== null, 'no-results': !shown.length && !store.seq }">
      <aside class="events-panel" :style="{ width: width + 'px' }" aria-label="事件记录">
        <div v-if="store.seq === null && shown.length" class="ledger-head idh-grid" aria-hidden="true"><span>序号</span><span>事件</span><span>内容预览</span><span>阶段 / 大小</span><span>时间</span></div>
        <div class="event-list" :class="{ compact }" tabindex="0" aria-label="事件列表">
          <button v-for="e in shown" :key="e.seq" class="event-row row" :class="['cat-' + (CATEGORIES[e.category] ?? 'other'), { selected: e.seq === store.seq }]"
            type="button" :data-seq="e.seq" :aria-pressed="e.seq === store.seq" @click="select(e.seq)">
            <span class="event-index">#{{ e.seq }}</span>
            <span class="event-body">
              <span class="event-top"><span class="event-name">{{ titleFor(e) }}</span>
                <time class="event-time">{{ fmt(shortTime, e.timeMs) }}</time></span>
              <span class="event-sub"><span class="pill phase" :class="{ aborted: e.phase === 'aborted' }">{{ getPhase(e.phase) }}</span>
                <span v-if="e.update" class="pill">更新</span>
                <span v-if="sizeLabel(e)" class="event-io">{{ sizeLabel(e) }}</span>
                <span v-if="e.callId || e.sourceSeq != null" class="event-source">{{ e.callId ? '关联 ' + e.callId : '原记录 #' + (e.sourceSeq ?? '—') }}</span></span>
              <span v-if="previewFor(e)" class="event-preview">{{ previewFor(e) }}</span>
            </span>
          </button>
          <button v-if="shown.length < filtered.length" type="button" class="btn sm load-more"
            @click="store.limit += store.prefs.displayCap">继续加载 · {{ filtered.length - shown.length }} 条</button>
          <button v-if="store.hasOlder" type="button" class="btn sm load-more" :disabled="store.loadingOlder"
            @click="loadOlder">{{ store.loadingOlder ? '正在加载…' : '加载更早 · 设备还有 ' + olderLeft + ' 条' }}</button>
          <div v-if="!shown.length" class="empty-state">
            <strong>{{ emptyTitle }}</strong><p>{{ emptyDesc }}</p>
          </div>
        </div>
        <div class="event-footer">
          <span><span class="status-dot" :class="{ warn: paused || cleared, ok: store.session?.status === 'observing' }"></span>{{ footerMode }}</span>
          <span>{{ sort === 'asc' ? '按时间正序' : '按时间倒序' }}</span>
        </div>
      </aside>
      <div ref="splitterEl" class="splitter" tabindex="0" role="separator" aria-label="调整事件列表宽度"
        aria-orientation="vertical" @pointerdown="splitDown" @pointermove="splitMove" @lostpointercapture="splitUp"
        @keydown="splitKey"></div>
      <main class="detail-pane" aria-label="事件详情"><button v-if="store.seq !== null" type="button" class="mobile-return" @click="store.seq = null">‹ 返回列表</button><EventDetail /></main>
    </div>

    <div v-if="clearConfirm" class="modal-mask show" @click.self="clearConfirm = false">
      <div class="dialog-card" role="alertdialog" aria-label="清空显示确认">
        <p id="clearPrompt">清空本板块当前显示的已保存摘要？</p>
        <div class="dialog-actions">
          <button class="btn sm" type="button" @click="clearConfirm = false">取消</button>
          <button class="btn sm danger" type="button" @click="confirmClear">清空显示</button>
        </div>
      </div>
    </div>
    <div v-if="deviceClearConfirm" class="modal-mask show" @click.self="deviceClearConfirm = false">
      <div class="dialog-card" role="alertdialog" aria-label="清理设备记录确认">
        <p>删除设备上该应用的全部已保存记录？此操作不可恢复。</p>
        <div class="dialog-actions">
          <button class="btn sm" type="button" @click="deviceClearConfirm = false">取消</button>
          <button class="btn sm danger" type="button" :disabled="clearing" @click="confirmDeviceClear">{{ clearing ? '正在清理…' : '清理设备记录' }}</button>
        </div>
      </div>
    </div>
  </div>
</template>
