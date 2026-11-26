<script setup lang="ts">
import { computed, reactive, ref, watch, onMounted, onUnmounted } from 'vue';
import { store, belongsToApp, capRemoveWhere, capVisible, capDisplayCap, DISPLAY_CAPS, panelDisplay, savePanelDisplay, toast } from '../store';
import { getEvents, type DhEvent } from '../api';
import { catClass, cryptoView, rowLens, fmtTime, CATLABEL, type CatKey } from '../capview';
import { SearchOutline } from '@vicons/ionicons5';
import CapDetail from './CapDetail.vue';

const props = defineProps<{ kind: 'crypto' | 'system' | 'net' | 'keychain' }>();

const filter = reactive({
  q: '', min: null as number | null, max: null as number | null,
  cat: -2, paused: false, kind: 'all',
});
const advOpen = ref(false);
const sel = ref<number | null>(null);
const selDetail = ref<DhEvent | null>(null);
const scrollTop = ref(0);
const newCount = ref(0);
let lastShown = 0;

// ---- 分页与时间窗口状态 ----
const cursorStack = ref<Array<number | null>>([]);
const currentBeforeSeq = ref<number | null>(null);
const pagedItems = ref<DhEvent[] | null>(null);
const pagedHasMore = ref(false);
const pageLoading = ref(false);

// 时间范围：毫秒时间戳，n-date-picker 直接绑定。服务端不支持时间窗查询，按客户端过滤已加载记录。
const fromMs = ref<number | null>(null);
const toMs = ref<number | null>(null);
const fromTs = computed(() => fromMs.value);
const toTs = computed(() => toMs.value);
const hasTimeRange = computed(() => fromTs.value !== null || toTs.value !== null);
const isHistoricalMode = computed(() => pagedItems.value !== null);

const CAT_BY_SEL: Record<number, CatKey> = { 0: 'digest', 1: 'hmac', 2: 'sym', 3: 'asym' };
const SYS_KINDS: Array<[string, string]> = [['all', '全部活动'], ['system', '系统调用'], ['file', '文件读写']];
const LIST_ID: Record<string, string> = { crypto: 'cc-list', system: 'sy-list', net: 'nt-list', keychain: 'kc-list' };
const HEAD_LABELS: Record<string, [string, string, string]> = {
  crypto: ['算法', '内容预览', '输入 → 输出'],
  system: ['函数', '内容预览', '操作'],
  net: ['操作', '内容预览', '对端'],
  keychain: ['操作', '内容预览', '状态'],
};

function matchesPanel(c: DhEvent): boolean {
  if (props.kind === 'crypto') {
    if (c.category > 3) return false;
  } else if (props.kind === 'system') {
    if (c.category !== 4 && c.category !== 5) return false;
    if (filter.kind !== 'all') return c.category === (filter.kind === 'file' ? 4 : 5);
  } else if (props.kind === 'net') {
    if (c.category !== 6) return false;
  } else if (props.kind === 'keychain') {
    if (c.category !== 7) return false;
  }
  return true;
}

function serverCategories(): string {
  if (props.kind === 'crypto') return '0,1,2,3';
  if (props.kind === 'system') return filter.kind === 'all' ? '4,5' : filter.kind === 'file' ? '4' : '5';
  if (props.kind === 'net') return '6';
  return '7';
}

function applyClientFilter(source: DhEvent[]): DhEvent[] {
  let items = source.filter(c => matchesPanel(c) && belongsToApp(c) && capVisible(c));
  if (fromTs.value != null) items = items.filter(c => c.timeMs >= fromTs.value!);
  if (toTs.value != null) items = items.filter(c => c.timeMs <= toTs.value!);
  const q = filter.q.trim().toLowerCase();
  if (q) {
    items = items.filter(c => {
      if (/^#\d+$/.test(q)) return String(c.seq) === q.slice(1);
      const v = c.category <= 3 ? cryptoView(c) : null;
      return ((c.algorithm || '') + ' ' + (c.operation || '') + ' ' + (c.detail || '') + ' ' +
        (c.preview || '') + ' ' + (v?.title || '') + ' ' + (v?.direction || ''))
        .toLowerCase().includes(q);
    });
  }
  if (filter.min != null) items = items.filter(c => (c.inLen ?? 0) >= filter.min!);
  if (filter.max != null) items = items.filter(c => (c.inLen ?? 0) <= filter.max!);
  if (props.kind === 'crypto' && filter.cat >= 0) {
    items = items.filter(c => c.category === filter.cat);
  }
  return items;
}

// 本板块归属当前应用的记录（过滤前）
const scoped = computed(() => store.capItems.filter(c => matchesPanel(c)));

const visible = computed(() => applyClientFilter(pagedItems.value ?? store.capItems));

async function loadServerPage(beforeSeq: number | null) {
  if (!store.chosenPkg) return;
  const pkg = store.chosenPkg;
  pageLoading.value = true;
  try {
    const r = await getEvents(pkg, {
      categories: serverCategories(),
      before: beforeSeq ?? undefined,
      limit: capDisplayCap.value,
    });
    if (store.chosenPkg !== pkg) return;
    pagedItems.value = r.events ?? [];
    pagedHasMore.value = !!r.hasOlder;
    currentBeforeSeq.value = beforeSeq;
    const el = document.getElementById(LIST_ID[props.kind]);
    el?.scrollTo({ top: 0 });
  } catch {
    toast('读取分页记录失败');
  } finally {
    pageLoading.value = false;
  }
}

const frozenRows = ref<DhEvent[]>([]);
const liveOrPagedRows = computed(() => visible.value.slice(-capDisplayCap.value).reverse());
const rows = computed(() => (filter.paused && !isHistoricalMode.value && frozenRows.value.length ? frozenRows.value : liveOrPagedRows.value));
watch(() => filter.paused, p => {
  frozenRows.value = p ? [...liveOrPagedRows.value] : [];
});

const pageNumber = computed(() => cursorStack.value.length + 1);
const canPrevPage = computed(() => {
  if (pageLoading.value) return false;
  if (isHistoricalMode.value) return pagedHasMore.value && rows.value.length > 0;
  const bucketKey = props.kind === 'crypto' ? 'crypto' : props.kind === 'net' ? 'net' : props.kind === 'keychain' ? 'keychain' : 'system';
  return rows.value.length > 0 && (visible.value.length > capDisplayCap.value || store.capHasOlder[bucketKey]);
});
const canNextPage = computed(() => {
  if (pageLoading.value) return false;
  return cursorStack.value.length > 0;
});

async function prevPage() {
  if (!canPrevPage.value) return;
  const oldestShown = rows.value.at(-1)?.seq;
  if (oldestShown == null) return;
  cursorStack.value.push(currentBeforeSeq.value);
  await loadServerPage(oldestShown);
}
async function nextPage() {
  if (!canNextPage.value) return;
  const prevCursor = cursorStack.value.pop() ?? null;
  if (cursorStack.value.length === 0 && prevCursor === null && !hasTimeRange.value) {
    currentBeforeSeq.value = null;
    pagedItems.value = null;
    const el = document.getElementById(LIST_ID[props.kind]);
    el?.scrollTo({ top: 0 });
    return;
  }
  await loadServerPage(prevCursor);
}

function setQuickMinutes(mins: number) {
  fromMs.value = Date.now() - mins * 60_000;
  toMs.value = null;
}
function clearTimeRange() {
  fromMs.value = null;
  toMs.value = null;
  cursorStack.value = [];
  currentBeforeSeq.value = null;
  pagedItems.value = null;
}

function onPageCapChange(val: number) {
  if (DISPLAY_CAPS.includes(val)) {
    savePanelDisplay({ ...panelDisplay, limit: val });
    if (isHistoricalMode.value) void loadServerPage(currentBeforeSeq.value);
  }
}

// 新记录横幅：暂停或滚离顶部时累计
watch(liveOrPagedRows, () => {
  if ((filter.paused || scrollTop.value > 48) && !isHistoricalMode.value) {
    const diff = liveOrPagedRows.value.length - lastShown;
    if (diff > 0) newCount.value += diff;
  } else newCount.value = 0;
  lastShown = liveOrPagedRows.value.length;
});

const countText = computed(() => {
  const n = rows.value.length;
  const pg = pageNumber.value > 1 ? ` · 第${pageNumber.value}页` : '';
  return `${n} 条${pg}`;
});

function selectRow(c: DhEvent) {
  // IDH 事件自带全部详情字段（inputHex/keyHex 等随行内联），不需要二次读取。
  sel.value = c.seq;
  selDetail.value = c;
}
function closeDetail() { sel.value = null; selDetail.value = null; }

function onScroll(e: Event) {
  scrollTop.value = (e.target as HTMLElement).scrollTop;
  if (scrollTop.value <= 48) newCount.value = 0;
}
function jumpLatest() {
  filter.paused = false;
  cursorStack.value = [];
  currentBeforeSeq.value = null;
  pagedItems.value = null;
  scrollTop.value = 0; newCount.value = 0;
  const el = document.getElementById(LIST_ID[props.kind]);
  el?.scrollTo({ top: 0 });
}

// ---- 筛选徽标：只算高级筛选项（搜索词在框里可见）----
const advCount = computed(() => {
  let n = 0;
  if (filter.min != null || filter.max != null) n++;
  if (props.kind === 'crypto' && filter.cat >= 0) n++;
  if (props.kind === 'system' && filter.kind !== 'all') n++;
  if (hasTimeRange.value) n++;
  return n;
});
const filterActive = computed(() => !!(filter.q.trim() || advCount.value));
function resetFilter() {
  filter.q = ''; filter.min = null; filter.max = null; filter.cat = -2; filter.kind = 'all';
  clearTimeRange();
}
function downloadView() {
  const items = rows.value;
  const pkg = store.chosenPkg || 'all';
  const blob = new Blob([JSON.stringify(items, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob); a.download = `idh-${props.kind}-${pkg}-filtered.json`;
  document.body.appendChild(a); a.click(); a.remove(); URL.revokeObjectURL(a.href);
  toast(`已下载 ${items.length} 条`);
}
function clearView() {
  const pkg = store.chosenPkg;
  if (!confirm(`清空本页列表？（不删设备上的记录）\n${pkg ? '当前应用 ' + pkg : ''}`)) return;
  const n = capRemoveWhere(c => matchesPanel(c));
  closeDetail();
  toast(`已清空本页 ${n} 条`);
}

// 弹层外部点击关闭
function onDocClick(e: MouseEvent) {
  if (!(e.target as HTMLElement).closest('.filter-wrap')) advOpen.value = false;
}
const MORE_OPTS = [
  { label: '下载本页', key: 'dl' },
  { label: '清空本页', key: 'clear', props: { style: 'color:#f87171' } },
];
function onMoreSelect(k: string) { if (k === 'dl') downloadView(); else clearView(); }

// ---- 分栏拖动 ----
const listWidth = ref(0); // 0 = CSS 默认宽度
const dragging = ref(false);
function startDrag(e: MouseEvent) {
  e.preventDefault();
  const ws = (e.target as HTMLElement).parentElement!;
  const rect = ws.getBoundingClientRect();
  const move = (ev: MouseEvent) => {
    dragging.value = true;
    let w = ev.clientX - rect.left;
    w = Math.max(220, Math.min(Math.floor(rect.width * 0.7), rect.width - 260, w));
    listWidth.value = w;
  };
  const up = () => {
    document.removeEventListener('mousemove', move);
    document.removeEventListener('mouseup', up);
    dragging.value = false;
  };
  document.addEventListener('mousemove', move);
  document.addEventListener('mouseup', up);
}

onMounted(() => {
  document.addEventListener('click', onDocClick);
});
onUnmounted(() => {
  document.removeEventListener('click', onDocClick);
});
watch(() => store.chosenPkg, () => {
  sel.value = null; selDetail.value = null;
  cursorStack.value = []; currentBeforeSeq.value = null; pagedItems.value = null;
});

// 骨架屏开关：初次加载 / 切应用 / 翻历史页时，列表有行就保留旧行，没有才铺骨架
const showSkeleton = computed(() => {
  if (!store.chosenPkg) return false;
  if (store.capLoading || pageLoading.value) return !rows.value.length;
  return false;
});
const emptyText = computed(() => {
  if (!store.chosenPkg) return '先在顶部选择应用。';
  if (pageLoading.value) return '正在读取分页记录…';
  if (filterActive.value && scoped.value.length) return '没有符合筛选条件的记录。';
  if (props.kind === 'crypto') return '还没有加解密记录。';
  if (props.kind === 'net') return '还没有网络记录。';
  if (props.kind === 'keychain') return '还没有 Keychain 记录。';
  return '还没有系统事件。';
});
const listFootLeft = computed(() => {
  if (pageLoading.value) return '读取中…';
  if (hasTimeRange.value) return '时间段筛选';
  if (isHistoricalMode.value) return `历史记录 · 第 ${pageNumber.value} 页`;
  return filter.paused ? '已暂停刷新' : (store.wsState === 'live' ? '实时刷新中' : '等待连接');
});

function cryptoRow(c: DhEvent) {
  const v = cryptoView(c);
  return { ...v, cc: catClass(c) };
}
const searchPlaceholder = computed(() =>
  props.kind === 'crypto' ? '搜索 #序号、算法或预览' : '搜索 #序号、操作或预览');
</script>

<template>
  <div class="cap-view">
    <div class="filters">
      <div class="toolbar-main">
        <div class="toolbar-search">
          <n-input v-model:value="filter.q" size="small" clearable :placeholder="searchPlaceholder"
            class="toolbar-search-input">
            <template #prefix><n-icon :component="SearchOutline" class="search-ico" /></template>
          </n-input>
          <div class="menu-wrap filter-wrap">
            <n-button size="small" :secondary="!advCount" :type="advCount ? 'primary' : 'default'"
              @click="advOpen = !advOpen">
              筛选<template v-if="advCount"> · {{ advCount }}</template>
            </n-button>
            <section class="advanced-filters" :hidden="!advOpen">
              <div class="advanced-filter-head">
                <strong>事件筛选</strong>
                <n-button text size="small" type="primary" :disabled="!filterActive" @click="resetFilter">重置筛选</n-button>
              </div>
              <fieldset v-if="kind === 'system'" class="system-filter">
                <legend>活动类型</legend>
                <n-radio-group v-model:value="filter.kind" size="small">
                  <n-radio-button v-for="[k, l] in SYS_KINDS" :key="k" :value="k">{{ l }}</n-radio-button>
                </n-radio-group>
              </fieldset>
              <label v-if="kind === 'crypto'" class="filter-field">分类
                <n-select v-model:value="filter.cat" size="small" class="cat-select" :options="[
                    { label: '全部', value: -2 }, { label: '摘要', value: 0 }, { label: 'HMAC', value: 1 },
                    { label: '对称', value: 2 }, { label: '非对称', value: 3 },
                  ]" />
              </label>
              <div class="size-filter">
                <label>输入大小</label>
                <n-input-number v-model:value="filter.min" size="small" :min="0" placeholder="0" class="size-num" />
                <span class="sep">—</span>
                <n-input-number v-model:value="filter.max" size="small" :min="0" placeholder="不限" class="size-num" />
                <span class="unit">B</span>
              </div>
              <fieldset class="time-filter">
                <legend>时间范围</legend>
                <div class="time-quick">
                  <n-button size="tiny" @click="setQuickMinutes(1)">近 1 分钟</n-button>
                  <n-button size="tiny" @click="setQuickMinutes(5)">近 5 分钟</n-button>
                  <n-button size="tiny" @click="setQuickMinutes(30)">近 30 分钟</n-button>
                  <n-button v-if="hasTimeRange" size="tiny" tertiary @click="clearTimeRange">清除</n-button>
                </div>
                <div class="time-inputs">
                  <n-date-picker v-model:value="fromMs" type="datetime" size="small" clearable
                    placeholder="开始时间" />
                  <span class="sep">至</span>
                  <n-date-picker v-model:value="toMs" type="datetime" size="small" clearable
                    placeholder="结束时间" />
                </div>
              </fieldset>
            </section>
          </div>
        </div>
        <div class="toolbar-actions">
          <span id="count">{{ countText }}</span>
          <n-button size="small" :type="filter.paused ? 'warning' : 'default'" secondary
            :title="filter.paused ? '恢复列表刷新' : '只停列表刷新'"
            @click="filter.paused = !filter.paused">{{ filter.paused ? '继续' : '暂停刷新' }}</n-button>
          <n-dropdown trigger="click" :options="MORE_OPTS" @select="onMoreSelect">
            <n-button quaternary size="small" title="更多">⋯</n-button>
          </n-dropdown>
        </div>
      </div>
    </div>

    <div class="workspace capture-workspace" :class="{ 'compact-captures': panelDisplay.density === 'compact', 'detail-open': sel !== null, 'no-results': !showSkeleton && sel === null && !rows.length }">
      <div class="list-pane" :style="listWidth ? { width: listWidth + 'px' } : undefined">
        <div class="new-banner" :class="{ show: newCount > 0 }">
          <span>{{ newCount }} 条新记录</span>
          <n-button text size="tiny" type="primary" @click="jumpLatest">跳到最新</n-button>
        </div>

        <div v-if="sel === null && rows.length" class="ledger-head adh-grid" aria-hidden="true"><span>序号</span><span>{{ HEAD_LABELS[kind][0] }}</span><span>{{ HEAD_LABELS[kind][1] }}</span><span>{{ HEAD_LABELS[kind][2] }}</span><span>时间</span></div>
        <div class="cap-list" :id="LIST_ID[kind]" tabindex="0" @scroll="onScroll">
          <template v-if="showSkeleton">
            <div v-for="i in 8" :key="'sk' + i" class="row sk-row" aria-hidden="true">
              <div class="sk-line sk-a"></div>
              <div class="sk-line sk-b"></div>
            </div>
          </template>
          <template v-else>
          <div v-if="hasTimeRange" class="ex-note time-banner">
            <span>时间筛选已启用</span>
            <n-button text size="small" type="primary" @click="clearTimeRange">切回实时</n-button>
          </div>
          <div v-for="c in rows" :key="c.seq" class="row"
            :class="[`cat-${catClass(c)}`, { selected: sel === c.seq, 'crypto-row': c.category <= 3 }]"
            role="button" tabindex="0" @keydown.enter.prevent="selectRow(c)" @keydown.space.prevent="selectRow(c)" @click="selectRow(c)">
            <template v-if="c.category <= 3">
              <div class="top">
                <span class="seq">#{{ c.seq }}</span>
                <span class="algo">{{ cryptoRow(c).title }}</span>
                <span v-if="cryptoRow(c).direction" class="op">{{ cryptoRow(c).direction }}</span>
                <span v-if="cryptoRow(c).sizeLabel" class="sizes">{{ cryptoRow(c).sizeLabel }}</span>
                <span v-if="cryptoRow(c).hasKey" class="mark">有密钥</span>
                <span class="ts">{{ fmtTime(c.timeMs) }}</span>
              </div>
              <div v-if="cryptoRow(c).preview || cryptoRow(c).hook" class="subline">
                <span v-if="cryptoRow(c).preview" class="preview">{{ cryptoRow(c).preview }}</span>
                <span v-if="cryptoRow(c).hook" class="hook">{{ cryptoRow(c).hook }}</span>
              </div>
            </template>
            <template v-else>
              <div class="top">
                <span class="seq">#{{ c.seq }}</span>
                <span class="pill" :class="catClass(c)">{{ CATLABEL[catClass(c)] }}</span>
                <span class="algo">{{ c.algorithm }}</span>
                <span class="op">{{ c.operation }}</span>
                <span class="ts">{{ fmtTime(c.timeMs) }}</span>
              </div>
              <div class="lens">{{ c.detail || rowLens(c) }}</div>
              <div v-if="c.preview && c.category !== 6" class="preview">{{ c.preview }}</div>
            </template>
          </div>
          <p v-if="!rows.length" class="empty-row" role="status">{{ emptyText }}</p>
          </template>
        </div>
        <div v-if="canPrevPage || canNextPage || rows.length || isHistoricalMode" class="capture-list-foot">
          <span>{{ listFootLeft }}</span>
          <div class="pager-controls">
            <n-select :value="capDisplayCap" size="small" class="page-cap-select" title="单页返回条数上限"
              :options="DISPLAY_CAPS.map(cap => ({ label: `${cap} 条/页`, value: cap }))"
              @update:value="onPageCapChange" />
            <n-button v-if="canPrevPage || canNextPage" size="small" :disabled="!canPrevPage" title="读取更早一页" @click="prevPage">上一页</n-button>
            <n-button v-if="canPrevPage || canNextPage" size="small" :disabled="!canNextPage" title="读取更新一页" @click="nextPage">下一页</n-button>
            <n-button v-if="isHistoricalMode" size="small" tertiary @click="jumpLatest">最新</n-button>
          </div>
        </div>
      </div>

      <div class="splitter" :class="{ dragging }" @mousedown="startDrag"></div>

      <section class="capture-detail-shell">
        <div class="capture-detail-nav">
          <n-button quaternary size="small" @click="closeDetail">‹ 返回列表</n-button>
        </div>
        <div class="detail-pane">
          <CapDetail v-if="selDetail" :detail="selDetail" />
          <div v-else class="detail-empty detail-placeholder">
            选择一条记录查看详情
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.cap-list { outline: none; }
.sk-row { pointer-events: none; }
.sk-line {
  height: 11px;
  border-radius: 4px;
  background: linear-gradient(90deg, rgba(255,255,255,.05) 25%, rgba(255,255,255,.11) 50%, rgba(255,255,255,.05) 75%);
  background-size: 200% 100%;
  animation: sk-shimmer 1.25s ease-in-out infinite;
}
.sk-a { width: 62%; }
.sk-b { width: 84%; margin-top: 10px; }
@keyframes sk-shimmer { to { background-position: -200% 0; } }
.detail-placeholder { min-height: 62vh; display: grid; place-items: center; padding: 0; }
.toolbar-search-input { flex: 1; min-width: 160px; }
.search-ico { font-size: 14px; opacity: 0.55; }
.pager-controls {
  display: flex;
  align-items: center;
  gap: 6px;
}
.page-cap-select { width: 96px; }
.cat-select { width: 110px; }
.size-num { width: 88px; }
.time-filter {
  border: 0;
  padding: 0;
  margin: 10px 0 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.time-filter legend {
  font-size: 12px;
  opacity: 0.78;
  margin-bottom: 2px;
}
.time-quick {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.time-inputs {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.time-inputs :deep(.n-date-picker) { flex: 1; min-width: 150px; }
.time-banner {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
</style>
