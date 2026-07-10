<div align="center">
  <h1>Surfboard Vacuum Table DXF Generator</h1>
  <p>一个本地 CAD 自动化工具，可从 DXF 轮廓生成冲浪板真空台吸孔和胶囊槽。</p>

  <p>
    <a href="README.md">English</a>
    &middot;
    <a href="#快速开始">快速开始</a>
    &middot;
    <a href="#核心能力">核心能力</a>
    &middot;
    <a href="#技术栈">技术栈</a>
  </p>

  <p>
    <img alt="Python: FastAPI" src="https://img.shields.io/badge/Python-FastAPI-3776AB?style=for-the-badge&logo=python&logoColor=white" />
    <img alt="CAD: DXF" src="https://img.shields.io/badge/CAD-DXF-287866?style=for-the-badge" />
    <img alt="Automation: manufacturing" src="https://img.shields.io/badge/Automation-manufacturing-7d73b7?style=for-the-badge" />
  </p>
</div>

<p align="center">
  <img src=".github/assets/readme-hero.svg" alt="Surfboard Vacuum Table DXF Generator 项目概览图" width="100%" />
</p>

<p align="center">
  <img src="docs/assets/Pic.png" alt="Surfboard vacuum table DXF generator interface screenshot" width="100%" />
</p>

## 项目概览

当吸孔和胶囊槽需要沿曲线板边生成时，手工编辑 DXF 很慢，也容易出错。

这个工具把轮廓选择转换成可重复的加工几何，并提供预览辅助和导出控制。

## 核心能力

- 上传并预览冲浪板轮廓 DXF。
- 根据选中边生成射线、吸孔和胶囊槽。
- 调节射线、孔、槽、间距、对称和禁槽参数。
- 把预览辅助线与真实加工几何分开。
- 包含 Windows 启动器和打包材料，便于本地车间使用。

## 工作方式

1. 上传 DXF 轮廓。
2. 在浏览器预览中选择目标边。
3. 调节生成参数并预览结果。
4. 导出只包含加工几何的新 DXF。

## 快速开始

可以用下面的命令在本地运行项目。

```bash
git clone https://github.com/Ha22yX/dxf-auto-shape-tool.git
cd dxf-auto-shape-tool
pip install -r requirements.txt
python main.py
```

在 Windows 上，`scripts/windows/start-manager-hidden.vbs` 可启动本地服务管理器。

## 配置项

| 项目 | 作用 |
| --- | --- |
| 输入 DXF | 使用干净轮廓，并在导出前确认选中边。 |
| 几何参数 | 根据工装调整孔/槽间距、对称和禁槽区域。 |
| 导出 | 加工前必须在 CAD/CAM 软件中检查生成 DXF。 |
| 打包 | 可用 Windows 脚本/PyInstaller 材料部署到本地工作站。 |

## 技术栈

| 层级 | 技术 | 作用 |
| --- | --- | --- |
| 后端 | FastAPI, Python | DXF 处理和本地 Web 服务。 |
| 几何 | ezdxf, custom helpers | 读取轮廓并生成加工实体。 |
| 前端 | HTML, CSS, JavaScript, SVG | 交互预览和参数面板。 |
| 打包 | Windows scripts / PyInstaller | 本地启动器和可执行文件路径。 |

## 项目结构

```text
backend/                 FastAPI 服务和 DXF 引擎
frontend/                浏览器 UI 和 SVG 预览器
scripts/windows/         本地启动脚本
packaging/               PyInstaller spec 和构建脚本
docs/assets/Pic.png      README 界面截图
tests/                   几何、DXF、点击和 websocket 测试
```

## 项目状态

这是面向特定冲浪板真空台流程的实用制造辅助工具，不是通用 CAD 软件。

## 许可证

当前仓库尚未声明项目级开源许可证；公开复用或分发前建议先补充 License。
