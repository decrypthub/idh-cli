<script setup lang="ts">
import { store } from '../store';
</script>

<template>
  <div class="modal-mask show" @click.self="store.wechatOpen = false">
    <div class="dialog-card" role="dialog" aria-label="公众号">
      <div class="dialog-head"><strong>公众号</strong>
        <button class="set-close-x" type="button" aria-label="关闭" @click="store.wechatOpen = false">
          <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"><path d="M4 4l8 8M12 4l-8 8" /></svg></button></div>
      <img class="wechat-qr" :src="'/wechat-follow.png'" alt="公众号二维码" />
      <div class="dialog-actions">
        <button class="btn sm" type="button" @click="store.wechatOpen = false">关闭</button>
      </div>
    </div>
  </div>
</template>
