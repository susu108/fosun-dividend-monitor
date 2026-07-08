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
from playwright.sync_api import Locator
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


def BuildUnpublishedMarkdown(years: list[str]) -> tuple[str, str]:
    """构建“未公布”弱提醒的标题与 markdown 内容。"""
    # 弱提醒：信息量较少、语气更平缓，避免刷屏焦虑。
    title: str = "⏳ 复星保德信2026年度红利实现率：未公布（弱提醒）"
    markdown_text: str = (
        "### ⏳ 未公布\n"
        f"- 当前年份选项：`{', '.join(years)}`\n"
        f"- 查询入口：[复星保德信官网红利实现率查询页]({TARGET_URL})\n"
        "- 建议：保持关注，后续将自动更新通知。\n"
    )
    return title, markdown_text


def BuildPublishedMarkdown() -> tuple[str, str]:
    """构建“已公布”强提醒的标题与 markdown 内容。"""
    # 强提醒：更醒目的标题 + 明确结论 + 附官网入口链接。
    title: str = "✅ 已公布！复星保德信2026年度红利实现率（强提醒）"
    markdown_text: str = (
        "## ✅ 已公布\n"
        "- 已检测到“分红年度”下拉选项包含：`2026`\n"
        f"- 查询入口：[复星保德信官网红利实现率查询页]({TARGET_URL})\n"
        "- 下一步：请尽快查看对应产品的红利实现率披露内容。\n"
    )
    return title, markdown_text


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
    candidates: Sequence[str] = (
        "xpath=//label[contains(normalize-space(.),'分红年度')]/following::*[contains(@class,'el-select')][1]//input",
        "xpath=//*[contains(@class,'el-form-item')][.//*[contains(normalize-space(.),'分红年度')]]"
        "//*[contains(@class,'el-select')]//input",
        "div.el-form-item:has-text('分红年度') .el-select input",
        "input[placeholder*='分红年度']",
        "div.el-select input[role='combobox']",
    )

    last_error: Exception | None = None
    found_any: bool = False

    for selector in candidates:
        locator = page.locator(selector)
        try:
            count: int = locator.count()
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            continue

        if count <= 0:
            continue

        found_any = True
        try:
            locator.first.scroll_into_view_if_needed(timeout=timeout_ms)
            locator.first.click(timeout=timeout_ms, force=True)
            page.wait_for_timeout(300)
            return
        except Exception as exc:  # noqa: BLE001
            last_error = exc

    if not found_any:
        raise RuntimeError("无法定位“分红年度”输入框/下拉触发器（页面结构可能已变更）。")
    raise RuntimeError(f"无法展开“分红年度”下拉框，最后错误：{last_error}")


def FetchDividendYears(target_url: str, timeout_seconds: int) -> list[str]:
    """抓取页面分红年度下拉中的所有年份。"""
    timeout_ms: int = max(timeout_seconds, 5) * 1000
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        try:
            page.goto(target_url, wait_until="domcontentloaded", timeout=timeout_ms)
            page.wait_for_load_state("networkidle", timeout=timeout_ms)
            _OpenYearDropdown(page, timeout_ms)

            # 页面中可能同时存在多个下拉框（例如：产品下拉 + 分红年度下拉）。
            # 因此先找“包含最多年份（20xx）文本”的下拉容器，再对该容器滚动加载并提取年份。
            dropdowns = page.locator("div.el-select-dropdown")
            dropdown_count: int = dropdowns.count()
            if dropdown_count <= 0:
                raise RuntimeError("已展开下拉框，但未找到任何下拉容器。")

            year_re = re.compile(r"(20\d{2})")

            def _ExtractYearsFromDropdown(dropdown: Locator) -> list[str]:
                # 使用文本搜索而非 fullmatch，避免 DOM 文本带有额外字符。
                items = dropdown.locator("li.el-select-dropdown__item")
                if items.count() <= 0:
                    return []
                raw_texts: list[str] = items.all_inner_texts()
                found: list[str] = []
                for text in raw_texts:
                    match = year_re.search(text)
                    if match is not None:
                        found.append(match.group(1))
                return list(dict.fromkeys(found))

            best_years: list[str] = []
            best_dropdown_idx: int | None = None

            for idx in range(dropdown_count):
                candidate = dropdowns.nth(idx)
                years_found: list[str] = _ExtractYearsFromDropdown(candidate)
                if len(years_found) > len(best_years):
                    best_years = years_found
                    best_dropdown_idx = idx

            if best_dropdown_idx is None or not best_years:
                # 兜底：直接在页面所有下拉 item 里搜索年份（但可能受虚拟滚动影响）
                all_items = page.locator("li.el-select-dropdown__item")
                if all_items.count() <= 0:
                    raise RuntimeError("已展开下拉框，但未找到任何下拉选项。")
                raw_texts = all_items.all_inner_texts()
                years: list[str] = []
                for text in raw_texts:
                    match = year_re.search(text)
                    if match is not None:
                        years.append(match.group(1))
                dedup_years: list[str] = list(dict.fromkeys(years))
                if not dedup_years:
                    raise RuntimeError("下拉选项存在，但未解析出任何 4 位年份。")
                return dedup_years

            dropdown_root = dropdowns.nth(best_dropdown_idx)
            # 注意：有些下拉 DOM 可能存在但不一定处于 visible 状态（例如被遮挡），
            # 这里等待的是 attached 而不是 visible。
            dropdown_root.wait_for(state="attached", timeout=timeout_ms)

            wrap = dropdown_root.locator("div.el-select-dropdown__wrap").first
            if wrap.count() <= 0:
                # 某些情况下年份选项已经在 DOM 中完整渲染，此时无需滚动。
                return best_years

            # 虚拟滚动：向下滚动直到年份数量不再增长。
            last_count: int = len(best_years)
            for _ in range(10):
                if wrap.count() > 0:
                    wrap.evaluate("el => { el.scrollTop = el.scrollHeight; }")
                    page.wait_for_timeout(250)
                else:
                    break

                current_years: list[str] = _ExtractYearsFromDropdown(dropdown_root)
                if len(current_years) > last_count:
                    best_years = current_years
                    last_count = len(current_years)
                    continue
                if last_count > 0:
                    break

            if not best_years:
                raise RuntimeError("分红年度下拉容器已加载，但未解析到任何年份。")
            return best_years
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
            title, markdown_text = BuildPublishedMarkdown()
            SendDingTalk(webhook, secret, title, markdown_text)
            logging.info("已发送“已公布”通知。")
        else:
            title, markdown_text = BuildUnpublishedMarkdown(years)
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
