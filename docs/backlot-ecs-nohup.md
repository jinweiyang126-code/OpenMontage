# Backlot 在 ECS 上后台运行（nohup 方式）

OpenMontage Backlot 是本地制作看板，默认监听 `127.0.0.1:4750`。在阿里云 ECS 上可用 **nohup** 挂后台，SSH 断开后服务仍运行；本机通过 **SSH 端口转发** 在浏览器访问。

---

## 一、启动（ECS 上执行）

```bash
cd /root/OpenMontage
source .venv/bin/activate

nohup python -m backlot serve --port 4750 > /var/log/backlot.log 2>&1 &
echo $! > /tmp/backlot.pid

# 健康检查
curl -s http://127.0.0.1:4750/api/health
```

### 命令说明

| 命令                                                                                           | 含义                                         |
| ---------------------------------------------------------------------------------------------- | -------------------------------------------- |
| `nohup ... &`                                                                                | 后台运行，忽略挂断信号，SSH 退出后进程不退出 |
| `> /var/log/backlot.log 2>&1`                                                                | 标准输出和错误都写入日志文件                 |
| `echo $! > /tmp/backlot.pid` | `$!` 是刚启动的后台进程 PID，写入文件便于后续 `kill` 停止 |                                              |

若项目不在 `/root/OpenMontage`，请将 `cd` 路径改为 ECS 上的实际目录。

---

## 二、本机浏览器访问

Backlot 只绑定 `127.0.0.1`，不能直接用 `http://ECS公网IP:4750`。在本机 **另开** PowerShell：

```powershell
ssh -L 4750:127.0.0.1:4750 root@43.106.20.90
```

若已配置 SSH 别名 `aliyun-ecs`：

```powershell
ssh -L 4750:127.0.0.1:4750 aliyun-ecs
```

保持该窗口不断开，浏览器打开：

| 页面     | 地址                                           |
| -------- | ---------------------------------------------- |
| 项目库   | http://127.0.0.1:4750                          |
| 单个项目 | http://127.0.0.1:4750/p/<project-id> |

---

## 三、外网访问（方式 1：uvicorn 绑定 0.0.0.0）

> **安全警告：** Backlot **没有登录鉴权**。绑定 `0.0.0.0` 并对公网开放后，任何知道 IP 和端口的人都能访问项目看板与媒体预览。仅建议在测试环境使用，或配合安全组 **仅放行你的公网 IP**。

默认命令 `python -m backlot serve` 只监听 `127.0.0.1`，外网无法访问。若需 **公网 IP 直接打开浏览器**，改用 uvicorn 绑定所有网卡：

### 启动（ECS 上执行）

```bash
cd /root/OpenMontage
source .venv/bin/activate

# 若已有旧进程，先停止
kill $(cat /tmp/backlot.pid) 2>/dev/null
pkill -f "backlot serve" 2>/dev/null
pkill -f "uvicorn backlot.server" 2>/dev/null

nohup uvicorn backlot.server:app --host 0.0.0.0 --port 4750 > /var/log/backlot.log 2>&1 &
echo $! > /tmp/backlot.pid

# 健康检查（本机）
curl -s http://127.0.0.1:4750/api/health
```

### 阿里云安全组

ECS 控制台 → **安全组 → 入方向**，新增规则：

| 协议 | 端口 | 来源 | 说明 |
|------|------|------|------|
| TCP | 4750 | 你的公网 IP/32 | 推荐，仅自己可访问 |
| TCP | 4750 | 0.0.0.0/0 | 不推荐，全网可访问 |

查询本机公网 IP：浏览器搜索「IP」或访问 https://ifconfig.me

### 浏览器访问

将 `43.106.20.90` 换成 ECS 公网 IP：

| 页面 | 地址 |
|------|------|
| 项目库 | http://43.106.20.90:4750 |
| 单个项目 | http://43.106.20.90:4750/p/<project-id> |

**无需** SSH 端口转发；本机任意网络均可直接打开（在安全组放行前提下）。

### 停止 / 重启（外网模式）

```bash
kill $(cat /tmp/backlot.pid)
# 或
pkill -f "uvicorn backlot.server"

# 重启
cd /root/OpenMontage && source .venv/bin/activate
nohup uvicorn backlot.server:app --host 0.0.0.0 --port 4750 > /var/log/backlot.log 2>&1 &
echo $! > /tmp/backlot.pid
```

### 改回仅本机访问（SSH 隧道模式）

停止 uvicorn 后，改回「一、启动」中的 `python -m backlot serve`（监听 `127.0.0.1`），并 **删除安全组 4750 入站规则**。

---

## 四、外网访问（方式 2：Nginx 反向代理 + 密码鉴权）

> **推荐的外网方案。** Backlot 仍只监听 `127.0.0.1:4750`，不对外暴露 4750 端口；由 Nginx 对外提供 80/443，并加 HTTP Basic 认证。  
> **生产环境使用阿里云 ECS + 宝塔面板** 时，请直接看 **「2. 宝塔面板部署」**；下文「3. 命令行 Nginx」为无宝塔时的备选。

### 架构

```text
浏览器 → Nginx（80/443，用户名密码） → 127.0.0.1:4750（Backlot，仅本机）
```

### 1. 启动 Backlot（仅本机，不要用 0.0.0.0）

```bash
cd /root/OpenMontage
source .venv/bin/activate

pkill -f "uvicorn backlot.server" 2>/dev/null
pkill -f "backlot serve" 2>/dev/null

nohup python -m backlot serve --port 4750 > /var/log/backlot.log 2>&1 &
echo $! > /tmp/backlot.pid

curl -s http://127.0.0.1:4750/api/health
```

### 2. 宝塔面板部署（生产推荐）

前提：ECS 已安装 **宝塔 Linux 面板**，且 Nginx 由宝塔管理（面板 → 软件商店 → 已安装 Nginx）。

#### 2.1 添加网站

1. 登录宝塔面板（一般为 `http://ECS公网IP:8888/xxxx`，勿对全网长期开放 8888）。
2. **网站** → **添加站点**：
   - **域名**：填公网 IP（如 `43.106.20.90`）或已解析的域名（如 `backlot.example.com`）
   - **根目录**：默认即可（Backlot 走反向代理，不用站点目录里的文件）
   - **PHP 版本**：选 **纯静态** 或 **不创建 PHP**（视面板版本而定）
3. 提交创建站点。

#### 2.2 配置反向代理

1. 进入该站点 → **设置** → **反向代理** → **添加反向代理**。
2. 填写：

| 项 | 值 |
|----|-----|
| 代理名称 | `backlot` |
| 目标 URL | `http://127.0.0.1:4750` |
| 发送域名 | `$host` |
| 内容替换 | 不填 |

3. 保存后，在反向代理条目上点 **配置文件** 或 **编辑**，在 `location` 内 **追加**（Backlot 的 SSE 实时看板需要）：

```nginx
proxy_buffering off;
proxy_cache off;
proxy_read_timeout 3600s;
proxy_send_timeout 3600s;
proxy_http_version 1.1;
proxy_set_header Range $http_range;
proxy_set_header If-Range $http_if_range;
```

4. 保存并重载 Nginx（面板一般会提示重载；或 **软件商店 → Nginx → 重载配置**）。

> 若面板只有「反向代理」表单、无法编辑片段：到站点 **设置 → 配置文件**，找到 `#PROXY-START/` 与 `#PROXY-END/` 之间的 `location`，手动加入上面几行。

#### 2.3 密码鉴权（二选一）

**方法 A：宝塔「密码访问」（推荐，图形界面）**

1. 站点 **设置** → **密码访问**（部分版本在 **访问限制** 下）。
2. 开启，设置 **用户名**、**密码**（如 `backlot` / 强密码）。
3. 保存。

**方法 B：HTTP Basic Auth（与命令行 htpasswd 一致）**

SSH 到 ECS：

```bash
dnf install -y httpd-tools   # 或 yum install
mkdir -p /www/server/pass/backlot
htpasswd -c /www/server/pass/backlot/.htpasswd backlot
```

站点 **设置 → 配置文件**，在 `server { ... }` 内、`location` 之前或 `location /` 内增加：

```nginx
auth_basic "Backlot";
auth_basic_user_file /www/server/pass/backlot/.htpasswd;
```

保存并重载 Nginx。

#### 2.4 HTTPS（建议）

1. 站点 **设置 → SSL**。
2. **Let's Encrypt** 一键申请（需域名已解析到 ECS），或 **其他证书** 上传阿里云申请的 `.pem` / `.key`。
3. 开启 **强制 HTTPS**。

#### 2.5 防火墙与安全组

| 位置 | 操作 |
|------|------|
| **阿里云安全组** | 放行 **80、443**；**不要** 对公网开放 **4750** |
| **宝塔 → 安全** | 放行 **80、443**（若启用了宝塔系统防火墙） |
| **宝塔面板 8888** | 仅允许你的 IP 访问，或改非常用端口 |

#### 2.6 访问与验证

| 页面 | 地址 |
|------|------|
| 项目库 | `http://你的域名或IP/` |
| 单个项目 | `http://你的域名或IP/p/<project-id>` |

浏览器会先弹出 **用户名/密码**（密码访问或 Basic Auth），通过后进入 Backlot。

```bash
# SSH 验证（方法 B 时）
curl -u backlot:你的密码 http://127.0.0.1/api/health

# 经 Nginx 验证
curl -u backlot:你的密码 http://43.106.20.90/api/health
```

#### 2.7 宝塔常见问题

| 现象 | 处理 |
|------|------|
| 502 Bad Gateway | Backlot 未启动；`curl http://127.0.0.1:4750/api/health` |
| 看板不实时刷新 | 反向代理 location 缺少 `proxy_buffering off` |
| 401 / 反复要密码 | 检查密码访问是否重复配置了 Basic Auth；清除浏览器缓存 |
| 视频无法播放 | 确认已加 `Range` / `If-Range` 头；增大 `proxy_read_timeout` |
| 改配置不生效 | 宝塔 **Nginx → 重载**；或 `nginx -t` 检查语法 |

站点 Nginx 配置常见路径（便于 SSH 排查）：

```text
/www/server/panel/vhost/nginx/你的域名.conf
```

---

### 3. 命令行 Nginx（无宝塔 / 备选）

#### 3.1 安装 Nginx 与 htpasswd 工具

阿里云 Linux / CentOS / RHEL：

```bash
dnf install -y nginx httpd-tools
# 若无 dnf：yum install -y nginx httpd-tools
```

Ubuntu / Debian：

```bash
apt update && apt install -y nginx apache2-utils
```

#### 3.2 创建访问账号（HTTP Basic Auth）

```bash
# 首次创建 -c；追加用户去掉 -c
htpasswd -c /etc/nginx/.htpasswd_backlot backlot
# 按提示输入密码（至少 8 位建议）

# 追加第二个用户（不要用 -c，会覆盖文件）
# htpasswd /etc/nginx/.htpasswd_backlot alice

chmod 640 /etc/nginx/.htpasswd_backlot
chown root:nginx /etc/nginx/.htpasswd_backlot
```

#### 3.3 Nginx 站点配置

创建 `/etc/nginx/conf.d/backlot.conf`（将 `43.106.20.90` 换成域名或 ECS 公网 IP）：

```nginx
server {
    listen 80;
    server_name 43.106.20.90;   # 或 backlot.example.com

    # 可选：强制 HTTPS（配置好证书后取消注释）
    # return 301 https://$host$request_uri;

    location / {
        auth_basic "Backlot";
        auth_basic_user_file /etc/nginx/.htpasswd_backlot;

        proxy_pass http://127.0.0.1:4750;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Backlot 使用 SSE 推送变更，必须关闭缓冲
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;

        # 视频 /media  Range 请求透传
        proxy_set_header Range $http_range;
        proxy_set_header If-Range $http_if_range;
    }
}
```

检查并重载：

```bash
nginx -t
systemctl enable nginx
systemctl restart nginx
```

#### 3.4 阿里云安全组

| 协议 | 端口 | 来源 | 说明 |
|------|------|------|------|
| TCP | 80 | 0.0.0.0/0 或你的 IP | HTTP 访问 |
| TCP | 443 | 0.0.0.0/0 或你的 IP | HTTPS（若配置证书） |
| TCP | 4750 | **不开放** | Backlot 仅本机，经 Nginx 访问 |

#### 3.5 浏览器访问

| 页面 | 地址 |
|------|------|
| 项目库 | http://43.106.20.90/ |
| 单个项目 | http://43.106.20.90/p/<project-id> |

首次打开会弹出 **用户名 / 密码** 对话框（即 `htpasswd` 创建的账号）。

#### 3.6 命令行验证

```bash
curl -u backlot:你的密码 http://127.0.0.1/api/health
curl -u backlot:你的密码 http://43.106.20.90/api/health
```

#### 3.7 可选：HTTPS（Let's Encrypt 或阿里云证书）

有域名且解析到 ECS 时，可用 certbot：

```bash
dnf install -y certbot python3-certbot-nginx
certbot --nginx -d backlot.example.com
```

或在 Nginx 中手动配置 `ssl_certificate` / `ssl_certificate_key`（阿里云免费证书下载的 `.pem` / `.key`）。

HTTPS 示例片段：

```nginx
server {
    listen 443 ssl;
    server_name backlot.example.com;

    ssl_certificate     /etc/nginx/ssl/backlot.pem;
    ssl_certificate_key /etc/nginx/ssl/backlot.key;

    location / {
        auth_basic "Backlot";
        auth_basic_user_file /etc/nginx/.htpasswd_backlot;
        proxy_pass http://127.0.0.1:4750;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
        proxy_set_header Range $http_range;
        proxy_set_header If-Range $http_if_range;
    }
}
```

#### 3.8 运维

```bash
# 修改密码 / 新增用户
htpasswd /etc/nginx/.htpasswd_backlot backlot

# 重载 Nginx
nginx -t && systemctl reload nginx

# 查看 Nginx 日志
tail -f /var/log/nginx/access.log /var/log/nginx/error.log
```

### 4. 与方式 1 对比

| 项 | 方式 1（0.0.0.0:4750） | 方式 2（Nginx + 密码） |
|----|------------------------|-------------------------|
| 鉴权 | 无 | HTTP Basic 用户名密码 |
| 暴露端口 | 4750 | 80 / 443 |
| Backlot 绑定 | 0.0.0.0 | 127.0.0.1（更安全） |
| 推荐度 | 临时测试 | **长期外网推荐** |

---

## 五、日常运维

### 查看是否在运行

```bash
curl -s http://127.0.0.1:4750/api/health
ps aux | grep -E "backlot serve|uvicorn backlot"
cat /tmp/backlot.pid
```

### 查看日志

```bash
tail -f /var/log/backlot.log
```

### 停止服务

```bash
kill $(cat /tmp/backlot.pid)
# 若 PID 文件丢失：
pkill -f "backlot serve"
pkill -f "uvicorn backlot.server"
```

### 重启服务（本机模式）

```bash
kill $(cat /tmp/backlot.pid) 2>/dev/null
pkill -f "backlot serve" 2>/dev/null
pkill -f "uvicorn backlot.server" 2>/dev/null

cd /root/OpenMontage
source .venv/bin/activate
nohup python -m backlot serve --port 4750 > /var/log/backlot.log 2>&1 &
echo $! > /tmp/backlot.pid
```

---

## 六、自定义端口

```bash
export BACKLOT_PORT=8080
nohup python -m backlot serve --port 8080 > /var/log/backlot.log 2>&1 &
echo $! > /tmp/backlot.pid
```

本机隧道：

```powershell
ssh -L 8080:127.0.0.1:8080 root@43.106.20.90
```

浏览器：http://127.0.0.1:8080

---

外网模式自定义端口示例：

```bash
nohup uvicorn backlot.server:app --host 0.0.0.0 --port 8080 > /var/log/backlot.log 2>&1 &
echo $! > /tmp/backlot.pid
```

安全组同步放行 **8080**，浏览器：`http://ECS公网IP:8080`

---

## 七、无真实项目时的演示

```bash
cd /root/OpenMontage
source .venv/bin/activate
python scripts/backlot_simulate_run.py
```

演示项目 ID 一般为 `backlot-demo-run`（需先建 SSH 隧道）：

http://127.0.0.1:4750/p/backlot-demo-run

---

## 八、常见问题

| 现象                  | 处理                                                                               |
| --------------------- | ---------------------------------------------------------------------------------- |
| `curl` 健康检查失败 | 确认 venv 已激活、依赖已安装；查看`/var/log/backlot.log`                         |
| 本机浏览器打不开（隧道模式） | 确认 ECS 上进程在跑，且本机 `ssh -L` 窗口未关闭 |
| SSE 看板不刷新（Nginx 模式） | 确认 `proxy_buffering off`；`nginx -t` 后 reload |
| 401 Unauthorized | 检查 `htpasswd` 用户名密码；`auth_basic_user_file` 路径与权限 |
| 外网打不开（方式 1） | 确认 `uvicorn --host 0.0.0.0`；安全组放行 4750 |
| 外网打不开（方式 2） | 确认 Nginx 运行；安全组放行 80/443；Backlot 在 127.0.0.1:4750 |
| 看板为空              | `projects/` 下尚无项目；先用 Cursor Agent 制作或运行 `backlot_simulate_run.py` |
| 端口被占用            | 换`--port`，或 `pkill -f "backlot serve"` 后重启                               |
| ECS 重启后服务消失    | nohup 不会开机自启；需重新执行「一、启动」，或改用 systemd                         |

---

## 九、与 Cursor Remote-SSH 配合

1. ECS 上按本文「一、启动」挂好 Backlot（可关闭 SSH，服务仍在）。
2. 本机 PowerShell 执行 `ssh -L 4750:127.0.0.1:4750 ...`。
3. Cursor 连 ECS 做视频制作；Backlot 随 `projects/` 变更自动刷新看板。

---

## 十、安全说明

| 模式 | 监听地址 | 对外端口 | 鉴权 | 适用场景 |
|------|----------|----------|------|----------|
| 本机 + SSH 隧道（「一」） | `127.0.0.1:4750` | 无 | SSH | **日常自用，最安全** |
| 外网直连（「三、方式 1」） | `0.0.0.0:4750` | 4750 | 无 | 临时测试，慎用 |
| Nginx + 密码（「四、方式 2」） | `127.0.0.1:4750` | 80/443 | HTTP Basic | **外网长期推荐** |
| 宝塔反向代理 + 密码（「四、2」） | `127.0.0.1:4750` | 80/443 | 面板密码/Basic | **生产（宝塔）推荐** |

外网建议：

- 已装宝塔：用 **第四节「2. 宝塔面板部署」**，并开 HTTPS
- 无宝塔：用 **方式 2 命令行 Nginx + htpasswd**
- 方式 1 若必须使用：安全组限制为你的公网 IP，不用时关闭规则
- Basic 认证密码请用强密码；HTTPS 避免明文传输密码

---

*方式：nohup 后台挂起。若需开机自启与崩溃自动重启，可改用 systemd。*
