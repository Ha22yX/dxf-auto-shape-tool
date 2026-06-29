# DXF 自动图形工具

一个基于 Python + FastAPI + ezdxf 的本地网页工具，用于在 DXF 文件的外轮廓边上按参数自动生成等距圆。

## 功能

- 启动程序后自动打开浏览器。
- 上传 DXF 文件并在网页中预览。
- 点击选中一条或多条相连的边（支持直线、圆弧、LWPOLYLINE）。
- 实时调整参数：圆半径、每射线圆数、圆间距、射线偏移、射线数量、射线方向。
- 实时预览生成结果。
- 一键切换“原图 / 生成图”。
- 一键保存生成后的 DXF。

## 安装

```bash
pip install -r requirements.txt
```

## 启动

```bash
python main.py
```

程序会自动在浏览器中打开 `http://localhost:8000`。

## 依赖

- FastAPI
- uvicorn
- ezdxf
- websockets
- python-multipart
- aiofiles
