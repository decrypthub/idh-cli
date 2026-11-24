<script setup lang="ts">
import { computed } from 'vue';
import { store } from '../store';

const props = defineProps<{ kind: 'files' | 'symbols' | 'dump' }>();
const app = computed(() => store.selected || '无当前应用');
const heading = computed(() => ({ files: '文件浏览', symbols: '符号查询', dump: 'Dump' }[props.kind]));
const subtitle = computed(() => ({
  files: '按目录查看文件，在右侧查看所选文件的信息。',
  symbols: '按模块组织符号，区分符号名和地址。',
  dump: '按 App 查看任务状态和产物，不使用事件时间线。',
}[props.kind]));
const status = computed(() => ({
  files: '设备目录未接入', symbols: '设备符号索引未接入', dump: '设备任务接口未接入',
}[props.kind]));
</script>

<template>
  <main class="tool-page">
    <div class="tool-header"><div><h2>{{ heading }}</h2><p>{{ subtitle }}</p></div>
      <span class="pill tool-status">{{ status }}</span></div>
    <section v-if="kind === 'dump'" class="tool-surface" style="margin-bottom:12px">
      <h3>当前会话关联的 App</h3><div class="tool-content mono">{{ app }}</div></section>
    <div class="tool-grid">
      <section class="tool-surface"><h3>{{ kind === 'files' ? '设备目录' : kind === 'symbols' ? '模块与符号' : '任务状态' }}</h3>
        <div class="tool-content"><p class="tool-note">{{
          kind === 'files' ? '此连接没有提供文件清单。'
            : kind === 'symbols' ? '当前 idhjd 没有返回模块符号索引，不显示模拟条目。'
              : '当前连接不能创建或查看 Dump 任务。' }}</p></div></section>
      <section class="tool-surface"><h3>{{ kind === 'files' ? '文件详情' : kind === 'symbols' ? '符号详情' : '产物' }}</h3>
        <div class="tool-content"><p class="tool-note">{{
          kind === 'files' ? '需要设备文件接口，才能查看实际路径、属性和内容。'
            : kind === 'symbols' ? '需要设备符号索引。'
              : '设备未提供产物清单，此处不显示会话摘要。' }}</p></div></section>
    </div>
  </main>
</template>
