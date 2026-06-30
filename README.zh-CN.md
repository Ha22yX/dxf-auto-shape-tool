# 冲浪板吸附台 DXF 自动生成工具

[English](README.md) | 中文

![冲浪板吸附台 DXF 自动生成工具预览](docs/assets/Pic.png)

这是一个本地网页工具，用来根据冲浪板外形 DXF，自动生成用于 Rufa.com / Rufa 公司的冲浪板缝合机布料吸附台的辅助加工图形。

项目面向的实际场景是：导入冲浪板边缘轮廓，选择需要布置吸附结构的边线后，工具会沿边线生成垂直射线、吸附圆孔、胶囊形长条槽，并导出新的 DXF 文件，方便后续加工吸附台面。

Rufa 公司网址：[http://rufajx.com/](http://rufajx.com/)

## 主要能力

- 上传冲浪板外形 DXF，并在浏览器中预览。
- 鼠标悬浮在可选线段上时高亮，点击选择目标边线。
- 支持 `Ctrl + 点击` 追加相邻边线，组合成连续边界。
- 根据所选边线生成射线、圆孔和胶囊形长条槽。
- 支持冲浪板常见的左右对称外形，自动显示垂直/水平对称轴和默认顶点。
- 顶部尖端附近可设置不生成射线的间隔，让左右两侧从相同距离开始生成，保证对称。
- 可设置水平对称轴上方/下方的无长条区域：该区域保留圆孔，但不生成胶囊长条。
- 自动剔除重叠圆孔，被剔除的圆孔在预览中灰色半透明显示，导出时不写入 DXF。
- 参数拖动时优先使用前端快速预览，后端只同步最新参数，减少操作延迟。
- 导出 DXF 时只写入实际需要加工的圆孔和长条槽，不导出辅助线、对称轴和预览标记。

## 适用流程

1. 准备冲浪板外形 DXF 文件。
2. 打开工具，点击 `上传 DXF`。
3. 鼠标移动到冲浪板边线附近，看到高亮后点击选中。
4. 在右侧参数面板调整圆孔、射线、长条和间隔参数。
5. 检查预览效果，确认吸附圆孔和长条槽分布正确。
6. 点击 `保存 DXF`，得到可用于后续加工的生成文件。

## 参数说明

右侧参数面板按用途分区。

### 圆圈

- `圆圈半径`：每个吸附圆孔的半径。
- `每射线圆数`：每条射线上生成几个圆孔。
- `圆间距`：同一条射线上相邻圆孔之间的距离。

### 射线

- `射线整体偏移`：整体调整射线相对所选边线的偏移位置。
- `射线数量`：沿所选边线生成多少条射线。
- `射线方向`：选择向内或向外生成。
- `闭合端点射线去重`：用于闭合或近似闭合边线，避免端点附近重复生成射线。顶部间隔不为 0 时会自动忽略该设置。

### 长条与间隔

- `长条起点距离`：胶囊长条靠近射线起点一端的位置。
- `胶囊安全间距`：胶囊长条之间额外保留的安全距离。当两条胶囊距离过近时，工具会从其中一条的最外层圆开始缩短；如果有对称轴，会同步处理镜像侧。
- `水平轴上方无长条距离`：水平对称轴上方指定范围内不生成长条。
- `水平轴下方无长条距离`：水平对称轴下方指定范围内不生成长条。
- `顶部间隔`：顶点附近不生成射线的距离，用于让左右两侧保持对称。

### 显示

- `显示生成图`：控制是否显示生成的圆孔、射线和长条预览。

默认参数维护在 [backend/config.py](backend/config.py) 的 `DEFAULT_PARAMS` 中。

## 快速启动

推荐使用 Windows 桌面管理器，直接双击：

```text
scripts/windows/start-manager-hidden.vbs
```

如果不介意短暂出现命令行窗口，也可以双击：

```text
scripts/windows/start-manager.cmd
```

它会打开一个小窗口：

- 默认自动启动本地网页服务；
- 显示本机访问地址和局域网访问地址；
- 可以一键打开网页；
- 用绿色/红色圆点显示服务运行状态；
- 可以手动“运行服务/停止运行”；
- 可以打开网站日志窗口，日志窗口会显示打开之前已经产生的日志；
- 日志使用有限缓冲，长时间运行后打开也不会一次性渲染过多内容；
- 关闭管理器窗口时，网页服务会一起停止。

后期打包 exe 时，可以把 [launcher.py](launcher.py) 作为程序入口。这个窗口本身只使用 Python 标准库，不额外增加桌面 UI 依赖。

旧的控制台启动脚本仍然保留：

```text
scripts/windows/start-service.cmd
```

脚本会先关闭旧的本地服务，再启动新的服务，并打开：

```text
http://127.0.0.1:8000/
```

也可以手动启动：

```bash
pip install -r requirements.txt
python -m uvicorn backend.app:app --host 127.0.0.1 --port 8000
```

或者：

```bash
python main.py
```

在开发机上重新打包 Windows 单文件 exe：

```text
packaging/build-exe.cmd
```

## 项目结构

```text
backend/
  app.py                    本地网页服务、接口、WebSocket
  config.py                 默认参数、端口、图层名
  state.py                  会话状态和参数模型
  dxf_engine/
    loader.py               DXF 读取
    svg_exporter.py         DXF 转 SVG 预览
    entity_mapper.py        鼠标命中 DXF 实体
    path_analyzer.py        构建连续选中边线
    geometry_utils.py       几何采样、弧线、对称轴计算
    circle_generator.py     射线、圆孔、长条槽、重叠剔除、导出实体

frontend/
  index.html                页面结构和参数面板
  css/
    main.css                面板、按钮、参数分区样式
    viewer.css              SVG 画布、悬浮高亮、辅助线样式
  js/
    app.js                  前端主流程
    api.js                  HTTP 接口封装
    websocket.js            实时预览消息同步
    svg_viewer.js           SVG 预览、缩放、平移、前端快速渲染
    parameter_panel.js      参数输入和滑块同步
    selector.js             选择辅助逻辑

tests/                      自动化测试
Test Files/                 手工测试 DXF 文件
docs/assets/                README 图片和文档资源
packaging/                  PyInstaller 配置和打包脚本
scripts/windows/            Windows 启动器和服务辅助脚本
temp/                       运行时临时文件
```

## 技术说明

- 后端使用 FastAPI 和 ezdxf 处理 DXF。
- 前端使用原生 HTML/CSS/JavaScript 渲染 SVG 预览。
- 预览分为两层：原始 DXF 图层和生成结果图层。
- 拖动参数时，前端会先快速重绘；后端计算完成后再同步最终结果。
- 导出 DXF 以 `backend/dxf_engine/circle_generator.py` 中的核心几何逻辑为准。

## 测试

运行完整测试：

```bash
python -m pytest
```

运行主要 DXF/生成逻辑测试：

```bash
python -m pytest tests/test_dxf_engine.py
```

检查前端 JavaScript 语法：

```bash
node --check frontend/js/svg_viewer.js
node --check frontend/js/parameter_panel.js
node --check frontend/js/app.js
```

## 常见问题

### 页面没有更新

浏览器可能缓存了旧的 JS/CSS 文件。刷新浏览器即可；如果仍然没有更新，可以清理浏览器缓存后重新打开。

### 导入后图形变成大块灰色

通常是 DXF 转 SVG 后线宽处理异常导致的。当前版本避免对原始图层强制使用非缩放线宽，只对预览辅助图形使用稳定线宽。

### 拖动参数时感觉延迟

前端会先渲染当前参数，后端只保留最新参数进行计算。如果仍然感觉慢，优先检查是否有旧服务占用端口，或浏览器是否加载了旧缓存。

### 预览和导出不一致

拖动过程中的预览可能是前端快速结果；停止调整后，后端会同步最终结果。最终导出的 DXF 以后端稳定结果为准。

## 开发约定

- 生成实体使用专用图层，辅助线、对称轴、顶点标记和范围提示线只用于预览。
- 被自动剔除的圆孔只作为灰色半透明预览，不导出到 DXF。
- 修改几何生成逻辑后，建议至少运行：

```bash
python -m pytest
node --check frontend/js/svg_viewer.js
node --check frontend/js/parameter_panel.js
node --check frontend/js/app.js
```
