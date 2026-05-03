# 雷神加速器自动化方案

## 应用分析

### 结构

雷神加速器 v11.0.23 是基于 Electron 的桌面应用，由两个 asar 包组成：

```
C:\Program Files (x86)\LeiGod_Acc\resources\
├── app.asar              # 主进程
│   ├── dist/main/main.js → main.jsc   (bytenode 编译, 232KB)
│   ├── dist/preload/preload.js → preload.jsc
│   ├── node_modules/     (axios, bytenode, leigod-simplify-electron...)
│   └── package.json      (name: "leigod-electron-app")
└── renderer.asar          # 渲染进程 (Vue SPA)
    ├── index.html
    └── assets/
        ├── index-yK-B6zUJ.js    # 3MB Vue 主 bundle
        ├── ipc-MaPts_Nk.js      # 28KB IPC/HTTP 封装层
        ├── login-default-*.js   # 登录主页面
        ├── PasswordLogin-*.js   # 密码登录
        ├── MobileLogin-*.js     # 短信登录
        ├── WechatLogin-*.js     # 微信扫码
        ├── WechatMiniProgram-*.js  # 微信小程序
        ├── ThirdLogin-*.js      # QQ登录
        ├── BindPhone-*.js       # 绑定手机
        ├── ForgetPassword-*.js  # 忘记密码
        └── gt-*.js              # 极验验证码
```

**注意**：主进程代码 (`main.jsc`) 是 bytenode 编译的 V8 字节码，无法直接阅读源码，但通过 `strings` 提取可获得关键 API 端点和逻辑。

---

## 登录流程

### 登录入口

登录页面 (`login-default`) 分为：
- **左侧**：微信扫码 / 微信小程序（由 feature flag `v11_wechat_miniprogram_login` 控制切换）
- **右侧**：短信登录 / 密码登录 选项卡 + QQ 登录入口
- 首次用户默认显示短信登录，有历史账号的用户默认显示密码登录

---

### 方式一：密码登录 (`PasswordLogin`)

```
用户输入手机号 + 密码
    ↓
POST user/password_code        ← 格式校验 (6-20位数字+字母)
    ↓
密码经主进程 md5() 加密 (IPC 通道 "bq")
    ↓
POST clientapi/client/login
    body: {
        mobile_num, country_code (默认"86"),
        password (已加密), user_type: 0,
        remember: 1, autologin: 1,
        device_info: "Windows"
    }
    ↓
成功 → loginSuccess 事件
失败 code 4009691 → 新设备验证 (发短信)
失败 code 400969  → 异地登录验证 (发短信)
```

---

### 方式二：短信验证码登录 (`MobileLogin`)

```
POST clientapi/client/login/send_code
    body: { mobile_num, country_code, phone }
    ↓
返回 { smscode_key, bind_status, verify_key }
    ↓
用户输入验证码
    ↓
若 bind_status==6 (新用户) → 弹窗同意《用户协议》《隐私协议》《儿童保护及监护人须知》
    ↓
POST clientapi/client/login/code
    body: {
        country_code, mobile_num, smscode,
        smscode_key, state: 4,
        device_info, install_package_name, unique_no
    }
    ↓
loginSuccess
```

若短信长时间收不到，会弹出 `InitiativeSendSms` 组件，提供自动编辑短信二维码或手动发短信方式。

---

### 方式三：微信扫码登录 (`WechatLogin`)

```
从 store 获取 wechatLoginInfo.loginurl
    ↓
URL 追加: ?href=https://www.leigod.com/css/wxlogin.css&self_redirect=true
    ↓
iframe (166x166) 加载微信开放平台二维码
    ↓
通过 window.addEventListener("message") 接收 postMessage:
    - wx-scan-change → 已扫码
    - wx-code-change + pathname含"bind" → 需要绑定手机
    - wx-code-change + data.code → 获取到微信 code
    ↓
POST clientapi/client/otherlogin
    body: { code, type: 0, check_code, device_info, install_package_name }
    ↓
loginSuccess
```

微信登录的二维码来源：`open.weixin.qq.com/connect/qrconnect`

---

### 方式四：微信小程序登录 (`WechatMiniProgram`)

```
POST clientapi/client/micro_qrcode        ← 获取二维码图片 (width=280)
    ↓
轮询 POST clientapi/client/micro/qrcode/listen (每3秒)
    state: 1=等待扫码, 2=已授权, 4=过期, 5=待确认, 6=错误
    ↓
state==2 → 获取 access_code
    ↓
POST clientapi/client/user/login/token
    body: { access_code }
    ↓
loginSuccess
```

---

### 方式五：QQ 登录 (`ThirdLogin` + `login-default`)

```
openQQLoginWindow → 打开新窗口加载 qqLoginInfo.loginurl
    ↓
iframe 加载 QQ 授权页面
    ↓
返回 pathname 含 "bind" → 进入绑定手机流程
否则取出 code
    ↓
POST clientapi/client/otherlogin
    body: { code, type: 0, check_code, device_info, install_package_name }
    ↓
loginSuccess
```

---

### 绑定手机 (`BindPhone`)

第三方登录(QQ/微信)首次登录触发：

```
POST clientapi/client/uplink/code/send    ← 发送验证码
POST clientapi/client/rebuild              ← 绑定
    body: { code, verify_code, verify_key, state: "pc", register_type: 3 }
```

---

## API 端点汇总

### 登录相关

| 端点 | 用途 |
|---|---|
| `clientapi/client/login` | 密码登录 |
| `clientapi/client/login/send_code` | 发送短信验证码 |
| `clientapi/client/login/code` | 短信验证码登录 |
| `clientapi/client/otherlogin` | QQ / 微信扫码登录 |
| `clientapi/client/micro_qrcode` | 微信小程序二维码 |
| `clientapi/client/micro/qrcode/listen` | 轮询小程序扫码状态 |
| `clientapi/client/user/login/token` | 小程序 access_code 换 token |
| `clientapi/client/rebuild` | 第三方账号绑定手机 |
| `clientapi/client/uplink/code/send` | 绑定流程发验证码 |
| `user/password_code` | 密码格式验证 |
| `user/verify_code` | 通用验证码 |

### 用户 / 配置

| 端点 | 用途 |
|---|---|
| `clientapi/client/setting/list` | 客户端配置 |
| `secapi/client/user/telecom/state/v2` | 电信用户状态 |
| `secapi/client/user/time/status` | 用户时间状态 |
| `secapi/client/user/agreement/status` | 协议同意状态 |
| `secapi/client/user/agreement/log` | 协议日志 |
| `secapi/client/user/recent/log` | 最近使用日志 |
| `secapi/client/user/speed/stats` | 加速统计 |
| `user/edit/v1` | 编辑用户信息 |
| `user/modify/phone` | 修改手机号 |
| `user/package` | 套餐信息 |
| `user/time/log` | 时间日志 |

### 工具 / 游戏

| 端点 | 用途 |
|---|---|
| `secapi/tools/version/list` | 版本列表 |
| `secapi/tools/banner/list/city` | Banner 列表 |
| `secapi/tools/notice/popup/new/v1` | 弹窗公告 |
| `secapi/tools/polling/game/list` | 游戏列表轮询 |
| `secapi/tools/drainage/ad` | 广告 |
| `secapi/tools/behavior/reported` | 行为上报 |
| `secapi/tools/upload` | 上传 |
| `secapi/tools/upload/image` | 上传图片 |
| `secapi/tools/user/error_report` | 错误上报 |
| `secapi/client/game/report/v2` | 游戏上报 |
| `secapi/client/game/server/official/stats` | 服务器统计 |
| `secapi/tools/game/toolbox/tips/report` | 工具箱提示 |

---

## IPC 通道（主进程 ↔ 渲染进程）

渲染进程通过 `window.leigodSimplify.invoke(channel, ...args)` 调用主进程功能：

| 通道 | 功能 |
|---|---|
| `login` | 密码登录 |
| `logout` | 登出 |
| `pause-user-time` | **暂停计时** |
| `[disabled-time-switch-channel]` | **保持当前计时状态** |
| `refresh-user-time-info` | 刷新时间余额 |
| `get-login-info` | 获取登录状态 |
| `get-cached-user-info` | 获取缓存用户信息 |
| `get-user-identify-info` | 用户身份信息 |
| `get-acc-config` | 应用配置 |
| `start-acc` | 开始加速 |
| `stop-acc` | 停止加速 |
| `stop-other-acc` | 停止其他加速 |
| `get-line-list` | 获取线路列表 |
| `get-exclusive-ip-line-list` | 专线列表 |
| `minimize-window` | 最小化 |
| `hide-window-to-tray` | 隐藏到托盘 |
| `open-login-window` | 打开登录窗口 |
| `close-login-window` | 关闭登录窗口 |
| `get-auto-launch-status` | 开机自启状态 |
| `set-auto-launch-status` | 设置开机自启 |
| `toggle-hardware-acceleration-status` | 硬件加速开关 |
| `get-npcap-driver-status` | Npcap 驱动状态 |
| `start-mobile-game` | 启动手游 |
| `get-game-tools` | 获取游戏工具 |
| `check-virtual-mobile` | 检查虚拟手机号 |
| `decrypt-data` | 解密数据 |
| `http-request` | HTTP 请求 |
| `md5` | MD5 加密 |
| `open-external` | 打开外部链接 |
| `get-install-src-channel` | 安装来源渠道 |

---

## 安全相关

- **密码传输**：客户端用 `md5(password)` 加密后传输（IPC 通道 "bq" 对应 `md5` 函数）
- **设备识别**：登录时携带 `device_info`（系统信息）、`install_package_name`（安装包名）、`unique_no`（设备唯一标识）
- **异地/新设备保护**：密码登录时检测 `code 4009691`(新设备) / `code 400969`(异地)，触发短信二次验证
- **验证码**：集成极验 GeeTest (`captchaId: 95b0b1c603d85acf526d8c82fcc5b731`) 和腾讯验证码 (`appId: 195788894`)，通过 feature flag `v11_is_off_geetest` 控制使用哪个
- **微信登录凭证**：通过 postMessage 从 iframe 获取微信 code
- **用户协议**：新用户（`bind_status==6` 或 `4`）首次登录需同意《用户协议》《隐私协议》《儿童保护及监护人须知》
- **系统时间校验**：IPC 调用时校验本地时间与服务器时间差，超过 25 秒会警告（前10分钟内不校验）

---

## 自动化方案

### 原理

通过 Chrome DevTools Protocol (CDP) 连接雷神客户端的 Electron 渲染进程，在渲染进程的 JS 上下文中直接调用 `window.leigodSimplify.invoke()` IPC 接口。

### 启动客户端（开启调试端口）

```bash
"C:\Program Files (x86)\LeiGod_Acc\leigod.exe" --remote-debugging-port=9222 --remote-allow-origins=*
```

### 连接 CDP

```python
import requests, websocket, json

# 1. 获取渲染进程 WebSocket URL
resp = requests.get("http://127.0.0.1:9222/json")
targets = resp.json()
page = next(t for t in targets if t["type"] == "page")
ws = websocket.create_connection(page["webSocketDebuggerUrl"])

# 2. 执行 JS
msg_id = 1
def evaluate(js):
    global msg_id
    msg_id += 1
    ws.send(json.dumps({"id": msg_id, "method": "Runtime.evaluate",
        "params": {"expression": js, "returnByValue": True, "awaitPromise": True}}))
    while True:
        r = json.loads(ws.recv())
        if r.get("id") == msg_id:
            return r["result"]["result"].get("value")

# 3. 调用 IPC
def invoke(channel, *args):
    args_json = json.dumps(list(args))
    js = f"""
    (async () => {{
        try {{
            const r = await window.leigodSimplify.invoke("{channel}", ...{args_json});
            return JSON.stringify({{ok: true, data: r}});
        }} catch(e) {{
            return JSON.stringify({{ok: false, error: String(e)}});
        }}
    }})()
    """
    return json.loads(evaluate(js))
```

### 自动登录

```python
import hashlib

password_encrypted = hashlib.md5("your_password".encode()).hexdigest()

result = invoke("login", {
    "mobile_num": "13800138000",
    "country_code": "86",
    "password": password_encrypted,
    "user_type": 0,
    "remember": 1,
    "autologin": 1,
    "device_info": "Windows",
})
```

### 暂停 / 保持当前计时状态

```python
invoke("pause-user-time")     # 暂停
invoke("refresh-user-time-info")  # 查看余额
```

### 进程监控自动暂停

通过 `tasklist` 每隔 N 秒扫描目标进程：
- 全部关闭 → 调用 `pause-user-time`
- 任一运行 → 不执行计时切换

完整脚本见 `leigod_wrapper.py`，配置文件见 `leigod_config.yaml`。

---

## 已知问题

- `main.jsc` 是 bytenode 字节码，无法直接反编译为源码，主进程逻辑只能通过字符串提取推断
- Chromium 新版对调试端口有安全限制，需要 `--remote-allow-origins=*` 参数
- 部分 HTTP 客户端连接 `127.0.0.1:9222` 时会被 reset (10054)，可能与客户端的 HTTP 指纹检测有关；当前实现已改为标准 `requests`，必要时会回退到原始 socket 探活
- 密码加密方式为简单 MD5，无盐值



