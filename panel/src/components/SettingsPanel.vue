<script setup lang="ts">
import { computed, ref } from 'vue';
import { store, panelDisplay, savePanelDisplay, hiddenHooks, resetHidden, toast } from '../store';
import { summarize } from '../observations';
import { setHidden } from '../store';
import { setAppearance, isDark } from '../appearance';

const density = computed(() => panelDisplay.density);
const timeFmt = computed(() => panelDisplay.time);

function setDensity(v: 'standard' | 'compact') {
  savePanelDisplay({ ...panelDisplay, density: v });
}
function setTime(v: 'time' | 'date') {
  savePanelDisplay({ ...panelDisplay, time: v });
}

// 已隐藏的算法/Hook：从当前记录汇总，允许恢复显示
const hiddenList = computed(() => {
  const items = summarize(store.capItems, hiddenHooks);
  return items.filter(i => hiddenHooks.has(i.key) || i.shown < i.count);
});
const hiddenCount = computed(() => hiddenHooks.size);
const expandHidden = ref(false);

function showAgain(key: string) {
  setHidden(key, true);
  toast('已恢复显示');
}
function resetAllHidden() {
  resetHidden();
  toast('已重置全部隐藏项');
}
</script>

<template>
  <div class="settingspane">
    <section class="set-card">
      <h3>外观</h3>
      <div class="set-row">
        <span>主题</span>
        <n-radio-group size="small" :value="isDark ? 'dark' : 'light'" @update:value="(v: string) => setAppearance(v === 'dark' ? 'dark' : 'light')">
          <n-radio-button value="light">浅色</n-radio-button>
          <n-radio-button value="dark">深色</n-radio-button>
        </n-radio-group>
      </div>
      <div class="set-row">
        <span>列表密度</span>
        <n-radio-group size="small" :value="density" @update:value="setDensity">
          <n-radio-button value="standard">标准</n-radio-button>
          <n-radio-button value="compact">紧凑</n-radio-button>
        </n-radio-group>
      </div>
      <div class="set-row">
        <span>时间格式</span>
        <n-radio-group size="small" :value="timeFmt" @update:value="setTime">
          <n-radio-button value="time">时刻</n-radio-button>
          <n-radio-button value="date">日期+时刻</n-radio-button>
        </n-radio-group>
      </div>
    </section>

    <section class="set-card">
      <h3>注入范围 · {{ store.scope.size }}</h3>
      <p class="set-status">在应用弹窗里勾选。已打开的进程下次启动才注入。</p>
      <div class="scope-chips">
        <span v-for="pkg in [...store.scope]" :key="pkg" class="scope-chip mono">{{ pkg }}</span>
        <span v-if="!store.scope.size" class="set-status">空</span>
      </div>
    </section>

    <section class="set-card">
      <h3>显示筛选</h3>
      <div class="set-row">
        <span>已隐藏 {{ hiddenCount }} 项</span>
        <span>
          <n-button v-if="hiddenCount" size="tiny" tertiary @click="expandHidden = !expandHidden">{{ expandHidden ? '收起' : '查看' }}</n-button>
          <n-button v-if="hiddenCount" size="tiny" type="primary" text @click="resetAllHidden">全部恢复</n-button>
        </span>
      </div>
      <div v-if="expandHidden" class="hidden-list">
        <div v-for="item in hiddenList" :key="item.key" class="hidden-row">
          <span>{{ item.name }} · {{ item.count }} 条</span>
          <n-button size="tiny" text type="primary" @click="showAgain(item.key)">恢复</n-button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.settingspane { padding: 18px 22px; overflow: auto; display: flex; flex-direction: column; gap: 14px; max-width: 720px; }
.set-card {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px 16px;
  background: var(--surface);
}
.set-card h3 { margin: 0 0 10px; font-size: 13px; }
.set-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 6px 0; font-size: 12.5px; }
.set-row > span:last-child { display: flex; gap: 8px; align-items: center; }
.scope-chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 6px; }
.scope-chip {
  border: 1px solid var(--line);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11.5px;
}
.mono { font-family: ui-monospace, Consolas, monospace; }
.hidden-list { margin-top: 8px; display: flex; flex-direction: column; gap: 4px; }
.hidden-row { display: flex; justify-content: space-between; align-items: center; font-size: 12px; }
</style>
