# 雷神加速器自动暂停方案 - 最终结果

## 1. 最终状态

已实现并调试通过：

- 自动启动雷神加速器客户端。
- 自动开启 Electron Chrome DevTools Protocol，端口为 9222。
- 通过 CDP 连接雷神渲染进程。
- 在渲染进程 JS 上下文中调用 window.leigodSimplify.invoke(...)。
- 支持根据进程列表自动暂停 / 保持当前计时状态：
  - 监控进程全部关闭：调用 pause-user-time 暂停计时。
  - 任一监控进程运行：调用 ecover-user-time 保持当前计时状态。
- 支持配置文件热重载。
- 支持自动登录，留空时使用已有登录态。
- 支持雷神更新后重新 patch。

当前已验证：

`	ext
http://127.0.0.1:9222/json -> HTTP 200
typeof window.leigodSimplify -> object
get-login-info -> ok True
refresh-user-time-info -> ok True
pause-user-time -> 可调用；运行中进程不触发计时切换
`

---

## 2. 文件清单

工作目录：

`	ext
C:\Users\User\leigod_analysis
`

核心文件：

`	ext
leigod_wrapper.py          # 主程序：启动雷神、连接 CDP、监控进程、暂停/保持当前计时状态
leigod_config.yaml         # 配置文件
patch_leigod_debug.py      # patch 雷神 app.asar，注入 CDP 调试端口
requirements.txt           # Python 依赖
leigod_analysis.md         # 分析文档
leigod_final_result.md     # 本最终说明文档
`

雷神安装目录相关文件：

`	ext
C:\Program Files (x86)\LeiGod_Acc\resources\app.asar      # 已 patch 的 app.asar
C:\Program Files (x86)\LeiGod_Acc\resources\app.asar.bak  # 原始备份
`

---

## 3. 为什么需要 patch app.asar

最初方案是直接这样启动：

`powershell
"C:\Program Files (x86)\LeiGod_Acc\leigod.exe" --remote-debugging-port=9222 --remote-allow-origins=*
`

实际调试发现：

1. leigod.exe --remote-debugging-port=9222 会短暂开启 DevTools 后立即退出。
2. leigod_launcher.exe 能正常启动雷神，但不会正确转发 --remote-debugging-port 参数。
3. 因此最终采用：修改 pp.asar 内的 dist/main/main.js，在 Electron 主进程启动早期注入：

`js
const { app } = require("electron");
app.commandLine.appendSwitch("remote-debugging-port", process.env.LEIGOD_DEBUG_PORT || "9222");
app.commandLine.appendSwitch("remote-allow-origins", "*");
`

这样之后，正常通过 leigod_launcher.exe 启动雷神，也会自动开启 CDP 端口。

---

## 4. 当前配置

配置文件：

`	ext
C:\Users\User\leigod_analysis\leigod_config.yaml
`

当前示例配置：

`yaml
watched_processes:
  - "notepad.exe"

check_interval: 60
show_time_info: true
leigod_exe: "C:\\Program Files (x86)\\LeiGod_Acc\\leigod_launcher.exe"
debug_port: 9222

login_mobile: ""
login_password: ""
login_country: "86"

connect_retries: 5
connect_retry_interval: 5
`

实际使用时，把 watched_processes 改成游戏进程即可，例如：

`yaml
watched_processes:
  - "steam.exe"
  - "GenshinImpact.exe"
  - "LeagueClient.exe"
`

---

## 5. 安装依赖

首次使用前执行：

`powershell
cd C:\Users\User\leigod_analysis
pip install -r requirements.txt
`

---

## 6. 正常使用方式

### 一键运行

`powershell
cd C:\Users\User\leigod_analysis
python leigod_wrapper.py
`

脚本会读取配置、启动 leigod_launcher.exe、等待 127.0.0.1:9222、连接 CDP，然后根据进程状态自动暂停 / 保持当前计时状态。

### 雷神已打开时运行

`powershell
python leigod_wrapper.py --no-launch
`

### 临时指定监控进程

`powershell
python leigod_wrapper.py "game.exe" "steam.exe"
`

### 临时修改轮询间隔

`powershell
python leigod_wrapper.py --interval 10
`

### 不打印时间余额

`powershell
python leigod_wrapper.py --no-time-info
`

### 启动后隐藏到托盘

`powershell
python leigod_wrapper.py --tray
`

---

## 7. 自动登录

默认不自动登录，使用雷神已有登录态。

如果需要自动登录，可以在配置文件里填写：

`yaml
login_mobile: "手机号"
login_password: "密码"
login_country: "86"
`

或者命令行传入：

`powershell
python leigod_wrapper.py --mobile 手机号 --password 密码
`

---

## 8. 更新雷神后怎么办

雷神更新后，大概率会覆盖：

`	ext
C:\Program Files (x86)\LeiGod_Acc\resources\app.asar
`

如果被覆盖，CDP 端口会失效。表现为 http://127.0.0.1:9222/json 打不开，或者 leigod_wrapper.py 无法连接。

解决方法：重新 patch。

`powershell
cd C:\Users\User\leigod_analysis
python patch_leigod_debug.py
python leigod_wrapper.py
`

---

## 9. patch 工具用法

### 重新 patch

`powershell
cd C:\Users\User\leigod_analysis
python patch_leigod_debug.py
`

默认 patch：

`	ext
C:\Program Files (x86)\LeiGod_Acc\resources\app.asar
`

默认端口：9222。

### 指定端口 patch

`powershell
python patch_leigod_debug.py --port 9333
`

如果改端口，也需要同步修改 leigod_config.yaml：

`yaml
debug_port: 9333
`

### 还原原始 app.asar

如果 patch 后雷神打不开，可以还原：

`powershell
python patch_leigod_debug.py --restore
`

会从这里还原：

`	ext
C:\Program Files (x86)\LeiGod_Acc\resources\app.asar.bak
`

### 权限问题

如果 patch 时提示权限不足，请用管理员 PowerShell 执行：

`powershell
cd C:\Users\User\leigod_analysis
python patch_leigod_debug.py
`

---

## 10. 常见问题

### 端口 9222 无法连接

`powershell
tasklist | findstr leigod
netstat -ano | findstr 9222
`

如果雷神启动了但端口没有监听，重新 patch：

`powershell
python patch_leigod_debug.py
`

### 雷神更新后脚本失效

`powershell
python patch_leigod_debug.py
python leigod_wrapper.py
`

### taskkill 拒绝访问

使用管理员 PowerShell：

`powershell
taskkill /IM leigod.exe /F
taskkill /IM leigod_launcher.exe /F
taskkill /IM leishenSdk.exe /F
`

### 暂停失败 / 暂停失败

可能原因：

- 当前已经处于暂停状态，又调用暂停。
- 雷神内部状态暂时不允许切换。
- 未登录或登录态异常。

可以先检查：

`powershell
python leigod_wrapper.py --no-launch --no-time-info
`

---

## 11. 验证命令

### 验证 CDP 端口

雷神启动后访问：

`	ext
http://127.0.0.1:9222/json
`

能看到 JSON 页面说明 CDP 开启成功。

### 验证 IPC 可用

PowerShell 下运行：

`powershell
@'
from leigod_wrapper import connect
cdp = connect(9222, retries=1, interval=1)
print(cdp.eval('typeof window.leigodSimplify'))
print(cdp.invoke('get-login-info', timeout=8).get('ok'))
print(cdp.invoke('refresh-user-time-info', timeout=8).get('ok'))
cdp.close()
'@ | python -
`

期望输出：

`	ext
object
True
True
`

---

## 12. 推荐日常流程

### 首次或雷神更新后

`powershell
cd C:\Users\User\leigod_analysis
python patch_leigod_debug.py
python leigod_wrapper.py
`

### 日常使用

`powershell
cd C:\Users\User\leigod_analysis
python leigod_wrapper.py
`

### 修改监控进程

编辑：

`	ext
C:\Users\User\leigod_analysis\leigod_config.yaml
`

修改：

`yaml
watched_processes:
  - "你的游戏进程.exe"
`

保存后，正在运行的 leigod_wrapper.py 会自动热重载配置。

---

## 13. 当前结论

最终可行方案不是直接给 leigod.exe 传 --remote-debugging-port，而是：

1. patch pp.asar，在 Electron 主进程启动早期注入 CDP 参数。
2. 正常通过 leigod_launcher.exe 启动客户端。
3. leigod_wrapper.py 连接 127.0.0.1:9222。
4. 通过 window.leigodSimplify.invoke() 调用雷神内部 IPC。
5. 根据进程状态自动暂停 / 保持当前计时状态。

该方案已在当前环境调试通过。


