# Douyin Media Studio

一个本地运行的抖音作品归档桌面网页工具。支持直接粘贴整段抖音分享口令，自动提取链接，并把下载结果整理为 `mp4` 和 `images` 两个文件夹。

> 仅用于你自己的账号或已获授权的内容。

## 功能

- 直接粘贴整段抖音分享内容
- 自动提取 `https://v.douyin.com/...` 链接
- 网页按钮打开抖音登录窗口，保存 Cookie
- 自动整理输出：

```text
保存位置/
  mp4/
  images/
  _raw/
  manifest.json
```

## 首次安装

需要 Windows、Python、Git。

在 PowerShell 中运行：

```powershell
.\setup.ps1
```

安装脚本会自动：

- 克隆 `jiji262/douyin-downloader`
- 创建 Python 虚拟环境
- 安装下载依赖
- 安装 Playwright Chromium
- 安装本网页工具依赖

## 启动

双击：

```text
start-desktop.bat
```

或运行：

```powershell
python app.py
```

打开地址：

```text
http://127.0.0.1:5055
```

## 登录抖音

如果下载失败并提示 Cookie 失效：

1. 点击网页左侧的“重新登录抖音”。
2. 在弹出的浏览器里登录抖音。
3. 登录成功后，回到 PowerShell 窗口按 Enter。
4. 再重新开始下载。

## 打包成 EXE

可选。运行：

```powershell
.\build-exe.ps1
```

生成文件：

```text
dist/DouyinMediaStudio.exe
```

注意：EXE 只封装网页控制台本身，底层 `douyin-downloader` 和浏览器依赖仍建议通过 `setup.ps1` 安装。

## 发布到 GitHub

```powershell
git init -b main
git add .
git commit -m "Initial Douyin Media Studio"
gh repo create douyin-media-studio --private --source . --remote origin --push
```

如果要公开给别人下载，把 `--private` 改成 `--public`。
