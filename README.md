# 抖音媒体工作台

Windows 桌面归档工具，用于下载本人账号或已获授权的抖音作品。

## 安装使用

1. 打开 [Releases](https://github.com/iTakatox/douyin-media-studio/releases)。
2. 下载最新版 `DouyinMediaStudio-Setup-*.exe`。
3. 双击安装，安装程序会创建桌面和开始菜单图标。
4. 打开“抖音媒体工作台”。
5. 首次启动会自动安装下载组件，请保持网络连接。
6. 在软件内登录抖音、粘贴主页链接、选择保存目录并开始下载。

应用基于 Electron，后台下载服务静默运行，不会弹出命令行窗口。

## 主要功能

- 软件内登录抖音
- 系统文件夹选择窗口，也支持手动修改路径
- 分别下载视频作品和图文作品
- 可设置最大数量、日期范围和是否包含置顶
- 不下载视频封面、头像和背景音乐
- 自动删除临时原始目录
- 显示作品日期、标题、类型、点赞、评论、收藏
- 生成 Excel 可打开的 `作品清单.csv`

输出结构：

```text
选择的保存位置/
  博主名称/
    博主名称-视频/
      博主名称-标题-作品ID.mp4
    博主名称-图文/
      博主名称-标题-作品ID-1.jpg
    作品清单.csv
```

## 开发

环境要求：

- Windows
- Node.js
- Python
- Git

```powershell
npm install
npm start
```

构建安装包：

```powershell
npm run dist
```

输出：

```text
release-electron/DouyinMediaStudio-Setup-*.exe
```
