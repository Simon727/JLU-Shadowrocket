# 第三方工具与参考

仓库不捆绑第三方可执行文件。`setup`从官方发布地址下载固定版本，按`tools.lock.json`校验SHA-256，保存在被Git忽略的`tools/`中。各工具按其自身许可证提供。

| 工具 | 用途 | 上游与许可 |
| --- | --- | --- |
| sing-box | VMess AEAD/WebSocket入口及受限制的校内出站 | [SagerNet/sing-box](https://github.com/SagerNet/sing-box)，[GPL-3.0](https://github.com/SagerNet/sing-box/blob/v1.14.4/LICENSE) |
| cloudflared | Cloudflare Tunnel便携连接器 | [cloudflare/cloudflared](https://github.com/cloudflare/cloudflared)，[Apache-2.0](https://github.com/cloudflare/cloudflared/blob/2026.10.3/LICENSE) |

设计调研参考了[Open-JLU](https://github.com/userElaina/Open-JLU)汇总和[Yesterday17/jlu-http-proxy](https://github.com/Yesterday17/jlu-http-proxy)。最终仓库使用校内直连，不包含其2020版协议实现，也不要求复用旧WebVPN加密参数。

本仓库自己的Python部署程序和文档使用MIT许可。第三方工具的许可证不因本仓库的许可而改变。Cloudflare服务本身还受其服务条款约束。
