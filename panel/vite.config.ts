import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { viteSingleFile } from 'vite-plugin-singlefile';
import { cpSync, readFileSync, writeFileSync } from 'node:fs';

// 单文件产物落 src/idh/panel.html，由 cli.py 原样提供（设备地址从 /api/devices 读，不注入）。
export default defineConfig({
  plugins: [
    vue(),
    viteSingleFile(),
    {
      name: 'emit-panel-html',
      closeBundle() {
        cpSync('dist/index.html', '../src/idh/panel.html');
        // 构建期注释可能被压缩掉，确保 cli.py 的端点注入占位符一定存在。
        const html = readFileSync('../src/idh/panel.html', 'utf-8');
        if (!html.includes('<!-- IDH_DEVICE_ENDPOINT -->')) {
          writeFileSync('../src/idh/panel.html',
            html.replace('</head>', '  <!-- IDH_DEVICE_ENDPOINT -->\n</head>'));
        }
      },
    },
  ],
  build: { outDir: 'dist' },
});
