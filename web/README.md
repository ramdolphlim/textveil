# 文隐 TextVeil · 网页版

线上地址：<https://textveil.limch.cc>

网页版和桌面版用的是**同一套界面和脱敏引擎**：浏览器后台线程（Web Worker）里用 [Pyodide](https://pyodide.org) 运行 Python，文档只在浏览器内存里处理，**不会上传**。

| 文件 | 作用 |
|---|---|
| `build_web.py` | 生成 `dist/`：复制 `desktop/ui` 并打少量补丁（下载方式、去掉 PDF 和本机文件夹相关设置），把引擎打成 `engine.zip`、纯 Python 依赖打成 `libs.zip` |
| `web_api.py` | 网页版的 `Api`：继承桌面版，去掉线程、子进程和本机路径相关功能 |
| `src/tvweb.js` | 页面里的桥接层：把界面的 `/api/...` 请求转给 Worker，处理上传和下载 |
| `src/pyworker.js` | Web Worker：加载 Pyodide（官方 CDN）、`lxml`、`Pillow`、引擎和依赖 |
| `src/worker.js` | Cloudflare Worker：从本仓库 `site` 分支取静态文件，加上缓存和安全响应头后返回 |
| `publish_site.sh` | 把 `dist/` 发布到 `site` 分支（保留当前版本和上一个版本） |

## 网页版的限制

- 不支持 PDF（浏览器里没有可用的 PyMuPDF），拖入 PDF 会提示改用桌面版
- 没有监视文件夹、固定输出目录、在访达中显示等本机功能
- 浏览器里只保存「设置」；批次和映射表只留在当前页面，刷新就清除。需要还原的话，脱敏后先下载 `映射表.json`

## 本地构建与测试

```bash
python web/build_web.py           # 自动 pip download 依赖；离线可加 --site-packages <虚拟环境的 site-packages>
python tests/test_web_engine.py   # 用 dist 里的 engine.zip + libs.zip 跑一遍扫描 / 脱敏 / 还原
```

## 部署

推送到 `main` 后，`.github/workflows/site.yml` 会自动构建、测试并发布到 `site` 分支，几分钟内线上生效，不需要任何 Cloudflare 密钥。

只有修改了 `src/worker.js` 才需要重新部署 Worker（Cloudflare 免费版即可）：

```bash
cp wrangler.toml.example wrangler.toml
npx wrangler deploy
```
