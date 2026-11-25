import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { viteSingleFile } from 'vite-plugin-singlefile';
import { readFileSync, writeFileSync } from 'node:fs';

// 单文件产物落 src/idh/panel.html，由 cli.py 原样提供（设备地址从 /api/devices 读，不注入）。
export default defineConfig({
  plugins: [
    vue(),
    viteSingleFile(),
    {
      name: 'emit-panel-html',
      closeBundle() {
        // Windows 的 autocrlf 会把模板检成 CRLF；嵌入 cli.py 的单文件产物统一写 LF。
        const newline = String.fromCharCode(10);
        let html = readFileSync('dist/index.html', 'utf-8').split(String.fromCharCode(13)).join('');
        // 构建期注释可能被压缩掉，确保 cli.py 的端点注入占位符一定存在。
        if (!html.includes('<!-- IDH_DEVICE_ENDPOINT -->')) {
          html = html.replace('</head>', '  <!-- IDH_DEVICE_ENDPOINT -->' + newline + '</head>');
        }
        writeFileSync('../src/idh/panel.html', html);
      },
    },
  ],
  build: { outDir: 'dist' },
});
