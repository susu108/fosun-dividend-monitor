from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import sys
import time
import urllib.parse
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

import requests
from playwright.sync_api import Page
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

TARGET_URL: Final[str] = (
    "https://www.pflife.com.cn/fbofficialweb/Special?"
    "submenu=Special&itemsmenu=NewProducts&childmenu=DividendProducts&redFitShowflag=redFitShow"
)
TARGET_YEAR: Final[str] = "2026"
DEFAULT_TIMEOUT_SECONDS: Final[int] = 45


@dataclass(frozen=True)
class DingTalkSign:
    timestamp: str
    sign: str


def BuildDingTalkSign(secret: str) -> DingTalkSign:
    """生成钉钉机器人加签参数。"""
    timestamp: str = str(round(time.time() * 1000))
    sign_content: str = f"{timestamp}\n{secret}"
    hmac_code: bytes = hmac.new(
        secret.encode("utf-8"),
        sign_content.encode("utf-8"),
        digestmod=hashlib.sha256,
    ).digest()
    base64_sign: str = base64.b64encode(hmac_code).decode("utf-8")
    url_encoded_sign: str = urllib.parse.quote_plus(base64_sign)
    return DingTalkSign(timestamp=timestamp, sign=url_encoded_sign)


def SendDingTalk(webhook: str, secret: str | None, title: str, markdown_text: str) -> None:
    """发送钉钉 markdown 消息。"""
    if not webhook.strip():
        raise ValueError("DINGTALK_WEBHOOK 为空，无法发送钉钉通知。")

    request_url: str = webhook.strip()
    if secret and secret.strip():
        sign_payload: DingTalkSign = BuildDingTalkSign(secret.strip())
        connector: str = "&" if "?" in request_url else "?"
        request_url = (
            f"{request_url}{connector}timestamp={sign_payload.timestamp}&sign={sign_payload.sign}"
        )

    payload: dict[str, object] = {
        "msgtype": "markdown",
        "markdown": {"title": title, "text": markdown_text},
    }
    response: requests.Response = requests.post(
        request_url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        timeout=15,
    )
    response.raise_for_status()
    body: dict[str, object] = response.json()
    errcode: int = int(body.get("errcode", -1))
    if errcode != 0:
        errmsg: str = str(body.get("errmsg", "unknown error"))
        raise RuntimeError(f"钉钉接口返回错误，errcode={errcode}, errmsg={errmsg}")


def _OpenYearDropdown(page: Page, timeout_ms: int) -> None:
    """展开分红年度下拉框，兼容多个可能选择器。"""
    selectors: Sequence[str] = (
        "div.el-form-item:has-text('分红年度') .el-select .el-input__wrapper",
        "div.el-form-item:has-text('分红年度') .el-select .el-input",
        "input[placeholder*='分红年度']",
        "div.el-select:has(input[placeholder*='分红']) .el-input__wrapper",
    )
    last_error: Exception | None = None
    for selector in selectors:
        locator = page.locator(selector)
        count: int = locator.count()
        if count <= 0:
            continue
        try:
            locator.first.click(timeout=timeout_ms)
            page.wait_for_timeout(500)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
    raise RuntimeError(f"无法展开“分红年度”下拉框，最后错误：{last_error}")


def FetchDividendYears(target_url: str, timeout_seconds: int) -> list[str]:
    """抓取页面分红年度下拉中的所有年份。"""
    timeout_ms: int = max(timeout_seconds, 5) * 1000
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            _OpenYearDropdown(page, timeout_ms)

            option_locator = page.locator(
                "li.el-select-dropdown__item, div.el-select-dropdown__item"
            )
            option_locator.first.wait_for(timeout=timeout_ms)
            option_count: int = option_locator.count()
            if option_count <= 0:
                raise RuntimeError("已展开下拉框，但未找到任何年份选项。")

            years: list[str] = []
            for index in range(option_count):
                text: str = option_locator.nth(index).inner_text(timeout=timeout_ms).strip()
                if re.fullmatch(r"\d{4}", text):
                    years.append(text)

            dedup_years: list[str] = list(dict.fromkeys(years))
            if not dedup_years:
                raise RuntimeError("下拉选项存在，但未解析出任何 4 位年份。")
            return dedup_years
        except PlaywrightTimeoutError as exc:
            raise RuntimeError(f"页面加载或元素等待超时：{exc}") from exc
        finally:
            browser.close()


def EvaluatePublication(years: list[str], target_year: str) -> bool:
    """判断目标分红年度是否已公布。"""
    return target_year in years


def Main() -> int:
    """脚本入口。返回进程退出码。"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stdout,
    )

    webhook: str = os.getenv("DINGTALK_WEBHOOK", "").strip()
    secret: str | None = os.getenv("DINGTALK_SECRET")

    try:
        if not webhook:
            raise ValueError("缺少环境变量 DINGTALK_WEBHOOK。")

        years: list[str] = FetchDividendYears(TARGET_URL, DEFAULT_TIMEOUT_SECONDS)
        logging.info("当前下拉框年份选项：%s", years)

        if EvaluatePublication(years, TARGET_YEAR):
            title: str = "✅ 复星保德信2026年度红利实现率已公布"
            markdown_text: str = (
                "### ✅ 复星保德信2026年度红利实现率已公布\n"
                f"- 检测到分红年度选项包含 `{TARGET_YEAR}`\n"
                f"- 查询入口：{TARGET_URL}\n"
            )
            SendDingTalk(webhook, secret, title, markdown_text)
            logging.info("已发送“已公布”通知。")
        else:
            title = "⏳ 复星保德信2026年度红利实现率尚未公布"
            markdown_text = (
                "### ⏳ 复星保德信2026年度红利实现率尚未公布\n"
                f"- 当前年份选项：`{', '.join(years)}`\n"
                f"- 查询入口：{TARGET_URL}\n"
            )
            # 如不想每天接收“未公布”消息，可注释下一行。
            SendDingTalk(webhook, secret, title, markdown_text)
            logging.info("已发送“未公布”通知。")

        return 0
    except Exception as exc:  # noqa: BLE001
        logging.exception("脚本执行失败：%s", exc)
        if webhook:
            try:
                title = "⚠️ 复星保德信红利监控脚本异常"
                markdown_text = (
                    "### ⚠️ 复星保德信红利监控脚本异常\n"
                    f"- 错误信息：`{type(exc).__name__}: {exc}`\n"
                    f"- 查询入口：{TARGET_URL}\n"
                )
                SendDingTalk(webhook, secret, title, markdown_text)
                logging.info("已发送异常通知。")
            except Exception as notify_exc:  # noqa: BLE001
                logging.error("发送异常通知失败：%s", notify_exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(Main())
