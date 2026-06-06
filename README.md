# Douyin Media Studio

一个 Windows 本地桌面应用，用于归档你自己的或已获授权的抖音作品。安装后会在桌面创建图标，双击打开独立应用窗口，不需要手动打开浏览器。

> 仅用于你自己的账号或已获授权的内容。

## 用户下载和安装（推荐）

1. 打开 Releases 页面。
2. 下载最新的安装包：

```text
DouyinMediaStudioSetup-*.exe
```

3. 双击运行安装包。
4. 安装器会自动解压程序、安装依赖、创建桌面图标。
5. 安装完成后，桌面会出现：

```text
Douyin Media Studio
```

6. 双击桌面图标启动。

## ZIP 源码包安装（备用）

如果你下载的是 `DouyinMediaStudio-*.zip`：

```powershell
.\setup.ps1
```

## 功能

- 独立桌面窗口，不需要手动打开浏览器
- 直接粘贴整段抖音分享口令
- 自动提取 `https://v.douyin.com/...` 链接
- 网页内按钮触发抖音重新登录
- 自动整理输出：

```text
保存位置/
  mp4/
  images/
  _raw/
  manifest.json
```

## 首次安装会做什么

安装包内部会调用 `setup.ps1`，自动：

- 克隆底层项目 `jiji262/douyin-downloader`
- 创建 Python 虚拟环境
- 安装下载依赖
- 安装 Playwright Chromium
- 安装桌面窗口依赖 `pywebview`
- 创建桌面快捷方式

需要 Windows、Python、Git。

## 登录抖音

如果下载失败并提示 Cookie 失效：

1. 点击应用左侧的“重新登录抖音”。
2. 在弹出的登录窗口里登录抖音。
3. 登录成功后，回到 PowerShell 窗口按 Enter 保存 Cookie。
4. 重新开始下载。

## 开发运行

```powershell
python desktop_app.py
```

如果只想用浏览器调试：

```powershell
python app.py
```

浏览器地址：

```text
http://127.0.0.1:5055
```

## 打包 EXE

可选：

```powershell
.\build-exe.ps1
```

生成：

```text
dist/DouyinMediaStudio.exe
```

说明：EXE 封装的是桌面窗口和控制台界面；底层下载器和浏览器依赖仍建议用 `setup.ps1` 安装。

## 构建安装包

推荐使用 PyInstaller 安装器：

```powershell
.\build-installer-py.ps1
```

生成：

```text
release/DouyinMediaStudioSetup-v1.2.1.exe
```

旧的 IExpress 构建脚本保留作备用，但不推荐。

```powershell
.\build-installer.ps1
```

生成：

```text
release/DouyinMediaStudioSetup-v1.2.0.exe
```
