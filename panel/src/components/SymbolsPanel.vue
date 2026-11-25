<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { store, copyText } from '../store';
import * as A from '../api';

const app = computed(() => store.selected);
const images = ref<A.SymbolImage[]>([]);
const imageIdx = ref<number | null>(null);
const query = ref('');
const result = ref<A.SymbolRows | null>(null);
const loading = ref(false);
const searching = ref(false);
const error = ref('');

const currentImage = computed(() => images.value.find((x) => x.idx === imageIdx.value) ?? null);

async function loadImages() {
  if (!app.value) { images.value = []; error.value = '先选择应用'; return; }
  loading.value = true; error.value = ''; result.value = null;
  try {
    const data = await A.listSymbolImages(app.value);
    if (data.error) throw new Error(data.error);
    images.value = data.images ?? [];
    imageIdx.value = images.value.find((x) => x.main)?.idx ?? images.value[0]?.idx ?? null;
    if (imageIdx.value != null) await search();
  } catch (e) {
    error.value = e instanceof Error ? e.message : '设备符号索引暂时无法读取';
    images.value = [];
  } finally { loading.value = false; }
}

async function search() {
  if (!app.value || imageIdx.value == null) return;
  searching.value = true; error.value = '';
  try {
    const data = await A.listSymbols(app.value, imageIdx.value, query.value.trim(), 300);
    if (data.error) throw new Error(data.error);
    result.value = data;
  } catch (e) {
    error.value = e instanceof Error ? e.message : '符号列表暂时无法读取';
    result.value = null;
  } finally { searching.value = false; }
}

watch(imageIdx, () => void search());
watch(app, () => { query.value = ''; void loadImages(); }, { immediate: true });
</script>

<template>
  <main class="tool-page">
    <div class="tool-header"><div><h2>符号查询</h2><p>{{ app || '无当前应用' }} 进程导入表中的符号。</p></div>
      <span class="pill tool-status">{{ loading || searching ? '读取中' : error ? '读取失败' : '设备符号索引' }}</span></div>
    <div v-if="error" class="notice warn">{{ error }}</div>
    <div class="tool-grid">
      <section class="tool-surface">
        <h3>模块</h3>
        <div class="tool-content" style="padding:0;max-height:560px;overflow:auto">
          <button v-for="img in images" :key="img.idx" type="button" class="symbol-image" :class="{ active: img.idx === imageIdx }"
            @click="imageIdx = img.idx">
            <span class="symbol-image-name">{{ img.name }}</span>
            <span class="n">{{ img.imports ?? 0 }} 项{{ img.main ? ' · 主程序' : '' }}</span>
          </button>
          <p v-if="!loading && !images.length" class="tool-note" style="padding:13px 14px">没有可读取的导入模块。</p>
        </div>
      </section>
      <section class="tool-surface">
        <h3>符号</h3>
        <div class="tool-content">
          <form class="symbol-search" @submit.prevent="search">
            <input v-model="query" type="search" placeholder="过滤符号名" aria-label="过滤符号名" />
            <button type="submit" class="hbtn" :disabled="imageIdx == null || searching">查询</button>
          </form>
          <p v-if="currentImage" class="tool-note" style="margin:8px 0 12px">
            {{ currentImage.name }} · 共 {{ result?.total ?? '—' }} 项，显示 {{ result?.shown ?? 0 }} 项
          </p>
          <div class="symbol-list">
            <button v-for="sym in result?.symbols ?? []" :key="sym" type="button" class="symbol-row" title="复制符号名" @click="copyText(sym)">
              {{ sym }}
            </button>
          </div>
          <p v-if="!searching && result && !(result.symbols ?? []).length" class="tool-note">没有匹配符号。</p>
        </div>
      </section>
    </div>
  </main>
</template>
