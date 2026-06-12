const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("desktop", {
  chooseFolder: current => ipcRenderer.invoke("choose-folder", current),
  openFolder: target => ipcRenderer.invoke("open-folder", target),
  openLogin: () => ipcRenderer.invoke("open-login"),
  saveLogin: () => ipcRenderer.invoke("save-login"),
});
