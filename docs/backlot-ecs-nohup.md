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

| 命令 | 含义 |
|------|------|
| `nohup ... &` | 后台运行，忽略挂断信号，SSH 退出后进程不退出 |
| `> /var/log/backlot.log 2>&1` | 标准输出和错误都写入日志文件 |
| `echo $! > /tmp/backlot.pid` | `$!` 是刚启动的后台进程 PID，写入文件便于后续 `kill` 停止 |

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

| 页面 | 地址 |
|------|------|
| 项目库 | http://127.0.0.1:4750 |
| 单个项目 | http://127.0.0.1:4750/p/<project-id> |

---

## 三、日常运维

### 查看是否在运行

```bash
curl -s http://127.0.0.1:4750/api/health
ps aux | grep "backlot serve"
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
```

### 重启服务

```bash
kill $(cat /tmp/backlot.pid) 2>/dev/null
pkill -f "backlot serve" 2>/dev/null

cd /root/OpenMontage
source .venv/bin/activate
nohup python -m backlot serve --port 4750 > /var/log/backlot.log 2>&1 &
echo $! > /tmp/backlot.pid
```

---

## 四、自定义端口

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

## 五、无真实项目时的演示

```bash
cd /root/OpenMontage
source .venv/bin/activate
python scripts/backlot_simulate_run.py
```

演示项目 ID 一般为 `backlot-demo-run`（需先建 SSH 隧道）：

http://127.0.0.1:4750/p/backlot-demo-run

---

## 六、常见问题

| 现象 | 处理 |
|------|------|
| `curl` 健康检查失败 | 确认 venv 已激活、依赖已安装；查看 `/var/log/backlot.log` |
| 本机浏览器打不开 | 确认 ECS 上进程在跑，且本机 `ssh -L` 窗口未关闭 |
| 看板为空 | `projects/` 下尚无项目；先用 Cursor Agent 制作或运行 `backlot_simulate_run.py` |
| 端口被占用 | 换 `--port`，或 `pkill -f "backlot serve"` 后重启 |
| ECS 重启后服务消失 | nohup 不会开机自启；需重新执行「一、启动」，或改用 systemd |

---

## 七、与 Cursor Remote-SSH 配合

1. ECS 上按本文「一、启动」挂好 Backlot（可关闭 SSH，服务仍在）。
2. 本机 PowerShell 执行 `ssh -L 4750:127.0.0.1:4750 ...`。
3. Cursor 连 ECS 做视频制作；Backlot 随 `projects/` 变更自动刷新看板。

---

## 八、安全说明

- 默认监听 `127.0.0.1`，无需在安全组开放 `4750`。
- 仅通过 SSH（22）+ 本地端口转发访问，勿改为公网 `0.0.0.0` 暴露。

---

*方式：nohup 后台挂起。若需开机自启与崩溃自动重启，可改用 systemd。*
