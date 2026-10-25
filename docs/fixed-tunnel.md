# 固定域名部署

临时入口适合先验证能否使用。长期使用需要一个 Cloudflare 管理的域名、一个命名 Tunnel，以及始终在线的校内电脑。固定模式沿用同一域名，正常重启不必重新添加订阅；不提供学校账号免认证功能，也不会让离线电脑继续提供服务。

**验证范围：** 2026-10-24 已使用真实命名 Tunnel 完成公网 TLS、VMess、九个校园入口及下载鉴权的完整链路验证；受控重启后再次通过，域名、链接及私有凭据保持不变。2026-10-25，同结构原型保留可用临时节点，仅修改三个域名字段后，手机也成功打开 OA。该手机结果来自原型，不代表独立发布版的所有环境均已验证；首次部署仍须执行 `check` 并做手机实际访问测试，详见[验证记录](validation.md)。

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

## 固定订阅 + Quick 数据通道

如果手机端固定数据入口反复卡住，而真实 Quick 数据入口能完整传输，可保留固定下载地址，将校园流量交给独立的 Quick 隧道。Cloudflare 的固定 Published application 路由仍指向本机 `web_port`，无需新增域名或改动原 DNS。

编辑 `private/config.json`，在已有 named 配置中增加：

```json
{
  "data_tunnel": "quick",
  "data_metrics_port": 18084
}
```

这是字段片段，不要覆盖整份配置。`data_metrics_port` 必须与原四个本地端口不同。正常停止本项目后原样启动，程序会运行一条命名下载隧道和一条 Quick 数据隧道，复用同一个 HTTP 前端、VMess 后端和密钥；等待 Quick 域名生成后才发布链接。

- `Subscription`、`Config` 仍使用固定域名，重新启动后 URL 保持不变。
- 订阅里的节点地址、TLS SNI、WebSocket Host 使用 Quick 数据域名，三者应一致；它们不必等于订阅 URL 的域名。不要把节点手改成固定域名。
- 手机首次导入后保持同一个节点名称。电脑重建 Quick 隧道会改变数据域名，届时更新原固定订阅即可；不必重新建立订阅或更换学校规则。
- `check` 分别检查固定下载地址与 Quick 业务路径。`runtime.json` 中 `host` 是固定控制地址，`node_host` 是实际数据地址；二者不同是预期行为。
- Quick 数据通道没有可用性保证。分离模式提供固定的订阅发现地址，并没有把临时数据域名变成永久域名；当前程序的进程退出会停止该实例，需要重新启动并刷新订阅，不承诺后台自动续期或无需维护。

回到固定数据模式时，将 `data_tunnel` 设为 `same`，受控重启后刷新订阅，仍需手机完整传输验证。已能用的手机配置应保留，避免反复换节点名称。

## 从临时模式迁移或切回

- 保存原配置的本地副本，保留 `private/secrets.json`。使用同一实例切换时，停止本实例后只修改上述三个字段，保留端口、学校域名和 `node_name`。
- 固定模式首次启用时，订阅地址和节点主机名会改变，需要在手机导入固定链接。日常配置引用的节点名保持一致时，学校 DOMAIN 规则无需改名。
- 若要在不中断临时入口的情况下验证，使用独立项目目录和四个不冲突的回环端口；Cloudflare 路由填写新实例的实际 `web_port`。验证新实例成功并确认手机已切换后，再停止旧实例。
- 切回临时模式：停止本实例，将 `private/config.json` 的 `tunnel_mode` 改为 `quick`，再运行 `prepare` 和 `start`。`hostname` 与令牌文件可保留供以后使用，不必删除。新临时链接会改变，手机需要重新导入。
- 固定模式保持域名、路由、密钥和令牌有效时，正常重启继续使用固定链接。域名到期、隧道配置变更、电脑休眠或断网仍会影响访问。

### 临时入口可用，固定入口却打不开时

先保留能用的手机节点和配置，记录各字段，避免同时更换密钥、WebSocket 路径、前端程序或路由规则。如果两个入口确实共用同一个后端及 VMess 密钥，可关闭手机 VPN，在可用节点中只把以下三项改为自己的固定主机名，例如 `campus.example.com`：

1. 节点地址。
2. TLS 的 SNI。
3. WebSocket 的 Host。

端口仍为443，保留 UUID、WebSocket 路径、TLS 校验、节点名称和分流配置。保存后开启 VPN，实际访问 OA。仅在同一后端、相同认证参数的条件下，这才是有效的域名对照；独立实例的密钥不同，不能直接照搬此操作。

若这样成功，说明固定域名具备访问能力，应对照旧固定节点的导入参数、同名条目和配置实际引用，不能直接断言 Cloudflare 或域名被阻断。需要重新导入时采用可辨认的唯一节点名，并同步更新明确引用该名称的规则；不要先删除可用节点。若修改的是临时订阅里的条目，刷新临时订阅可能恢复临时主机名，日常使用前应将订阅 URL 也迁移到固定入口，并核对更新后的三个字段。

一次手改成功并不能证明重新订阅也成功。若重新导入后再次失败，应核对手机实际导出与本机参数，以及服务端是否已完成 WebSocket 升级、VMess 认证和目标出站；不要仅凭节点名称或 Host 在 JSON 中的表示形式确定根因。受控重启本项目实例前记录当前版本和参数，不删除数据，也不更换密钥。恢复后保留可用节点，直到有实际需要再导入。

令牌通过文件路径传给 cloudflared，不放在进程命令行中。不要把令牌、`private/`、包含令牌的日志或控制台截图提交到 GitHub。需要更换密钥时先停止服务，在自己的 Cloudflare 账户处理 Tunnel 令牌，再按原路径更新本地文件。

### 隧道传输协议对照

可选 `tunnel_protocol` 支持 `http2`（默认）、`auto`、`quic`，只控制电脑到 Cloudflare 的隧道传输，不改变手机 VMess 或学校规则。分离模式的数据隧道使用 HTTP2。修改协议时记录原值，只重启本项目，再用完整传输对照，不能仅凭 TCP 延迟判断修复；本次个人环境改为 QUIC 仍有固定数据超时，未将其当作最终修复。[Cloudflare 官方排障](https://developers.cloudflare.com/tunnel/troubleshooting/)

## 官方资料

- [创建和管理 Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/)
- [Cloudflare Tunnel 运行参数](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/cloudflared-parameters/run-parameters/)
- [临时入口的限制](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
