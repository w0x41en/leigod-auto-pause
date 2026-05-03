# LeiGod Auto Pause

LeiGod Auto Pause 是一个 Windows 本地自动化工具，用于通过 Electron Chrome DevTools Protocol（CDP）连接本机雷神加速器客户端，并根据指定进程是否运行，自动调用客户端内部 IPC 接口暂停计时。

> 免责声明：本项目仅用于本机自动化和个人效率用途，不隶属于、也不代表雷神加速器或其关联公司。本仓库不包含雷神客户端、asar 解包内容、字节码、图片、二进制资源等第三方专有文件。请自行确保你的使用方式符合当地法律法规和相关软件服务条款。

## 功能

- 自动启动雷神客户端启动器。
- 通过 `127.0.0.1:9222` 连接 Electron CDP。
- 调用 `window.leigodSimplify.invoke()` 内部 IPC。
- 优先读取雷神当前加速对象关联的进程名，并以它作为监控目标。
- 监控指定进程：任一进程运行则保持当前状态，全部关闭则暂停计时。
- 支持配置文件热重载。
- 支持已有登录态，也支持可选自动登录。
- 支持打包为单文件 exe。
- PyInstaller exe 通过 manifest 在启动前请求管理员权限，便于重启/管理雷神进程且不丢失运行时 stdout。

## 目录结构

```text
.
├── README.md
├── LICENSE
├── requirements.txt
├── leigod_wrapper.spec
├── src/
│   └── leigod_wrapper.py
├── tools/\n│   ├── patch_leigod_debug.py\n│   └── build_exe.ps1
├── config/
│   └── leigod_config.example.yaml
├── docs/
│   ├── leigod_analysis.md
│   └── leigod_final_result.md
```


## 环境要求

- Windows 10/11
- Python 3.10+
- 已安装雷神加速器客户端
- 如需重新 patch `app.asar`：需要 Node.js/npm，因为 patch 工具使用 `npx asar`

安装 Python 依赖：

```powershell
pip install -r requirements.txt
```

## 快速开始

### 1. 准备配置

复制示例配置：

```powershell
copy .\config\leigod_config.example.yaml .\leigod_config.yaml
```

编辑 `leigod_config.yaml`，把 `watched_processes` 改成你要监控的游戏或程序进程名：

```yaml
prefer_acc_processes: true

watched_processes:
  - "game.exe"
  - "steam.exe"

check_interval: 60
show_time_info: true
leigod_exe: "C:\\Program Files (x86)\\LeiGod_Acc\\leigod_launcher.exe"
debug_port: 9222

login_mobile: ""
login_password: ""
login_country: "86"

connect_retries: 5
connect_retry_interval: 5
```

`prefer_acc_processes: true` 时，wrapper 会先尝试从雷神当前加速对象读取关联进程名；读不到时再使用 `watched_processes`。这样通常不需要频繁手动修改监控进程，`watched_processes` 主要作为备用列表。

### 2. 为雷神客户端开启 CDP

由于新版雷神直接向 `leigod.exe` 传 `--remote-debugging-port` 可能会退出，而 `leigod_launcher.exe` 又不会稳定转发该参数，本项目提供本地 patch 工具，在 `app.asar` 的入口 `dist/main/main.js` 中注入 CDP 参数。

首次使用或雷神更新后执行：

```powershell
python .\tools\patch_leigod_debug.py
```

默认 patch 目标：

```text
C:\Program Files (x86)\LeiGod_Acc\resources\app.asar
```

默认备份文件：

```text
C:\Program Files (x86)\LeiGod_Acc\resources\app.asar.bak
```

如遇权限不足，请使用管理员 PowerShell 运行。

如需还原：

```powershell
python .\tools\patch_leigod_debug.py --restore
```

### 3. 运行源码版

```powershell
python .\src\leigod_wrapper.py
```

源码模式会自动请求管理员权限并重新启动自身。exe 模式通过 manifest 在启动前请求管理员权限，不使用运行后重启。若只想连接已经开启 CDP 的客户端，源码模式可跳过提权：

```powershell
python .\src\leigod_wrapper.py --no-admin --no-launch
```

## 使用 exe

本地已构建的 exe 位于：

```text
release\leigod_wrapper.exe
```

使用时确保 exe 同目录存在配置文件：

```text
release\leigod_config.yaml
```

运行：

```powershell
.\release\leigod_wrapper.exe
```

常用参数（exe 已内置管理员权限 manifest，启动前会由系统请求 UAC）：

```powershell
.\release\leigod_wrapper.exe --interval 10
.\release\leigod_wrapper.exe --no-time-info
.\release\leigod_wrapper.exe "game.exe" "steam.exe"
```

## 构建 exe

```powershell
powershell -ExecutionPolicy Bypass -File .\tools\build_exe.ps1
```

构建完成后会生成：

```text
release\leigod_wrapper.exe
release\leigod_config.yaml
```

也可以手动构建：

```powershell
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python -m PyInstaller --clean .\leigod_wrapper.spec
copy .\dist\leigod_wrapper.exe .\release\leigod_wrapper.exe
copy .\config\leigod_config.example.yaml .\release\leigod_config.yaml
```

## 验证 CDP 和 IPC

雷神启动后访问：

```text
http://127.0.0.1:9222/json
```

能看到 JSON 说明 CDP 已开启。

验证 IPC 可用：

```powershell
python -c "from src.leigod_wrapper import connect; c=connect(9222,retries=1,interval=1); print(c.eval('typeof window.leigodSimplify')); print(c.invoke('get-login-info',timeout=8).get('ok')); print(c.invoke('refresh-user-time-info',timeout=8).get('ok')); c.close()"
```

期望输出：

```text
object
True
True
```

## 自动登录

默认不自动登录，使用客户端已有登录态。

如需自动登录，可在配置中填写：

```yaml
login_mobile: "手机号"
login_password: "密码"
login_country: "86"
```

也可以通过命令行传入：

```powershell
python .\src\leigod_wrapper.py --mobile 手机号 --password 密码
```

密码会在本地做 MD5 后传入客户端 IPC。请不要把真实账号配置提交到公开仓库。

## 雷神更新后怎么办

更新后如果 `http://127.0.0.1:9222/json` 打不开，通常说明 `app.asar` 被覆盖，需要重新 patch：

```powershell
python .\tools\patch_leigod_debug.py
```

然后重新运行 wrapper。

## 常见问题

### 端口 9222 无法连接

```powershell
tasklist | findstr leigod
netstat -ano | findstr 9222
```

如果雷神已启动但端口未监听，请重新执行 patch。

### `taskkill` 拒绝访问

雷神部分进程可能以管理员权限运行。使用默认自动提权运行 wrapper，或手动用管理员 PowerShell 关闭：

```powershell
taskkill /IM leigod.exe /F
taskkill /IM leigod_launcher.exe /F
taskkill /IM leishenSdk.exe /F
```

### 暂停失败

可能原因：

- 当前已经处于目标状态。
- 未登录或登录态异常。
- 客户端内部状态暂时不允许切换。

可打开雷神客户端确认当前账号与计时状态。

## License

MIT License. See [LICENSE](LICENSE).




