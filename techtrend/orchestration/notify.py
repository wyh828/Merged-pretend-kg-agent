"""报告推送（P5，第 8 阶段）。

按 notify_channels 推送到 file/telegram/discord；任一渠道失败仅记 warning 不阻断。
- file：写 output/notify_latest.md（兜底，永远成功）
- telegram：POST https://api.telegram.org/bot<token>/sendMessage
- discord：POST <webhook>（{"content": ...}）

本机 Clash 代理方向相反（见 memory [[windows-clash-proxy-localhost]]）：
本地 RSSHub 请求走 trust_env=False；外网 Telegram/Discord 推送走 trust_env=True（代理）。
"""
import logging

from techtrend.config import Settings

log = logging.getLogger(__name__)

# 各渠道消息长度上限（telegram sendMessage 4096 字符 / discord content 2000 字符）
_LIMITS = {"telegram": 4000, "discord": 1900}


def push_report(settings: Settings, report_text: str, channels: list[str] | None = None) -> dict:
    """按渠道推送报告文本，返回 {channel: status}。"""
    if channels is None:
        channels = [c.strip() for c in settings.notify_channels.split(",") if c.strip()]
    results: dict[str, str] = {}
    for ch in channels:
        try:
            handler = _HANDLERS.get(ch)
            if handler is None:
                log.warning("未知推送渠道 %s，跳过", ch)
                results[ch] = "unknown"
                continue
            results[ch] = handler(settings, report_text)
        except Exception as exc:  # noqa: BLE001 —— 渠道级失败不阻断他渠道
            log.exception("notify[%s] 失败", ch)
            results[ch] = "error"
    return results


def _notify_file(settings: Settings, text: str) -> str:
    path = settings.output_dir / "notify_latest.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    log.info("notify[file] → %s", path)
    return "ok"


def _notify_telegram(settings: Settings, text: str) -> str:
    token = settings.notify_telegram_bot_token
    chat_id = settings.notify_telegram_chat_id
    if not token or not chat_id:
        return "skipped(no token/chat_id)"
    import httpx

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    with httpx.Client(timeout=30, trust_env=True) as client:  # 外网走系统代理（Clash）
        resp = client.post(url, json={"chat_id": chat_id, "text": text[:_LIMITS["telegram"]]})
        resp.raise_for_status()
    log.info("notify[telegram] ok")
    return "ok"


def _notify_discord(settings: Settings, text: str) -> str:
    webhook = settings.notify_discord_webhook
    if not webhook:
        return "skipped(no webhook)"
    import httpx

    with httpx.Client(timeout=30, trust_env=True) as client:  # 外网走系统代理（Clash）
        resp = client.post(webhook, json={"content": text[:_LIMITS["discord"]]})
        resp.raise_for_status()
    log.info("notify[discord] ok")
    return "ok"


_HANDLERS = {
    "file": _notify_file,
    "telegram": _notify_telegram,
    "discord": _notify_discord,
}


__all__ = ["push_report"]
