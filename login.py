# login.py
import os
import asyncio
import aiohttp
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

# ===================== 配置 =====================
LOGIN_URL = "https://wispbyte.com/client/login"   # 登录页（不是直接服务器页）

# ===================== Telegram 通知 =====================
async def tg_notify(message: str):
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        print("Warning: 未设置 TG_BOT_TOKEN / TG_CHAT_ID，跳过通知")
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    async with aiohttp.ClientSession() as session:
        try:
            await session.post(url, data={
                "chat_id": chat_id,
                "text": message,
                "parse_mode": "HTML",
                "disable_web_page_preview": True
            })
        except Exception as e:
            print(f"Warning: Telegram 消息发送失败: {e}")

async def tg_notify_photo(photo_path: str, caption: str = ""):
    token = os.getenv("TG_BOT_TOKEN")
    chat_id = os.getenv("TG_CHAT_ID")
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendPhoto"
    async with aiohttp.ClientSession() as session:
        try:
            with open(photo_path, "rb") as f:
                data = aiohttp.FormData()
                data.add_field("chat_id", chat_id)
                data.add_field("photo", f, filename=os.path.basename(photo_path))
                if caption:
                    data.add_field("caption", caption)
                    data.add_field("parse_mode", "HTML")
                await session.post(url, data=data)
        except Exception as e:
            print(f"Warning: Telegram 图片发送失败: {e}")
        finally:
            try:
                os.remove(photo_path)
            except:
                pass

# ===================== 报告生成 =====================
def build_report(results, start_time, end_time):
    success = [r for r in results if r["success"]]
    failed  = [r for r in results if not r["success"]]

    lines = [
        "Wispbyte 自动登录报告",
        f"目标: <a href='https://wispbyte.com/client'>控制面板</a>",
        f"时间: {start_time} → {end_time}",
        f"结果: <b>{len(success)} 成功</b> | <b>{len(failed)} 失败</b>",
        ""
    ]

    if success:
        lines.append("Success 成功：")
        lines.extend([f"   • <code>{r['email']}</code>" for r in success])
        lines.append("")

    if failed:
        lines.append("Failed 失败：")
        lines.extend([f"   • <code>{r['email']}</code>" for r in failed])

    return "\n".join(lines)

# ===================== 单账号登录 =====================
async def login_one(email: str, password: str):
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--window-size=1920,1080",
                # 新增：绕过 Cloudflare 检测
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security"
            ]
        )
        context = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        page.set_default_timeout(90000)  # 延长到 90s

        result = {"email": email, "success": False}

        # 重试逻辑（最多 2 次）
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                print(f"[{email}] 尝试 {attempt + 1}: 打开登录页...")
                
                # 优化：用 'load' 而非 'networkidle'，避免 Cloudflare 无限等待
                await page.goto(LOGIN_URL, wait_until="load", timeout=90000)
                
                # 等待 Cloudflare 挑战完成（如果有）
                await page.wait_for_load_state("domcontentloaded", timeout=30000)
                await asyncio.sleep(5)  # 给 JS 挑战时间（关键！）

                # 检查是否已登录
                if "client" in page.url and "login" not in page.url.lower():
                    print(f"[{email}] 已登录！")
                    result["success"] = True
                    return result

                # 等待登录表单（用更宽松选择器）
                await page.wait_for_selector('input[placeholder*="Email"], input[placeholder*="Username"], input[type="email"], input[type="text"]', timeout=20000)
                print(f"[{email}] 检测到登录表单")

                # 填写账号密码
                # 尝试多种选择器（兼容变化）
                email_selector = 'input[placeholder*="Email"], input[placeholder*="Username"], input[type="email"], input[type="text"]'
                pwd_selector = 'input[placeholder*="Password"], input[type="password"]'
                
                await page.fill(email_selector, email)
                await page.fill(pwd_selector, password)

                # 点击 “确认您是真人” 复选框（如果存在）
                try:
                    await page.wait_for_selector('text=确认您是真人, input[type="checkbox"], .cf-turnstile', timeout=10000)
                    # 尝试点击 checkbox 或文字
                    checkbox = page.locator('input[type="checkbox"]').first
                    if await checkbox.is_visible():
                        await checkbox.check()
                    else:
                        await page.click('text=确认您是真人')
                    print(f"[{email}] 已勾选 '确认您是真人'")
                    await asyncio.sleep(3)  # 等待验证
                except Exception as e:
                    print(f"[{email}] 未检测到复选框: {e}")

                # 点击登录按钮
                login_btn = page.locator('button:has-text("Log In"), input[type="submit"]').first
                await login_btn.click()
                print(f"[{email}] 已点击登录按钮")

                # 等待跳转到仪表板
                await page.wait_for_url("**/client**", timeout=30000)
                print(f"[{email}] 登录成功，进入控制面板！")
                result["success"] = True
                return result  # 成功即退出重试

            except Exception as e:
                print(f"[{email}] 尝试 {attempt + 1} 失败: {e}")
                if attempt < max_retries:
                    # 换 User-Agent 重试
                    await context.close()
                    context = await browser.new_context(
                        viewport={"width": 1920, "height": 1080},
                        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                    )
                    page = await context.new_page()
                    await asyncio.sleep(2)
                else:
                    # 最终失败：截图 + 通知
                    screenshot = f"error_{email.replace('@', '_')}_{int(datetime.now().timestamp())}.png"
                    await page.screenshot(path=screenshot, full_page=True)
                    await tg_notify_photo(screenshot,
                        caption=f"Wispbyte 登录失败\n"
                                f"账号: <code>{email}</code>\n"
                                f"错误: <i>{str(e)[:200]}</i>\n"
                                f"URL: {page.url}\n"
                                f"建议: 检查网络或手动登录一次"
                    )
                    print(f"[{email}] 所有重试失败: {e}")
        
        finally:
            await context.close()
            await browser.close()
        return result
# ===================== 主流程 =====================
async def main():
    start_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"登录任务开始: {start_time}")

    accounts_str = os.getenv("LOGIN_ACCOUNTS")
    if not accounts_str:
        await tg_notify("Failed: 未配置任何账号")
        return

    accounts = [a.strip() for a in accounts_str.split(",") if ":" in a]
    if not accounts:
        await tg_notify("Failed: LOGIN_ACCOUNTS 格式错误，应为 email:password")
        return

    tasks = [login_one(email, pwd) for acc in accounts for email, pwd in [acc.split(":", 1)]]
    results = await asyncio.gather(*tasks)

    end_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    final_msg = build_report(results, start_time, end_time)
    await tg_notify(final_msg)
    print(final_msg)

# ===================== 启动 =====================
if __name__ == "__main__":
    asyncio.run(main())
