# DXF 自动图形工具

一个本地网页工具，用于上传 DXF 文件、选择边线，并沿所选边线自动生成圆圈和胶囊形长条。项目主要面向冲浪板边缘类图形：支持弧形/多段线预览、对称轴辅助、顶部间隔、中心无长条区域、重叠圆自动剔除，以及导出新的 DXF。

## 主要功能

- 上传 DXF 并在浏览器中预览。
- 鼠标悬浮可选对象时高亮，点击选择边线，`Ctrl + 点击` 追加相连边。
- 按所选边线生成射线、圆圈和胶囊形长条。
- 支持前端实时预览参数变化，避免每次拖动都等待后端完整计算。
- 自动估计垂直/水平对称轴，并显示默认顶点。
- 支持顶部间隔：顶点附近不生成射线，方便保持左右对称。
- 支持水平轴上方/下方独立设置无长条距离：该区域内保留圆圈，但不生成胶囊。
- 自动剔除重叠圆圈，被剔除圆在预览中灰色半透明显示，导出时不写入。
- 导出 DXF 时只写入保留的圆圈和胶囊，不导出预览辅助线。

## 快速启动

推荐直接双击：

```text
一键启动服务.cmd
```

脚本会先关闭旧的 8000 端口服务，再启动新服务，并打开：

```text
http://127.0.0.1:8000/
```

也可以手动启动：

```bash
pip install -r requirements.txt
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

或：

```bash
python main.py
```

## 使用流程

1. 打开网页后点击 `上传 DXF`。
2. 鼠标移动到可选线段上，看到高亮后点击选择。
3. 需要追加相邻边时，按住 `Ctrl` 再点击。
4. 在右侧参数面板调整参数，预览会实时更新。
5. 点击 `保存 DXF` 下载生成后的文件。

## 参数分区

右侧参数面板按用途分区：

- `圆圈`
  - 圆圈半径
  - 每射线圆数
  - 圆间距

- `射线`
  - 射线整体偏移
  - 射线数量
  - 射线方向
  - 闭合端点射线去重

- `长条与间隔`
  - 长条起点距离
  - 水平轴上方无长条距离
  - 水平轴下方无长条距离
  - 顶部间隔

- `显示`
  - 显示生成图

默认参数在 [backend/config.py](backend/config.py) 的 `DEFAULT_PARAMS` 中维护。

## 项目结构

```text
backend/
  app.py                    FastAPI 接口、WebSocket、上传/下载流程
  config.py                 默认参数、端口、图层名
  state.py                  会话状态和参数模型
  dxf_engine/
    loader.py               DXF 读取
    svg_exporter.py         DXF 到 SVG 预览
    entity_mapper.py        鼠标坐标到 DXF 实体的命中判断
    path_analyzer.py        选择边线后构建连续链
    geometry_utils.py       几何采样、弧线、多段线、对称轴计算
    circle_generator.py     射线、圆圈、胶囊、重叠剔除、导出实体

frontend/
  index.html                页面结构
  css/
    main.css                面板、按钮、参数区样式
    viewer.css              SVG 画布、悬浮高亮、辅助线样式
  js/
    app.js                  前端主流程
    api.js                  HTTP API 封装
    websocket.js            实时预览消息队列
    svg_viewer.js           SVG 预览、缩放、平移、本地快速渲染
    parameter_panel.js      参数输入、滑块同步
    selector.js             选择相关辅助

tests/                      几何、DXF 生成和接口测试
Test Files/                 手工测试用 DXF 文件
temp/                       运行时上传/下载临时文件
```

## 接口概览

- `GET /`：返回前端页面。
- `POST /api/upload`：上传 DXF，创建会话，返回基础 SVG 和默认参数。
- `GET /api/session/{session_id}/download`：下载生成后的 DXF。
- `DELETE /api/session/{session_id}`：删除会话和临时文件。
- `WS /ws/{session_id}`：选择、参数变化、预览更新等实时消息。

## 测试

运行完整测试：

```bash
python -m pytest
```

运行主要 DXF/生成逻辑测试：

```bash
python -m pytest tests/test_dxf_engine.py
```

## 常见问题

### 页面没有更新

前端文件使用查询参数做缓存刷新。如果改了 JS/CSS/HTML 后页面还是旧的，可以刷新浏览器；必要时清缓存后再打开。

### 导入图变成大块灰色

这是原始 SVG 线宽处理的问题。当前版本已避免对导入原始图层强制设置非缩放线宽，只对预览辅助图形使用稳定线宽。

### 拖动参数时感觉延迟

前端对常用参数会先本地快速重绘，WebSocket 只同步最新参数。后端如果仍在计算旧参数，前端会忽略过期结果。

### 生成结果和导出不一致

原则上预览和导出共用后端核心几何逻辑；前端快速预览只用于拖动过程。如果发现最终下载 DXF 与稳定后的预览不一致，优先检查 `backend/dxf_engine/circle_generator.py` 中的生成逻辑。

## 开发约定

- 生成实体使用图层 `GENERATED_CIRCLES`。
- 辅助线、对称轴、顶点标记、范围提示线只用于前端预览，不导出。
- 手工改文件后建议至少运行：

```bash
python -m pytest
node --check frontend/js/svg_viewer.js
node --check frontend/js/parameter_panel.js
node --check frontend/js/app.js
```
