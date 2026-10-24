# 固定域名部署

临时入口适合先验证能否使用。长期使用需要一个 Cloudflare 管理的域名、一个命名 Tunnel，以及始终在线的校内电脑。固定模式沿用同一域名，正常重启不必重新添加订阅；不提供学校账号免认证功能，也不会让离线电脑继续提供服务。

**验证范围：** 2026-10-24 已使用真实命名 Tunnel 完成公网 TLS、VMess、九个校园入口及下载鉴权的完整链路验证；受控重启后再次通过，域名、链接及私有凭据保持不变。该记录不代表所有学校业务均已登录或所有手机环境均可用，首次部署仍须执行 `check` 并做手机实际访问测试，详见[验证记录](validation.md)。

## Cloudflare 一侧

1. 确认自己的域名已在 Cloudflare 正常托管。在控制台 **Networking → Tunnels** 创建一个专用 Cloudflare Tunnel；不同版本界面也可能位于 Cloudflare One 的网络连接器页面。
2. 为这个 Tunnel 添加 **Published application** 路由，配置一个固定主机名，例如 `campus.example.com`。优先使用根域下一级子域名，并检查该名称没有被已有网站或 DNS 记录使用；不要覆盖无关配置。
3. 服务类型选择 **HTTP**，服务地址填写 **`127.0.0.1:18080`**，路径留空；如果改了 `web_port`，同步修改这里。订阅下载和 WebSocket 必须走同一 HTTP 前端，不能填 `vmess_port`。
4. 使用控制台为这个 Tunnel 提供的连接令牌，将**令牌本身**保存到本项目 `private/cloudflare-token.txt`，不要连同安装命令一起粘贴。
5. 不必运行安装 Windows 系统服务的命令，本程序会用便携 cloudflared 启动连接。

连接令牌用于运行这个特定 Tunnel，不是 Cloudflare 全局 API Key。请在本地编辑器中保存，不要将令牌或包含令牌的安装命令发给公共聊天、Issue 或仓库。

Cloudflare 的发布应用需支持 WebSocket。不要给节点路径增加需要浏览器交互或邮件验证码的 Access 登录；Shadowrocket 无法完成该交互。节点本身仍由独立 VMess 密钥认证，订阅和配置下载另有随机令牌保护。

## 本地配置

先运行 `setup`。编辑 `private/config.json` 的以下字段，其余保持原值：

```json
{
  "tunnel_mode": "named",
  "hostname": "campus.example.com",
  "cloudflare_token_file": "cloudflare-token.txt"
}
```

这只是需要修改的字段，不是完整配置文件。`hostname` 不带 `https://`，不带路径。令牌文件只能位于 `private/` 中。

```powershell
py -3 -B .\jlu_shadowrocket.py prepare
py -3 -B .\jlu_shadowrocket.py start
```

在另一个终端运行：

```powershell
py -3 -B .\jlu_shadowrocket.py check
```

控制台显示固定链接不代表连接已经建立。先确认 Cloudflare Tunnel 健康、域名 DNS 与有效 HTTPS 证书就绪，再验证两条受保护的下载链接和完整校园访问链路。手机关闭 VPN 总开关后导入启动窗口显示的新订阅和分流链接，按 README 测试。

首次验证成功后，在启动窗口按 Ctrl+C 停止本实例，再运行 `start`，确认主机名和链接不变，并重新执行 `check`。这项重启验证不需要删除 Tunnel、DNS、配置或密钥。

## 从临时模式迁移或切回

- 保存原配置的本地副本，保留 `private/secrets.json`。使用同一实例切换时，停止本实例后只修改上述三个字段，保留端口、学校域名和 `node_name`。
- 固定模式首次启用时，订阅地址和节点主机名会改变，需要在手机导入固定链接。日常配置引用的节点名保持一致时，学校 DOMAIN 规则无需改名。
- 若要在不中断临时入口的情况下验证，使用独立项目目录和四个不冲突的回环端口；Cloudflare 路由填写新实例的实际 `web_port`。验证新实例成功并确认手机已切换后，再停止旧实例。
- 切回临时模式：停止本实例，将 `private/config.json` 的 `tunnel_mode` 改为 `quick`，再运行 `prepare` 和 `start`。`hostname` 与令牌文件可保留供以后使用，不必删除。新临时链接会改变，手机需要重新导入。
- 固定模式保持域名、路由、密钥和令牌有效时，正常重启继续使用固定链接。域名到期、隧道配置变更、电脑休眠或断网仍会影响访问。

令牌通过文件路径传给 cloudflared，不放在进程命令行中。不要把令牌、`private/`、包含令牌的日志或控制台截图提交到 GitHub。需要更换密钥时先停止服务，在自己的 Cloudflare 账户处理 Tunnel 令牌，再按原路径更新本地文件。

## 官方资料

- [创建和管理 Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/)
- [Cloudflare Tunnel 运行参数](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/cloudflared-parameters/run-parameters/)
- [临时入口的限制](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
