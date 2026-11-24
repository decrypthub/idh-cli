<script setup lang="ts">
import { store, copyText } from '../store';

const endpoint = document.querySelector('meta[name="idh-device-endpoint"]')?.getAttribute('content')
  || location.origin;
const command = `idh mcp --device-session --endpoint "${endpoint}"`;
</script>

<template>
  <div class="modal-mask show" @click.self="store.mcpOpen = false">
    <div class="dialog-card" role="dialog" aria-label="MCP 连接">
      <div class="dialog-head"><strong>MCP 连接</strong>
        <button class="set-close-x" type="button" aria-label="关闭" @click="store.mcpOpen = false">
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8" /></svg></button></div>
      <p class="helper">在 AI 客户端中配置以下命令，连接当前面板对应的设备会话。</p>
      <pre class="code-body">{{ command }}</pre>
      <div class="dialog-actions">
        <button class="btn sm" type="button" @click="copyText(command)">复制命令</button>
        <button class="btn sm" type="button" @click="store.mcpOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
