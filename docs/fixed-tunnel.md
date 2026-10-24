# 固定域名部署

临时入口适合先验证能否使用。长期使用需要一个 Cloudflare 管理的域名、一个命名 Tunnel，以及始终在线的校内电脑。固定域名可以减少重启后重新添加订阅的操作；不提供学校账号免认证功能。

**验证范围：** 本仓库已核对 cloudflared 2026.10.3 的 `--token-file` 参数，并测试令牌文件路径限制；没有使用真实命名 Tunnel 账户做端到端验证。首次部署后必须执行 `check` 并做手机实际访问测试。

## Cloudflare 一侧

1. 在自己的 Cloudflare 账户创建 Cloudflare Tunnel。
2. 为这个 Tunnel 配置一个发布应用的固定主机名，例如 `campus.example.com`。
3. 服务类型选择 **HTTP**，服务地址填写 **`localhost:18080`**；如果改了 `web_port`，同步修改这里。
4. 使用控制台为这个 Tunnel 提供的连接令牌，将**令牌本身**保存到本项目 `private/cloudflare-token.txt`，不要连同安装命令一起粘贴。
5. 不必运行安装 Windows 系统服务的命令，本程序会用便携 cloudflared 启动连接。

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

在另一个终端运行 `check`。手机导入启动窗口显示的新订阅和分流链接，按 README 测试。

令牌通过文件路径传给 cloudflared，不放在进程命令行中。不要把令牌、`private/`、包含令牌的日志或控制台截图提交到 GitHub。需要更换密钥时先停止服务，在自己的 Cloudflare 账户处理 Tunnel 令牌，再按原路径更新本地文件。

## 官方资料

- [创建和管理 Cloudflare Tunnel](https://developers.cloudflare.com/tunnel/)
- [Cloudflare Tunnel 运行参数](https://developers.cloudflare.com/cloudflare-one/networks/connectors/cloudflare-tunnel/configure-tunnels/cloudflared-parameters/run-parameters/)
- [临时入口的限制](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
