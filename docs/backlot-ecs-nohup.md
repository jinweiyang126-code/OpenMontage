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

## 四、日常运维

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

## 五、自定义端口

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

## 六、无真实项目时的演示

```bash
cd /root/OpenMontage
source .venv/bin/activate
python scripts/backlot_simulate_run.py
```

演示项目 ID 一般为 `backlot-demo-run`（需先建 SSH 隧道）：

http://127.0.0.1:4750/p/backlot-demo-run

---

## 七、常见问题

| 现象                  | 处理                                                                               |
| --------------------- | ---------------------------------------------------------------------------------- |
| `curl` 健康检查失败 | 确认 venv 已激活、依赖已安装；查看`/var/log/backlot.log`                         |
| 本机浏览器打不开（隧道模式） | 确认 ECS 上进程在跑，且本机 `ssh -L` 窗口未关闭 |
| 外网浏览器打不开 | 确认用 `uvicorn --host 0.0.0.0` 启动；安全组已放行 4750；ECS 防火墙未拦截 |
| 看板为空              | `projects/` 下尚无项目；先用 Cursor Agent 制作或运行 `backlot_simulate_run.py` |
| 端口被占用            | 换`--port`，或 `pkill -f "backlot serve"` 后重启                               |
| ECS 重启后服务消失    | nohup 不会开机自启；需重新执行「一、启动」，或改用 systemd                         |

---

## 八、与 Cursor Remote-SSH 配合

1. ECS 上按本文「一、启动」挂好 Backlot（可关闭 SSH，服务仍在）。
2. 本机 PowerShell 执行 `ssh -L 4750:127.0.0.1:4750 ...`。
3. Cursor 连 ECS 做视频制作；Backlot 随 `projects/` 变更自动刷新看板。

---

## 九、安全说明

| 模式 | 监听地址 | 安全组 | 适用场景 |
|------|----------|--------|----------|
| 本机 + SSH 隧道（「一、启动」） | `127.0.0.1` | 无需开放 4750 | **推荐**，日常自用 |
| 外网直连（「三、方式 1」） | `0.0.0.0` | 需开放 4750 | 测试/临时分享；**无鉴权，慎用** |

外网模式额外建议：

- 安全组来源设为 **你的公网 IP/32**，不要用 `0.0.0.0/0`
- 不用时停止服务并关闭安全组规则
- 生产环境如需长期外网访问，应在前端加 Nginx + HTTPS + 基础认证（本文未覆盖）

---

*方式：nohup 后台挂起。若需开机自启与崩溃自动重启，可改用 systemd。*
