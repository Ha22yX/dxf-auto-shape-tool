<div align="center">
  <h1>Surfboard Vacuum Table DXF Generator</h1>
  <p>A local CAD automation tool for generating surfboard vacuum-table suction holes and capsule slots from DXF outlines.</p>

  <p>
    <a href="README.zh-CN.md">Chinese</a>
    &middot;
    <a href="#quickstart">Quickstart</a>
    &middot;
    <a href="#features">Features</a>
    &middot;
    <a href="#tech-stack">Tech Stack</a>
  </p>

  <p>
    <img alt="Python: FastAPI" src="https://img.shields.io/badge/Python-FastAPI-3776AB?style=for-the-badge&logo=python&logoColor=white" />
    <img alt="CAD: DXF" src="https://img.shields.io/badge/CAD-DXF-287866?style=for-the-badge" />
    <img alt="Automation: manufacturing" src="https://img.shields.io/badge/Automation-manufacturing-7d73b7?style=for-the-badge" />
  </p>
</div>

<p align="center">
  <img src=".github/assets/readme-hero.svg" alt="Surfboard Vacuum Table DXF Generator overview image" width="100%" />
</p>

<p align="center">
  <img src="docs/assets/Pic.png" alt="Surfboard vacuum table DXF generator interface screenshot" width="100%" />
</p>

## Overview

Manual DXF editing is slow and error-prone when suction holes and capsule slots must follow a curved board edge.

This tool turns an outline selection into repeatable machining geometry with preview guides and export controls.

## Features

- Upload and preview surfboard outline DXF files.
- Generate rays, suction holes, and capsule slots from selected edges.
- Tune ray, hole, slot, gap, symmetry, and no-slot parameters.
- Separate preview guides from real machining geometry.
- Windows launcher and packaging materials for local shop use.

## How It Works

1. Upload a DXF outline.
2. Select target edges in the browser preview.
3. Adjust generation parameters and preview the result.
4. Export a new DXF containing only machining geometry.

## Quickstart

Run the project locally with the commands below.

```bash
git clone https://github.com/Ha22yX/dxf-auto-shape-tool.git
cd dxf-auto-shape-tool
pip install -r requirements.txt
python main.py
```

On Windows, `scripts/windows/start-manager-hidden.vbs` launches the local service manager.

## Configuration

| Item | Purpose |
| --- | --- |
| Input DXF | Use clean outlines and verify selected edges before export. |
| Geometry parameters | Adjust hole/slot spacing, symmetry, and no-slot zones for the fixture. |
| Export | Inspect generated DXF in CAD/CAM software before machining. |
| Packaging | Use Windows scripts/PyInstaller materials for local workstation deployment. |

## Tech Stack

| Layer | Technology | Role |
| --- | --- | --- |
| Backend | FastAPI, Python | DXF processing and local web service. |
| Geometry | ezdxf, custom helpers | Load outlines and generate machining entities. |
| Frontend | HTML, CSS, JavaScript, SVG | Interactive preview and parameter panel. |
| Packaging | Windows scripts / PyInstaller | Local launcher and executable path. |

## Project Layout

```text
backend/                 FastAPI service and DXF engine
frontend/                browser UI and SVG viewer
scripts/windows/         local service launchers
packaging/               PyInstaller spec and build script
docs/assets/Pic.png      README interface screenshot
tests/                   geometry, DXF, click, and websocket tests
```

## Status

Practical manufacturing helper for a specific surfboard vacuum-table workflow, not a general-purpose CAD package.

## License

No project-wide open-source license has been declared yet.
