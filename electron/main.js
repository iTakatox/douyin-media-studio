const { app, BrowserWindow, dialog, ipcMain, shell, session } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const http = require("http");

const PORT = 5055;
const APP_VERSION = app.getVersion();
let mainWindow;
let loginWindow;
let backend;
let setupWindow;

function resourcePath(...parts) {
  return path.join(app.isPackaged ? process.resourcesPath : path.join(__dirname, ".."), ...parts);
}

function runtimeDir() {
  return path.join(app.getPath("userData"), "runtime");
}

function downloaderDir() {
  return process.env.DOUYIN_DOWNLOADER_DIR || path.join(app.getPath("userData"), "douyin-downloader");
}

function backendCommand() {
  if (app.isPackaged) {
    return {
      command: resourcePath("backend", "DouyinBackend.exe"),
      args: [],
      cwd: resourcePath("backend"),
    };
  }
  return {
    command: "python",
    args: ["app.py"],
    cwd: path.join(__dirname, ".."),
  };
}

function waitForBackend(timeout = 20000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const probe = () => {
      const request = http.get(`http://127.0.0.1:${PORT}/`, response => {
        response.resume();
        resolve();
      });
      request.on("error", () => {
        if (Date.now() - started > timeout) reject(new Error("下载服务启动超时"));
        else setTimeout(probe, 250);
      });
      request.setTimeout(1000, () => request.destroy());
    };
    probe();
  });
}

async function startBackend() {
  fs.mkdirSync(runtimeDir(), { recursive: true });
  const spec = backendCommand();
  backend = spawn(spec.command, spec.args, {
    cwd: spec.cwd,
    windowsHide: true,
    env: {
      ...process.env,
      DOUYIN_DOWNLOADER_DIR: downloaderDir(),
      DOUYIN_APP_DATA_DIR: runtimeDir(),
      PYTHONUTF8: "1",
      PYTHONIOENCODING: "utf-8",
    },
    stdio: "ignore",
  });
  await waitForBackend();
}

function setupScript() {
  return app.isPackaged ? resourcePath("setup.ps1") : path.join(__dirname, "..", "setup.ps1");
}

function createSetupWindow() {
  setupWindow = new BrowserWindow({
    width: 680,
    height: 470,
    resizable: false,
    title: "抖音媒体工作台初始化",
    icon: resourcePath("app.ico"),
    autoHideMenuBar: true,
  });
  const html = `<!doctype html><meta charset="utf-8"><style>
    body{margin:0;padding:36px;background:#f3f5f7;color:#17191c;font-family:"Microsoft YaHei UI",sans-serif}
    h1{font-size:24px;margin:0 0 8px}p{color:#6d737c;margin:0 0 22px}
    .bar{height:8px;background:#e1e4e8;border-radius:4px;overflow:hidden}.bar i{display:block;height:100%;width:42%;background:#ef3340;animation:m 1.5s infinite alternate}
    pre{height:245px;overflow:auto;margin:18px 0 0;padding:14px;background:#17191c;color:#dce1e7;border-radius:6px;font:12px/1.6 Consolas,monospace;white-space:pre-wrap}
    @keyframes m{to{width:86%}}
  </style><h1>首次启动初始化</h1><p>正在安装下载组件和登录浏览器，只需执行一次，请保持网络连接。</p><div class="bar"><i></i></div><pre id="log">准备中...</pre>
  <script>window.addEventListener("setup-log",e=>{const n=document.getElementById("log");n.textContent+=e.detail+"\\n";n.scrollTop=n.scrollHeight})</script>`;
  setupWindow.loadURL(`data:text/html;charset=utf-8,${encodeURIComponent(html)}`);
}

function sendSetupLog(line) {
  if (!setupWindow || setupWindow.isDestroyed()) return;
  setupWindow.webContents.executeJavaScript(
    `window.dispatchEvent(new CustomEvent("setup-log",{detail:${JSON.stringify(line)}}))`
  ).catch(() => {});
}

async function ensureRuntime() {
  const python = path.join(downloaderDir(), ".venv", "Scripts", "python.exe");
  const config = path.join(downloaderDir(), "config.yml");
  if (fs.existsSync(python) && fs.existsSync(config)) return;

  createSetupWindow();
  await new Promise((resolve, reject) => {
    const child = spawn(
      "powershell.exe",
      ["-NoProfile", "-ExecutionPolicy", "Bypass", "-File", setupScript()],
      {
        windowsHide: true,
        env: {...process.env, DOUYIN_DOWNLOADER_DIR: downloaderDir(), PYTHONUTF8: "1"},
        stdio: ["ignore", "pipe", "pipe"],
      }
    );
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", data => data.split(/\r?\n/).filter(Boolean).forEach(sendSetupLog));
    child.stderr.on("data", data => data.split(/\r?\n/).filter(Boolean).forEach(sendSetupLog));
    child.on("error", reject);
    child.on("exit", code => code === 0 ? resolve() : reject(new Error(`初始化失败，错误代码 ${code}`)));
  });
  if (setupWindow && !setupWindow.isDestroyed()) setupWindow.close();
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 860,
    minWidth: 1040,
    minHeight: 700,
    title: "抖音媒体工作台",
    icon: resourcePath("app.ico"),
    autoHideMenuBar: true,
    backgroundColor: "#f3f5f7",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadURL(`http://127.0.0.1:${PORT}`);
  mainWindow.webContents.on("did-finish-load", () => {
    mainWindow.webContents.send("app-version", APP_VERSION);
  });
}

function yamlCookieBlock(cookies) {
  return "cookies:\n" + cookies
    .sort((a, b) => a.name.localeCompare(b.name))
    .map(cookie => `  ${cookie.name}: ${JSON.stringify(cookie.value)}`)
    .join("\n") + "\n";
}

function saveCookies(cookies) {
  const configPath = path.join(downloaderDir(), "config.yml");
  if (!fs.existsSync(configPath)) throw new Error("下载组件尚未安装");
  const source = fs.readFileSync(configPath, "utf8");
  const block = yamlCookieBlock(cookies);
  const updated = /^cookies:\s*\n(?:^[ \t]+.*\n?)*/m.test(source)
    ? source.replace(/^cookies:\s*\n(?:^[ \t]+.*\n?)*/m, block)
    : `${source.trimEnd()}\n\n${block}`;
  fs.writeFileSync(configPath, updated, "utf8");
}

ipcMain.handle("choose-folder", async (_event, current) => {
  const result = await dialog.showOpenDialog(mainWindow, {
    title: "选择作品保存位置",
    defaultPath: current || app.getPath("downloads"),
    properties: ["openDirectory", "createDirectory"],
  });
  return result.canceled ? "" : result.filePaths[0];
});

ipcMain.handle("open-folder", async (_event, target) => {
  fs.mkdirSync(target, { recursive: true });
  return shell.openPath(target);
});

ipcMain.handle("open-login", async () => {
  if (loginWindow && !loginWindow.isDestroyed()) {
    loginWindow.focus();
    return true;
  }
  const partition = "persist:douyin-login";
  loginWindow = new BrowserWindow({
    width: 1100,
    height: 780,
    title: "登录抖音",
    parent: mainWindow,
    icon: resourcePath("app.ico"),
    autoHideMenuBar: true,
    webPreferences: { partition },
  });
  const isWebUrl = url => /^https?:\/\//i.test(url);
  const isAllowedResource = url => /^(https?|data|blob):/i.test(url);
  const blockExternalProtocol = (event, url) => {
    if (!isWebUrl(url)) {
      event.preventDefault();
      return true;
    }
    return false;
  };
  loginWindow.webContents.on("will-navigate", (event, url) => {
    blockExternalProtocol(event, url);
  });
  loginWindow.webContents.on("will-redirect", (event, url) => {
    blockExternalProtocol(event, url);
  });
  loginWindow.webContents.on("will-frame-navigate", event => {
    blockExternalProtocol(event, event.url);
  });
  loginWindow.webContents.setWindowOpenHandler(({ url }) => {
    if (isWebUrl(url) && /(^|\.)douyin\.com$/i.test(new URL(url).hostname)) {
      loginWindow.loadURL(url).catch(() => {});
    }
    return { action: "deny" };
  });
  session.fromPartition(partition).webRequest.onBeforeRequest((details, callback) => {
    callback({ cancel: !isAllowedResource(details.url) });
  });
  await loginWindow.loadURL("https://www.douyin.com/");
  return true;
});

ipcMain.handle("save-login", async () => {
  const allCookies = await session.fromPartition("persist:douyin-login").cookies.get({});
  const cookies = allCookies.filter(cookie => {
    const domain = (cookie.domain || "").replace(/^\./, "").toLowerCase();
    return domain === "douyin.com" || domain.endsWith(".douyin.com");
  });
  if (!cookies.length) throw new Error("没有读取到登录信息，请先完成登录");
  const names = new Set(cookies.map(cookie => cookie.name));
  if (!names.has("ttwid")) {
    throw new Error("Login data is incomplete (ttwid is missing). Refresh the Douyin page and try again.");
  }
  saveCookies(cookies);
  if (loginWindow && !loginWindow.isDestroyed()) loginWindow.close();
  return cookies.length;
});

app.whenReady().then(async () => {
  try {
    await ensureRuntime();
    await startBackend();
    createWindow();
  } catch (error) {
    dialog.showErrorBox("启动失败", error.message);
    app.quit();
  }
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", () => {
  if (backend && !backend.killed) backend.kill();
});
