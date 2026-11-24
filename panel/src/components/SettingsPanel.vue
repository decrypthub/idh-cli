<script setup lang="ts">
import { appearance, setAppearance, type Appearance } from '../appearance';
import { computed, reactive, ref, onMounted, watch } from 'vue';
import { store, savePrefs, copyText, downloadText } from '../store';
import {
  SUMMARY_KINDS, DISPLAY_CHOICES, LIMIT_FIELDS, LIMITS, CATEGORIES,
  type PanelPrefs, type DeviceLimits, type EventItem,
  defaults, mergePanel, deviceLimits, parseProfile, portableProfile, cleanEvent,
  getCategory, getPhase, fmt, longTime,
} from '../model';
import { getSettingsExport, postSettingsImport } from '../api';

const PAGES: Array<[string, string]> = [
  ['capture', '捕获'], ['display', '显示'], ['log', '日志'], ['noise', '噪声'], ['spoof', '伪装'],
  ['bypass', '绕过'], ['data', '数据'], ['rawcfg', '配置 JSON'],
];
const page = ref(store.settingsPage || 'capture');
watch(page, v => { store.settingsPage = v; });

interface Sheet {
  panel: PanelPrefs; loaded: { revision: string; deviceSession: DeviceLimits } | null;
  limits: DeviceLimits | null; busy: boolean; error: string; rawEdited: boolean;
}
const sheet = reactive<Sheet>({
  panel: mergePanel(store.prefs, {}), loaded: null, limits: null,
  busy: false, error: '', rawEdited: false,
});
const rawText = ref('');
const rawHint = ref('');
const rawHintCls = ref<'error' | 'warn' | ''>('');
const fileEl = ref<HTMLInputElement | null>(null);

const jsonSame = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
const panelChanged = computed(() => !jsonSame(sheet.panel, store.prefs));
const deviceChanged = computed(() =>
  sheet.loaded !== null && sheet.limits !== null &&
  LIMIT_FIELDS.some(({ key }) => sheet.limits![key] !== sheet.loaded!.deviceSession[key]));
const dirty = computed(() => sheet.rawEdited || panelChanged.value || deviceChanged.value);
const saveText = computed(() =>
  sheet.busy ? '正在处理…' : dirty.value ? '有未保存的更改' : '当前配置已保存');
function feedback(text: string, cls: 'error' | 'warn' | '' = '') { rawHint.value = text; rawHintCls.value = cls; }

async function load(reset: boolean) {
  if (sheet.busy) return;
  sheet.busy = true;
  try {
    const data = await getSettingsExport();
    if (data.error || typeof data.revision !== 'string') throw new Error(data.error || '设备未返回配置版本');
    const limits = deviceLimits(data.deviceSession as Record<string, unknown>, true);
    sheet.loaded = { revision: data.revision, deviceSession: limits };
    sheet.limits = { ...limits };
    sheet.error = '';
    if (reset) { sheet.rawEdited = false; sheet.panel = mergePanel(store.prefs, {}); }
    if (page.value === 'rawcfg' && !sheet.rawEdited) rawText.value = portableProfile(sheet.limits, sheet.panel);
    if (page.value === 'rawcfg') feedback('已读取设备配置和面板偏好');
  } catch (e) {
    sheet.error = (e as Error).message;
    if (!sheet.loaded) sheet.limits = null;
    feedback(sheet.error, 'error');
  } finally { sheet.busy = false; }
}
onMounted(() => { void load(false); });

function parseDraft(text: string) { return parseProfile(JSON.parse(text), sheet.panel); }
function stageDraft(p: ReturnType<typeof parseDraft>) {
  if (p.hasDevice && !sheet.loaded) throw new Error('请先读取目标设备的配置');
  sheet.panel = p.panel;
  if (p.hasDevice) sheet.limits = { ...(sheet.limits ?? {}), ...p.deviceSession };
  sheet.rawEdited = false;
}
function switchPage(next: string) {
  if (sheet.busy) return;
  if (sheet.rawEdited && page.value === 'rawcfg' && next !== 'rawcfg') {
    try { stageDraft(parseDraft(rawText.value)); } catch (e) { feedback((e as Error).message, 'error'); return; }
  }
  page.value = next;
  if (next === 'rawcfg' && !sheet.rawEdited) {
    try { rawText.value = sheet.loaded ? portableProfile(sheet.limits!, sheet.panel) : ''; }
    catch { rawText.value = JSON.stringify({ version: 1, deviceSession: sheet.limits, panel: sheet.panel }, null, 2); }
  }
}
function portableDraft(): string {
  if (!sheet.loaded) throw new Error('请先读取真实设备配置');
  const draft = sheet.rawEdited ? parseDraft(rawText.value) : { deviceSession: sheet.limits!, panel: sheet.panel };
  return portableProfile({ ...sheet.loaded.deviceSession, ...draft.deviceSession }, draft.panel);
}
async function importFile(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0];
  (ev.target as HTMLInputElement).value = '';
  if (!file) return;
  if (file.size > 4096) { feedback('导入失败：配置文件超过 4 KB', 'error'); return; }
  try {
    const text = await file.text();
    parseDraft(text);
    rawText.value = text; sheet.rawEdited = true;
    feedback('已载入文件，保存后才会应用。', 'warn');
  } catch (e) { feedback('导入失败：' + (e as Error).message, 'error'); }
}
async function save() {
  if (sheet.busy) return;
  try {
    if (sheet.rawEdited) stageDraft(parseDraft(rawText.value));
    if (sheet.limits) sheet.limits = deviceLimits(sheet.limits as Record<string, unknown>, true);
  } catch (e) { feedback('保存失败：' + (e as Error).message, 'error'); return; }
  sheet.busy = true;
  try {
    const devChanged = deviceChanged.value;
    if (devChanged) {
      const next = await postSettingsImport({ revision: sheet.loaded!.revision, deviceSession: sheet.limits! });
      if (next.error || typeof next.revision !== 'string') throw new Error(next.error || '设备未返回配置版本');
      const limits = deviceLimits(next.deviceSession as Record<string, unknown>, true);
      sheet.loaded = { revision: next.revision, deviceSession: limits };
      sheet.limits = { ...limits };
    }
    savePrefs(mergePanel(defaults(), sheet.panel));
    store.limit = store.prefs.displayCap;
    feedback(devChanged ? '已保存并应用；设备限额从下一场会话生效。' : '已保存并应用');
  } catch (e) { feedback('保存失败：' + (e as Error).message, 'error'); }
  finally { sheet.busy = false; }
}

// data 页导出
const BOARD_CATS: Record<string, number[]> = { crypto: [0, 1, 2, 3], sys: [4, 5], net: [6], keychain: [7], other: [8] };
const cats = BOARD_CATS[store.tab] ? BOARD_CATS[store.tab] : [0, 1, 2, 3];
function exportData(scope: 'board' | 'filtered' | 'session') {
  const events = (scope === 'board'
    ? store.events.filter(e => cats.includes(e.category)) : store.events).map(cleanEvent);
  downloadText('idh-app-' + (store.session?.bundleId ?? 'app') + (scope === 'board' ? '-board' : '') + '.json',
    JSON.stringify({ session: store.session, events }, null, 2));
}

const noiseText: Record<string, string> = {
  noise: '「隐藏更新」只根据 idhjd 已保存的更新标记调整当前列表。旧 App 按原始输入匹配的噪声规则不会在此应用。',
  spoof: '这张面板只读会话摘要与保存会话限额，不接受伪装配置。',
  bypass: '当前设备会话没有绕过检测入口，可移植配置也不会启用此类功能。',
};
void CATEGORIES; void getCategory; void getPhase; void fmt; void longTime;
</script>

<template>
  <div class="settings-wrap">
    <aside class="settings-nav">
      <h2>设置</h2>
      <button v-for="[key, label] in PAGES" :key="key" type="button"
        :aria-pressed="page === key" @click="switchPage(key)">{{ label }}</button>
    </aside>
    <section class="settings-main">
      <div class="settings-body">
        <template v-if="page === 'capture'">
          <section class="settings-group"><h3>摘要类别</h3><p class="muted">只影响列表显示，不改变设备采集。</p>
            <label v-for="{ key, label } in SUMMARY_KINDS" :key="key" class="field">
              <span>{{ label }}</span>
              <input class="switch" type="checkbox" v-model="sheet.panel.summaryCategories[key]" :disabled="sheet.busy" />
            </label></section>
        </template>
        <template v-else-if="page === 'display'"><section class="settings-group"><h3>电脑面板</h3><label class="appearance-row"><span>外观</span><select aria-label="外观" :value="appearance" @change="setAppearance(($event.target as HTMLSelectElement).value as Appearance)">
              <option value="system">跟随系统</option><option value="light">浅色</option><option value="dark">深色</option>
            </select></label></section></template>
        <template v-else-if="page === 'log'">
          <section class="settings-group"><h3>电脑面板</h3>
            
            <label class="field"><span>每次展示条数<small>可以继续加载其余摘要</small></span>
              <select v-model.number="sheet.panel.displayCap" :disabled="sheet.busy">
                <option v-for="v in DISPLAY_CHOICES" :key="v" :value="v">{{ v }} 行</option></select></label>
            <label class="field"><span>自动刷新<small>按会话状态更新列表</small></span>
              <input class="switch" type="checkbox" v-model="sheet.panel.autoRefresh" :disabled="sheet.busy" /></label>
            <label class="field"><span>打开时展开筛选<small>只影响电脑面板</small></span>
              <input class="switch" type="checkbox" v-model="sheet.panel.advancedFilters" :disabled="sheet.busy" /></label>
          </section>
          <section class="settings-group"><h3>设备会话限额</h3>
            <template v-if="sheet.limits">
              <label v-for="{ key, label, unit } in LIMIT_FIELDS" :key="key" class="field">
                <span>{{ label }}<small>{{ LIMITS[key][0] }}–{{ LIMITS[key][1] }} {{ unit }}</small></span>
                <input type="number" inputmode="numeric" :min="LIMITS[key][0]" :max="LIMITS[key][1]" step="1"
                  :value="sheet.limits[key]" :disabled="sheet.busy"
                  @input="sheet.limits[key] = ($event.target as HTMLInputElement).value === '' ? '' as unknown as number : ($event.target as HTMLInputElement).valueAsNumber" />
              </label>
            </template>
            <div v-else class="field">设备限额暂不可读。
              <button class="btn sm" type="button" @click="load(false)">重新读取</button></div>
          </section>
        </template>
        <template v-else-if="page === 'rawcfg'">
          <p class="helper">版本 1：会话限额与电脑偏好。不包含地址、凭证、并发版本号或日志；也支持原来的 deviceSession 文件。</p>
          <div class="raw-actions">
            <button class="btn sm" type="button" :disabled="sheet.busy" @click="load(true)">重新载入</button>
            <button class="btn sm" type="button" :disabled="!sheet.loaded || sheet.busy"
              @click="copyText(portableDraft())">复制</button>
            <button class="btn sm" type="button" :disabled="!sheet.loaded || sheet.busy"
              @click="downloadText('dh-settings.json', portableDraft())">下载</button>
            <button class="btn sm" type="button" :disabled="!sheet.loaded || sheet.busy"
              @click="fileEl?.click()">从文件载入</button>
            <input ref="fileEl" type="file" accept=".json,application/json" hidden @change="importFile" />
          </div>
          <textarea v-model="rawText" :disabled="!sheet.loaded || sheet.busy" aria-label="可移植配置 JSON"
            spellcheck="false" @input="sheet.rawEdited = true"></textarea>
        </template>
        <template v-else-if="page === 'data'">
          <section class="settings-group"><h3>会话摘要</h3>
            <div class="field"><span>当前板块全部摘要</span>
              <button class="btn sm" type="button" :disabled="!store.session" @click="exportData('board')">下载 JSON</button></div>
            <div class="field"><span>当前筛选结果</span>
              <button class="btn sm" type="button" :disabled="!store.session" @click="exportData('filtered')">导出 JSON</button></div>
            <div class="field"><span>完整会话</span>
              <button class="btn sm" type="button" :disabled="!store.session" @click="exportData('session')">下载摘要</button></div>
          </section>
        </template>
        <template v-else>
          <p class="helper">{{ noiseText[page] }}</p>
        </template>
      </div>
      <footer v-if="page !== 'display'" class="settings-foot">
        <span class="dirty-status" :class="rawHintCls || (dirty ? 'warn' : '')">{{ rawHint || saveText }}</span>
        <button class="btn" type="button" :disabled="sheet.busy || !dirty" @click="save">保存</button>
      </footer>
    </section>
  </div>
</template>
