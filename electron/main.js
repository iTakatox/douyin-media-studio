const { app, BrowserWindow, dialog, ipcMain, shell, session } = require("electron");
const { spawn } = require("child_process");
const fs = require("fs");
const path = require("path");
const http = require("http");
const net = require("net");
const crypto = require("crypto");

const APP_VERSION = app.getVersion();
const INSTANCE_TOKEN = crypto.randomBytes(24).toString("hex");
const PAGE_BRIDGE_TOKEN = crypto.randomBytes(24).toString("hex");
const LOGIN_PARTITION = "persist:douyin-login";
const REQUIRED_LOGIN_COOKIES = ["sessionid_ss", "ttwid", "passport_csrf_token"];
const APP_USER_MODEL_ID = "com.itakatox.mediaarchivestudio";
let backendPort;
let pageBridgePort;
let mainWindow;
let loginWindow;
let pageBridgeWindow;
let backend;
let setupWindow;
let pageBridgeServer;
let pageBridgeQueue = Promise.resolve();

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
      command: resourcePath("backend", "MediaArchiveBackend.exe"),
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

function reservePort() {
  return new Promise((resolve, reject) => {
    const server = net.createServer();
    server.unref();
    server.on("error", reject);
    server.listen(0, "127.0.0.1", () => {
      const address = server.address();
      const port = typeof address === "object" && address ? address.port : 0;
      server.close(error => error ? reject(error) : resolve(port));
    });
  });
}

function runtimeMarkerPath() {
  return path.join(runtimeDir(), "runtime-version.json");
}

function runtimeIsCurrent() {
  const markerPath = runtimeMarkerPath();
  if (!fs.existsSync(markerPath)) return false;
  try {
    const marker = JSON.parse(fs.readFileSync(markerPath, "utf8"));
    return marker.version === APP_VERSION;
  } catch (_error) {
    return false;
  }
}

function markRuntimeCurrent() {
  fs.writeFileSync(runtimeMarkerPath(), JSON.stringify({version: APP_VERSION}), "utf8");
}

function createBridgeError(code, message) {
  const error = new Error(message);
  error.code = code;
  return error;
}

function chromeUserAgent() {
  return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    + "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36";
}

function loginSession() {
  const loginSession = session.fromPartition(LOGIN_PARTITION);
  loginSession.setUserAgent(chromeUserAgent());
  return loginSession;
}

async function hasLoginSession() {
  const currentSession = loginSession();
  const cookieSets = await Promise.all([
    currentSession.cookies.get({domain: ".douyin.com"}),
    currentSession.cookies.get({domain: ".iesdouyin.com"}),
    currentSession.cookies.get({domain: "www.douyin.com"}),
  ]);
  const names = new Set(cookieSets.flat().map(cookie => cookie.name));
  return REQUIRED_LOGIN_COOKIES.every(name => names.has(name));
}

function sleep(milliseconds) {
  return new Promise(resolve => setTimeout(resolve, milliseconds));
}

async function getPageBridgeWindow() {
  if (pageBridgeWindow && !pageBridgeWindow.isDestroyed()) return pageBridgeWindow;
  if (!(await hasLoginSession())) {
    throw createBridgeError("NOT_LOGGED_IN", "请先在应用内完成抖音登录，再读取作品。");
  }
  pageBridgeWindow = new BrowserWindow({
    show: false,
    width: 1280,
    height: 900,
    title: "抖音请求服务",
    webPreferences: {
      partition: LOGIN_PARTITION,
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });
  pageBridgeWindow.on("closed", () => { pageBridgeWindow = null; });
  pageBridgeWindow.webContents.setUserAgent(chromeUserAgent());
  pageBridgeWindow.webContents.setWindowOpenHandler(() => ({action: "deny"}));
  await pageBridgeWindow.loadURL("https://www.douyin.com/user/self");
  const deadline = Date.now() + 20000;
  while (Date.now() < deadline) {
    const ready = await pageBridgeWindow.webContents.executeJavaScript(
      "typeof window.bdms === 'object' && typeof window.byted_acrawler === 'object'",
      true,
    );
    if (ready) return pageBridgeWindow;
    await sleep(500);
  }
  pageBridgeWindow.destroy();
  pageBridgeWindow = null;
  throw createBridgeError("PAGE_LOAD_FAILED", "抖音页面签名组件未能及时加载，请检查网络后重试。");
}

function buildPageBridgeRequest(requestPath, params) {
  if (typeof requestPath !== "string" || !requestPath.startsWith("/aweme/")) {
    throw createBridgeError("INVALID_PATH", "页面请求地址不受支持");
  }
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params || {})) {
    if (value !== undefined && value !== null && !["msToken", "a_bogus", "uifid"].includes(key)) {
      query.set(key, String(value));
    }
  }
  return `${requestPath}${query.size ? `?${query.toString()}` : ""}`;
}

async function fetchViaDouyinPage(requestPath, params, method, data) {
  const targetPath = buildPageBridgeRequest(requestPath, params);
  const bridgeWindow = await getPageBridgeWindow();
  const payload = {
    path: targetPath,
    method: String(method || "GET").toUpperCase(),
    body: data || null,
  };
  const script = `(() => {
    const request = ${JSON.stringify(payload)};
    const options = {
      method: request.method,
      credentials: "include",
      signal: AbortSignal.timeout(25000),
    };
    if (request.body && request.method !== "GET") {
      options.headers = {"Content-Type": "application/x-www-form-urlencoded"};
      options.body = new URLSearchParams(request.body).toString();
    }
    return fetch(request.path, options).then(async response => ({
      status: response.status,
      text: (await response.text()).slice(0, 2 * 1024 * 1024),
    }));
  })()`;
  try {
    const result = await bridgeWindow.webContents.executeJavaScript(script, true);
    return {
      status: Number(result && result.status) || 0,
      text: String((result && result.text) || ""),
    };
  } catch (error) {
    throw createBridgeError("PAGE_FETCH_FAILED", error.message || "应用内抖音页面请求失败");
  }
}

async function startPageBridge() {
  if (pageBridgeServer) return;
  pageBridgeServer = http.createServer(async (request, response) => {
    const send = (status, body) => {
      response.writeHead(status, {"Content-Type": "application/json; charset=utf-8"});
      response.end(JSON.stringify(body));
    };
    const remoteAddress = request.socket.remoteAddress;
    if (
      !["127.0.0.1", "::1", "::ffff:127.0.0.1"].includes(remoteAddress)
      || request.method !== "POST"
      || request.url !== "/fetch"
      || request.headers["x-douyin-bridge-token"] !== PAGE_BRIDGE_TOKEN
    ) {
      send(403, {code: "FORBIDDEN", message: "未授权的本地请求"});
      return;
    }
    let raw = "";
    request.setEncoding("utf8");
    request.on("data", chunk => {
      raw += chunk;
      if (raw.length > 1024 * 1024) request.destroy();
    });
    request.on("end", async () => {
      try {
        const input = JSON.parse(raw || "{}");
        const task = pageBridgeQueue.then(() => fetchViaDouyinPage(
          input.path,
          input.query,
          input.method,
          input.form,
        ));
        pageBridgeQueue = task.catch(() => {});
        const result = await task;
        send(200, result);
      } catch (error) {
        send(502, {code: error.code || "PAGE_BRIDGE_ERROR", message: error.message || "应用内请求失败"});
      }
    });
  });
  await new Promise((resolve, reject) => {
    pageBridgeServer.once("error", reject);
    pageBridgeServer.listen(0, "127.0.0.1", () => {
      pageBridgeServer.off("error", reject);
      const address = pageBridgeServer.address();
      pageBridgePort = typeof address === "object" && address ? address.port : 0;
      resolve();
    });
  });
}

function waitForBackend(timeout = 20000) {
  const started = Date.now();
  return new Promise((resolve, reject) => {
    const probe = () => {
      if (backend && backend.exitCode !== null) {
        reject(new Error(`下载服务启动失败，退出代码 ${backend.exitCode}`));
        return;
      }
      const request = http.get(`http://127.0.0.1:${backendPort}/api/health`, response => {
        let body = "";
        response.setEncoding("utf8");
        response.on("data", chunk => { body += chunk; });
        response.on("end", () => {
          try {
            const result = JSON.parse(body);
            if (response.statusCode === 200 && result.instance_token === INSTANCE_TOKEN) {
              resolve();
              return;
            }
          } catch (_error) {
            // The endpoint is not the backend instance started by this process.
          }
          if (Date.now() - started > timeout) reject(new Error("下载服务身份校验失败"));
          else setTimeout(probe, 250);
        });
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
  await startPageBridge();
  backendPort = await reservePort();
  const spec = backendCommand();
  backend = spawn(spec.command, spec.args, {
    cwd: spec.cwd,
    windowsHide: true,
    env: {
      ...process.env,
      DOUYIN_DOWNLOADER_DIR: downloaderDir(),
      DOUYIN_APP_DATA_DIR: runtimeDir(),
      DOUYIN_PORT: String(backendPort),
      DOUYIN_INSTANCE_TOKEN: INSTANCE_TOKEN,
      DOUYIN_PAGE_BRIDGE_URL: `http://127.0.0.1:${pageBridgePort}/fetch`,
      DOUYIN_PAGE_BRIDGE_TOKEN: PAGE_BRIDGE_TOKEN,
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
    title: "多平台媒体归档初始化",
    icon: resourcePath("app-icon-v2.ico"),
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
  fs.mkdirSync(runtimeDir(), { recursive: true });
  const python = path.join(downloaderDir(), ".venv", "Scripts", "python.exe");
  const config = path.join(downloaderDir(), "config.yml");
  const universalEngine = path.join(downloaderDir(), ".venv", "Scripts", "yt-dlp.exe");
  if (fs.existsSync(python) && fs.existsSync(config) && fs.existsSync(universalEngine) && runtimeIsCurrent()) return;

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
  markRuntimeCurrent();
  if (setupWindow && !setupWindow.isDestroyed()) setupWindow.close();
}

function createWindow() {
  mainWindow = new BrowserWindow({
    width: 1360,
    height: 860,
    minWidth: 1040,
    minHeight: 700,
    title: "多平台媒体归档",
    icon: resourcePath("app-icon-v2.ico"),
    autoHideMenuBar: true,
    backgroundColor: "#f3f5f7",
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  mainWindow.loadURL(`http://127.0.0.1:${backendPort}`);
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
  const block = yamlCookieBlock(cookies);
  try {
    fs.copyFileSync(configPath, `${configPath}.bak`);
  } catch (_error) {
    // Backup failure should not prevent repairing the configuration.
  }
  fs.writeFileSync(configPath, block, "utf8");
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
  const partition = LOGIN_PARTITION;
  loginWindow = new BrowserWindow({
    width: 1100,
    height: 780,
    title: "登录抖音",
    parent: mainWindow,
    icon: resourcePath("app-icon-v2.ico"),
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
  loginSession();
  loginWindow.webContents.setUserAgent(chromeUserAgent());
  await loginWindow.loadURL("https://www.douyin.com/");
  return true;
});

ipcMain.handle("save-login", async () => {
  const allCookies = await loginSession().cookies.get({});
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

app.setAppUserModelId(APP_USER_MODEL_ID);

app.whenReady().then(async () => {
  try {
    await ensureRuntime();
    await startBackend();
    createWindow();
  } catch (error) {
    console.error("多平台媒体归档启动失败:", error);
    dialog.showErrorBox("启动失败", error.message);
    app.quit();
  }
});

app.on("window-all-closed", () => app.quit());
app.on("before-quit", () => {
  if (backend && !backend.killed) backend.kill();
  if (pageBridgeServer) pageBridgeServer.close();
  if (pageBridgeWindow && !pageBridgeWindow.isDestroyed()) pageBridgeWindow.destroy();
});
