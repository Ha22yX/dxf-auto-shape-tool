<div align="center">
  <h1>Surfboard Vacuum Table DXF Generator</h1>
  <p>我为爸爸公司开发的工具：从冲浪板轮廓生成定制真空吸附底板图纸。</p>

  <p>
    <a href="README.md">English</a>
    &middot;
    <a href="#在本地运行">快速开始</a>
    &middot;
    <a href="#怎么使用">使用流程</a>
    &middot;
    <a href="#用到的技术">技术栈</a>
  </p>

  <p>
    <img alt="Python: FastAPI" src="https://img.shields.io/badge/Python-FastAPI-3776AB?style=for-the-badge&logo=python&logoColor=white" />
    <img alt="CAD: DXF" src="https://img.shields.io/badge/CAD-DXF-287866?style=for-the-badge" />
    <img alt="Automation: manufacturing" src="https://img.shields.io/badge/Automation-manufacturing-7d73b7?style=for-the-badge" />
  </p>
</div>

<p align="center">
  <img src=".github/assets/readme-hero.svg" alt="冲浪板吸附底板生成流程：导入 DXF 轮廓、选择边、生成孔和槽、导出 DXF" width="100%" />
</p>

这是我为爸爸的公司开发的一个工具，用来生成冲浪板加工时所需的真空吸附底板图纸。导入冲浪板轮廓后，使用者可以调整孔和槽的参数，再导出底板的 DXF 图纸。

## 我为什么做这个项目

我爸爸的公司是常州市如发机械有限公司，主要生产加工冲浪板的机器。加工时，需要用一块定制底板，通过真空吸附把冲浪板固定在机器上。不同客户的冲浪板形状不一样，底板也要跟着调整。

在我开发这个程序之前，公司每遇到一种新的冲浪板型号，就要重新画一套底板图纸。虽然很多步骤是重复的，但每个新设计仍然要花几个小时。我想把这些重复的画图步骤写成程序，让电脑来完成。

现在只需要导入轮廓、调整参数，就能生成图纸。在爸爸公司的使用流程中，这个过程从原来的**每个设计数小时**缩短到了**不到 30 秒**。这里说的是准备图纸的时间，实际加工底板还需要另外完成。

## 从图纸到实物

下面这张照片是根据我的程序生成的图纸加工出来的真空吸附底板。它用于在加工时固定冲浪板，也是程序输出实际用到公司机器上的一个例子。

<p align="center">
  <img src="docs/assets/surfboard-vacuum-fixture.jpg" alt="根据本程序生成的图纸加工出来的冲浪板真空吸附底板实物" width="480" />
</p>

*根据程序生成的图纸加工出来的底板实物。*

## 怎么使用

1. 导入包含冲浪板轮廓的 DXF 文件。
2. 在预览中选中用于生成孔和槽的轮廓边。
3. 调整孔的大小、间距、槽的设置，以及不需要生成槽的区域，并查看预览。
4. 导出新的 DXF 图纸，在 CAD/CAM 软件中检查后再用于加工。

使用者可以直接修改参数，不用每次重新画整个布局。界面中的辅助线方便查看孔和槽的排列，导出的 DXF 则保留加工需要的图形。

![程序中的冲浪板轮廓预览和参数面板](docs/assets/Pic.png)

## 用到的技术

| 部分 | 工具 | 用途 |
| --- | --- | --- |
| 后端 | Python、FastAPI | 在本地运行，处理文件上传和图纸生成。 |
| 图形处理 | ezdxf 和自己编写的几何处理代码 | 读取轮廓，生成吸孔、胶囊形长槽和导风槽。 |
| 界面 | HTML、CSS、JavaScript、SVG | 显示轮廓、选中的边、参数和预览。 |
| Windows 启动与打包 | 启动脚本、PyInstaller | 提供本地启动和打包方式。 |

## 在本地运行

安装 Python 和 Git 后，运行以下命令：

```bash
git clone https://github.com/Ha22yX/dxf-auto-shape-tool.git
cd dxf-auto-shape-tool
pip install -r requirements.txt
python main.py
```

程序会启动本地服务，并自动在浏览器中打开界面。如果浏览器没有自动打开，可以访问默认地址 [http://127.0.0.1:8000](http://127.0.0.1:8000)。

Windows 用户也可以通过 [`scripts/windows/start-manager-hidden.vbs`](scripts/windows/start-manager-hidden.vbs) 启动本地服务管理器。目前的软件界面是中文。

## 使用时需要注意的地方

- 这个工具是围绕爸爸公司的实际流程做的，其他类型的底板可能需要调整图形生成规则或参数。
- 尽量使用干净的 DXF 轮廓，并确认选中了正确的边。
- 孔间距、槽的间隙、对称设置和禁槽区域，需要根据实际底板调整。
- 加工前仍然需要在 CAD/CAM 软件中检查导出的文件。

## 项目文件

```text
backend/                 Python 服务和 DXF 图形处理代码
frontend/                浏览器界面和 SVG 预览
scripts/windows/         Windows 启动脚本
packaging/               PyInstaller 配置和构建脚本
.github/assets/          SVG 流程概览图
docs/assets/             软件界面截图和底板实物照片
Test Files/              DXF 示例文件
tests/                   几何、DXF、交互和 WebSocket 测试
main.py                  启动本地服务并打开浏览器
```

## 许可证

[MIT](LICENSE)。
